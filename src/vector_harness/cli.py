from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from uuid import uuid4

from vector_harness.assembly import DEFAULT_KEEP_LAST, DEFAULT_MAX_CHARS
from vector_harness.bootstrap import (
    DEFAULT_SYSTEM,
    build_agent,
    load_provider,
    memory_path as _memory_path,
    merged_env,
)
from vector_harness.cli_render import _Printer
from vector_harness.core.session import Session
from vector_harness.types import ProviderError
from vector_harness.web_sessions import session_path

__all__ = [
    "DEFAULT_SYSTEM",
    "build_agent",
    "merged_env",
    "_memory_path",
    "main",
]


def _parser() -> argparse.ArgumentParser:
    """命令行定义。密钥没有对应参数，避免出现在进程列表里。"""
    parser = argparse.ArgumentParser(
        prog="vector-harness",
        description=(
            "Run an agent in a workspace. "
            f"With --compact, fold the context after {DEFAULT_MAX_CHARS} characters "
            f"and keep the last {DEFAULT_KEEP_LAST} messages. "
            "Connection settings can live in ~/.vector-harness/config.toml "
            "as api_key, base_url, and model."
        ),
    )
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--session", default=None)
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Append long-term memory at {workspace}/.vector/MEMORY.md.",
    )
    parser.add_argument(
        "--memory-path",
        default=None,
        help="Memory file to use instead of the workspace default.",
    )
    parser.add_argument("--skills", default=None)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--reflect", action="store_true")
    parser.add_argument("--subagents", action="store_true")
    parser.add_argument("--fetch", action="store_true", help="Enable web_fetch tool.")
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("task", nargs="*")
    return parser


def _task_source(task: list[str], stdin_lines: Iterable[str] | None):
    """有任务文本就只跑这一句。否则逐行读取，空行跳过，``/exit`` 结束且不送给模型。"""
    joined = " ".join(task).strip()
    if joined:
        yield joined
        return
    source = stdin_lines if stdin_lines is not None else sys.stdin
    for line in source:
        text = line.strip()
        if not text:
            continue
        if text == "/exit":
            return
        yield text


async def _run_source(agent, source, printer: _Printer):
    """每拿到一行就跑一轮并打印。某一轮不是 ``complete`` 时停下来，不再读后面的行。"""
    result = None
    for text in source:
        result = await agent.run(text)
        printer.close_line()
        if result.status != "complete":
            return result
    return result


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    provider=None,
    stdin_lines: Iterable[str] | None = None,
    config_file: Path | None = None,
) -> int:
    """终端入口。成功返回 0，缺配置、工作目录无效或这一轮没有完成时返回 1。"""
    args = _parser().parse_args(argv)
    workspace = Path(args.workspace)
    if not workspace.is_dir():
        print(args.workspace, file=sys.stderr)
        return 1
    skills_dir: Path | None = None
    if args.skills is not None:
        skills_dir = Path(args.skills)
        if not skills_dir.is_dir():
            print("skills directory not found", file=sys.stderr)
            return 1
    if provider is None:
        try:
            provider = load_provider(
                environ=environ,
                config_file=config_file,
                model=args.model,
                base_url=args.base_url,
            )
        except ProviderError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.session:
        path = Path(args.session)
    else:
        path = session_path(workspace, uuid4().hex)
    agent = build_agent(
        provider=provider,
        workspace=workspace,
        session=Session(path),
        skills_dir=skills_dir,
        memory_path=_memory_path(args.memory, args.memory_path, workspace),
        compact=args.compact,
        plan=args.plan,
        reflect=args.reflect,
        subagents=args.subagents,
        fetch=args.fetch,
        max_steps=args.max_steps,
    )
    printer = _Printer(sys.stdout)
    agent.loop.on_event = printer.on_event
    result = asyncio.run(
        _run_source(agent, _task_source(args.task, stdin_lines), printer)
    )
    if result is None or result.status == "complete":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
