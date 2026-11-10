"""本机 HTTP：会话列表、新建、读取、发送一句的事件流，以及 dist 里的静态文件。

绑定调用方传入的地址，默认 ``127.0.0.1``。本模块不进入工具循环。
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from vector_harness.cli import build_agent
from vector_harness.core.session import Session
from vector_harness.tools.shell import Shell, signal_kill
from vector_harness.types import Message, ProviderEvent, Role
from vector_harness.patterns.skills import Skills
from vector_harness.web_sessions import (
    begin_run,
    create_session,
    delete_session,
    finish_run,
    is_session_id,
    list_sessions,
    read_messages,
    session_run,
    session_skill,
    set_session_skill,
)

_NO_DIST = "页面还没有构建。请先在 web/ 执行 npm run build。\n"
_JSON = "application/json; charset=utf-8"
_EVENT_STREAM = "text/event-stream"
# 页面上的三种模式。缺省时沿用启动服务时的 --plan / --reflect。
_MODES = {
    "react": (False, False),
    "plan": (True, False),
    "reflect": (False, True),
}
_PREVIEW_LIMIT = 2 * 1024 * 1024
_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".py",
    ".csv",
    ".log",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
}
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


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
        self.workdir = settings.workspace.resolve()
        self.provider = provider
        self.port = 0
        self.running_id: str | None = None
        # 盖住「检查正忙」到这一轮结束。拿不到锁就是已经有一轮。
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._processes: list = []
        self._process_lock = threading.Lock()
        self._run_loop: asyncio.AbstractEventLoop | None = None
        self._run_task: asyncio.Task | None = None
        self._httpd: _BoundServer | None = None
        self._thread: threading.Thread | None = None

    def request_stop(self, session_id: str) -> bool:
        """停下正在跑的那一轮。不是这一份会话时返回 False。"""
        if self.running_id != session_id:
            return False
        self._cancel.set()
        with self._process_lock:
            procs = list(self._processes)
        for proc in procs:
            signal_kill(proc)
        loop = self._run_loop
        task = self._run_task
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)
        return True

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

    def do_DELETE(self) -> None:
        _route(self, "DELETE")

    def log_message(self, format: str, *args: object) -> None:
        return


def _provider_model(provider: object) -> str:
    """页面展示当前模型名。测试里的假提供方可以没有这个属性。"""
    model = getattr(provider, "model", "")
    return model if isinstance(model, str) else ""


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
    if method == "GET" and segments == ["api", "skills"]:
        _send_json(handler, 200, {"skills": _skill_catalog(app)})
        return
    if method == "GET" and segments == ["api", "workdir"]:
        _send_json(handler, 200, {"path": str(app.workdir)})
        return
    if method == "GET" and segments == ["api", "dirs"]:
        _send_dirs(handler, app.workdir)
        return
    if method == "POST" and segments == ["api", "workdir"]:
        _set_workdir(app, handler)
        return
    if method == "GET" and segments == ["api", "file", "bytes"]:
        _send_file_bytes(handler)
        return
    if method == "GET" and segments == ["api", "file"]:
        _send_file_meta(handler)
        return
    if method == "POST" and segments == ["api", "file", "rename"]:
        _rename_file(handler)
        return
    if method == "DELETE" and segments == ["api", "file"]:
        _delete_file(handler)
        return
    if method == "GET" and segments == ["api", "sessions"]:
        _send_json(
            handler,
            200,
            {
                "sessions": list_sessions(workspace),
                "running_id": app.running_id,
                "model": _provider_model(app.provider),
            },
        )
        return
    if method == "POST" and segments == ["api", "sessions"]:
        _send_json(handler, 201, {"id": create_session(workspace)})
        return
    if method == "GET" and len(segments) == 3 and segments[:2] == ["api", "sessions"]:
        _send_session(handler, workspace, segments[2])
        return
    if method == "DELETE" and len(segments) == 3 and segments[:2] == ["api", "sessions"]:
        _delete_session(app, handler, segments[2])
        return
    if (
        method == "POST"
        and len(segments) == 4
        and segments[:2] == ["api", "sessions"]
        and segments[3] == "messages"
    ):
        _send_message(app, handler, segments[2])
        return
    if (
        method == "POST"
        and len(segments) == 4
        and segments[:2] == ["api", "sessions"]
        and segments[3] == "stop"
    ):
        _stop_run(app, handler, segments[2])
        return
    if (
        method == "POST"
        and len(segments) == 4
        and segments[:2] == ["api", "sessions"]
        and segments[3] == "skill"
    ):
        _set_skill(app, handler, segments[2])
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
    request = _message_request(raw)
    if request is None:
        _send_json(handler, 400, {"error": "bad_request"})
        return
    text, mode = request
    if text.strip() == "":
        _send_json(handler, 400, {"error": "empty"})
        return
    if mode is None:
        plan, reflect = app.settings.plan, app.settings.reflect
    else:
        plan, reflect = _MODES[mode]
    # 锁在启动运行之前就占住，一直留到 run 返回。第二次发送拿不到锁。
    if not app._lock.acquire(blocking=False):
        _send_json(handler, 409, {"error": "busy"})
        return
    app._cancel.clear()
    app.running_id = session_id
    begin_run(app.settings.workspace, session_id)
    try:
        _stream_turn(app, handler, session_path, text, plan=plan, reflect=reflect)
    finally:
        app.running_id = None
        finish_run(app.settings.workspace, session_id)
        app._lock.release()


def _stream_turn(
    app: WebServer,
    handler: BaseHTTPRequestHandler,
    session_path: Path,
    text: str,
    *,
    plan: bool,
    reflect: bool,
) -> None:
    """新建一轮 runner，把模型事件和最后的 run_result 逐条写出去。"""
    settings = app.settings
    chosen = session_skill(settings.workspace, session_path.stem)
    agent = build_agent(
        provider=app.provider,
        workspace=app.workdir,
        session=Session(session_path),
        skills_dir=settings.skills_dir if chosen else None,
        skill_name=chosen,
        memory_path=settings.memory_path,
        compact=settings.compact,
        plan=plan,
        reflect=reflect,
        subagents=settings.subagents,
        max_steps=settings.max_steps,
    )

    fragment: list[str] = []

    def on_event(event: ProviderEvent) -> None:
        if event.kind == "tool_call_end":
            fragment.clear()
        elif event.kind == "text_delta" and event.origin != "child" and event.text:
            fragment.append(event.text)
        _write_event(handler, _event_payload(event))

    for tool in agent.loop.tools:
        if isinstance(tool, Shell):
            tool.cancel = app._cancel
            tool.processes = app._processes
            tool.process_lock = app._process_lock

    agent.loop.on_event = on_event
    _begin_event_stream(handler)

    async def drive():
        app._run_loop = asyncio.get_running_loop()
        app._run_task = asyncio.current_task()
        try:
            if app._cancel.is_set():
                _keep_partial(session_path, "".join(fragment))
                return None
            return await agent.run(text)
        except asyncio.CancelledError:
            _keep_partial(session_path, "".join(fragment))
            return None
        finally:
            app._run_task = None
            app._run_loop = None

    result = asyncio.run(drive())
    _write_event(
        handler,
        {
            "kind": "run_result",
            "status": "stopped" if result is None else result.status,
            "text": "" if result is None else result.text,
            "name": "",
            "tool_call_id": "",
            "arguments": None,
            "origin": "",
        },
    )


def _delete_session(app: WebServer, handler: BaseHTTPRequestHandler, session_id: str) -> None:
    """删掉一份空闲会话。正在跑的那一轮拿着锁，这里拿不到就拒绝。"""
    if not is_session_id(session_id):
        _send_json(handler, 400, {"error": "bad_session"})
        return
    if not app._lock.acquire(blocking=False):
        _send_json(handler, 409, {"error": "busy"})
        return
    try:
        try:
            delete_session(app.settings.workspace, session_id)
        except FileNotFoundError:
            _send_json(handler, 404, {"error": "not_found"})
            return
        _send_json(handler, 200, {"deleted": True})
    finally:
        app._lock.release()


def _stop_run(app: WebServer, handler: BaseHTTPRequestHandler, session_id: str) -> None:
    """停止正在跑的会话。没有这一轮时 ``stopped`` 为 false。"""
    if not is_session_id(session_id):
        _send_json(handler, 400, {"error": "bad_session"})
        return
    _send_json(handler, 200, {"stopped": app.request_stop(session_id)})


def _keep_partial(session_path: Path, text: str) -> None:
    """停止时把还没写入会话的正文补上。已经落盘的不再写一遍。"""
    if text == "":
        return
    session = Session(session_path)
    messages = session.load()
    if messages and messages[-1].role == Role.ASSISTANT and messages[-1].content == text:
        return
    session.append(Message(role=Role.ASSISTANT, content=text))


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


def _message_request(raw: bytes) -> tuple[str, str | None] | None:
    """正文必须是带字符串 ``text`` 的 JSON 对象。

    ``mode`` 可以不写。写出时只能是 ``react``、``plan``、``reflect``。
    返回 ``(text, mode)``；``mode`` 为 None 表示沿用启动参数。格式不对返回 None。
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    text = payload.get("text")
    if not isinstance(text, str):
        return None
    if "mode" not in payload:
        return text, None
    mode = payload.get("mode")
    if not isinstance(mode, str) or mode not in _MODES:
        return None
    return text, mode


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


