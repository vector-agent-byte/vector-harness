"""把模式装到工具循环上。

终端的 ``build_agent`` 和嵌入用的 ``attach`` 都调用 ``apply_patterns``。
每种模式怎么挂上，写在该模式自己的 ``attach_*`` 里。这里只决定顺序和重复装配：

同名工具就地替换；同一段提示已经在系统提示里就不再追加；
压缩只保留一份并更新阈值；计划和反思按「循环、计划、反思」重新包一层，不叠加。
传入 ``False`` 的开关不拆掉已经装上的模式。

这个模块可以导入模式。核心和包的顶部导入不会加载它。
"""

from __future__ import annotations

from pathlib import Path

from vector_harness.core.agent import VectorHarness
from vector_harness.core.loop import Loop
from vector_harness.types import Model, Runnable


def _load_patterns() -> None:
    """导入本模块时加载模式包。``attach`` 的延迟导出依赖这一点。"""
    import vector_harness.patterns.compact
    import vector_harness.patterns.memory
    import vector_harness.patterns.plan
    import vector_harness.patterns.reflect
    import vector_harness.patterns.skills
    import vector_harness.patterns.subagent


_load_patterns()

DEFAULT_MAX_CHARS = 80000
DEFAULT_KEEP_LAST = 8
DEFAULT_CHILD_MAX_STEPS = 10


def apply_patterns(
    loop: Loop,
    runner: Runnable,
    *,
    provider: Model,
    skills_dir: Path | None = None,
    skill_name: str | None = None,
    memory_path: Path | None = None,
    compact: bool = False,
    plan: bool = False,
    reflect: bool = False,
    subagents: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    keep_last: int = DEFAULT_KEEP_LAST,
    child_max_steps: int = DEFAULT_CHILD_MAX_STEPS,
) -> Runnable:
    """把打开的模式装到 ``loop`` 上，返回最外层运行对象。"""
    if skills_dir is not None:
        from vector_harness.patterns.skills import attach_skills

        attach_skills(loop, skills_dir, only=skill_name)
    if memory_path is not None:
        from vector_harness.patterns.memory import attach_memory

        attach_memory(loop, memory_path)
    if compact:
        from vector_harness.patterns.compact import attach_compaction

        attach_compaction(
            loop, provider, max_chars=max_chars, keep_last=keep_last
        )
    if subagents:
        from vector_harness.patterns.subagent import attach_delegate

        attach_delegate(loop, provider=provider, max_steps=child_max_steps)
    return _rewrap(loop, runner, plan=plan, reflect=reflect)


def attach(
    agent: VectorHarness,
    *,
    skills_dir: Path | None = None,
    skill_name: str | None = None,
    memory_path: Path | None = None,
    compact: bool = False,
    plan: bool = False,
    reflect: bool = False,
    subagents: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    keep_last: int = DEFAULT_KEEP_LAST,
    child_max_steps: int = DEFAULT_CHILD_MAX_STEPS,
) -> None:
    """按显式参数装配。未打开的模式不挂上，已经打开的模式不会被拆掉。"""
    agent.runner = apply_patterns(
        agent.loop,
        agent.runner,
        provider=agent.llm,
        skills_dir=skills_dir,
        skill_name=skill_name,
        memory_path=memory_path,
        compact=compact,
        plan=plan,
        reflect=reflect,
        subagents=subagents,
        max_chars=max_chars,
        keep_last=keep_last,
        child_max_steps=child_max_steps,
    )
    agent.system_prompt = agent.loop.system


def _rewrap(loop: Loop, runner: Runnable, *, plan: bool, reflect: bool) -> Runnable:
    """需要计划或反思时，从工具循环重新包一层。两个都不要时保持原运行对象。"""
    from vector_harness.patterns.plan import TodoPlan
    from vector_harness.patterns.reflect import ToolReflect

    if not plan and not reflect:
        return runner
    has_reflect = isinstance(runner, ToolReflect)
    inner = runner.inner if has_reflect else runner
    has_plan = isinstance(inner, TodoPlan)
    wrapped: Runnable = TodoPlan(loop) if plan or has_plan else loop
    if reflect or has_reflect:
        return ToolReflect(wrapped)
    return wrapped
