from __future__ import annotations

import asyncio
import sys

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Loop, Session, ToolCall
from vector_harness.patterns.plan import TodoPlan


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


def test_update_todos_tool_registered_on_loop() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(turns=[ScriptedTurn(content="done")])
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    runner = TodoPlan(loop)

    assert runner.loop is loop
    assert any(t.name == "update_todos" for t in loop.tools)


def test_all_completed_todos_no_continuation() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="update_todos",
                        arguments={
                            "todos": [
                                {"id": 1, "content": "step one", "status": "completed"}
                            ]
                        },
                    )
                ]
            ),
            ScriptedTurn(content="done"),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    runner = TodoPlan(loop)

    result = run(runner.run("do it"))

    assert result.status == "complete"
    assert result.text == "done"
    assert result.steps == 2
    assert len(provider.turns) == 0


def test_unfinished_todos_trigger_continuation() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            # First run: creates todos but leaves one pending
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="update_todos",
                        arguments={
                            "todos": [
                                {"id": 1, "content": "step one", "status": "pending"}
                            ]
                        },
                    )
                ]
            ),
            ScriptedTurn(content="started"),
            # Continuation: marks task completed
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="update_todos",
                        arguments={
                            "todos": [
                                {"id": 1, "content": "step one", "status": "completed"}
                            ]
                        },
                    )
                ]
            ),
            ScriptedTurn(content="done"),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    runner = TodoPlan(loop)

    result = run(runner.run("do it"))

    assert result.status == "complete"
    assert result.text == "done"
    assert result.steps == 4
    messages = session.load()
    reminder = next(
        (m for m in messages if m.role == "user" and "未完成" in m.content), None
    )
    assert reminder is not None


def test_two_in_progress_rejected() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="update_todos",
                        arguments={
                            "todos": [
                                {"id": 1, "content": "step one", "status": "in_progress"},
                                {"id": 2, "content": "step two", "status": "in_progress"},
                            ]
                        },
                    )
                ]
            ),
            ScriptedTurn(content="done"),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    runner = TodoPlan(loop)

    result = run(runner.run("do it"))

    assert result.status == "complete"
    tool_msg = next(m for m in session.load() if m.role == "tool")
    assert "Error" in tool_msg.content
    assert "in_progress" in tool_msg.content


def test_no_todos_simple_answer() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(turns=[ScriptedTurn(content="hello")])
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    runner = TodoPlan(loop)

    result = run(runner.run("hi"))

    assert result.status == "complete"
    assert result.text == "hello"
    assert result.steps == 1


def test_plan_prompt_added_to_system() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(turns=[ScriptedTurn(content="ok")])
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    TodoPlan(loop)

    assert "update_todos" in loop.system


def test_max_steps_during_execution_propagates() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="unknown_tool", arguments={})
                ]
            ),
        ]
    )
    loop = Loop(
        provider=provider, tools=[], session=session, system="sys", max_steps=1
    )
    runner = TodoPlan(loop)

    result = run(runner.run("do it"))

    assert result.status == "max_steps"