def _skill_catalog(app: WebServer) -> list[dict[str, str]]:
    directory = app.settings.skills_dir
    if directory is None:
        return []
    return Skills(directory).catalog()


def _set_skill(app: WebServer, handler: BaseHTTPRequestHandler, session_id: str) -> None:
    """给这一份会话单独记下技能。空名字表示不使用技能。"""
    if not is_session_id(session_id):
        _send_json(handler, 400, {"error": "bad_session"})
        return
    payload = _object_body(_read_body(handler))
    if payload is None or "name" not in payload:
        _send_json(handler, 400, {"error": "bad_request"})
        return
    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        _send_json(handler, 400, {"error": "bad_request"})
        return
    chosen = name.strip() if isinstance(name, str) else ""
    if chosen and chosen not in {item["name"] for item in _skill_catalog(app)}:
        _send_json(handler, 400, {"error": "unknown_skill"})
        return
    try:
        set_session_skill(app.settings.workspace, session_id, chosen or None)
    except FileNotFoundError:
        _send_json(handler, 404, {"error": "not_found"})
        return
    _send_json(handler, 200, {"id": session_id, "skill": chosen or None})


def _send_dirs(handler: BaseHTTPRequestHandler, workdir: Path) -> None:
    """列出某个目录下的子目录和文件。没给路径时从当前工作目录开始。"""
    query = parse_qs(urlsplit(handler.path).query)
    raw_values = query.get("path", [])
    raw = raw_values[0] if raw_values else ""
    target = workdir if raw.strip() == "" else Path(raw)
    listing = _dir_listing(target)
    if listing is None:
        _send_json(handler, 400, {"error": "not_a_directory"})
        return
    _send_json(handler, 200, listing)


