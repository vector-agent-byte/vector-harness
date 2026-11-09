from __future__ import annotations

import json

from vector_harness.types import Message

_SUMMARY_SYSTEM = "Summarize the conversation prefix. Preserve facts, decisions, and file paths."


def _char_count(messages: list[Message]) -> int:
    """统计正文、工具名和参数的字符数，用来判断要不要压缩。"""
    total = 0
    for message in messages:
        total += len(message.content)
        for call in message.tool_calls or []:
            total += len(call.name)
            total += len(json.dumps(call.arguments, sort_keys=True))
    return total


def _format_prefix(messages: list[Message]) -> str:
    """把待摘要的消息收成文本，工具调用的名字和参数也写进去。"""
    lines: list[str] = []
    for message in messages:
        lines.append(f"{message.role}: {message.content}")
        for call in message.tool_calls or []:
            lines.append(f"{call.name} {json.dumps(call.arguments, sort_keys=True)}")
    return "\n".join(lines)


class Compaction:
    def __init__(self, provider, *, max_chars: int, keep_last: int) -> None:
        """记下模型和阈值。``last_failure`` 留给调用方查看最近一次摘要失败。"""
        self.provider = provider
        self.max_chars = max_chars
        self.keep_last = keep_last
        self.last_failure: str | None = None

    async def apply(self, messages: list[Message]) -> list[Message]:
        """超长时把前面的消息折成一条摘要，保留最近若干条。摘要失败则原样返回。"""
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
