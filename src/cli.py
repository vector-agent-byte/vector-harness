from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from uuid import uuid4

from vector_harness.assembly import (
    DEFAULT_CHILD_MAX_STEPS,
    DEFAULT_KEEP_LAST,
    DEFAULT_MAX_CHARS,
    apply_patterns,
)
from vector_harness.core.loop import Loop
from vector_harness.core.provider import (
    OpenAICompatibleProvider,
    apply_config,
    default_config_path,
)
from vector_harness.core.session import Session
from vector_harness.tools.edit import EditFile
from vector_harness.tools.read import ReadFile
from vector_harness.tools.shell import Shell
from vector_harness.types import ProviderError, ProviderEvent

DEFAULT_SYSTEM = "You are a capable agent. Use tools to finish the task in the workspace."


def build_agent(
    *,
    provider,
    workspace: Path,
    session: Session,
    skills_dir: Path | None = None,
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
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("task", nargs="*")
    return parser


def _memory_path(
    enabled: bool, explicit: str | None, workspace: Path
) -> Path | None:
    """决定记忆文件。``--memory`` 只是开关，后面的文字仍是任务。自定义路径用 ``--memory-path``。"""
    if explicit:
        return Path(explicit)
    if enabled:
        return workspace / ".vector" / "MEMORY.md"
    return None


_RESET = "\033[0m"
_CYAN = "\033[36m"
_SHELL = "\033[1;36m"
_COMMAND = "\033[33m"


def _color_enabled(stream) -> bool:
    """``NO_COLOR`` 或 ``VECTOR_COLOR=never`` 关闭颜色。``always`` 强制打开，否则只在终端里上色。"""
    if os.environ.get("NO_COLOR"):
        return False
    mode = os.environ.get("VECTOR_COLOR", "auto").strip().lower()
    if mode in {"always", "1", "true", "yes"}:
        return True
    if mode in {"never", "0", "false", "no"}:
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except OSError:
        return False


def _enable_windows_vt(stream) -> None:
    """让 Windows 控制台解释 ANSI 颜色。管道和旧控制台保持原样。"""
    if sys.platform != "win32":
        return
    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        return
    try:
        fileno()
    except (AttributeError, OSError, ValueError):
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except (AttributeError, OSError):
        return


def _paint(text: str, code: str, *, color: bool) -> str:
    """给一段文字套上颜色。不上色时原文返回。"""
    if not color or not text:
        return text
    return f"{code}{text}{_RESET}"


def _shell_block(command: str, *, color: bool) -> str:
    """把一条命令排成带标签的两行。多行命令每一行都缩进。"""
    label = _paint("  shell", _SHELL, color=color)
    lines = command.splitlines() or [""]
    body = "\n".join(_paint(f"    {line}", _COMMAND, color=color) for line in lines)
    return f"{label}\n{body}\n"


class _Printer:
    """把模型文本和 shell 命令写到标准输出。"""

    def __init__(self, stream) -> None:
        self.stream = stream
        self.color = _color_enabled(stream)
        if self.color:
            _enable_windows_vt(stream)
        self.line_open = False

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def on_event(self, event: ProviderEvent) -> None:
        """边收边打印模型文本。shell 在执行前单独成块。"""
        if event.kind == "text_delta" and event.text:
            self._write(_paint(event.text, _CYAN, color=self.color))
            self.line_open = not event.text.endswith("\n")
        elif event.kind == "tool_call_end" and event.name == "shell":
            arguments = event.arguments or {}
            command = arguments.get("command", "") if isinstance(arguments, dict) else ""
            if not isinstance(command, str):
                command = str(command)
            # 模型文本常常不以换行结束，命令块单独起一行。
            if self.line_open:
                self._write("\n")
            self._write(_shell_block(command, color=self.color))
            self.line_open = False

    def close_line(self) -> None:
        """一轮结束时补上缺少的换行，避免提示符粘在回复后面。"""
        if self.line_open:
            self._write("\n")
            self.line_open = False


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
    env = merged_env(
        os.environ if environ is None else environ,
        model=args.model,
        base_url=args.base_url,
    )
    try:
        env = apply_config(
            env, default_config_path() if config_file is None else config_file
        )
    except ProviderError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if provider is None:
        try:
            provider = OpenAICompatibleProvider.from_env(env)
        except ProviderError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.session:
        session_path: Path | None = Path(args.session)
    else:
        session_path = workspace / ".vector" / "sessions" / f"{uuid4().hex}.jsonl"
    agent = build_agent(
        provider=provider,
        workspace=workspace,
        session=Session(session_path),
        skills_dir=skills_dir,
        memory_path=_memory_path(args.memory, args.memory_path, workspace),
        compact=args.compact,
        plan=args.plan,
        reflect=args.reflect,
        subagents=args.subagents,
        max_steps=args.max_steps,
    )
    loop = agent
    while not isinstance(loop, Loop):
        loop = loop.loop
    printer = _Printer(sys.stdout)
    loop.on_event = printer.on_event
    result = asyncio.run(
        _run_source(agent, _task_source(args.task, stdin_lines), printer)
    )
    if result is None or result.status == "complete":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
