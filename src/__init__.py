"""包的公开入口。

这里只导出核心类型、循环、会话、模型实现、对话助手和默认工具。
模式类不在这个列表里，这样 ``import vector_harness`` 不会把模式包加载进来。
"""

from vector_harness.core.agent import SimpleAgent
from vector_harness.core.loop import Loop
from vector_harness.core.provider import OpenAICompatibleProvider
from vector_harness.core.session import Session
from vector_harness.tools.calculator import Calculator
from vector_harness.tools.edit import EditFile
from vector_harness.tools.read import ReadFile
from vector_harness.tools.shell import Shell
from vector_harness.types import Message, ProviderError, ProviderEvent, RunResult, ToolCall

__all__ = [
    "Message",
    "ToolCall",
    "RunResult",
    "ProviderEvent",
    "ProviderError",
    "Session",
    "Loop",
    "SimpleAgent",
    "OpenAICompatibleProvider",
    "ReadFile",
    "EditFile",
    "Shell",
    "Calculator",
]
