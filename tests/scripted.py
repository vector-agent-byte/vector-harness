from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vector_harness.types import Message, ProviderEvent, ToolCall


@dataclass
class ScriptedTurn:
    content: str = ""
    tool_calls: list[ToolCall] | None = None


@dataclass
class ScriptedProvider:
    turns: list[ScriptedTurn]
    calls: list[dict] = field(default_factory=list)

    @staticmethod
    def _message_to_dict(message: Message) -> dict:
        tool_calls = None
        if message.tool_calls is not None:
            tool_calls = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in message.tool_calls
            ]
        return {
            "role": message.role,
            "content": message.content,
            "tool_calls": tool_calls,
            "tool_call_id": message.tool_call_id,
            "is_error": message.is_error,
        }

    async def stream(self, *, system: str, messages: list[Message], tools: list[Any]) -> Any:
        if not self.turns:
            raise AssertionError("no scripted turns left")
        turn = self.turns.pop(0)
        self.calls.append(
            {
                "system": system,
                "messages": [self._message_to_dict(m) for m in messages],
                "tools": [getattr(t, "name", str(t)) for t in tools],
            }
        )
        if turn.content:
            yield ProviderEvent(kind="text_delta", text=turn.content)
        for tc in turn.tool_calls or []:
            yield ProviderEvent(
                kind="tool_call_start",
                name=tc.name,
                tool_call_id=tc.id,
                arguments=None,
            )
            yield ProviderEvent(
                kind="tool_call_end",
                name=tc.name,
                tool_call_id=tc.id,
                arguments=tc.arguments,
            )
