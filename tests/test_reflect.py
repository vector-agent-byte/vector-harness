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
    from vector_harness.patterns.reflect import ToolReflect

    return ToolReflect


def test_pass_keeps_the_answer_and_does_not_run_again() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="answer"),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="v1",
                        name="submit_verdict",
                        arguments={"pass": True, "critique": "通过"},
                    )
                ]
            ),
            ScriptedTurn(content="should-not-run"),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "complete"
    assert result.text == "answer"
    assert result.steps == 2
    assert len(provider.turns) == 1
    assert provider.calls[1]["tools"] == ["submit_verdict"]
    last_msg = provider.calls[1]["messages"][-1]["content"]
    assert "ship it" in last_msg
    assert "answer" in last_msg
    assert all("Reflection:" not in message.content for message in session.load())


def test_fail_runs_critique_once() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="draft"),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="v1",
                        name="submit_verdict",
                        arguments={"pass": False, "critique": "add a period"},
                    )
                ]
            ),
            ScriptedTurn(content="draft."),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "complete"
    assert result.text == "draft."
    assert result.steps == 3
    assert len(provider.turns) == 0
    assert provider.calls[1]["tools"] == ["submit_verdict"]
    critique = session.load()[2]
    assert critique.role == "user"
    assert critique.content == "Reflection:\nadd a period"
    assert provider.calls[2]["messages"][-1]["content"] == critique.content


def test_no_tool_call_uses_text_as_critique() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="answer"),
            ScriptedTurn(content="needs more detail"),  # reviewer outputs text, no tool
            ScriptedTurn(content="revised"),
        ]
    )
    loop = Loop(provider=provider, tools=[], session=session, system="sys")

    result = run(_reflect()(loop).run("ship it"))

    assert result.status == "complete"
    assert result.text == "revised"
    assert result.steps == 3
    messages = session.load()
    assert any("Reflection:\nneeds more detail" in m.content for m in messages)


def test_max_steps_skips_reflection() -> None:
    session = Session.in_memory()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="missing", arguments={"path": "x"})
                ]
            ),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="v1",
                        name="submit_verdict",
                        arguments={"pass": True, "critique": "通过"},
                    )
                ]
            ),
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
    from vector_harness.patterns.plan import TodoPlan
    from vector_harness.patterns.reflect import ToolReflect

    assert type(agent) is ToolReflect
    assert type(agent.inner) is TodoPlan
    assert type(agent.loop) is CoreLoop


def test_reflect_flag_prints_the_inner_loop(tmp_path: Path, capsys) -> None:
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="answer"),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="v1",
                        name="submit_verdict",
                        arguments={"pass": True, "critique": "通过"},
                    )
                ]
            ),
        ]
    )
    code = main(
        ["--workspace", str(workspace), "--reflect", "ship it"],
        environ={},
        provider=provider,
    )
    assert code == 0
    assert "answer" in capsys.readouterr().out
    assert provider.calls[1]["tools"] == ["submit_verdict"]
