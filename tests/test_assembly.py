from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import VectorHarness
from vector_harness.assembly import attach
from vector_harness.patterns.compact import Compaction


@pytest.fixture(scope="module", autouse=True)
def _unload_patterns_after_module():
    yield
    for name in list(sys.modules):
        if name == "vector_harness.patterns" or name.startswith(
            "vector_harness.patterns."
        ):
            del sys.modules[name]


def _agent(system: str = "原文") -> VectorHarness:
    return VectorHarness(name="助手", llm=object(), system_prompt=system)


def _names(agent: VectorHarness) -> list[str]:
    return [tool.name for tool in agent.loop.tools]


@dataclass
class NamedTool:
    name: str
    description: str = "tool"
    parameters: dict = field(default_factory=dict)

    async def execute(self, arguments: dict) -> str:
        return self.name


def test_attach_defaults_leave_agent_unchanged():
    agent = _agent()
    tool = NamedTool("echo")
    agent.add_tool(tool)

    attach(agent)

    assert agent.loop.system == "原文"
    assert agent.loop.tools == [tool]
    assert agent.runner is agent.loop


def test_skills_append_index_and_read_tool(tmp_path: Path):
    skill = tmp_path / "greet.md"
    skill.write_text(
        "---\nname: greet\ndescription: Say hello\n---\nHello\n",
        encoding="utf-8",
        newline="\n",
    )
    agent = _agent()

    attach(agent, skills_dir=tmp_path)

    assert agent.loop.system.startswith("原文\n")
    assert "- greet:" in agent.loop.system
    assert "read_skill" in _names(agent)


def test_missing_skill_dir_keeps_system_and_adds_read_tool(tmp_path: Path):
    agent = _agent()

    attach(agent, skills_dir=tmp_path / "missing")

    assert agent.loop.system == "原文"
    assert "read_skill" in _names(agent)


def test_memory_appends_existing_text_and_remember_tool(tmp_path: Path):
    existing = tmp_path / "MEMORY.md"
    existing.write_text("- 2026-11-09: 代号\n", encoding="utf-8")
    agent = _agent()
    attach(agent, memory_path=existing)
    assert "代号" in agent.loop.system
    assert "remember" in _names(agent)

    fresh = _agent()
    attach(fresh, memory_path=tmp_path / "absent.md")
    assert fresh.loop.system == "原文"
    assert "remember" in _names(fresh)


def test_compact_uses_given_thresholds():
    agent = _agent()

    attach(agent, compact=True, max_chars=25, keep_last=1)

    assert len(agent.loop.context_transforms) == 1
    compaction = agent.loop.context_transforms[0]
    assert isinstance(compaction, Compaction)
    assert compaction.max_chars == 25
    assert compaction.keep_last == 1


def test_subagent_snapshot_excludes_tools_added_later():
    agent = _agent()
    agent.add_tool(NamedTool("echo"))

    attach(agent, subagents=True, child_max_steps=4)
    agent.add_tool(NamedTool("later"))

    assert _names(agent) == ["echo", "delegate", "later"]
    delegate = agent.loop.tools[1]
    assert [tool.name for tool in delegate.tools] == ["echo"]
    assert delegate.max_steps == 4
    assert delegate.host is agent.loop


def test_attach_updates_system_prompt_attribute(tmp_path: Path):
    skill = tmp_path / "greet.md"
    skill.write_text(
        "---\nname: greet\ndescription: Say hello\n---\nHello\n",
        encoding="utf-8",
        newline="\n",
    )
    agent = _agent()

    attach(agent, skills_dir=tmp_path)

    assert agent.system_prompt == agent.loop.system
    assert agent.system_prompt.startswith("原文\n")
    assert "- greet:" in agent.system_prompt


