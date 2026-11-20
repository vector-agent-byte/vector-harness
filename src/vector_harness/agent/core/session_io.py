from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from vector_harness.agent.core.codec import message_from_dict
from vector_harness.types import Message


class SessionCorruptionError(ValueError):
    pass


@dataclass
class SessionScan:
    messages: list[Message] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)
    issue: str | None = None
    valid_bytes: int = 0
    tail: bytes = b""


def scan_session(path: Path, *, tolerant: bool = False) -> SessionScan:
    result = SessionScan()
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return result
    lines = data.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            if result.issue is None:
                result.valid_bytes += len(line)
            continue
        try:
            record = json.loads(line.decode("utf-8"))
            if not isinstance(record, dict):
                raise ValueError("not a message object")
            message = message_from_dict(record)
            if not isinstance(message.role, str) or message.role not in {"user", "assistant", "tool"} or not isinstance(message.content, str):
                raise ValueError("invalid message")
            if not isinstance(message.is_error, bool):
                raise ValueError("invalid result error flag")
            if message.tool_call_id is not None and not isinstance(message.tool_call_id, str):
                raise ValueError("invalid result call identifier")
            if message.role == "tool" and not isinstance(message.tool_call_id, str):
                raise ValueError("missing result call identifier")
            for call in message.tool_calls or []:
                if not isinstance(call.id, str) or not isinstance(call.name, str):
                    raise ValueError("invalid tool call")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            partial = index == len(lines) - 1 and not line.endswith((b"\n", b"\r"))
            if partial and result.issue is None:
                result.issue = "partial_tail"
                result.tail = data[result.valid_bytes:]
            else:
                result.issue = "invalid_record"
                if not tolerant:
                    raise SessionCorruptionError(f"会话记录损坏：第 {index + 1} 行，不能继续执行") from exc
            continue
        result.messages.append(message)
        result.records.append(record)
        if result.issue is None:
            result.valid_bytes += len(line)
    return result


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def repair_partial_tail(path: Path) -> Path | None:
    scan = scan_session(path)
    if scan.issue != "partial_tail":
        return None
    backup = path.with_name(f"{path.stem}.recovery-{uuid4().hex}.bin")
    with backup.open("xb") as stream:
        stream.write(scan.tail)
        stream.flush()
        os.fsync(stream.fileno())
    original = path.read_bytes()
    if original[scan.valid_bytes:] != scan.tail:
        raise SessionCorruptionError("会话在恢复期间发生变化，未修改原文件")
    atomic_write_bytes(path, original[:scan.valid_bytes])
    return backup
