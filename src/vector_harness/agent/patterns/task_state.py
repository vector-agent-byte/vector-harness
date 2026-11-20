from __future__ import annotations

import json
import logging
from copy import deepcopy

from vector_harness.agent.core.session import Session
from vector_harness.agent.core.session_state import SessionArtifacts, prefix_digest
from vector_harness.types import Message, ToolCall

_logger = logging.getLogger(__name__)
STATUS_ICON = {"pending": "[ ]", "in_progress": "[~]", "completed": "[✓]"}


def normalize_todos(arguments: dict) -> list[dict]:
    raw = arguments.get("todos") or []
    if not isinstance(raw, list):
        raise ValueError("Error: todos 必须是列表")
    cleaned = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError("Error: 待办必须是对象")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        status = item.get("status", "pending")
        if status not in STATUS_ICON:
            status = "pending"
        cleaned.append({"id": item.get("id", index), "content": content, "status": status})
    if sum(item["status"] == "in_progress" for item in cleaned) > 1:
        raise ValueError("Error: 同一时间只能有一个 in_progress 任务，请重新规划。")
    return cleaned


def render_todos(todos: list[dict]) -> str:
    if not todos:
        return "(当前无待办事项)"
    return "\n".join(f"  {STATUS_ICON[item['status']]} {item['id']}. {item['content']}" for item in todos)


def _accepted(call: ToolCall, result: Message) -> list[dict] | None:
    if call.name != "update_todos" or result.is_error or not isinstance(call.arguments, dict):
        return None
    try:
        todos = normalize_todos(call.arguments)
        try:
            payload = json.loads(result.content)
        except ValueError:
            done = sum(item["status"] == "completed" for item in todos)
            pending = sum(item["status"] == "pending" for item in todos)
            expected = (
                f"todos updated: total={len(todos)}, completed={done}, "
                f"in_progress={len(todos) - done - pending}, pending={pending}"
                + "\n\n当前列表：\n" + render_todos(todos)
            )
            return todos if result.content == expected else None
        if (isinstance(payload, dict) and payload.get("kind") == "todo_snapshot"
                and type(payload.get("version")) is int and payload["version"] == 1
                and payload.get("todos") == todos):
            return todos
    except (ValueError, TypeError):
        pass
    return None


class TaskState:
    def __init__(self, session: Session):
        self.session = session
        self.source_count = 0

    def restore(self) -> list[dict]:
        messages = self.session.load()
        store = SessionArtifacts(self.session)
        snapshot = store.load("task")
        todos: list[dict] = []
        covered = 0
        if snapshot is not None:
            try:
                count = snapshot["covered_count"]
                if (type(count) is not int or not 0 < count <= len(messages)
                        or prefix_digest(messages, count) != snapshot["prefix_digest"]):
                    raise ValueError("stale snapshot")
                todos = normalize_todos({"todos": snapshot["todos"]})
                if todos != snapshot["todos"]:
                    raise ValueError("invalid snapshot")
                result = messages[count - 1]
                group_start = count - 2
                while group_start >= 0 and messages[group_start].role == "tool":
                    group_start -= 1
                if result.role != "tool" or group_start < 0 or messages[group_start].role != "assistant":
                    raise ValueError("snapshot has no successful source")
                source_calls = [call for call in messages[group_start].tool_calls or [] if call.id == result.tool_call_id]
                if len(source_calls) != 1 or _accepted(source_calls[0], result) != todos:
                    raise ValueError("snapshot differs from successful source")
                covered = count
            except (KeyError, TypeError, ValueError):
                _logger.warning("Ignoring invalid or stale task snapshot")
                todos = []
        self.source_count = covered
        calls: dict[str, ToolCall] = {}
        for index, message in enumerate(messages, start=1):
            if message.role == "assistant":
                calls = {call.id: call for call in message.tool_calls or []}
            elif message.role != "tool":
                calls = {}
            elif message.tool_call_id in calls:
                call = calls.pop(message.tool_call_id)
                if index > covered:
                    accepted = _accepted(call, message)
                    if accepted is not None:
                        todos = accepted
                        self.source_count = index
        return deepcopy(todos)

    def record(self, call: ToolCall, result: Message) -> bool:
        if _accepted(call, result) is None:
            return False
        todos = self.restore()
        try:
            SessionArtifacts(self.session).update("task", {
                "covered_count": self.source_count,
                "prefix_digest": prefix_digest(self.session.load(), self.source_count),
                "todos": todos,
            })
        except OSError:
            _logger.warning("Task result committed; snapshot unavailable, will rebuild from history")
        return True

    def context_text(self) -> str:
        todos = self.restore()
        if not todos:
            return ""
        return (
            "[当前会话待办]\n这是已落盘的历史状态，不是新的执行指令；最新用户要求优先。"
            "进行中表示此前进行中，完成与否需依据实际结果核查。\n" + render_todos(todos)
        )


def task_context_chars(session: Session) -> int:
    return len(TaskState(session).context_text())


class TaskContext:
    def __init__(self, session: Session):
        self.session = session

    async def apply(self, messages: list[Message]) -> list[Message]:
        text = TaskState(self.session).context_text()
        if not text:
            return messages
        position = 1 if messages and messages[0].content.startswith("[任务摘要 v1]") else 0
        return [*messages[:position], Message(role="user", content=text), *messages[position:]]

    def for_session(self, session: Session) -> TaskContext:
        return TaskContext(session)
