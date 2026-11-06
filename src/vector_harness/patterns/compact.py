from __future__ import annotations

import json

from vector_harness.types import Message

_SUMMARY_SYSTEM = "Summarize the conversation prefix. Preserve facts, decisions, and file paths."


def _char_count(messages: list[Message]) -> int:
    total = 0
    for message in messages:
        total += len(message.content)
        for call in message.tool_calls or []:
            total += len(call.name)
            total += len(json.dumps(call.arguments, sort_keys=True))
    return total


def _format_prefix(messages: list[Message]) -> str:
    return "\n".join(f"{message.role}: {message.content}" for message in messages)


class Compaction:
    def __init__(self, provider, *, max_chars: int, keep_last: int) -> None:
        self.provider = provider
        self.max_chars = max_chars
        self.keep_last = keep_last
        self.last_failure: str | None = None

    async def apply(self, messages: list[Message]) -> list[Message]:
        if len(messages) <= self.keep_last:
            return messages
        if _char_count(messages) <= self.max_chars:
            return messages

        if self.keep_last == 0:
            prefix, tail = messages, []
        else:
            prefix = messages[: -self.keep_last]
            tail = messages[-self.keep_last :]

        summary_messages = [Message(role="user", content=_format_prefix(prefix))]
        try:
            text = ""
            async for event in self.provider.stream(
                system=_SUMMARY_SYSTEM,
                messages=summary_messages,
                tools=[],
            ):
                if event.kind == "text_delta":
                    text += event.text
        except Exception as exc:
            self.last_failure = str(exc)
            return list(messages)

        self.last_failure = None
        compacted = Message(
            role="user",
            content=f"[compacted context]\n{text}",
        )
        return [compacted, *tail]
