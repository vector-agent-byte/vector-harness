"""本机 HTTP：路由表、服务器生命周期和各个接口。

业务细节分在三个地方：``web_http`` 只管写响应和事件流，``web_files`` 是
目录与文件的纯逻辑，``web_runs`` 管「同一时间只跑一轮」。这里只剩把请求
分派给它们，并把结果写回去。

绑定调用方传入的地址，默认 ``127.0.0.1``。本模块不进入工具循环。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from vector_harness.patterns.skills import Skills
from vector_harness.web_files import (
    delete_entry,
    dir_listing,
    file_in_dist,
    file_kind,
    rename_entry,
    resolve_entry,
)
from vector_harness.web_http import (
    begin_event_stream,
    event_payload,
    is_root,
    media_type,
    object_body,
    query_first,
    read_body,
    segments,
    send_bytes,
    send_error,
    send_json,
    stream_file,
    write_event,
)
from vector_harness.web_runs import RunManager, RunSettings
from vector_harness.web_sessions import (
    create_session,
    delete_session,
    is_session_id,
    list_sessions,
    read_messages,
    session_path,
    session_run,
    session_skill,
    set_session_skill,
)

_logger = logging.getLogger("vector_harness.web")

_NO_DIST = "页面还没有构建。请先在 web/ 执行 npm run build。\n"
# 页面上的三种模式。缺省时沿用启动服务时的 --plan / --reflect。
_MODES = {
    "react": (False, False),
    "plan": (True, False),
    "reflect": (False, True),
}


def _setup_log(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-5s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG)


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
        _setup_log(settings.workspace / ".vector" / "server.log")
        self.port = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._handler_stream: BaseHTTPRequestHandler | None = None
        self.runs = RunManager(
            RunSettings(
                workspace=settings.workspace,
                workdir=lambda: self.workdir,
                skills_dir=settings.skills_dir,
                memory_path=settings.memory_path,
                compact=settings.compact,
                plan=settings.plan,
                reflect=settings.reflect,
                subagents=settings.subagents,
                max_steps=settings.max_steps,
            ),
            provider,
            self._emit,
        )

    @property
    def running_id(self) -> str | None:
        """正在跑的那一轮的会话 id。"""
        return self.runs.running_id

    def request_stop(self, session_id: str) -> bool:
        """停下正在跑的那一轮。不是这一份会话时返回 False。"""
        return self.runs.stop(session_id)

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

    def _emit(self, event) -> None:
        """一轮里的事件写到当时那条响应上。没有在写的响应时丢掉。"""
        handler = self._handler_stream
        if handler is None:
            return
        write_event(handler, event_payload(event))


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
        _logger.info(format, *args)


# 路由表。(方法, 路径段, 处理器)。路径段里的 None 是一段变量，
# 段数必须完全一致。先匹配到的先执行。
_ROUTES: list[tuple[str, tuple[str | None, ...], object]] = [
    ("GET", ("api", "skills"), "skills"),
    ("GET", ("api", "workdir"), "workdir"),
    ("GET", ("api", "dirs"), "dirs"),
    ("POST", ("api", "workdir"), "set_workdir"),
    ("GET", ("api", "file", "bytes"), "file_bytes"),
    ("GET", ("api", "file"), "file_meta"),
    ("POST", ("api", "file", "rename"), "rename"),
    ("DELETE", ("api", "file"), "delete"),
    ("GET", ("api", "sessions"), "list_sessions"),
    ("POST", ("api", "sessions"), "create_session"),
    ("GET", ("api", "sessions", None), "read_session"),
    ("DELETE", ("api", "sessions", None), "delete_session"),
    ("POST", ("api", "sessions", None, "messages"), "messages"),
    ("POST", ("api", "sessions", None, "stop"), "stop"),
    ("POST", ("api", "sessions", None, "skill"), "skill"),
]

_HANDLERS: dict[str, object] | None = None


def _handlers() -> dict[str, object]:
    """名字到处理器的表。第一次取用时装配，函数定义都在下面。"""
    global _HANDLERS
    if _HANDLERS is None:
        _HANDLERS = {
            "skills": _handle_skills,
            "workdir": _handle_workdir,
            "dirs": _handle_dirs,
            "set_workdir": _handle_set_workdir,
            "file_bytes": _handle_file_bytes,
            "file_meta": _handle_file_meta,
            "rename": _handle_rename,
            "delete": _handle_delete,
            "list_sessions": _handle_list_sessions,
            "create_session": _handle_create_session,
            "read_session": _handle_read_session,
            "delete_session": _handle_delete_session,
            "messages": _handle_messages,
            "stop": _handle_stop,
            "skill": _handle_skill,
        }
    return _HANDLERS


def _route(handler: BaseHTTPRequestHandler, method: str) -> None:
    server = handler.server
    assert isinstance(server, _BoundServer)
    app = server.app
    parts = segments(handler.path)
    if parts[:1] == ["api"]:
        name, variables = _match(method, parts)
        if name is not None:
            _handlers()[name](app, handler, variables)
            return
        send_error(handler, 404, "not_found")
        return
    if method == "GET":
        _serve_static(app, handler)
        return
    send_error(handler, 404, "not_found")


def _match(
    method: str, parts: list[str]
) -> tuple[str | None, list[str]]:
    """按路由表找处理器。变量段按出现顺序返回。"""
    for route_method, shape, name in _ROUTES:
        if route_method != method or len(shape) != len(parts):
            continue
        variables: list[str] = []
        for expected, actual in zip(shape, parts):
            if expected is None:
                variables.append(actual)
            elif expected != actual:
                break
        else:
            return name, variables
    return None, []


def _provider_model(provider: object) -> str:
    """页面展示当前模型名。测试里的假提供方可以没有这个属性。"""
    model = getattr(provider, "model", "")
    return model if isinstance(model, str) else ""


def _skill_catalog(app: WebServer) -> list[dict[str, str]]:
    directory = app.settings.skills_dir
    if directory is None:
        return []
    return Skills(directory).catalog()


def _handle_skills(app: WebServer, handler, _variables: list[str]) -> None:
    send_json(handler, 200, {"skills": _skill_catalog(app)})


def _handle_workdir(app: WebServer, handler, _variables: list[str]) -> None:
    send_json(handler, 200, {"path": str(app.workdir)})


def _handle_create_session(app: WebServer, handler, _variables: list[str]) -> None:
    send_json(handler, 201, {"id": create_session(app.settings.workspace)})


def _handle_list_sessions(app: WebServer, handler, _variables: list[str]) -> None:
    send_json(
        handler,
        200,
        {
            "sessions": list_sessions(app.settings.workspace),
            "running_id": app.running_id,
            "model": _provider_model(app.provider),
        },
    )


def _handle_read_session(app: WebServer, handler, variables: list[str]) -> None:
    session_id = variables[0]
    if not is_session_id(session_id):
        send_error(handler, 400, "bad_session")
        return
    workspace = app.settings.workspace
    try:
        messages = read_messages(workspace, session_id)
    except FileNotFoundError:
        send_error(handler, 404, "not_found")
        return
    started_at, duration_ms = session_run(workspace, session_id)
    send_json(
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


def _handle_delete_session(app: WebServer, handler, variables: list[str]) -> None:
    """删掉一份空闲会话。正在跑的那一轮拿着锁，这里拿不到就拒绝。"""
    session_id = variables[0]
    if not is_session_id(session_id):
        send_error(handler, 400, "bad_session")
        return
    if not app.runs.acquire():
        send_error(handler, 409, "busy")
        return
    try:
        try:
            delete_session(app.settings.workspace, session_id)
        except FileNotFoundError:
            send_error(handler, 404, "not_found")
            return
        send_json(handler, 200, {"deleted": True})
    finally:
        app.runs.release()


def _handle_stop(app: WebServer, handler, variables: list[str]) -> None:
    """停止正在跑的会话。没有这一轮时 ``stopped`` 为 false。"""
    session_id = variables[0]
    if not is_session_id(session_id):
        send_error(handler, 400, "bad_session")
        return
    send_json(handler, 200, {"stopped": app.request_stop(session_id)})


def _handle_skill(app: WebServer, handler, variables: list[str]) -> None:
    """给这一份会话单独记下技能。空名字表示不使用技能。"""
    session_id = variables[0]
    if not is_session_id(session_id):
        send_error(handler, 400, "bad_session")
        return
    payload = object_body(read_body(handler))
    if payload is None or "name" not in payload:
        send_error(handler, 400, "bad_request")
        return
    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        send_error(handler, 400, "bad_request")
        return
    chosen = name.strip() if isinstance(name, str) else ""
    if chosen and chosen not in {item["name"] for item in _skill_catalog(app)}:
        send_error(handler, 400, "unknown_skill")
        return
    try:
        set_session_skill(app.settings.workspace, session_id, chosen or None)
    except FileNotFoundError:
        send_error(handler, 404, "not_found")
        return
    send_json(handler, 200, {"id": session_id, "skill": chosen or None})


def _handle_messages(app: WebServer, handler, variables: list[str]) -> None:
    """发送一句。检查失败时返回 JSON，成功时把这一轮流式写回去。"""
    session_id = variables[0]
    raw = read_body(handler)
    if not is_session_id(session_id):
        send_error(handler, 400, "bad_session")
        return
    path = session_path(app.settings.workspace, session_id)
    if not path.is_file():
        send_error(handler, 404, "not_found")
        return
    request = _message_request(raw)
    if request is None:
        send_error(handler, 400, "bad_request")
        return
    text, mode = request
    if text.strip() == "":
        send_error(handler, 400, "empty")
        return
    if mode is None:
        plan, reflect = app.settings.plan, app.settings.reflect
    else:
        plan, reflect = _MODES[mode]
    # 锁在启动运行之前就占住，一直留到 run 返回。第二次发送拿不到锁。
    if not app.runs.acquire():
        send_error(handler, 409, "busy")
        return
    app._handler_stream = handler
    begin_event_stream(handler)
    try:
        status, content = app.runs.run(
            session_id, path, text, plan=plan, reflect=reflect
        )
        write_event(
            handler,
            {
                "kind": "run_result",
                "status": status,
                "text": content,
                "name": "",
                "tool_call_id": "",
                "arguments": None,
                "origin": "",
            },
        )
    finally:
        app._handler_stream = None
        app.runs.release()


def _message_request(raw: bytes) -> tuple[str, str | None] | None:
    """正文必须是带字符串 ``text`` 的 JSON 对象。

    ``mode`` 可以不写。写出时只能是 ``react``、``plan``、``reflect``。
    返回 ``(text, mode)``；``mode`` 为 None 表示沿用启动参数。格式不对返回 None。
    """
    payload = object_body(raw)
    if payload is None:
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


def _handle_dirs(app: WebServer, handler, _variables: list[str]) -> None:
    """列出某个目录下的子目录和文件。没给路径时从当前工作目录开始。"""
    raw = query_first(handler.path, "path")
    target = app.workdir if raw is None or raw.strip() == "" else Path(raw)
    listing = dir_listing(target)
    if listing is None:
        send_error(handler, 400, "not_a_directory")
        return
    send_json(handler, 200, listing)


def _handle_set_workdir(app: WebServer, handler, _variables: list[str]) -> None:
    """改工具使用的工作目录。会话仍留在启动服务时的目录里。有一轮正在跑时不改。"""
    payload = object_body(read_body(handler))
    if payload is None:
        send_error(handler, 400, "bad_request")
        return
    raw = payload.get("path")
    if not isinstance(raw, str) or raw.strip() == "":
        send_error(handler, 400, "bad_request")
        return
    listing = dir_listing(Path(raw))
    if listing is None:
        send_error(handler, 400, "not_a_directory")
        return
    if not app.runs.acquire():
        send_error(handler, 409, "busy")
        return
    try:
        app.workdir = Path(listing["path"])
        send_json(handler, 200, {"path": str(app.workdir)})
    finally:
        app.runs.release()


def _handle_file_meta(app: WebServer, handler, _variables: list[str]) -> None:
    resolved, failure = resolve_entry(query_first(handler.path, "path"))
    if failure is not None:
        send_json(handler, *failure)
        return
    info = file_kind(resolved)
    if info is None:
        send_error(handler, 404, "not_found")
        return
    send_json(handler, 200, info)


def _handle_file_bytes(app: WebServer, handler, _variables: list[str]) -> None:
    resolved, failure = resolve_entry(query_first(handler.path, "path"))
    if failure is not None:
        send_json(handler, *failure)
        return
    inline = query_first(handler.path, "inline") == "1"
    info = file_kind(resolved)
    if info is None:
        send_error(handler, 404, "not_found")
        return
    if inline:
        if info["kind"] == "too_large" and resolved.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
        }:
            send_error(handler, 413, "too_large")
            return
        if info["kind"] != "image":
            send_error(handler, 400, "not_an_image")
            return
        try:
            body = resolved.read_bytes()
        except OSError:
            send_error(handler, 404, "not_found")
            return
        send_bytes(handler, 200, body, str(info["media_type"]))
        return
    from urllib.parse import quote

    disposition = f"attachment; filename*=UTF-8''{quote(resolved.name)}"
    stream_file(
        handler,
        resolved,
        "application/octet-stream",
        (("Content-Disposition", disposition),),
    )


def _handle_rename(app: WebServer, handler, _variables: list[str]) -> None:
    payload = object_body(read_body(handler))
    if payload is None:
        send_error(handler, 400, "bad_name")
        return
    send_json(handler, *rename_entry(payload.get("path"), payload.get("name")))


def _handle_delete(app: WebServer, handler, _variables: list[str]) -> None:
    payload = object_body(read_body(handler))
    raw = None if payload is None else payload.get("path")
    send_json(handler, *delete_entry(raw))


def _serve_static(app: WebServer, handler) -> None:
    dist = app.settings.dist_dir
    index = None if dist is None else dist / "index.html"
    if index is not None and index.is_file() and dist is not None:
        target = file_in_dist(dist, handler.path)
        chosen = target if target is not None else index
        send_bytes(handler, 200, chosen.read_bytes(), media_type(chosen))
        return
    if is_root(handler.path):
        send_bytes(handler, 503, _NO_DIST.encode("utf-8"), "text/plain; charset=utf-8")
        return
    send_error(handler, 404, "not_found")
