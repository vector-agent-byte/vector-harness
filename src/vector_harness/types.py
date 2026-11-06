from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    is_error: bool = False


@dataclass
class RunResult:
    status: str
    text: str
    steps: int
    session_path: Path | None


@dataclass
class ProviderEvent:
    kind: str
    text: str = ""
    name: str = ""
    tool_call_id: str = ""
    arguments: dict | None = None


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    parameters: dict

    async def execute(self, arguments: dict) -> str: ...


@runtime_checkable
class ContextTransform(Protocol):
    async def apply(self, messages: list[Message]) -> list[Message]: ...
