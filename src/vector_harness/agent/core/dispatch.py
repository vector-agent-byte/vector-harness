"""执行一步里的工具调用。

未知工具、非对象参数，以及解析失败留下的特殊键，都不调用 ``execute``。
钩子可以改参数或拒绝。工具自己抛出的异常写成失败结果，不中断循环。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextvars import ContextVar
from itertools import groupby

from vector_harness.agent.core.session import Session
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

current_tool_call_id: ContextVar[str] = ContextVar("current_tool_call_id", default="")
_logger = logging.getLogger(__name__)


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
        """仅并发执行显式允许并发的连续同名调用，普通工具作为顺序屏障。"""
        tool_map = {tool.name: tool for tool in self.tools}
        known = set(tool_map)
        for name, group in groupby(tool_calls, key=lambda call: call.name):
            calls = list(group)
            limit = getattr(tool_map.get(name), "max_concurrency", 1)
            if not isinstance(limit, int) or limit < 2 or len(calls) == 1:
                for call in calls:
                    current = await self._prepare_call(call, known)
                    if current is not None:
                        await self._execute(current, tool_map[current.name])
                continue
            prepared = []
            for call in calls:
                current = await self._prepare_call(call, known)
                if current is not None:
                    prepared.append(current)
            semaphore = asyncio.Semaphore(limit)

            async def execute_limited(call: ToolCall) -> None:
                async with semaphore:
                    await self._execute(call, tool_map[call.name])

            async with asyncio.TaskGroup() as tasks:
                for call in prepared:
                    tasks.create_task(execute_limited(call))

    async def _prepare_call(self, call: ToolCall, known: set[str]) -> ToolCall | None:
        reason = rejection_reason(call, known)
        if reason is None:
            call, reason = await self._prepare(call)
        if reason is not None:
            self._append_error(call, reason)
            self._emit_result(call, reason, is_error=True)
            return None
        return call

    async def _execute(self, call: ToolCall, tool: Tool) -> None:
        if self.on_event is not None:
            self.on_event(ProviderEvent(
                kind=EventKind.TOOL_EXECUTION_START,
                name=call.name,
                tool_call_id=call.id,
            ))
        token = current_tool_call_id.set(call.id)
        try:
            output = await tool.execute(call.arguments)
        except Exception as exc:
            self._append_error(call, str(exc))
            self._emit_result(call, str(exc), is_error=True)
        else:
            result = Message(role=Role.TOOL, content=output, tool_call_id=call.id)
            self.session.append(result)
            callback = getattr(tool, "after_result_persisted", None)
            if callback is not None:
                try:
                    callback(call, result)
                except Exception:
                    _logger.warning("Tool result persisted, but derived-state notification failed for %s", call.name)
            self._emit_result(call, output)
        finally:
            current_tool_call_id.reset(token)

    def _emit_result(self, call: ToolCall, text: str, *, is_error: bool = False) -> None:
        if self.on_event is not None:
            self.on_event(ProviderEvent(
                kind=EventKind.TOOL_RESULT,
                text=text,
                tool_call_id=call.id,
                name="error" if is_error else "",
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
