"""可嵌入的对话助手。

包住现有的工具循环，给调用方一个同步的 ``run``。历史留在内存会话里，
同一实例上的下一次 ``run`` 能看见之前的消息。创建时就能传入工具和模式，
之后还可以用 ``add_tool`` 或 ``attach`` 再补，下一轮才会交给模型。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from vector_harness.core.loop import Loop
from vector_harness.core.session import Session
from vector_harness.types import (
    Message,
    Model,
    ProviderError,
    ProviderEvent,
    Runnable,
    Tool,
    ToolHook,
)


class VectorHarness:
    """带名字、系统提示和可选工具的助手。

    ``llm`` 只要有 ``stream(system, messages, tools)``，测试可以传入脚本化的实现。
    ``run`` 在普通脚本里调用。它自己开事件循环，不要放进已经在跑的异步函数里。
    ``max_model_turns`` 是这一轮里模型最多回答几次。一次回答算一次，中间可以调用工具。
    要计划和要反思的那几次另算。默认 25。到达上限时 ``run`` 抛出 ``ProviderError``，文本是 ``max_steps``。
    """

    def __init__(
        self,
        *,
        name: str,
        llm: Model,
        system_prompt: str,
        session: Session | None = None,
        tools: list[Tool] | None = None,
        skills_dir: Path | None = None,
        memory_path: Path | None = None,
        compact: bool = False,
        plan: bool = False,
        reflect: bool = False,
        subagents: bool = False,
        tool_hooks: list[ToolHook] | None = None,
        loop_on_event: Callable[[ProviderEvent], None] | None = None,
        max_chars: int = 80000,
        keep_last: int = 8,
        child_max_steps: int = 10,
        max_model_turns: int = 25,
    ) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        # 不传会话时只留在内存，同一实例的下一次 run 仍能看见这些消息。
        self.session = session if session is not None else Session.in_memory()
        # 复制一份，调用方之后改自己的列表不会影响助手。
        self.loop = Loop(
            provider=llm,
            tools=list(tools or []),
            session=self.session,
            system=system_prompt,
            tool_hooks=tool_hooks,
            on_event=loop_on_event,
            max_steps=max_model_turns,
        )
        # 没装模式时 runner 就是工具循环。装配会把它换成计划或反思，run 走最外层。
        self.runner: Runnable = self.loop
        # 这些阈值和 attach 的默认值相同。不打开任何模式时不加载模式包。
        if (
            skills_dir is not None
            or memory_path is not None
            or compact
            or plan
            or reflect
            or subagents
        ):
            from vector_harness.assembly import attach

            attach(
                self,
                skills_dir=skills_dir,
                memory_path=memory_path,
                compact=compact,
                plan=plan,
                reflect=reflect,
                subagents=subagents,
                max_chars=max_chars,
                keep_last=keep_last,
                child_max_steps=child_max_steps,
            )

    def add_tool(self, tool: Tool) -> None:
        """登记一个工具。下一次 ``run`` 会把它放进模型请求。"""
        self.loop.tools.append(tool)

    def run(self, user_text: str) -> str:
        """跑一轮，返回模型最后的文本。

        模型失败或到达步数上限时抛出 ``ProviderError``。工具调用成功后，
        返回的是模型看到工具结果之后给出的那一段回复。
        """
        # 自己开事件循环。已经有循环在跑时不能调用这个方法。
        result = asyncio.run(self.runner.run(user_text))
        if result.status == "error":
            raise ProviderError(result.text)
        # max_steps 等其它状态也收成 ProviderError，文本就是状态名。
        if result.status != "complete":
            raise ProviderError(result.status)
        return result.text

    def get_history(self) -> list[Message]:
        """返回这份会话里的全部消息，包括用户、助手和工具结果。"""
        return self.session.load()
