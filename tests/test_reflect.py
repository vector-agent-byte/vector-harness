from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Loop, Session, ToolCall
from vector_harness.types import ProviderError, ProviderEvent


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


def _reflect():
    from vector_harness.patterns.reflect import Reflect

    return Reflect


def test_ok_keeps_the_answer_and_does_not_run_again() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="answer"),
            ScriptedTurn(content='{"ok": true}'),
            ScriptedTurn(content="should-not-run"),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "complete"
    assert result.text == "answer"
    assert result.steps == 2
    assert len(provider.turns) == 1
    assert provider.calls[1]["tools"] == []
    assert provider.calls[1]["messages"][-1]["content"] == "answer"
    assert all("Reflection:" not in message.content for message in session.load())


def test_not_ok_runs_the_critique_once() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="draft"),
            ScriptedTurn(content='{"ok": false, "critique": "add a period"}'),
            ScriptedTurn(content="draft."),
            ScriptedTurn(content='{"ok": true}'),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "complete"
    assert result.text == "draft."
    assert result.steps == 3
    assert len(provider.turns) == 1
    assert provider.calls[1]["tools"] == []
    critique = session.load()[2]
    assert critique.role == "user"
    assert critique.content == "Reflection:\nadd a period"
    assert provider.calls[2]["messages"][-1]["content"] == critique.content


def test_invalid_json_retries_once_then_accepts() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="answer"),
            ScriptedTurn(content="nope"),
            ScriptedTurn(content='{"ok": true}'),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "complete"
    assert result.text == "answer"
    assert result.steps == 3
    assert provider.calls[2]["tools"] == []
    assert provider.calls[2]["messages"] == [
        {
            "role": "user",
            "content": "Invalid reflection JSON: nope",
            "tool_calls": None,
            "tool_call_id": None,
            "is_error": False,
        }
    ]


def test_two_invalid_reflections_error_without_revising() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="answer"),
            ScriptedTurn(content="nope"),
            ScriptedTurn(content="nope"),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="edit_file", arguments={"path": "x"})
                ]
            ),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "error"
    assert result.text.startswith("Invalid reflection JSON:")
    assert result.steps == 3
    assert len(provider.turns) == 1
    assert all("Reflection:" not in message.content for message in session.load())


def test_max_steps_skips_reflection() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="missing", arguments={"path": "x"})
                ]
            ),
            ScriptedTurn(content='{"ok": true}'),
        ]
    )
    loop = Loop(
        provider=provider, tools=[], session=session, system="sys", max_steps=1
    )

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "max_steps"
    assert result.steps == 1
    assert len(provider.turns) == 1


def test_reflection_provider_error_stops() -> None:
    session = Session.in_memory()

    class Flaky:
        def __init__(self) -> None:
            self.calls = 0

        async def stream(self, *, system: str, messages: list, tools: list):
            self.calls += 1
            if self.calls == 1:
                yield ProviderEvent(kind="text_delta", text="draft")
                return
            raise ProviderError("reflect down")

    provider = Flaky()
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "error"
    assert result.text == "reflect down"
    assert result.steps == 2
    assert provider.calls == 2


def test_build_agent_wraps_reflect_outside_plan(tmp_path: Path) -> None:
    import vector_harness.cli as cli_mod
    from vector_harness.core.loop import Loop as CoreLoop

    workspace = tmp_path / "ws"
    workspace.mkdir()
    agent = cli_mod.build_agent(
        provider=ScriptedProvider(turns=[]),
        workspace=workspace,
        session=Session.in_memory(),
        plan=True,
        reflect=True,
    )
    assert type(agent) is cli_mod.Reflect
    assert type(agent.inner) is cli_mod.PlanThenExecute
    assert type(agent.loop) is CoreLoop


def test_reflect_flag_prints_the_inner_loop(tmp_path: Path, capsys) -> None:
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="answer"),
            ScriptedTurn(content='{"ok": true}'),
        ]
    )
    code = main(
        ["--workspace", str(workspace), "--reflect", "ship it"],
        environ={},
        provider=provider,
    )
    assert code == 0
    assert "answer" in capsys.readouterr().out
    assert provider.calls[1]["tools"] == []
