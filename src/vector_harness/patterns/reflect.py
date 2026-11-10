"""执行完成后的一次反思。

只在内层结果是 ``complete`` 时向模型要一份 JSON。通过就保留原回复。
不通过就把批评写进会话，再执行一次。最多改一版。
"""

from __future__ import annotations

import json

from vector_harness.core.turn import collect_text
from vector_harness.types import Message, ProviderError, RunResult

_REFLECT_SYSTEM = (
    'Reply with JSON only, of the form {"ok": true} '
    'or {"ok": false, "critique": "..."}.'
)


def format_reflection(critique: str) -> str:
    """把批评收成 ``Reflection:`` 开头的用户消息，交给下一轮执行。"""
    return f"Reflection:\n{critique}"


def _parse_reflection(text: str) -> tuple[bool, str] | None:
    """解析反思 JSON。``ok`` 为真时不用批评；为假时 ``critique`` 必须是非空字符串。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        return None
    if data["ok"]:
        return True, ""
    critique = data.get("critique")
    if not isinstance(critique, str) or not critique:
        return None
    return False, critique


class Reflect:
    def __init__(self, inner) -> None:
        """包住已经装配好的循环或计划外层。反思不往内层加工具。

        ``loop`` 取内层已经露出的工具循环。计划和工具循环都提供这个属性，
        调用方不用再沿包装链往下找。
        """
        self.inner = inner
        self.loop = inner.loop

    async def _collect(self, messages: list[Message]) -> str:
        """向模型要一份反思。工具列表为空，文本增量走循环上的同一个回调。"""
        host = self.loop
        return await collect_text(
            host.provider,
            system=_REFLECT_SYSTEM,
            messages=messages,
            on_event=host.on_event,
        )

    async def run(self, user_text: str) -> RunResult:
        """先跑内层。完成后最多要两次反思。不通过时只再执行一次。"""
        result = await self.inner.run(user_text)
        if result.status != "complete":
            return result
        host = self.loop
        prompt_messages = list(host.session.load())
        last_text = ""
        for attempt in range(1, 3):
            try:
                last_text = await self._collect(prompt_messages)
            except ProviderError as exc:
                return RunResult(
                    status="error",
                    text=str(exc),
                    steps=result.steps + attempt,
                    session_path=host.session.path,
                )
            parsed = _parse_reflection(last_text)
            if parsed is not None:
                ok, critique = parsed
                if ok:
                    return RunResult(
                        status=result.status,
                        text=result.text,
                        steps=result.steps + attempt,
                        session_path=result.session_path,
                    )
                revised = await self.inner.run(format_reflection(critique))
                return RunResult(
                    status=revised.status,
                    text=revised.text,
                    steps=result.steps + attempt + revised.steps,
                    session_path=revised.session_path,
                )
            prompt_messages = [
                Message(
                    role="user",
                    content=f"Invalid reflection JSON: {last_text}",
                )
            ]
        return RunResult(
            status="error",
            text=prompt_messages[0].content,
            steps=result.steps + 2,
            session_path=host.session.path,
        )
