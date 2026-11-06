from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from vector_harness.core.loop import Loop
from vector_harness.core.provider import OpenAICompatibleProvider
from vector_harness.core.session import Session
from vector_harness.patterns.compact import Compaction
from vector_harness.patterns.memory import Memory
from vector_harness.patterns.plan import PlanThenExecute
from vector_harness.patterns.skills import Skills
from vector_harness.patterns.subagent import delegate_tool
from vector_harness.tools.edit import EditFile
from vector_harness.tools.read import ReadFile
from vector_harness.tools.shell import Shell
from vector_harness.types import ProviderError, ProviderEvent

DEFAULT_SYSTEM = "You are a capable agent. Use tools to finish the task in the workspace."
_DEFAULT_MEMORY = "__vector_harness_default_memory__"


def build_agent(
    *,
    provider,
    workspace: Path,
    session: Session,
    skills_dir: Path | None = None,
    memory_path: Path | None = None,
    compact: bool = False,
    plan: bool = False,
    subagents: bool = False,
    max_steps: int = 25,
) -> Loop | PlanThenExecute:
    tools: list = [
        ReadFile(workspace),
        EditFile(workspace),
        Shell(workspace),
    ]
    pieces = [DEFAULT_SYSTEM]
    if skills_dir is not None:
        skills = Skills(skills_dir)
        tools.append(skills.read_tool())
        pieces.append(skills.index_prompt())
    if memory_path is not None:
        memory = Memory(memory_path)
        tools.append(memory.remember_tool())
        pieces.append(memory.prompt())
    system = "\n".join(pieces)
    transforms: list = []
    if compact:
        transforms.append(Compaction(provider, max_chars=80000, keep_last=8))
    if subagents:
        tools.append(
            delegate_tool(
                provider=provider,
                tools=list(tools),
                system=system,
                context_transforms=transforms,
            )
        )
    loop = Loop(
        provider=provider,
        tools=tools,
        session=session,
        system=system,
        context_transforms=transforms,
        max_steps=max_steps,
    )
    if plan:
        return PlanThenExecute(loop)
    return loop


def merged_env(
    env: Mapping[str, str], *, model: str | None, base_url: str | None
) -> dict:
    merged = dict(env)
    if model is not None:
        merged["VECTOR_MODEL"] = model
    if base_url is not None:
        merged["VECTOR_BASE_URL"] = base_url
    return merged


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vector-harness",
        description=(
            "Run an agent in a workspace. "
            "With --compact, fold the context after 80000 characters "
            "and keep the last 8 messages."
        ),
    )
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--session", default=None)
    parser.add_argument("--memory", nargs="?", const=_DEFAULT_MEMORY, default=None)
    parser.add_argument("--skills", default=None)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--subagents", action="store_true")
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("task", nargs="*")
    return parser


def _memory_path(value: str | None, workspace: Path) -> Path | None:
    if value is None:
        return None
    if value == _DEFAULT_MEMORY:
        return workspace / ".vector" / "MEMORY.md"
    return Path(value)


def _on_event(event: ProviderEvent) -> None:
    if event.kind == "text_delta":
        sys.stdout.write(event.text)
        sys.stdout.flush()
    elif event.kind == "tool_call_end" and event.name == "shell":
        arguments = event.arguments or {}
        command = arguments.get("command", "") if isinstance(arguments, dict) else ""
        sys.stdout.write(f"command: {command}\n")
        sys.stdout.flush()


def _task_texts(task: list[str], stdin_lines: list[str] | None) -> list[str]:
    joined = " ".join(task).strip()
    if joined:
        return [joined]
    texts: list[str] = []
    source = stdin_lines if stdin_lines is not None else sys.stdin
    for line in source:
        text = line.strip()
        if not text:
            continue
        if text == "/exit":
            break
        texts.append(text)
    return texts


async def _run_texts(agent, texts: list[str]):
    result = None
    for text in texts:
        result = await agent.run(text)
        if result.status != "complete":
            return result
    return result


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    provider=None,
    stdin_lines: list[str] | None = None,
) -> int:
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
        memory_path=_memory_path(args.memory, workspace),
        compact=args.compact,
        plan=args.plan,
        subagents=args.subagents,
        max_steps=args.max_steps,
    )
    loop = agent.loop if isinstance(agent, PlanThenExecute) else agent
    loop.on_event = _on_event
    texts = _task_texts(args.task, stdin_lines)
    if not texts:
        return 0
    result = asyncio.run(_run_texts(agent, texts))
    if result.status == "complete":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
