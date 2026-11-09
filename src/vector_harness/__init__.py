"""包的公开入口。

这里只导出核心类型、循环、会话、模型实现、对话助手和默认工具。
模式类不在这个列表里，这样 ``import vector_harness`` 不会把模式包加载进来。
"""

from vector_harness.core.agent import VectorHarness
from vector_harness.core.loop import Loop
from vector_harness.core.provider import OpenAICompatibleProvider
from vector_harness.core.session import Session
from vector_harness.tools.calculator import Calculator
from vector_harness.tools.edit import EditFile
from vector_harness.tools.read import ReadFile
from vector_harness.tools.shell import Shell
from vector_harness.types import (
    EventKind,
    Message,
    Model,
    ProviderError,
    ProviderEvent,
    Role,
    RunResult,
    RunStatus,
    ToolCall,
)

__all__ = [
    "Message",
    "ToolCall",
    "RunResult",
    "ProviderEvent",
    "ProviderError",
    "Role",
    "RunStatus",
    "EventKind",
    "Model",
    "Session",
    "Loop",
    "VectorHarness",
    "OpenAICompatibleProvider",
    "ReadFile",
    "EditFile",
    "Shell",
    "Calculator",
]


def __getattr__(name: str):
    """``attach`` 单独延迟导出，避免导入本包时加载模式。"""
    if name == "attach":
        from vector_harness.assembly import attach

        return attach
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
