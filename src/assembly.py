"""把模式装到已经加好工具的 VectorHarness 上。

这个模块可以导入模式。核心和包的顶部导入不会加载它。
计划和反思包在循环外面，反思在最外层。
"""

from __future__ import annotations

from pathlib import Path

from vector_harness.core.agent import VectorHarness
from vector_harness.patterns.compact import Compaction
from vector_harness.patterns.memory import Memory
from vector_harness.patterns.plan import PlanThenExecute
from vector_harness.patterns.reflect import Reflect
from vector_harness.patterns.skills import Skills
from vector_harness.patterns.subagent import delegate_tool


def attach(
    agent: VectorHarness,
    *,
    skills_dir: Path | None = None,
    memory_path: Path | None = None,
    compact: bool = False,
    plan: bool = False,
    reflect: bool = False,
    subagents: bool = False,
    max_chars: int = 80000,
    keep_last: int = 8,
    child_max_steps: int = 10,
) -> None:
    """按显式参数装配。未打开的模式不挂上。"""
    if skills_dir is not None:
        skills = Skills(skills_dir)
        _append_prompt(agent, skills.index_prompt())
        agent.add_tool(skills.read_tool())
    if memory_path is not None:
        memory = Memory(memory_path)
        _append_prompt(agent, memory.prompt())
        agent.add_tool(memory.remember_tool())
    if compact:
        agent.loop.context_transforms.append(
            Compaction(agent.llm, max_chars=max_chars, keep_last=keep_last)
        )
    if subagents:
        delegate = delegate_tool(
            provider=agent.llm,
            tools=list(agent.loop.tools),
            system=agent.loop.system,
            context_transforms=agent.loop.context_transforms,
            max_steps=child_max_steps,
        )
        agent.add_tool(delegate)
        delegate.host = agent.loop
    if plan:
        agent.runner = PlanThenExecute(agent.runner)
    if reflect:
        agent.runner = Reflect(agent.runner)


def _append_prompt(agent: VectorHarness, text: str) -> None:
    """非空提示用一个换行接在系统提示后面。空文本不改原文。"""
    if text:
        agent.loop.system = agent.loop.system + "\n" + text
        agent.system_prompt = agent.loop.system
