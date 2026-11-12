"""从参数和环境拿到一个可运行的助手。

终端和网页共用这一层：环境合并、配置文件、模型提供方，以及按开关装配工具循环。
这里的函数不打印，也不决定失败时返回什么，调用方自己处理 ``ProviderError``。

这个模块可以导入模式，核心和包的顶部导入不会加载它。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from vector_harness.assembly import (
    DEFAULT_CHILD_MAX_STEPS,
    DEFAULT_KEEP_LAST,
    DEFAULT_MAX_CHARS,
    apply_patterns,
)
from vector_harness.core.config import apply_config, default_config_path
from vector_harness.core.loop import Loop
from vector_harness.core.provider import OpenAICompatibleProvider
from vector_harness.core.session import Session
from vector_harness.tools.edit import EditFile
from vector_harness.tools.read import ReadFile
from vector_harness.tools.shell import Shell

DEFAULT_SYSTEM = "You are a capable agent. Use tools to finish the task in the workspace."


def build_agent(
    *,
    provider,
    workspace: Path,
    session: Session,
    skills_dir: Path | None = None,
    skill_name: str | None = None,
    memory_path: Path | None = None,
    compact: bool = False,
    plan: bool = False,
    reflect: bool = False,
    subagents: bool = False,
    max_steps: int = 25,
):
    """按显式开关装配循环。默认只有读、改、命令三个工具，模式不打开就不挂上。

    模式的阈值和包装顺序与 ``attach`` 共用 ``apply_patterns``。
    """
    loop = Loop(
        provider=provider,
        tools=[
            ReadFile(workspace),
            EditFile(workspace),
            Shell(workspace),
        ],
        session=session,
        system=DEFAULT_SYSTEM,
        max_steps=max_steps,
    )
    return apply_patterns(
        loop,
        loop,
        provider=provider,
        skills_dir=skills_dir,
        skill_name=skill_name,
        memory_path=memory_path,
        compact=compact,
        plan=plan,
        reflect=reflect,
        subagents=subagents,
        max_chars=DEFAULT_MAX_CHARS,
        keep_last=DEFAULT_KEEP_LAST,
        child_max_steps=DEFAULT_CHILD_MAX_STEPS,
    )


def merged_env(
    env: Mapping[str, str], *, model: str | None, base_url: str | None
) -> dict:
    """命令行里的模型和基址覆盖环境变量。密钥不从这里进入。"""
    merged = dict(env)
    if model is not None:
        merged["VECTOR_MODEL"] = model
    if base_url is not None:
        merged["VECTOR_BASE_URL"] = base_url
    return merged


def load_provider(
    *,
    environ: Mapping[str, str] | None = None,
    config_file: Path | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> object:
    """合并环境、读配置文件、建提供方。缺配置时抛出 ``ProviderError``。"""
    env = merged_env(
        os.environ if environ is None else environ,
        model=model,
        base_url=base_url,
    )
    env = apply_config(
        env, default_config_path() if config_file is None else config_file
    )
    return OpenAICompatibleProvider.from_env(env)


def memory_path(
    enabled: bool, explicit: str | None, workspace: Path
) -> Path | None:
    """决定记忆文件。``--memory`` 只是开关，自定义路径用 ``--memory-path``。"""
    if explicit:
        return Path(explicit)
    if enabled:
        return workspace / ".vector" / "MEMORY.md"
    return None
