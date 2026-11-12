"""执行一步里的工具调用。

未知工具、非对象参数，以及解析失败留下的特殊键，都不调用 ``execute``。
钩子可以改参数或拒绝。工具自己抛出的异常写成失败结果，不中断循环。
"""

from __future__ import annotations

from collections.abc import Callable

from vector_harness.core.session import Session
from vector_harness.types import (
    INVALID_TOOL_ARGUMENTS,
    EventKind,
    Message,
    ProviderEvent,
    Role,
    Tool,
    ToolCall,
    ToolHook,
)


def rejection_reason(call: ToolCall, known_names: set[str]) -> str | None:
    """这次调用不能执行时，返回要写入会话的失败文本。可以执行则返回 None。"""
    if call.name not in known_names:
        return f"Error: Unknown tool: {call.name}"
    arguments = call.arguments
    if not isinstance(arguments, dict) or INVALID_TOOL_ARGUMENTS in arguments:
        return f"Error: invalid arguments for {call.name}"
    return None


class ToolDispatcher:
    """按当前工具表和钩子执行一组调用，并把每条结果追加进会话。"""

    def __init__(
        self,
        session: Session,
        tools: list[Tool],
        hooks: list[ToolHook] | None,
        on_event: Callable[[ProviderEvent], None] | None = None,
    ) -> None:
        self.session = session
        self.tools = tools
        self.hooks = hooks or []
        self.on_event = on_event

    async def dispatch(self, tool_calls: list[ToolCall]) -> None:
        """按调用顺序执行。同名工具以后登记的为准。"""
        tool_map = {tool.name: tool for tool in self.tools}
        known = set(tool_map)
        for call in tool_calls:
            reason = rejection_reason(call, known)
            if reason is not None:
                self._append_error(call, reason)
                continue
            current, failure = await self._prepare(call)
            if failure is not None:
                self._append_error(current, failure)
                continue
            try:
                output = await tool_map[current.name].execute(current.arguments)
            except Exception as exc:
                self._append_error(current, str(exc))
                if self.on_event is not None:
                    self.on_event(ProviderEvent(
                        kind=EventKind.TOOL_RESULT,
                        text=str(exc),
                        tool_call_id=current.id,
                        name="error",
                    ))
            else:
                self.session.append(
                    Message(
                        role=Role.TOOL,
                        content=output,
                        tool_call_id=current.id,
                        is_error=False,
                    )
                )
                if self.on_event is not None:
                    self.on_event(ProviderEvent(
                        kind=EventKind.TOOL_RESULT,
                        text=output,
                        tool_call_id=current.id,
                    ))

    def _append_error(self, call: ToolCall, content: str) -> None:
        self.session.append(
            Message(
                role=Role.TOOL,
                content=content,
                tool_call_id=call.id,
                is_error=True,
            )
        )

    def _persist_arguments(self, call: ToolCall) -> None:
        """把改写后的参数写回含有这次调用的助手消息。"""
        messages = self.session.load()
        for message in reversed(messages):
            if message.role != Role.ASSISTANT or not message.tool_calls:
                continue
            for stored in message.tool_calls:
                if stored.id != call.id:
                    continue
                stored.arguments = dict(call.arguments)
                self.session.replace_all(messages)
                return

    async def _prepare(self, call: ToolCall) -> tuple[ToolCall, str | None]:
        """按顺序跑执行前钩子。返回的文本不是 None 时不要执行工具。"""
        current = call
        for hook in self.hooks:
            try:
                result = await hook.before_execute(current, self.session.load())
                if result is None:
                    continue
                new_arguments = result.arguments
                deny = result.deny
            except Exception as exc:
                return current, str(exc)
            if new_arguments is not None:
                if not isinstance(new_arguments, dict):
                    return current, f"Error: invalid arguments for {current.name}"
                current = ToolCall(
                    id=current.id,
                    name=current.name,
                    arguments=new_arguments,
                )
                self._persist_arguments(current)
            if deny:
                return current, deny
        return current, None
