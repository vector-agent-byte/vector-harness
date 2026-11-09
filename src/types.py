"""核心里流通的数据结构。

循环、会话、模型和工具只通过这些类型交换信息。模式模块可以依赖它们，
核心不依赖任何模式。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class ProviderError(Exception):
    """模型请求在重试之后仍然失败。

    循环只把这一种异常收成 ``status="error"``。工具抛出的异常留在工具结果里，
    其它异常继续向外抛。
    """


@dataclass
class ToolCall:
    """模型发出的一次工具调用。

    ``arguments`` 在协议上是 dict。流还没结束时可以暂时是 ``None``，
    解析失败时循环会拒绝执行，而不是把它当成空参数。
    """

    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    """会话里的一条消息。

    ``role`` 是 ``user``、``assistant`` 或 ``tool``。助手消息可以带
    ``tool_calls``。工具消息用 ``tool_call_id`` 对上那一次调用，
    ``is_error`` 标记这次工具结果是失败。
    """

    role: str
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    is_error: bool = False


@dataclass
class RunResult:
    """一轮 ``Loop.run`` 的结果。

    ``complete``：模型给出了不含工具调用的回复。
    ``max_steps``：到达步数上限时仍在调用工具，``text`` 为空。
    ``error``：模型接口失败。``steps`` 计入每一次模型请求。
    """

    status: str
    text: str
    steps: int
    session_path: Path | None


@dataclass
class ProviderEvent:
    """模型流向外发出的一个观察事件。

    ``kind`` 只有 ``text_delta``、``tool_call_start``、``tool_call_end``、
    ``run_end``。这是终端的观察口，不是模式插件。
    ``tool_call_start`` 的 ``arguments`` 保持 ``None``，参数要等
    ``tool_call_end`` 才完整。
    """

    kind: str
    text: str = ""
    name: str = ""
    tool_call_id: str = ""
    arguments: dict | None = None


@runtime_checkable
class Tool(Protocol):
    """模型可以调用的一个工具。

    ``parameters`` 是 JSON Schema。``execute`` 返回给模型看的文本。
    抛出的异常由循环捕获，变成一条失败的工具消息，循环本身继续。
    """

    name: str
    description: str
    parameters: dict

    async def execute(self, arguments: dict) -> str:
        """用参数执行工具，返回交给模型的文本。"""
        ...


@runtime_checkable
class ContextTransform(Protocol):
    """每次模型请求前可以改写会话消息的钩子。

    只看见会话里的消息，看不见 system。返回的列表和原文序列化结果不同时，
    循环会整份写回会话。压缩是这个协议的一个实现，定义在模式包里。
    """

    async def apply(self, messages: list[Message]) -> list[Message]:
        """返回这一步实际送给模型的消息列表。"""
        ...
