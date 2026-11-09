"""工具循环。

一步就是一次模型请求。模型若给出工具调用，循环执行它们，把结果写回会话，
再进入下一步。模型给出不含工具调用的文本时，这一轮结束。

模式不进这个文件。调用方把压缩之类的变换放进 ``context_transforms``。
"""

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
    ProviderError,
    ProviderEvent,
    RunResult,
    Tool,
    ToolCall,
    ToolHook,
)


def _serialize_message(message: Message) -> dict:
    """收成可比较的字典，用来判断变换有没有改会话。"""
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
    """按序列化结果比较。变换如果原地改了列表再原样返回，这里看不出差别，也就不会重写文件。"""
    return json.dumps(
        [_serialize_message(m) for m in a], sort_keys=True
    ) == json.dumps([_serialize_message(m) for m in b], sort_keys=True)


@dataclass(kw_only=True)
class Loop:
    """带着工具跑一轮任务。

    ``provider`` 只要有 ``stream(system, messages, tools)``。
    ``on_event`` 在模型事件产生时立刻调用，工具要等这一步的流结束才执行。
    """

    provider: Any
    tools: list[Tool]
    session: Session
    system: str
    context_transforms: list[ContextTransform] | None = None
    tool_hooks: list[ToolHook] | None = None
    on_event: Callable[[ProviderEvent], None] | None = None
    max_steps: int = 25

    def __post_init__(self) -> None:
        """没传入变换或钩子时用空列表，后面就可以直接遍历。"""
        if self.context_transforms is None:
            self.context_transforms = []
        if self.tool_hooks is None:
            self.tool_hooks = []

    def _persist_tool_arguments(self, call: ToolCall) -> None:
        """把改写后的参数写回含有这次调用的助手消息。"""
        messages = self.session.load()
        for message in reversed(messages):
            if message.role != "assistant" or not message.tool_calls:
                continue
            for stored in message.tool_calls:
                if stored.id != call.id:
                    continue
                stored.arguments = dict(call.arguments)
                self.session.replace_all(messages)
                return

    async def _prepare_tool_call(self, call: ToolCall) -> tuple[ToolCall, str | None]:
        """按顺序跑执行前钩子。返回的文本不是 None 时不要执行工具。"""
        current = call
        for hook in self.tool_hooks or []:
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
                self._persist_tool_arguments(current)
            if deny:
                return current, deny
        return current, None

    def _emit(self, event: ProviderEvent) -> None:
        """有观察回调时立刻送出事件。没有回调就什么也不做。"""
        if self.on_event is not None:
            self.on_event(event)

    async def run(self, user_text: str) -> RunResult:
        """把用户文本追加进会话，然后一步一步问模型。

        到达 ``max_steps`` 的那一步仍然会执行工具，然后以 ``max_steps`` 返回，
        文本留空。只有 ``ProviderError`` 变成 ``status="error"``。
        """
        # 用户文本先落盘，这一轮后面的模型请求才能看见它。
        self.session.append(Message(role="user", content=user_text))
        result: RunResult | None = None

        # 一步就是一次模型请求。步数从 1 计，原样写进 RunResult.steps。
        for step in range(1, self.max_steps + 1):
            messages = self.session.load()
            transformed = messages
            # 变换只看见会话消息。system 由这一步的 stream 单独带上。
            for transform in self.context_transforms or []:
                transformed = await transform.apply(transformed)
            # 内容没变就不重写文件，避免每次请求都碰磁盘。
            if not _messages_equal(messages, transformed):
                self.session.replace_all(transformed)
                messages = transformed
            else:
                # 序列化结果相同就不写文件，这一步仍使用变换返回的列表。
                messages = transformed

            assistant_text = ""
            tool_calls: list[ToolCall] = []
            # start 先到，end 再补上完整参数。同一个 id 对上同一次调用。
            pending: dict[str, ToolCall] = {}

            try:
                async for event in self.provider.stream(
                    system=self.system, messages=messages, tools=self.tools
                ):
                    # 先把事件交出去，再记进这一步。终端因此能在工具执行前看到命令。
                    self._emit(event)
                    if event.kind == "text_delta":
                        # 增量拼成这一步的助手正文，和工具调用写在同一条消息里。
                        assistant_text += event.text
                    elif event.kind == "thinking_delta":
                        # 思考只给观察方。写进会话会变成下一次请求的正文。
                        pass
                    elif event.kind == "tool_call_start":
                        pending[event.tool_call_id] = ToolCall(
                            id=event.tool_call_id,
                            name=event.name,
                            arguments={},
                        )
                    elif event.kind == "tool_call_end":
                        # 参数以 end 事件为准。缺 start 时仍收下这次调用。
                        if event.tool_call_id in pending:
                            call = pending.pop(event.tool_call_id)
                            tool_calls.append(
                                ToolCall(
                                    id=call.id,
                                    name=call.name,
                                    arguments=event.arguments,
                                )
                            )
                        else:
                            tool_calls.append(
                                ToolCall(
                                    id=event.tool_call_id,
                                    name=event.name,
                                    arguments=event.arguments,
                                )
                            )
            except ProviderError as exc:
                result = RunResult(
                    status="error",
                    text=str(exc),
                    steps=step,
                    session_path=self.session.path,
                )
                break

            # 没有工具调用，这一步的文本就是最终回复。
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

            # 先记下调用再执行。进程若在写回结果前退出，会话里只看得到这次调用。
            self.session.append(
                Message(
                    role="assistant",
                    content=assistant_text,
                    tool_calls=tool_calls,
                )
            )

            # 同名工具以后登记的为准。
            tool_map = {tool.name: tool for tool in self.tools}
            for tc in tool_calls:
                # 未知工具、非对象，以及解析失败留下的 ``_invalid_json`` 都不执行。
                # None 也落在这里，不能当成 {}。
                if tc.name not in tool_map:
                    self.session.append(
                        Message(
                            role="tool",
                            content=f"Error: Unknown tool: {tc.name}",
                            tool_call_id=tc.id,
                            is_error=True,
                        )
                    )
                elif not isinstance(tc.arguments, dict) or "_invalid_json" in tc.arguments:
                    self.session.append(
                        Message(
                            role="tool",
                            content=f"Error: invalid arguments for {tc.name}",
                            tool_call_id=tc.id,
                            is_error=True,
                        )
                    )
                else:
                    current, failure = await self._prepare_tool_call(tc)
                    if failure is not None:
                        self.session.append(
                            Message(
                                role="tool",
                                content=failure,
                                tool_call_id=current.id,
                                is_error=True,
                            )
                        )
                        continue
                    try:
                        output = await tool_map[current.name].execute(current.arguments)
                    except Exception as exc:
                        # 工具失败写成一条结果，循环继续，让模型自己处理。
                        self.session.append(
                            Message(
                                role="tool",
                                content=str(exc),
                                tool_call_id=current.id,
                                is_error=True,
                            )
                        )
                    else:
                        # 正常返回的文本保持成功。以 Error: 开头的说明也是普通结果。
                        self.session.append(
                            Message(
                                role="tool",
                                content=output,
                                tool_call_id=current.id,
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

        # max_steps < 1 时循环一次都不会进，同样按到达上限返回。
        if result is None:
            result = RunResult(
                status="max_steps",
                text="",
                steps=self.max_steps,
                session_path=self.session.path,
            )

        # 三种结束状态都发 run_end。计划和反思的额外请求不经过这里。
        self._emit(ProviderEvent(kind="run_end"))
        return result
