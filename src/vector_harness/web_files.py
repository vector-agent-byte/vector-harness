"""工作目录里的目录清单、文件预览、重命名和删除。

这里的函数不写响应，只返回 ``(状态码, 响应体)``。路由和写出在 ``web_server``。
链接的判断也是纯函数，可以直接单测。
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

PREVIEW_LIMIT = 2 * 1024 * 1024

TEXT_SUFFIXES = {
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

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def dir_listing(path: Path) -> dict | None:
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
            entry = {"name": child.name, "path": str(child)}
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
    if suffix in TEXT_SUFFIXES or suffix in IMAGE_TYPES:
        if size > PREVIEW_LIMIT:
            info["kind"] = "too_large"
            return info
    if suffix in TEXT_SUFFIXES:
        try:
            info["text"] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        info["kind"] = "text"
        return info
    media = IMAGE_TYPES.get(suffix)
    if media is not None:
        info["kind"] = "image"
        info["media_type"] = media
        return info
    info["kind"] = "unsupported"
    return info


def resolve_entry(raw: object) -> tuple[Path | None, tuple[int, dict] | None]:
    """请求里的路径变成已解析的条目。不是存在的路径时给出状态码和响应体。"""
    if not isinstance(raw, str) or raw.strip() == "":
        return None, (404, {"error": "not_found"})
    try:
        resolved = Path(raw).expanduser().resolve()
    except OSError:
        return None, (404, {"error": "not_found"})
    if not resolved.exists():
        return None, (404, {"error": "not_found"})
    if resolved.is_dir():
        return None, (400, {"error": "not_a_file"})
    return resolved, None


def safe_name(value: object) -> str | None:
    """新名字只能是一个路径段。"""
    if not isinstance(value, str) or value.strip() in {"", ".", ".."}:
        return None
    if any(char in value for char in "/\\:"):
        return None
    return value


def is_junction(path: Path) -> bool:
    """目录联接（junction）。``Path.is_junction`` 在 3.12 才有，这里用属性位判断。

    junction 在 ``lstat`` 里是一个带重解析点的目录，``is_symlink()`` 返回 False。
    必须在这里认出来，否则删除会顺着它删掉真实目标。
    """
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not reparse or not attributes & reparse:
        return False
    # 只认目录联接，符号链接交给 is_symlink()。
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def is_directory_link(path: Path) -> bool:
    if is_junction(path):
        return True
    try:
        return path.is_symlink() and path.is_dir()
    except OSError:
        return False


def remove_link(path: Path) -> None:
    """只去掉链接本身。目录链接用 rmdir，避免沿链接删掉目标。"""
    if is_directory_link(path) and os.name == "nt":
        path.rmdir()
        return
    path.unlink()


def rename_entry(raw: object, name: object) -> tuple[int, dict]:
    """把 ``raw`` 所指的条目在同一目录内改名。返回状态码和响应体。"""
    new_name = safe_name(name)
    if not isinstance(raw, str) or raw.strip() == "" or new_name is None:
        return 400, {"error": "bad_name"}
    source = Path(raw).expanduser()
    try:
        present = source.is_symlink() or source.exists()
    except OSError:
        present = False
    if not present:
        return 404, {"error": "not_found"}
    destination = source.parent / new_name
    if not _rename_leaves_parent(source, new_name, destination):
        return 400, {"error": "bad_name"}
    try:
        taken = destination.exists() or destination.is_symlink()
        same_file = taken and source.samefile(destination)
    except OSError:
        taken = True
        same_file = False
    if taken and not (same_file and source.name != destination.name):
        return 409, {"error": "exists"}
    try:
        source.replace(destination)
    except OSError:
        return 500, {"error": "rename_failed"}
    return 200, {"path": str(destination), "name": destination.name}


def delete_entry(raw: object) -> tuple[int, dict]:
    """删掉一个文件、目录或链接。

    链接只去掉链接本身。删除整棵目录时在调用时取 ``shutil.rmtree``，
    这样测试可以换成会失败的版本。
    """
    if not isinstance(raw, str) or raw.strip() == "":
        return 404, {"error": "not_found"}
    source = Path(raw).expanduser()
    try:
        linked = source.is_symlink() or is_junction(source)
    except OSError:
        linked = False
    if linked:
        try:
            remove_link(source)
        except OSError:
            return 500, {"error": "delete_failed"}
        return 200, {"ok": True}
    try:
        resolved = source.resolve()
    except OSError:
        return 404, {"error": "not_found"}
    if not resolved.exists():
        return 404, {"error": "not_found"}
    if resolved.parent == resolved:
        return 400, {"error": "bad_path"}
    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        elif resolved.is_file():
            resolved.unlink()
        else:
            return 404, {"error": "not_found"}
    except OSError:
        return 500, {"error": "delete_failed"}
    return 200, {"ok": True}


def file_in_dist(dist: Path, url_path: str) -> Path | None:
    """解码后的路径必须落在 dist 里，并且是文件。越界或缺失都交回 index.html。"""
    from urllib.parse import unquote, urlsplit

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


def _rename_leaves_parent(source: Path, name: str, destination: Path) -> bool:
    if destination.name != name:
        return False
    if os.path.normcase(str(destination.parent)) != os.path.normcase(str(source.parent)):
        return False
    try:
        resolved = destination.resolve()
        parent = source.parent.resolve()
    except OSError:
        return False
    return resolved != parent
