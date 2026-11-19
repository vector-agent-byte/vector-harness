from __future__ import annotations

from copy import deepcopy
import logging
from pathlib import Path

from vector_harness.core.session import Session
from vector_harness.core.session_io import SessionCorruptionError
from vector_harness.core.session_state import SessionArtifacts
from vector_harness.types import Message

INTERRUPTED_RESULT = "上次运行中断，执行结果未知；不可据此认定未执行或成功，请先核查实际状态，不要自动重放。"


def workdir_context(session: Session, workdir: Path | None) -> str:
    if workdir is None:
        return ""
    current = str(workdir.resolve())
    artifacts = SessionArtifacts(session)
    previous = (artifacts.load("context") or {}).get("last_workdir")
    text = f"[当前运行环境]\n工作目录：{current}"
    if isinstance(previous, str) and previous != current:
        text += f"\n此前工作目录：{previous}。目录已变更，旧路径、文件状态和验证结果必须重新核查。"
    elif not isinstance(previous, str):
        text += "\n此前工作目录：未知。"
    return text


def confirm_workdir(session: Session, workdir: Path | None) -> None:
    if workdir is None:
        return
    try:
        SessionArtifacts(session).update("context", {"last_workdir": str(workdir.resolve())})
    except OSError:
        logging.getLogger(__name__).warning("Unable to save current workdir; runtime context remains available")


def repair_tool_pairs(messages: list[Message]) -> list[Message]:
    projected: list[Message] = []
    position = 0
    while position < len(messages):
        message = messages[position]
        if message.role == "tool":
            raise SessionCorruptionError("会话包含无法关联的工具结果，不能继续执行")
        projected.append(deepcopy(message))
        position += 1
        if not message.tool_calls:
            continue
        identifiers = [call.id for call in message.tool_calls]
        if message.role != "assistant" or any(not isinstance(identifier, str) for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
            raise SessionCorruptionError("会话工具调用组无效")
        pending = set(identifiers)
        while position < len(messages) and messages[position].role == "tool":
            result = messages[position]
            if not isinstance(result.tool_call_id, str) or result.tool_call_id not in pending:
                raise SessionCorruptionError("会话工具结果重复或不属于当前调用组")
            pending.remove(result.tool_call_id)
            projected.append(deepcopy(result))
            position += 1
        for identifier in identifiers:
            if identifier in pending:
                projected.append(Message(role="tool", content=INTERRUPTED_RESULT, tool_call_id=identifier, is_error=True))
    return projected
