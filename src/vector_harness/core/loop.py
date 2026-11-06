from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vector_harness.core.session import Session
from vector_harness.types import (
    ContextTransform,
    Message,
    ProviderEvent,
    RunResult,
    Tool,
    ToolCall,
)


def _serialize_message(message: Message) -> dict:
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


def _messages_equal(a: list[Message], b: list[Message]) -> bool:
    return json.dumps(
        [_serialize_message(m) for m in a], sort_keys=True
    ) == json.dumps([_serialize_message(m) for m in b], sort_keys=True)


@dataclass(kw_only=True)
class Loop:
    provider: Any
    tools: list[Tool]
    session: Session
    system: str
    context_transforms: list[ContextTransform] | None = None
    on_event: Callable[[ProviderEvent], None] | None = None
    max_steps: int = 25

    def __post_init__(self) -> None:
        if self.context_transforms is None:
            self.context_transforms = []

    def _emit(self, event: ProviderEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)

    async def run(self, user_text: str) -> RunResult:
        self.session.append(Message(role="user", content=user_text))
        result: RunResult | None = None

        for step in range(1, self.max_steps + 1):
            messages = self.session.load()
            transformed = messages
            for transform in self.context_transforms or []:
                transformed = await transform.apply(transformed)
            if not _messages_equal(messages, transformed):
                self.session.replace_all(transformed)
                messages = transformed
            else:
                messages = transformed

            assistant_text = ""
            tool_calls: list[ToolCall] = []
            pending: dict[str, ToolCall] = {}

            async for event in self.provider.stream(
                system=self.system, messages=messages, tools=self.tools
            ):
                self._emit(event)
                if event.kind == "text_delta":
                    assistant_text += event.text
                elif event.kind == "tool_call_start":
                    pending[event.tool_call_id] = ToolCall(
                        id=event.tool_call_id,
                        name=event.name,
                        arguments={},
                    )
                elif event.kind == "tool_call_end":
                    if event.tool_call_id in pending:
                        call = pending.pop(event.tool_call_id)
                        tool_calls.append(
                            ToolCall(
                                id=call.id,
                                name=call.name,
                                arguments=event.arguments
                                if event.arguments is not None
                                else {},
                            )
                        )
                    else:
                        tool_calls.append(
                            ToolCall(
                                id=event.tool_call_id,
                                name=event.name,
                                arguments=event.arguments
                                if event.arguments is not None
                                else {},
                            )
                        )

            if not tool_calls:
                self.session.append(
                    Message(role="assistant", content=assistant_text)
                )
                result = RunResult(
                    status="complete",
                    text=assistant_text,
                    steps=step,
                    session_path=self.session.path,
                )
                break

            self.session.append(
                Message(
                    role="assistant",
                    content=assistant_text,
                    tool_calls=tool_calls,
                )
            )

            tool_map = {tool.name: tool for tool in self.tools}
            for tc in tool_calls:
                if tc.name not in tool_map:
                    self.session.append(
                        Message(
                            role="tool",
                            content=f"Error: Unknown tool: {tc.name}",
                            tool_call_id=tc.id,
                            is_error=True,
                        )
                    )
                elif not isinstance(tc.arguments, dict):
                    self.session.append(
                        Message(
                            role="tool",
                            content=f"Error: invalid arguments for {tc.name}",
                            tool_call_id=tc.id,
                            is_error=True,
                        )
                    )
                else:
                    try:
                        output = await tool_map[tc.name].execute(tc.arguments)
                    except Exception as exc:
                        self.session.append(
                            Message(
                                role="tool",
                                content=str(exc),
                                tool_call_id=tc.id,
                                is_error=True,
                            )
                        )
                    else:
                        self.session.append(
                            Message(
                                role="tool",
                                content=output,
                                tool_call_id=tc.id,
                                is_error=False,
                            )
                        )

            if step == self.max_steps:
                result = RunResult(
                    status="max_steps",
                    text="",
                    steps=step,
                    session_path=self.session.path,
                )
                break

        if result is None:
            result = RunResult(
                status="max_steps",
                text="",
                steps=self.max_steps,
                session_path=self.session.path,
            )

        self._emit(ProviderEvent(kind="run_end"))
        return result
