from __future__ import annotations

import asyncio
import inspect
import sys
from dataclasses import dataclass, field

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Loop, Session, ToolCall
from vector_harness.patterns.subagent import delegate_tool


@pytest.fixture(scope="module", autouse=True)
def _unload_patterns_after_module():
    yield
    for name in list(sys.modules):
        if name == "vector_harness.patterns" or name.startswith(
            "vector_harness.patterns."
        ):
            del sys.modules[name]


def run(coro):
    return asyncio.run(coro)


@dataclass
class EchoTool:
    name: str = "echo"
    description: str = "Echo"
    parameters: dict = field(default_factory=dict)
    calls: int = 0

    async def execute(self, arguments: dict) -> str:
        self.calls += 1
        return arguments.get("text", "echoed")


@dataclass
class CountingTransform:
    calls: int = 0

    async def apply(self, messages):
        self.calls += 1
        return messages


def test_delegate_tool_max_steps_default_is_ten() -> None:
    assert inspect.signature(delegate_tool).parameters["max_steps"].default == 10


def test_delegate_strips_delegate_and_returns_child_final_text() -> None:
    echo = EchoTool()
    dummy_delegate = EchoTool(name="delegate")
    counter = CountingTransform()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="d1",
                        name="delegate",
                        arguments={"task": "find the token"},
                    )
                ]
            ),
            ScriptedTurn(content="CHILD-ONLY"),
            ScriptedTurn(content="parent-done"),
        ]
    )
    factory_tools = [dummy_delegate, echo]
    delegate = delegate_tool(
        provider=provider,
        tools=factory_tools,
        system="child-sys",
        context_transforms=[counter],
    )
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[echo, delegate],
        session=session,
        system="parent-sys",
    )

    result = run(loop.run("go"))

    assert result.status == "complete"
    assert result.text == "parent-done"

    child_call = provider.calls[1]
    assert "echo" in child_call["tools"]
    assert "delegate" not in child_call["tools"]
    assert any("find the token" in message["content"] for message in child_call["messages"])
    assert counter.calls >= 1

    messages = session.load()
    tool_messages = [m for m in messages if m.role == "tool"]
    assert tool_messages[0].content == "CHILD-ONLY"
    assert not any(
        m.role == "assistant" and m.content == "CHILD-ONLY" for m in messages
    )


def test_max_steps_one_echo_loop_prefixes_status() -> None:
    echo = EchoTool()
    dummy_delegate = EchoTool(name="delegate")
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="d1",
                        name="delegate",
                        arguments={"task": "find the token"},
                    )
                ]
            ),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="e1", name="echo", arguments={"text": "again"})
                ]
            ),
            ScriptedTurn(content="parent-done"),
        ]
    )
    delegate = delegate_tool(
        provider=provider,
        tools=[dummy_delegate, echo],
        system="child-sys",
        max_steps=1,
    )
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[echo, delegate],
        session=session,
        system="parent-sys",
    )

    result = run(loop.run("go"))

    assert result.status == "complete"
    tool_messages = [m for m in session.load() if m.role == "tool"]
    assert tool_messages[0].content.startswith("[max_steps]")
    child_calls = [c for c in provider.calls if "delegate" not in c["tools"]]
    assert len(child_calls) == 1


def test_delegate_keeps_the_same_hook_list() -> None:
    hooks: list = []
    delegate = delegate_tool(
        provider=object(),
        tools=[],
        system="s",
        tool_hooks=hooks,
    )
    assert delegate.tool_hooks is hooks


def test_child_hook_sees_child_messages_only() -> None:
    echo = EchoTool()

    class Remember:
        def __init__(self) -> None:
            self.seen: list[tuple[str, list[str]]] = []

        async def before_execute(self, call, messages):
            self.seen.append((call.name, [message.content for message in messages]))
            return None

    hook = Remember()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="d1",
                        name="delegate",
                        arguments={"task": "CHILD-TASK"},
                    )
                ]
            ),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="e1", name="echo", arguments={"text": "hi"})
                ]
            ),
            ScriptedTurn(content="child-done"),
            ScriptedTurn(content="parent-done"),
        ]
    )
    delegate = delegate_tool(
        provider=provider,
        tools=[echo],
        system="child-sys",
        tool_hooks=[hook],
    )
    loop = Loop(
        provider=provider,
        tools=[delegate],
        session=Session.in_memory(),
        system="parent-sys",
        tool_hooks=[hook],
    )

    result = run(loop.run("PARENT"))

    assert result.status == "complete"
    assert echo.calls == 1
    echo_calls = [contents for name, contents in hook.seen if name == "echo"]
    assert echo_calls
    assert any("CHILD-TASK" in content for content in echo_calls[0])
    assert all("PARENT" not in content for content in echo_calls[0])
