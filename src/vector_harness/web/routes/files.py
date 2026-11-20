"""Filesystem and static asset HTTP adapters."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from vector_harness.web.config import CONFIG_ERRORS
from vector_harness.web.files import delete_entry, dir_listing, file_in_dist, file_kind, rename_entry, resolve_entry
from vector_harness.web.http import is_root, media_type, object_body, query_first, read_body, send_bytes, send_error, \
    send_json, stream_file

_NO_DIST = "页面还没有构建。请先在 web/ 执行 npm run build。\n"


def workdir(app, handler, _variables):
    send_json(handler, 200, {"path": str(app.workdir)})


def dirs(app, handler, _variables):
    raw = query_first(handler.path, "path")
    target = app.workdir if raw is None or not raw.strip() else Path(raw)
    listing = dir_listing(target)
    if listing is None:
        send_error(handler, 400, "not_a_directory")
        return
    send_json(handler, 200, listing)


def set_workdir(app, handler, _variables):
    payload = object_body(read_body(handler))
    raw = payload.get("path") if payload else None
    if not isinstance(raw, str) or not raw.strip():
        send_error(handler, 400, "bad_request")
        return
    listing = dir_listing(Path(raw))
    if listing is None:
        send_error(handler, 400, "not_a_directory")
        return
    with app.sessions.exclusive():
        target = Path(listing["path"])
        if app.settings.config_file is not None:
            try:
                app.save_workdir(target)
            except CONFIG_ERRORS:
                send_error(handler, 500, "config_save_failed")
                return
        app.workdir = target
        send_json(handler, 200, {"path": str(app.workdir)})


def file_meta(app, handler, _variables):
    resolved, failure = resolve_entry(query_first(handler.path, "path"))
    if failure is not None:
        send_json(handler, *failure)
        return
    info = file_kind(resolved)
    if info is None:
        send_error(handler, 404, "not_found")
        return
    send_json(handler, 200, info)


def file_bytes(app, handler, _variables):
    resolved, failure = resolve_entry(query_first(handler.path, "path"))
    if failure is not None:
        send_json(handler, *failure)
        return
    info = file_kind(resolved)
    if info is None:
        send_error(handler, 404, "not_found")
        return
    if query_first(handler.path, "inline") == "1":
        if info["kind"] == "too_large" and resolved.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
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
    disposition = f"attachment; filename*=UTF-8''{quote(resolved.name)}"
    stream_file(handler, resolved, "application/octet-stream", (("Content-Disposition", disposition),))


def rename(app, handler, _variables):
    payload = object_body(read_body(handler))
    if payload is None:
        send_error(handler, 400, "bad_name")
        return
    send_json(handler, *rename_entry(payload.get("path"), payload.get("name")))


def delete(app, handler, _variables):
    payload = object_body(read_body(handler))
    send_json(handler, *delete_entry(None if payload is None else payload.get("path")))


def serve_static(app, handler):
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


ROUTES = [
    ("GET", ("api", "workdir"), workdir),
    ("POST", ("api", "workdir"), set_workdir),
    ("GET", ("api", "dirs"), dirs),
    ("GET", ("api", "file"), file_meta),
    ("GET", ("api", "file", "bytes"), file_bytes),
    ("POST", ("api", "file", "rename"), rename),
    ("DELETE", ("api", "file"), delete),
]