def _set_workdir(app: WebServer, handler: BaseHTTPRequestHandler) -> None:
    """改工具使用的工作目录。会话仍留在启动服务时的目录里。有一轮正在跑时不改。"""
    payload = _object_body(_read_body(handler))
    if payload is None:
        _send_json(handler, 400, {"error": "bad_request"})
        return
    raw = payload.get("path")
    if not isinstance(raw, str) or raw.strip() == "":
        _send_json(handler, 400, {"error": "bad_request"})
        return
    listing = _dir_listing(Path(raw))
    if listing is None:
        _send_json(handler, 400, {"error": "not_a_directory"})
        return
    if not app._lock.acquire(blocking=False):
        _send_json(handler, 409, {"error": "busy"})
        return
    try:
        app.workdir = Path(listing["path"])
        _send_json(handler, 200, {"path": str(app.workdir)})
    finally:
        app._lock.release()


def _dir_listing(path: Path) -> dict | None:
    """目录清单。点开头的名字不列出。路径不是目录时返回 None。"""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    if not resolved.is_dir():
        return None
    dirs: list[dict[str, str]] = []
    files: list[dict[str, str]] = []
    try:
        children = sorted(resolved.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        children = []
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            entry = {"name": child.name, "path": str(child.resolve())}
            if child.is_dir():
                dirs.append(entry)
            elif child.is_file():
                files.append(entry)
        except OSError:
            continue
    parent = resolved.parent
    return {
        "path": str(resolved),
        "parent": None if parent == resolved else str(parent),
        "dirs": dirs,
        "files": files,
    }


def _object_body(raw: bytes) -> dict | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


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
    started_at, duration_ms = session_run(workspace, session_id)
    _send_json(
        handler,
        200,
        {
            "id": session_id,
            "messages": messages,
            "skill": session_skill(workspace, session_id),
            "started_at": started_at,
            "duration_ms": duration_ms,
        },
    )


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


def file_kind(path: Path) -> dict | None:
    """文件预览信息。目录、缺失或读不出来时返回 None。"""
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
    except OSError:
        return None
    info: dict = {"name": path.name, "size": size}
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES or suffix in _IMAGE_TYPES:
        if size > _PREVIEW_LIMIT:
            info["kind"] = "too_large"
            return info
    if suffix in _TEXT_SUFFIXES:
        try:
            info["text"] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        info["kind"] = "text"
        return info
    media = _IMAGE_TYPES.get(suffix)
    if media is not None:
        info["kind"] = "image"
        info["media_type"] = media
        return info
    info["kind"] = "unsupported"
    return info


def _request_file(handler: BaseHTTPRequestHandler) -> tuple[Path | None, dict[str, list[str]]]:
    """解析查询里的 path。缺失、不是文件或读失败时已经写好响应，返回 None。"""
    query = parse_qs(urlsplit(handler.path).query)
    raw_values = query.get("path", [])
    raw = raw_values[0] if raw_values else ""
    if raw.strip() == "":
        _send_json(handler, 404, {"error": "not_found"})
        return None, query
    try:
        resolved = Path(raw).expanduser().resolve()
    except OSError:
        _send_json(handler, 404, {"error": "not_found"})
        return None, query
    if not resolved.exists():
        _send_json(handler, 404, {"error": "not_found"})
        return None, query
    if resolved.is_dir():
        _send_json(handler, 400, {"error": "not_a_file"})
        return None, query
    return resolved, query


def _send_file_meta(handler: BaseHTTPRequestHandler) -> None:
    resolved, _query = _request_file(handler)
    if resolved is None:
        return
    info = file_kind(resolved)
    if info is None:
        _send_json(handler, 404, {"error": "not_found"})
        return
    _send_json(handler, 200, info)


def _send_file_bytes(handler: BaseHTTPRequestHandler) -> None:
    resolved, query = _request_file(handler)
    if resolved is None:
        return
    inline = (query.get("inline") or [""])[0] == "1"
    info = file_kind(resolved)
    if info is None:
        _send_json(handler, 404, {"error": "not_found"})
        return
    if inline:
        if info["kind"] == "too_large" and resolved.suffix.lower() in _IMAGE_TYPES:
            _send_json(handler, 413, {"error": "too_large"})
            return
        if info["kind"] != "image":
            _send_json(handler, 400, {"error": "not_an_image"})
            return
        try:
            body = resolved.read_bytes()
        except OSError:
            _send_json(handler, 404, {"error": "not_found"})
            return
        _send_bytes(handler, 200, body, str(info["media_type"]))
        return
    try:
        body = resolved.read_bytes()
    except OSError:
        _send_json(handler, 404, {"error": "not_found"})
        return
    disposition = f"attachment; filename*=UTF-8''{quote(resolved.name)}"
    _send_bytes(
        handler,
        200,
        body,
        "application/octet-stream",
        (("Content-Disposition", disposition),),
    )


def _entry_name(value: object) -> str | None:
    """新名字只能是一个路径段。"""
    if not isinstance(value, str) or value in {"", ".", ".."}:
        return None
    if "/" in value or "\\" in value:
        return None
    return value


def _rename_file(handler: BaseHTTPRequestHandler) -> None:
    payload = _object_body(_read_body(handler))
    if payload is None:
        _send_json(handler, 400, {"error": "bad_name"})
        return
    raw = payload.get("path")
    name = _entry_name(payload.get("name"))
    if not isinstance(raw, str) or raw.strip() == "" or name is None:
        _send_json(handler, 400, {"error": "bad_name"})
        return
    source = Path(raw).expanduser()
    try:
        present = source.is_symlink() or source.exists()
    except OSError:
        present = False
    if not present:
        _send_json(handler, 404, {"error": "not_found"})
        return
    destination = source.parent / name
    try:
        taken = destination.exists() or destination.is_symlink()
    except OSError:
        taken = True
    if taken:
        _send_json(handler, 409, {"error": "exists"})
        return
    try:
        source.replace(destination)
    except OSError:
        _send_json(handler, 404, {"error": "not_found"})
        return
    _send_json(handler, 200, {"path": str(destination), "name": destination.name})


def _delete_file(handler: BaseHTTPRequestHandler) -> None:
    payload = _object_body(_read_body(handler))
    raw = None if payload is None else payload.get("path")
    if not isinstance(raw, str) or raw.strip() == "":
        _send_json(handler, 404, {"error": "not_found"})
        return
    source = Path(raw).expanduser()
    try:
        if source.is_symlink():
            source.unlink()
            _send_json(handler, 200, {"ok": True})
            return
        resolved = source.resolve()
    except OSError:
        _send_json(handler, 404, {"error": "not_found"})
        return
    if not resolved.exists():
        _send_json(handler, 404, {"error": "not_found"})
        return
    if resolved.parent == resolved:
        _send_json(handler, 400, {"error": "bad_path"})
        return
    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        elif resolved.is_file():
            resolved.unlink()
        else:
            _send_json(handler, 404, {"error": "not_found"})
            return
    except OSError:
        _send_json(handler, 404, {"error": "not_found"})
        return
    _send_json(handler, 200, {"ok": True})


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _send_bytes(handler, status, body, _JSON)


def _send_bytes(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    content_type: str,
    headers: tuple[tuple[str, str], ...] = (),
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    for name, value in headers:
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)
