from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from vector_harness.types import Message, ToolCall


def _message_to_dict(message: Message) -> dict:
    tool_calls: list[dict] | None
    if message.tool_calls is None:
        tool_calls = None
    else:
        tool_calls = [
            {
                "id": tc.id,
                "name": tc.name,
                "arguments": tc.arguments,
            }
            for tc in message.tool_calls
        ]
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": tool_calls,
        "tool_call_id": message.tool_call_id,
        "is_error": message.is_error,
    }


def _message_from_dict(data: dict) -> Message:
    raw_tool_calls = data.get("tool_calls")
    tool_calls: list[ToolCall] | None
    if raw_tool_calls is None:
        tool_calls = None
    else:
        tool_calls = [
            ToolCall(
                id=item["id"],
                name=item["name"],
                arguments=item["arguments"],
            )
            for item in raw_tool_calls
        ]
    return Message(
        role=data["role"],
        content=data["content"],
        tool_calls=tool_calls,
        tool_call_id=data.get("tool_call_id"),
        is_error=data.get("is_error", False),
    )


@dataclass
class Session:
    path: Path | None

    @classmethod
    def in_memory(cls) -> Session:
        return cls(path=None)

    def __post_init__(self) -> None:
        self._messages: list[Message] = []

    def load(self) -> list[Message]:
        if self.path is None:
            return list(self._messages)
        if not self.path.is_file():
            return []
        text = self.path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        messages: list[Message] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            messages.append(_message_from_dict(json.loads(line)))
        return messages

    def append(self, message: Message) -> None:
        if self.path is None:
            self._messages.append(message)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_message_to_dict(message), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def replace_all(self, messages: list[Message]) -> None:
        if self.path is None:
            self._messages = list(messages)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(_message_to_dict(m), ensure_ascii=False) for m in messages]
        content = "\n".join(lines)
        if lines:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")