def test_subagent_snapshot_includes_skills_and_memory(tmp_path: Path):
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    (skill_dir / "greet.md").write_text(
        "---\nname: greet\ndescription: Say hello\n---\nHello\n",
        encoding="utf-8",
        newline="\n",
    )
    memory = tmp_path / "MEMORY.md"
    memory.write_text("- 2026-11-09: 代号\n", encoding="utf-8")
    agent = _agent()
    agent.add_tool(NamedTool("echo"))

    attach(agent, skills_dir=skill_dir, memory_path=memory, subagents=True)
    agent.add_tool(NamedTool("later"))

    delegate = next(tool for tool in agent.loop.tools if tool.name == "delegate")
    assert [tool.name for tool in delegate.tools] == ["echo", "read_skill", "remember"]
    assert "later" not in [tool.name for tool in delegate.tools]
    assert "delegate" not in [tool.name for tool in delegate.tools]


def test_repeated_compact_replaces_the_existing_transform():
    agent = _agent()

    attach(agent, compact=True, max_chars=100, keep_last=4)
    attach(agent, compact=True, max_chars=25, keep_last=1)

    assert len(agent.loop.context_transforms) == 1
    compaction = agent.loop.context_transforms[0]
    assert isinstance(compaction, Compaction)
    assert compaction.max_chars == 25
    assert compaction.keep_last == 1


def test_repeated_plan_and_reflect_stay_one_layer():
    agent = _agent()

    attach(agent, plan=True, reflect=True)
    attach(agent, plan=True, reflect=True)

    assert type(agent.runner).__name__ == "Reflect"
    assert type(agent.runner.inner).__name__ == "PlanThenExecute"
    assert agent.runner.inner.loop is agent.loop
    assert agent.runner.loop is agent.loop


def test_attach_replaces_a_tool_with_the_same_name(tmp_path: Path):
    skill = tmp_path / "greet.md"
    skill.write_text(
        "---\nname: greet\ndescription: Say hello\n---\nHello\n",
        encoding="utf-8",
        newline="\n",
    )
    agent = _agent()
    agent.add_tool(NamedTool("read_skill"))

    attach(agent, skills_dir=tmp_path)
    attach(agent, skills_dir=tmp_path)

    assert _names(agent).count("read_skill") == 1
    assert agent.loop.system.count("Skills:") == 1
    tool = next(item for item in agent.loop.tools if item.name == "read_skill")
    assert asyncio.run(tool.execute({"name": "greet"})) == "Hello\n"


def test_constructor_attaches_skills_plan_and_reflect(tmp_path: Path):
    skill = tmp_path / "greet.md"
    skill.write_text(
        "---\nname: greet\ndescription: Say hello\n---\nHello\n",
        encoding="utf-8",
        newline="\n",
    )

    agent = VectorHarness(
        name="助手",
        llm=object(),
        system_prompt="原文",
        skills_dir=tmp_path,
        plan=True,
        reflect=True,
    )

    assert "- greet:" in agent.system_prompt
    assert agent.system_prompt == agent.loop.system
    assert "read_skill" in _names(agent)
    assert type(agent.runner).__name__ == "Reflect"
    assert type(agent.runner.inner).__name__ == "PlanThenExecute"
    assert agent.runner.loop is agent.loop


def test_constructor_forwards_compact_thresholds():
    agent = VectorHarness(
        name="助手",
        llm=object(),
        system_prompt="原文",
        compact=True,
        max_chars=25,
        keep_last=1,
    )

    compaction = agent.loop.context_transforms[0]
    assert isinstance(compaction, Compaction)
    assert compaction.max_chars == 25
    assert compaction.keep_last == 1


def test_plan_then_reflect_wraps_in_that_order():
    agent = _agent()

    attach(agent, plan=True, reflect=True)

    assert type(agent.runner).__name__ == "Reflect"
    assert type(agent.runner.inner).__name__ == "PlanThenExecute"
    assert agent.runner.inner.loop is agent.loop


def test_failed_reflection_plans_again():
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content='{"steps":["one"]}'),
            ScriptedTurn(content="第一版"),
            ScriptedTurn(content='{"ok": false, "critique": "改"}'),
            ScriptedTurn(content='{"steps":["two"]}'),
            ScriptedTurn(content="第二版"),
        ]
    )
    agent = VectorHarness(name="助手", llm=provider, system_prompt="原文")
    attach(agent, plan=True, reflect=True)

    assert agent.run("任务") == "第二版"
    text = "\n".join(message.content for message in agent.get_history())
    assert text.index("1. one") < text.index("1. two")
    assert "Reflection:" in text
