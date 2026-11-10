"""本机 HTTP：会话列表、新建、读取、发送一句的事件流，以及 dist 里的静态文件。

绑定调用方传入的地址，默认 ``127.0.0.1``。本模块不进入工具循环。
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from vector_harness.cli import build_agent
from vector_harness.core.session import Session
from vector_harness.types import ProviderEvent
from vector_harness.web_sessions import (
    create_session,
    is_session_id,
    list_sessions,
    read_messages,
)

_NO_DIST = "页面还没有构建。请先在 web/ 执行 npm run build。\n"
_JSON = "application/json; charset=utf-8"
_EVENT_STREAM = "text/event-stream"


@dataclass(frozen=True, kw_only=True)
class WebSettings:
    workspace: Path
    skills_dir: Path | None = None
    memory_path: Path | None = None
    compact: bool = False
    plan: bool = False
    reflect: bool = False
    subagents: bool = False
    max_steps: int = 25
    dist_dir: Path | None = None


class WebServer:
    def __init__(self, settings: WebSettings, provider: object) -> None:
        self.settings = settings
        self.provider = provider
        self.port = 0
        self.running_id: str | None = None
        # 盖住「检查正忙」到这一轮结束。拿不到锁就是已经有一轮。
        self._lock = threading.Lock()
        self._httpd: _BoundServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, host: str = "127.0.0.1", port: int = 0) -> None:
        """绑定完成后在守护线程里服务。返回时 ``port`` 已是实际端口。"""
        self._bind(host, port)
        thread = threading.Thread(target=self._serve, daemon=True)
        self._thread = thread
        thread.start()

    def listen(self, host: str, port: int) -> int:
        """绑定并监听。返回套接字实际得到的端口。"""
        self._bind(host, port)
        return self.port

    def serve_forever(self, host: str, port: int) -> None:
        """在当前线程阻塞服务。尚未监听时先绑定。"""
        if self._httpd is None:
            self._bind(host, port)
        self._serve()

    def shutdown(self) -> None:
        """停掉 ``start`` 起的线程。"""
        httpd = self._httpd
        thread = self._thread
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
            self._httpd = None
        if thread is not None:
            thread.join()
            self._thread = None

    def _bind(self, host: str, port: int) -> None:
        httpd = _BoundServer((host, port), self)
        self._httpd = httpd
        self.port = int(httpd.server_address[1])

    def _serve(self) -> None:
        assert self._httpd is not None
        self._httpd.serve_forever()


class _BoundServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], app: WebServer) -> None:
        self.app = app
        super().__init__(server_address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        _route(self, "GET")

    def do_POST(self) -> None:
        _route(self, "POST")

    def log_message(self, format: str, *args: object) -> None:
        return


def _route(handler: BaseHTTPRequestHandler, method: str) -> None:
    server = handler.server
    assert isinstance(server, _BoundServer)
    app = server.app
    segments = _segments(handler.path)
    if segments[:1] == ["api"]:
        _route_api(app, handler, method, segments)
        return
    if method == "GET":
        _serve_static(app, handler)
        return
    _send_json(handler, 404, {"error": "not_found"})


def _route_api(
    app: WebServer,
    handler: BaseHTTPRequestHandler,
    method: str,
    segments: list[str],
) -> None:
    workspace = app.settings.workspace
    if method == "GET" and segments == ["api", "sessions"]:
        _send_json(
            handler,
            200,
            {"sessions": list_sessions(workspace), "running_id": app.running_id},
        )
        return
    if method == "POST" and segments == ["api", "sessions"]:
        _send_json(handler, 201, {"id": create_session(workspace)})
        return
    if method == "GET" and len(segments) == 3 and segments[:2] == ["api", "sessions"]:
        _send_session(handler, workspace, segments[2])
        return
    if (
        method == "POST"
        and len(segments) == 4
        and segments[:2] == ["api", "sessions"]
        and segments[3] == "messages"
    ):
        _send_message(app, handler, segments[2])
        return
    _send_json(handler, 404, {"error": "not_found"})


def _send_message(app: WebServer, handler: BaseHTTPRequestHandler, session_id: str) -> None:
    """发送一句。检查失败时返回 JSON，成功时把这一轮流式写回去。"""
    raw = _read_body(handler)
    if not is_session_id(session_id):
        _send_json(handler, 400, {"error": "bad_session"})
        return
    session_path = app.settings.workspace / ".vector" / "sessions" / f"{session_id}.jsonl"
    if not session_path.is_file():
        _send_json(handler, 404, {"error": "not_found"})
        return
    text = _message_text(raw)
    if text is None:
        _send_json(handler, 400, {"error": "bad_request"})
        return
    if text.strip() == "":
        _send_json(handler, 400, {"error": "empty"})
        return
    # 锁在启动运行之前就占住，一直留到 run 返回。第二次发送拿不到锁。
    if not app._lock.acquire(blocking=False):
        _send_json(handler, 409, {"error": "busy"})
        return
    app.running_id = session_id
    try:
        _stream_turn(app, handler, session_path, text)
    finally:
        app.running_id = None
        app._lock.release()


def _stream_turn(
    app: WebServer,
    handler: BaseHTTPRequestHandler,
    session_path: Path,
    text: str,
) -> None:
    """新建一轮 runner，把模型事件和最后的 run_result 逐条写出去。"""
    settings = app.settings
    agent = build_agent(
        provider=app.provider,
        workspace=settings.workspace,
        session=Session(session_path),
        skills_dir=settings.skills_dir,
        memory_path=settings.memory_path,
        compact=settings.compact,
        plan=settings.plan,
        reflect=settings.reflect,
        subagents=settings.subagents,
        max_steps=settings.max_steps,
    )

    def on_event(event: ProviderEvent) -> None:
        _write_event(handler, _event_payload(event))

    agent.loop.on_event = on_event
    _begin_event_stream(handler)
    result = asyncio.run(agent.run(text))
    _write_event(
        handler,
        {
            "kind": "run_result",
            "status": result.status,
            "text": result.text,
            "name": "",
            "tool_call_id": "",
            "arguments": None,
            "origin": "",
        },
    )


def _event_payload(event: ProviderEvent) -> dict[str, object]:
    """循环事件原样转成事件流对象，字段与 ProviderEvent 一致。"""
    return {
        "kind": event.kind,
        "text": event.text,
        "name": event.name,
        "tool_call_id": event.tool_call_id,
        "arguments": event.arguments,
        "origin": event.origin,
    }


def _begin_event_stream(handler: BaseHTTPRequestHandler) -> None:
    """先把 200 和事件流类型写出去，后面的增量才能在这一轮结束前被看见。"""
    handler.send_response(200)
    handler.send_header("Content-Type", _EVENT_STREAM)
    handler.end_headers()
    handler.wfile.flush()


def _write_event(handler: BaseHTTPRequestHandler, payload: dict[str, object]) -> None:
    """一行 ``data: `` 加 JSON，再加一个空行。写完就 flush。

    状态行已经发出去之后，客户端断开只是这条流写不出去。错误留在这里，
    ``run`` 继续把这一轮写进会话。
    """
    line = "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
    try:
        handler.wfile.write(line.encode("utf-8"))
        handler.wfile.flush()
    except OSError:
        return


def _message_text(raw: bytes) -> str | None:
    """正文必须是带字符串 ``text`` 的 JSON 对象。否则返回 None。"""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    text = payload.get("text")
    if not isinstance(text, str):
        return None
    return text


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = handler.headers.get("Content-Length")
    if length is None:
        return b""
    try:
        size = int(length)
    except ValueError:
        return b""
    if size < 0:
        return b""
    return handler.rfile.read(size)


def _send_session(handler: BaseHTTPRequestHandler, workspace: Path, session_id: str) -> None:
    # 先按段解码，``%2f`` 仍留在这一段里，不会变成目录分隔符。
    if not is_session_id(session_id):
        _send_json(handler, 400, {"error": "bad_session"})
        return
    try:
        messages = read_messages(workspace, session_id)
    except FileNotFoundError:
        _send_json(handler, 404, {"error": "not_found"})
        return
    _send_json(handler, 200, {"id": session_id, "messages": messages})


def _serve_static(app: WebServer, handler: BaseHTTPRequestHandler) -> None:
    dist = app.settings.dist_dir
    index = None if dist is None else dist / "index.html"
    if index is not None and index.is_file() and dist is not None:
        target = _file_in_dist(dist, handler.path)
        chosen = target if target is not None else index
        _send_bytes(handler, 200, chosen.read_bytes(), _media_type(chosen))
        return
    if _is_root(handler.path):
        _send_bytes(handler, 503, _NO_DIST.encode("utf-8"), "text/plain; charset=utf-8")
        return
    _send_json(handler, 404, {"error": "not_found"})


def _file_in_dist(dist: Path, url_path: str) -> Path | None:
    """解码后的路径必须落在 dist 里，并且是文件。越界或缺失都交回 index.html。"""
    relative = unquote(urlsplit(url_path).path).lstrip("/")
    if relative == "":
        return None
    root = dist.resolve()
    try:
        candidate = root / relative
        lexical = candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    # Windows 上 ``relative_to`` 会留下 ``..``。先拒绝，避免解析到 dist 外面。
    if ".." in lexical.parts:
        return None
    try:
        resolved = candidate.resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    return resolved


def _segments(url_path: str) -> list[str]:
    raw = urlsplit(url_path).path
    return [unquote(part) for part in raw.split("/") if part]


def _is_root(url_path: str) -> bool:
    return urlsplit(url_path).path in ("", "/")


def _media_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed in {
        "application/javascript",
        "application/json",
    }:
        return f"{guessed}; charset=utf-8"
    return guessed


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _send_bytes(handler, status, body, _JSON)


def _send_bytes(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    content_type: str,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
