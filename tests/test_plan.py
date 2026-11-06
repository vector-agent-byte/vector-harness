from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import EditFile, Loop, Session, ToolCall
from vector_harness.patterns.plan import PlanThenExecute


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


def test_retries_non_string_steps_then_executes_with_plan_in_session(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "shipped.txt"
    session = Session.in_memory()
    edit = EditFile(workspace)

    class GuardedEdit:
        name = edit.name
        description = edit.description
        parameters = edit.parameters

        async def execute(self, arguments: dict) -> str:
            joined = "\n".join(message.content for message in session.load())
            assert "1. alpha" in joined
            assert not target.exists()
            return await edit.execute(arguments)

    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content='{"steps":[1]}'),
            ScriptedTurn(content='{"steps":["alpha"]}'),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="edit_file",
                        arguments={
                            "path": "shipped.txt",
                            "old_string": "",
                            "new_string": "ok",
                        },
                    )
                ]
            ),
            ScriptedTurn(content="done"),
        ]
    )
    loop = Loop(
        provider=provider,
        tools=[GuardedEdit()],
        session=session,
        system="sys",
    )
    runner = PlanThenExecute(loop)
    assert runner.loop is loop
    assert not target.exists()

    result = run(runner.run("ship it"))

    assert result.status == "complete"
    assert result.text == "done"
    assert result.steps == 4
    assert target.read_text(encoding="utf-8") == "ok"
    assert session.load()[0].content == "Plan:\n1. alpha"
    assert provider.calls[0]["tools"] == []
    assert any(
        "ship it" in message["content"] for message in provider.calls[0]["messages"]
    )


def test_two_invalid_plans_error_without_executing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "shipped.txt"
    session = Session.in_memory()
    edit = EditFile(workspace)
    leftover = ScriptedTurn(
        tool_calls=[
            ToolCall(
                id="1",
                name="edit_file",
                arguments={
                    "path": "shipped.txt",
                    "old_string": "",
                    "new_string": "nope",
                },
            )
        ]
    )
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="nope"),
            ScriptedTurn(content="nope"),
            leftover,
            ScriptedTurn(content="done"),
        ]
    )
    loop = Loop(
        provider=provider,
        tools=[edit],
        session=session,
        system="sys",
    )

    result = run(PlanThenExecute(loop).run("ship it"))

    assert result.status == "error"
    assert result.text.startswith("Invalid plan JSON:")
    assert result.steps == 2
    assert not target.exists()
    assert len(provider.turns) == 2
    assert all("Plan:" not in message.content for message in session.load())
