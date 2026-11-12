"""工作目录里的会话目录。

文件在 ``{workspace}/.vector/sessions/{id}.jsonl``。id 必须整段匹配
``^[0-9a-f]{32}$``。一行一个 JSON 对象。本模块不进入工具循环。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from uuid import uuid4


def is_session_id(value: str) -> bool:
    """32 位小写十六进制才是会话 id。"""
    return re.fullmatch(r"[0-9a-f]{32}", value) is not None


def session_path(workspace: Path, session_id: str) -> Path:
    """一份会话的 JSONL 路径。id 不合法时抛出 ``ValueError``。"""
    if not is_session_id(session_id):
        raise ValueError(session_id)
    return _sessions_dir(workspace) / f"{session_id}.jsonl"


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
        started_at, duration_ms = _read_run(directory / f"{session_id}.run.json")
        items.append(
            {
                "id": session_id,
                "title": _title(path, session_id),
                "updated_at": path.stat().st_mtime,
                "skill": _read_skill_file(directory / f"{session_id}.skill"),
                "started_at": started_at,
                "duration_ms": duration_ms,
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


def session_skill(workspace: Path, session_id: str) -> str | None:
    """这个会话单独选中的技能。没选过、或文件是空的，返回 None。"""
    if not is_session_id(session_id):
        raise ValueError(session_id)
    return _read_skill_file(_sessions_dir(workspace) / f"{session_id}.skill")


def set_session_skill(workspace: Path, session_id: str, name: str | None) -> None:
    """记下这个会话的技能。``name`` 为空就清掉。会话文件不存在时抛出 FileNotFoundError。"""
    if not is_session_id(session_id):
        raise ValueError(session_id)
    directory = _sessions_dir(workspace)
    if not (directory / f"{session_id}.jsonl").is_file():
        raise FileNotFoundError(session_id)
    path = directory / f"{session_id}.skill"
    if not name:
        path.unlink(missing_ok=True)
        return
    path.write_text(name + "\n", encoding="utf-8")


def session_run(workspace: Path, session_id: str) -> tuple[float | None, int | None]:
    """最近一轮的触发时间和耗时。没跑过时两项都是 None。耗时在这一轮结束前也是 None。"""
    if not is_session_id(session_id):
        raise ValueError(session_id)
    return _read_run(_sessions_dir(workspace) / f"{session_id}.run.json")


def begin_run(workspace: Path, session_id: str) -> None:
    """记下这一轮的触发时间，并清掉上一轮的耗时。"""
    if not is_session_id(session_id):
        raise ValueError(session_id)
    _write_run(_sessions_dir(workspace) / f"{session_id}.run.json", time.time(), None)


def finish_run(workspace: Path, session_id: str) -> None:
    """用触发时间算出耗时。没有触发时间时从现在起算，结果是 0。"""
    if not is_session_id(session_id):
        raise ValueError(session_id)
    path = _sessions_dir(workspace) / f"{session_id}.run.json"
    started_at, _duration = _read_run(path)
    if started_at is None:
        started_at = time.time()
    duration_ms = max(0, int((time.time() - started_at) * 1000))
    _write_run(path, started_at, duration_ms)


def delete_session(workspace: Path, session_id: str) -> None:
    """删掉会话正文、选中的技能和这一轮的计时。文件不存在时抛出 FileNotFoundError。"""
    if not is_session_id(session_id):
        raise ValueError(session_id)
    directory = _sessions_dir(workspace)
    path = directory / f"{session_id}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(session_id)
    path.unlink()
    (directory / f"{session_id}.skill").unlink(missing_ok=True)
    (directory / f"{session_id}.run.json").unlink(missing_ok=True)


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


def _read_run(path: Path) -> tuple[float | None, int | None]:
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    started = data.get("started_at")
    duration = data.get("duration_ms")
    started_at = float(started) if isinstance(started, (int, float)) and not isinstance(started, bool) else None
    duration_ms = duration if isinstance(duration, int) and not isinstance(duration, bool) else None
    return started_at, duration_ms


def _write_run(path: Path, started_at: float, duration_ms: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"started_at": started_at, "duration_ms": duration_ms}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_skill_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    name = path.read_text(encoding="utf-8").strip()
    return name or None


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
