"""执行后工具化反思。

审查官调用 submit_verdict 工具交回结论，不解析自由文本 JSON。
只在内层结果是 complete 时反思。通过就保留原回复，不通过把批评写进会话再执行一次。
"""
from __future__ import annotations

from vector_harness.core.turn import collect_turn
from vector_harness.types import Message, ProviderError, Role, RunResult

_REFLECT_SYSTEM = (
    "你是审查官，只审查、不执行。\n"
    "对照用户原始要求和助手草稿，调用 submit_verdict 交回结论。\n"
    "通过：草稿已回答用户要求，没有声称完成但实际未做的步骤。\n"
    "不通过：critique 必须写出要补的具体点和改法。"
)


def format_reflection(critique: str) -> str:
    """把批评收成 ``Reflection:`` 开头的用户消息，交给下一轮执行。"""
    return f"Reflection:\n{critique}"


class SubmitVerdictTool:
    """审查官用来交回草稿结论的工具。harness 从工具调用参数中直接读取结论。"""

    name = "submit_verdict"
    description = (
        "交回草稿审查结论。"
        "通过为 true 才允许交付，不通过必须给出可执行的修改意见。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pass": {
                "type": "boolean",
                "description": "true 表示草稿可以交付，false 表示需要返工",
            },
            "critique": {
                "type": "string",
                "description": "通过时一句话确认；不通过时写明要补的具体点和改法",
            },
        },
        "required": ["pass", "critique"],
    }

    async def execute(self, arguments: dict) -> str:
        return "verdict recorded"


def _extract_verdict(turn) -> dict | None:
    """从 turn.tool_calls 中取 submit_verdict 的参数，返回 {pass, critique}。"""
    for call in turn.tool_calls:
        if call.name != "submit_verdict":
            continue
        passed = call.arguments.get("pass")
        if not isinstance(passed, bool):
            continue
        critique = str(call.arguments.get("critique") or "").strip()
        if not passed and not critique:
            critique = "审查未通过，但没有给出具体意见。"
        if passed and not critique:
            critique = "草稿可以交付。"
        return {"pass": passed, "critique": critique}
    return None


class ToolReflect:
    """工具化反思：审查官通过 submit_verdict 工具交回结论，不解析 JSON 文本。

    ``loop`` 取内层已经露出的工具循环。计划和工具循环都提供这个属性，
    调用方不用再沿包装链往下找。
    """

    def __init__(self, inner) -> None:
        self.inner = inner
        self.loop = inner.loop

    @staticmethod
    def _review_message(messages: list[Message]) -> Message:
        """构建审查上下文：原始要求 + 助手草稿，不包含工具调用历史。

        直接把完整会话传给审查官会触发 HTTP 400：会话里有 role=tool 消息，
        但审查请求的工具列表里没有那些工具。用一条汇总消息绕过这个限制。
        """
        user_text = next(
            (
                m.content
                for m in messages
                if m.role == "user" and not m.content.startswith("Reflection:")
            ),
            "",
        )
        draft = next(
            (
                m.content
                for m in reversed(messages)
                if m.role == "assistant" and m.content and not m.tool_calls
            ),
            "",
        )
        content = f"【用户要求】\n{user_text}\n\n【助手草稿】\n{draft or '(空)'}"
        return Message(role="user", content=content)

    async def _collect_verdict(self, messages: list[Message]) -> dict:
        """向审查官要一次结论。从工具调用参数中取结论，不解析文本。"""
        host = self.loop
        turn = await collect_turn(
            host.provider,
            system=_REFLECT_SYSTEM,
            messages=[self._review_message(messages)],
            tools=[SubmitVerdictTool()],
            on_event=host.on_event,
        )
        verdict = _extract_verdict(turn)
        if verdict is not None:
            return verdict
        text = turn.text.strip()
        return {
            "pass": False,
            "critique": text or "审查官没有调用 submit_verdict，请对照用户要求复查草稿。",
        }

    async def run(self, user_text: str) -> RunResult:
        """先跑内层。完成后要一次反思。不通过时再执行一次。"""
        result = await self.inner.run(user_text)
        if result.status != "complete":
            return result

        messages = list(self.loop.session.load())
        try:
            verdict = await self._collect_verdict(messages)
        except ProviderError as exc:
            return RunResult(
                status="error",
                text=str(exc),
                steps=result.steps + 1,
                session_path=self.loop.session.path,
            )

        if verdict["pass"]:
            self.loop.session.append(
                Message(role=Role.ASSISTANT, content=f"[Reflection] 通过 — {verdict['critique']}")
            )
            return RunResult(
                status=result.status,
                text=result.text,
                steps=result.steps + 1,
                session_path=result.session_path,
            )

        revised = await self.inner.run(format_reflection(verdict["critique"]))
        return RunResult(
            status=revised.status,
            text=revised.text,
            steps=result.steps + 1 + revised.steps,
            session_path=revised.session_path,
        )
