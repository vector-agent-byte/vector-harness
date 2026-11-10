from __future__ import annotations

import json

from vector_harness.core.loop import Loop
from vector_harness.core.turn import collect_text
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


def _group_end(messages: list[Message], start: int) -> int:
    """助手的一次工具调用，加上紧随其后、对得上的工具结果，算一组。"""
    message = messages[start]
    calls = message.tool_calls or []
    if message.role != "assistant" or not calls:
        return start + 1
    pending = {call.id for call in calls}
    end = start + 1
    while end < len(messages):
        follower = messages[end]
        if follower.role != "tool" or follower.tool_call_id not in pending:
            break
        pending.discard(follower.tool_call_id)
        end += 1
    return end


def _tail_start(messages: list[Message], keep_last: int) -> int:
    """尾部至少保留 ``keep_last`` 条。切点落在工具组内部时，整组留在尾部。"""
    if keep_last <= 0:
        return len(messages)
    cut = max(len(messages) - keep_last, 0)
    start = 0
    while start < len(messages):
        end = _group_end(messages, start)
        if start < cut < end:
            return start
        start = end
    return cut


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
        """超长时把前面的消息折成一条摘要，保留最近若干条。

        不修改传入的列表和其中的消息。一次助手工具调用和紧随的工具结果是一组，
        只在组边界切分；为了不拆开这一组，尾部可以多于 ``keep_last``。
        整组都必须留下、前面没有可摘要的消息时，原样返回。摘要失败也原样返回。
        """
        if len(messages) <= self.keep_last:
            return messages
        if _char_count(messages) <= self.max_chars:
            return messages

        cut = _tail_start(messages, self.keep_last)
        if cut == 0:
            return list(messages)
        prefix = messages[:cut]
        tail = messages[cut:]

        summary_messages = [Message(role="user", content=_format_prefix(prefix))]
        try:
            text = await collect_text(
                self.provider,
                system=_SUMMARY_SYSTEM,
                messages=summary_messages,
                on_event=None,
            )
        except Exception as exc:
            self.last_failure = str(exc)
            return list(messages)

        self.last_failure = None
        compacted = Message(
            role="user",
            content=f"[compacted context]\n{text}",
        )
        return [compacted, *tail]


def attach_compaction(loop: Loop, provider, *, max_chars: int, keep_last: int) -> None:
    """压缩只留一份。再次装配时更新阈值，不追加第二个变换。"""
    for existing in loop.context_transforms or []:
        if isinstance(existing, Compaction):
            existing.provider = provider
            existing.max_chars = max_chars
            existing.keep_last = keep_last
            return
    loop.context_transforms.append(
        Compaction(provider, max_chars=max_chars, keep_last=keep_last)
    )
