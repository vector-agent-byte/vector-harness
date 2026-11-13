"""工具循环。

一步就是一次模型请求。模型若给出工具调用，循环执行它们，把结果写回会话，
再进入下一步。模型给出不含工具调用的文本时，这一轮结束。

模式不进这个文件。调用方把压缩之类的变换放进 ``context_transforms``，
用 ``install_prompt`` 和 ``replace_tool`` 挂上提示和工具。

整体执行路径是：
run(user_text)
  │
  ├─ 把用户消息追加到 session
  │
  └─ 循环，最多 max_steps 次
       │
       ├─ 读取历史消息，执行上下文变换
       │
       ├─ 请求模型，收集流式回复
       │    └─ ProviderError → 返回 error
       │
       ├─ 没有工具调用
       │    ├─ 保存助手回复
       │    └─ 返回 complete
       │
       └─ 有工具调用
            ├─ 保存助手正文和工具调用
            ├─ 执行工具，把工具结果写入 session
            ├─ 已达上限 → 返回 max_steps
            └─ 否则进入下一次模型请求

形成结果后，发送 RUN_END 事件并返回
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vector_harness.core.codec import messages_equal
from vector_harness.core.dispatch import ToolDispatcher
from vector_harness.core.session import Session
from vector_harness.core.turn import collect_turn
from vector_harness.types import (
    ContextTransform,
    EventKind,
    Message,
    Model,
    ProviderError,
    ProviderEvent,
    Role,
    RunResult,
    RunStatus,
    Tool,
    ToolHook,
)


def _result(session: Session, status: str, text: str, steps: int) -> RunResult:
    """用这份会话的路径组装一轮结果。"""
    return RunResult(
        status=status,
        text=text,
        steps=steps,
        session_path=session.path,
    )


@dataclass(kw_only=True)
class Loop:
    """带着工具跑一轮任务。

    ``provider`` 只要有 ``stream(system, messages, tools)``。
    ``on_event`` 在模型事件产生时立刻调用，工具要等这一步的流结束才执行。
    ``loop`` 指向自己，外层包装也暴露同名属性，调用方不用区分包了几层。
    """

    provider: Model
    tools: list[Tool]
    session: Session  # 保存对话历史，支持内存或 JSONL 文件
    system: str  # 系统提示词，与历史消息分开传给模型
    context_transforms: list[ContextTransform] | None = None  # 每次模型请求前，对历史消息做变换
    tool_hooks: list[ToolHook] | None = None  # 工具执行前，改写参数或拒绝调用
    on_event: Callable[[ProviderEvent], None] | None = None  # 接收流式事件，供终端等观察方展示
    max_steps: int = 50

    def __post_init__(self) -> None:
        """没传入变换或钩子时用空列表，后面就可以直接遍历。"""
        if self.context_transforms is None:
            self.context_transforms = []
        if self.tool_hooks is None:
            self.tool_hooks = []

    @property
    def loop(self) -> Loop:
        """最内层工具循环。这里就是自己。"""
        return self

    def install_prompt(self, text: str) -> None:
        """非空且尚未出现的提示，用一个换行接在系统提示后面。"""
        if text and text not in self.system:
            self.system = self.system + "\n" + text

    def replace_tool(self, tool: Tool) -> None:
        """同名工具留在原位置，换成新的。没有同名工具时追加到末尾。"""
        for index, existing in enumerate(self.tools):
            if existing.name == tool.name:
                self.tools[index] = tool
                return
        self.tools.append(tool)

    def _emit(self, event: ProviderEvent) -> None:
        """有观察回调时立刻送出事件。没有回调就什么也不做。"""
        if self.on_event is not None:
            self.on_event(event)

    async def _messages_for_model(self) -> list[Message]:
        """跑变换。内容变了才整份写回会话。"""
        messages = self.session.load()
        transformed = messages
        for transform in self.context_transforms or []:
            transformed = await transform.apply(transformed)
        if not messages_equal(messages, transformed):
            self.session.replace_all(transformed)
        return transformed

    async def run(self, user_text: str) -> RunResult:
        """把用户文本追加进会话，然后一步一步问模型。

        到达 ``max_steps`` 的那一步仍然会执行工具，然后以 ``max_steps`` 返回，
        文本留空。只有 ``ProviderError`` 变成 ``status="error"``。
        ``max_steps < 1`` 时一次模型请求都不发，同样按到达上限返回。
        """
        self.session.append(Message(role=Role.USER, content=user_text))
        result: RunResult | None = None

        for step in range(1, self.max_steps + 1):
            messages = await self._messages_for_model()
            try:
                turn = await collect_turn(
                    self.provider,
                    system=self.system,
                    messages=messages,
                    tools=self.tools,
                    on_event=self.on_event,
                )
            except ProviderError as exc:
                result = _result(self.session, RunStatus.ERROR, str(exc), step)
                break

            if not turn.tool_calls:
                self.session.append(Message(role=Role.ASSISTANT, content=turn.text))
                result = _result(self.session, RunStatus.COMPLETE, turn.text, step)
                break

            self.session.append(
                Message(
                    role=Role.ASSISTANT,
                    content=turn.text,
                    tool_calls=turn.tool_calls,
                )
            )
            await ToolDispatcher(
                self.session, self.tools, self.tool_hooks, self.on_event
            ).dispatch(turn.tool_calls)

            if step == self.max_steps:
                result = _result(self.session, RunStatus.MAX_STEPS, "", step)
                break

        if result is None:
            result = _result(self.session, RunStatus.MAX_STEPS, "", self.max_steps)

        self._emit(ProviderEvent(kind=EventKind.RUN_END))
        return result
