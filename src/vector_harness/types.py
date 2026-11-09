"""核心里流通的数据结构。

循环、会话、模型和工具只通过这些类型交换信息。模式模块可以依赖它们，
核心不依赖任何模式。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class Role(StrEnum):
    """会话消息的角色。值就是落盘和比较时用的字符串。"""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class RunStatus(StrEnum):
    """一轮运行的结束状态。"""

    COMPLETE = "complete"
    MAX_STEPS = "max_steps"
    ERROR = "error"


class EventKind(StrEnum):
    """模型流和循环向外发出的事件种类。"""

    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    RUN_END = "run_end"


# 参数 JSON 解析失败时放进 arguments 的键。循环见到它就拒绝执行。
INVALID_TOOL_ARGUMENTS = "_invalid_json"


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

    ``kind`` 有 ``thinking_delta``、``text_delta``、``tool_call_start``、
    ``tool_call_end``、``run_end``。这是终端的观察口，不是模式插件。
    ``thinking_delta`` 是模型的思考过程，只给观察方看，不写入会话。
    ``tool_call_start`` 的 ``arguments`` 保持 ``None``，参数要等
    ``tool_call_end`` 才完整。``origin`` 为空是当前循环，``child`` 是子代理。
    """

    kind: str
    text: str = ""
    name: str = ""
    tool_call_id: str = ""
    arguments: dict | None = None
    origin: str = ""


# 可以 isinstance 检查。循环按这些字段调用，工具不必继承某个基类。
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


# 和 Tool 一样，只约定方法，不规定放在哪个模块。
@runtime_checkable
class ContextTransform(Protocol):
    """每次模型请求前可以改写会话消息的钩子。

    只看见会话里的消息，看不见 system。返回的列表和原文序列化结果不同时，
    循环会整份写回会话。压缩是这个协议的一个实现，定义在模式包里。
    """

    async def apply(self, messages: list[Message]) -> list[Message]:
        """返回这一步实际送给模型的消息列表。"""
        ...


@dataclass
class ToolHookResult:
    """一次执行前钩子的决定。

    ``arguments`` 不是 None 时，用这份参数替换该次调用。
    ``deny`` 是非空字符串时不执行工具，这段文字成为失败的工具消息。
    两者都是 None，或钩子直接返回 None，表示原样放行。
    """

    arguments: dict | None = None
    deny: str | None = None


# 和 ContextTransform 一样，只约定方法。核心不附带具体策略。
@runtime_checkable
class ToolHook(Protocol):
    """工具执行前的钩子。

    看见这一次调用和当前会话消息，看不见 system。
    """

    async def before_execute(
        self, call: ToolCall, messages: list[Message]
    ) -> ToolHookResult | None:
        """返回放行、改参数或拒绝。返回 None 表示不改、不拒绝。"""
        ...


@runtime_checkable
class Model(Protocol):
    """能按会话流式回答的模型。

    测试里的脚本化模型和 ``OpenAICompatibleProvider`` 都满足这个协议。
    循环只依赖 ``stream``，不依赖具体客户端。
    """

    def stream(
        self, *, system: str, messages: list[Message], tools: list
    ) -> AsyncIterator[ProviderEvent]:
        """产出文本增量、思考增量和工具调用事件。"""
        ...


@runtime_checkable
class Runnable(Protocol):
    """能跑一轮用户文本的对象。

    工具循环、计划和反思都实现它。``loop`` 是最内层的工具循环，
    调用方用它挂观察回调，不用再沿包装链往下找。
    """

    loop: Any

    async def run(self, user_text: str) -> RunResult:
        """执行一轮，返回完整结果。"""
        ...
