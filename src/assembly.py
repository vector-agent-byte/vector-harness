"""把模式装到工具循环上。

终端的 ``build_agent`` 和嵌入用的 ``attach`` 都调用 ``apply_patterns``。
这个模块可以导入模式。核心和包的顶部导入不会加载它。

重复装配时：同名工具就地替换；同一段提示已经在系统提示里就不再追加；
压缩只保留一份并更新阈值；计划和反思按「循环、计划、反思」重新包一层，不叠加。
传入 ``False`` 的开关不拆掉已经装上的模式。
"""

from __future__ import annotations

from pathlib import Path

from vector_harness.core.agent import VectorHarness
from vector_harness.core.loop import Loop


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
    runner,
    *,
    provider,
    skills_dir: Path | None = None,
    memory_path: Path | None = None,
    compact: bool = False,
    plan: bool = False,
    reflect: bool = False,
    subagents: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    keep_last: int = DEFAULT_KEEP_LAST,
    child_max_steps: int = DEFAULT_CHILD_MAX_STEPS,
):
    """把打开的模式装到 ``loop`` 上，返回最外层运行对象。"""
    if skills_dir is not None:
        from vector_harness.patterns.skills import Skills

        skills = Skills(skills_dir)
        _install_prompt(loop, skills.index_prompt())
        _replace_tool(loop, skills.read_tool())
    if memory_path is not None:
        from vector_harness.patterns.memory import Memory

        memory = Memory(memory_path)
        _install_prompt(loop, memory.prompt())
        _replace_tool(loop, memory.remember_tool())
    if compact:
        _install_compaction(
            loop,
            provider,
            max_chars=max_chars,
            keep_last=keep_last,
        )
    if subagents:
        from vector_harness.patterns.subagent import delegate_tool

        child_tools = [tool for tool in loop.tools if tool.name != "delegate"]
        delegate = delegate_tool(
            provider=provider,
            tools=child_tools,
            system=loop.system,
            context_transforms=loop.context_transforms,
            tool_hooks=loop.tool_hooks,
            max_steps=child_max_steps,
        )
        _replace_tool(loop, delegate)
        delegate.host = loop
    return _rewrap(loop, runner, plan=plan, reflect=reflect)


def attach(
    agent: VectorHarness,
    *,
    skills_dir: Path | None = None,
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


def _install_prompt(loop: Loop, text: str) -> None:
    """非空且尚未出现的提示，用一个换行接在系统提示后面。"""
    if text and text not in loop.system:
        loop.system = loop.system + "\n" + text


def _replace_tool(loop: Loop, tool) -> None:
    """同名工具留在原位置，换成新的。没有同名工具时追加到末尾。"""
    for index, existing in enumerate(loop.tools):
        if existing.name == tool.name:
            loop.tools[index] = tool
            return
    loop.tools.append(tool)


def _install_compaction(loop: Loop, provider, *, max_chars: int, keep_last: int) -> None:
    """压缩只留一份。再次装配时更新阈值，不追加第二个变换。"""
    from vector_harness.patterns.compact import Compaction

    for existing in loop.context_transforms:
        if isinstance(existing, Compaction):
            existing.provider = provider
            existing.max_chars = max_chars
            existing.keep_last = keep_last
            return
    loop.context_transforms.append(
        Compaction(provider, max_chars=max_chars, keep_last=keep_last)
    )


def _rewrap(loop: Loop, runner, *, plan: bool, reflect: bool):
    """需要计划或反思时，从工具循环重新包一层。两个都不要时保持原运行对象。"""
    from vector_harness.patterns.plan import PlanThenExecute
    from vector_harness.patterns.reflect import Reflect

    if not plan and not reflect:
        return runner
    has_reflect = isinstance(runner, Reflect)
    inner = runner.inner if has_reflect else runner
    has_plan = isinstance(inner, PlanThenExecute)
    wrapped = PlanThenExecute(loop) if plan or has_plan else loop
    if reflect or has_reflect:
        return Reflect(wrapped)
    return wrapped
