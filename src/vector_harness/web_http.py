"""HTTP 上的字节和事件流。

只关心「怎么把一段内容写回响应」，不关心是谁要求的。
路由和业务判断在 ``web_server`` 和 ``web_files`` 里。
"""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from vector_harness.types import ProviderEvent

JSON = "application/json; charset=utf-8"
EVENT_STREAM = "text/event-stream"


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    send_bytes(handler, status, body, JSON)


def send_error(handler: BaseHTTPRequestHandler, status: int, code: str) -> None:
    """页面只认 ``{"error": code}``。"""
    send_json(handler, status, {"error": code})


def send_bytes(
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


def stream_file(
    handler: BaseHTTPRequestHandler,
    path: Path,
    content_type: str,
    headers: tuple[tuple[str, str], ...] = (),
) -> None:
    """按块送出文件。大小先写进头，读不出来时改成 404。"""
    try:
        size = path.stat().st_size
        handle = path.open("rb")
    except OSError:
        send_error(handler, 404, "not_found")
        return
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(size))
        for name, value in headers:
            handler.send_header(name, value)
        handler.end_headers()
        while True:
            chunk = handle.read(64 * 1024)
            if not chunk:
                break
            handler.wfile.write(chunk)
    finally:
        handle.close()


def media_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    if guessed is None:
        return "application/octet-stream"
    if guessed.startswith("text/") or guessed in {
        "application/javascript",
        "application/json",
    }:
        return f"{guessed}; charset=utf-8"
    return guessed


def read_body(handler: BaseHTTPRequestHandler) -> bytes:
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


def object_body(raw: bytes) -> dict | None:
    """正文必须是 JSON 对象。不是就返回 None。"""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def segments(url_path: str) -> list[str]:
    """路径按 ``/`` 切开并逐段解码。空段丢掉。"""
    raw = urlsplit(url_path).path
    return [unquote(part) for part in raw.split("/") if part]


def query_first(url_path: str, name: str) -> str | None:
    """查询串里某个参数的第一个值。"""
    values = parse_qs(urlsplit(url_path).query).get(name, [])
    return values[0] if values else None


def is_root(url_path: str) -> bool:
    return urlsplit(url_path).path in ("", "/")


def event_payload(event: ProviderEvent) -> dict[str, object]:
    """循环事件原样转成事件流对象，字段与 ``ProviderEvent`` 一致。"""
    return {
        "kind": event.kind,
        "text": event.text,
        "name": event.name,
        "tool_call_id": event.tool_call_id,
        "arguments": event.arguments,
        "origin": event.origin,
    }


def begin_event_stream(handler: BaseHTTPRequestHandler) -> None:
    """先把 200 和事件流类型写出去，后面的增量才能在这一轮结束前被看见。"""
    handler.send_response(200)
    handler.send_header("Content-Type", EVENT_STREAM)
    handler.end_headers()
    handler.wfile.flush()


def write_event(handler: BaseHTTPRequestHandler, payload: dict[str, object]) -> None:
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
