"""一次模型请求的收集。

工具循环用它收下助手正文和工具调用。计划、反思和压缩用它只要一段文本。
事件在产生时就交给观察回调，这里不执行工具。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vector_harness.types import EventKind, Message, Model, ProviderEvent, Tool, ToolCall


@dataclass(frozen=True)
class ModelTurn:
    """一次 ``stream`` 收齐之后的正文和工具调用。"""

    text: str
    tool_calls: list[ToolCall]


def emit(on_event: Callable[[ProviderEvent], None] | None, event: ProviderEvent) -> None:
    """有观察回调时立刻送出事件。"""
    if on_event is not None:
        on_event(event)


async def collect_turn(
    provider: Model,
    *,
    system: str,
    messages: list[Message],
    tools: list[Tool],
    on_event: Callable[[ProviderEvent], None] | None,
) -> ModelTurn:
    """跑一次模型流，拼出正文，并按 id 归并工具调用。

    ``tool_call_start`` 先到，``tool_call_end`` 再补上完整参数。
    只有 end、没有 start 时仍然收下这次调用。参数以 end 事件为准。
    思考增量只转给观察回调，不写入正文。
    """
    text = ""
    tool_calls: list[ToolCall] = []
    pending: dict[str, ToolCall] = {}
    async for event in provider.stream(system=system, messages=messages, tools=tools):
        emit(on_event, event)
        if event.kind == EventKind.TEXT_DELTA:
            text += event.text
        elif event.kind == EventKind.TOOL_CALL_START:
            pending[event.tool_call_id] = ToolCall(
                id=event.tool_call_id,
                name=event.name,
                arguments={},
            )
        elif event.kind == EventKind.TOOL_CALL_END:
            if event.tool_call_id in pending:
                call = pending.pop(event.tool_call_id)
                tool_calls.append(
                    ToolCall(id=call.id, name=call.name, arguments=event.arguments)
                )
            else:
                tool_calls.append(
                    ToolCall(
                        id=event.tool_call_id,
                        name=event.name,
                        arguments=event.arguments,
                    )
                )
    return ModelTurn(text=text, tool_calls=tool_calls)


async def collect_text(
    provider: Model,
    *,
    system: str,
    messages: list[Message],
    on_event: Callable[[ProviderEvent], None] | None,
) -> str:
    """向模型要一段文本。工具列表为空，文本增量仍走观察回调。"""
    turn = await collect_turn(
        provider,
        system=system,
        messages=messages,
        tools=[],
        on_event=on_event,
    )
    return turn.text
