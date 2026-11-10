"""工作目录里的会话目录。

文件在 ``{workspace}/.vector/sessions/{id}.jsonl``。id 必须整段匹配
``^[0-9a-f]{32}$``。一行一个 JSON 对象。本模块不进入工具循环。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4


def is_session_id(value: str) -> bool:
    """32 位小写十六进制才是会话 id。"""
    return re.fullmatch(r"[0-9a-f]{32}", value) is not None


def list_sessions(workspace: Path) -> list[dict]:
    """列出会话。修改时间新的在前；时间相同则按 id 升序。

    标题取第一条 ``role == "user"`` 的 ``content`` 再 strip。结果为空就用 id。
    会话目录不存在时返回空列表。
    """
    directory = _sessions_dir(workspace)
    if not directory.is_dir():
        return []
    items: list[dict] = []
    for path in directory.iterdir():
        session_id = _id_of(path)
        if session_id is None:
            continue
        items.append(
            {
                "id": session_id,
                "title": _title(path, session_id),
                "updated_at": path.stat().st_mtime,
            }
        )
    items.sort(key=lambda item: (-item["updated_at"], item["id"]))
    return items


def create_session(workspace: Path) -> str:
    """创建空会话文件并返回 id。"""
    directory = _sessions_dir(workspace)
    directory.mkdir(parents=True, exist_ok=True)
    session_id = uuid4().hex
    path = directory / f"{session_id}.jsonl"
    path.write_text("", encoding="utf-8")
    return session_id


def read_messages(workspace: Path, session_id: str) -> list[dict]:
    """读出消息对象。非法 id 在拼接路径之前拒绝。文件不存在则抛出 FileNotFoundError。

    空行、无法解析的行，以及不是 JSON 对象的行都跳过。
    """
    if not is_session_id(session_id):
        raise ValueError(session_id)
    path = _sessions_dir(workspace) / f"{session_id}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(path)
    return list(_objects(path))


def _sessions_dir(workspace: Path) -> Path:
    return workspace / ".vector" / "sessions"


def _id_of(path: Path) -> str | None:
    if not path.is_file() or path.suffix != ".jsonl":
        return None
    session_id = path.stem
    if not is_session_id(session_id):
        return None
    return session_id


def _title(path: Path, session_id: str) -> str:
    for message in _objects(path):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            return session_id
        return content.strip() or session_id
    return session_id


def _objects(path: Path) -> list[dict]:
    messages: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            messages.append(data)
    return messages
