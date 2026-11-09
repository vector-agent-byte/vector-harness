"""可嵌入的对话助手。

包住现有的工具循环，给调用方一个同步的 ``run``。历史留在内存会话里，
同一实例上的下一次 ``run`` 能看见之前的消息。工具用 ``add_tool`` 挂上，
下一轮才会交给模型。
"""

from __future__ import annotations

import asyncio
from typing import Any

from vector_harness.core.loop import Loop
from vector_harness.core.session import Session
from vector_harness.types import Message, ProviderError, Tool


class SimpleAgent:
    """带名字、系统提示和可选工具的助手。

    ``llm`` 只要有 ``stream(system, messages, tools)``，测试可以传入脚本化的实现。
    ``run`` 在普通脚本里调用。它自己开事件循环，不要放进已经在跑的异步函数里。
    """

    def __init__(
        self,
        *,
        name: str,
        llm: Any,
        system_prompt: str,
        session: Session | None = None,
        max_steps: int = 25,
    ) -> None:
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.session = session if session is not None else Session.in_memory()
        self.loop = Loop(
            provider=llm,
            tools=[],
            session=self.session,
            system=system_prompt,
            max_steps=max_steps,
        )

    def add_tool(self, tool: Tool) -> None:
        """登记一个工具。下一次 ``run`` 会把它放进模型请求。"""
        self.loop.tools.append(tool)

    def run(self, user_text: str) -> str:
        """跑一轮，返回模型最后的文本。

        模型失败或到达步数上限时抛出 ``ProviderError``。工具调用成功后，
        返回的是模型看到工具结果之后给出的那一段回复。
        """
        result = asyncio.run(self.loop.run(user_text))
        if result.status == "error":
            raise ProviderError(result.text)
        if result.status != "complete":
            raise ProviderError(result.status)
        return result.text

    def get_history(self) -> list[Message]:
        """返回这份会话里的全部消息，包括用户、助手和工具结果。"""
        return self.session.load()
