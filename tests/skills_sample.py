"""完整样例：创建助手时加载技能目录，并打开计划和反思。

在仓库根目录运行：

    python tests/skills_sample.py

这个文件不会被 pytest 收集。它会调用配置里的模型，并改写 demo/skill-sample。
技能文件放在 demo/skills。索引写进系统提示，正文要等模型调用 read_skill。
构造之后会打印运行链和最终工具名。
"""

from __future__ import annotations

import sys
from pathlib import Path

from vector_harness import (
    EditFile,
    OpenAICompatibleProvider,
    ReadFile,
    VectorHarness,
)
from vector_harness.types import ProviderEvent

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "demo" / "skill-sample"
SKILLS_DIR = ROOT / "demo" / "skills"
SYSTEM = """你是工作目录里的助手。路径只能用相对路径。
系统提示里只有技能索引。做技能描述的事之前，必须先调用 read_skill，按名字读出正文。
写文件用 edit_file：文件不存在时 old_string 用空字符串。
改已有文件前先用 read_file 读出原文，再替换唯一的一段。
回答用中文。"""


class PrintHook:
    """用户自己的执行前钩子。这里只打印工具名，不改参数，也不拒绝。"""

    async def before_execute(self, call, messages):
        print(f"\n[hook] {call.name}", flush=True)
        return None


def on_event(event: ProviderEvent) -> None:
    """边生成边打印，并在工具真正执行前打出调用。"""
    if event.kind == "text_delta" and event.text:
        print(event.text, end="", flush=True)
    elif event.kind == "tool_call_end":
        print(f"\n[tool] {event.name} {event.arguments}", flush=True)


def runner_chain(runner: object) -> str:
    """从外到内列出运行对象的类型名，直到工具循环。"""
    names: list[str] = []
    current = runner
    while current is not None:
        names.append(type(current).__name__)
        inner = getattr(current, "inner", None)
        if inner is not None:
            current = inner
            continue
        loop = getattr(current, "loop", None)
        if loop is not None and loop is not current:
            current = loop
            continue
        break
    return " -> ".join(names)


def show_shape(agent: VectorHarness) -> None:
    """打印装配之后的运行链和工具名。"""
    names = ", ".join(tool.name for tool in agent.loop.tools)
    print(f"运行链: {runner_chain(agent.runner)}")
    print(f"工具: {names}")


def show_history(agent: VectorHarness) -> None:
    print("\n=== 历史 ===")
    for index, message in enumerate(agent.get_history(), start=1):
        detail = ""
        if message.tool_calls:
            calls = ", ".join(call.name for call in message.tool_calls)
            detail = f" -> {calls}"
        text = " ".join(message.content.split())
        if len(text) > 160:
            text = text[:157] + "..."
        print(f"{index:02d}. {message.role}{detail}: {text}")


def main() -> None:
    if not SKILLS_DIR.is_dir():
        print(f"技能目录不存在: {SKILLS_DIR}", file=sys.stderr)
        raise SystemExit(1)

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    hello = WORKSPACE / "hello.txt"
    if hello.exists():
        hello.unlink()

    agent = VectorHarness(
        name="技能助手",
        llm=OpenAICompatibleProvider(),
        system_prompt=SYSTEM,
        tools=[ReadFile(WORKSPACE), EditFile(WORKSPACE)],
        skills_dir=SKILLS_DIR,
        plan=True,
        reflect=True,
        tool_hooks=[PrintHook()],
        loop_on_event=on_event,
        max_model_turns=12,
    )
    if "- greet:" not in agent.system_prompt:
        print("demo/skills 里没有可用的 greet 技能", file=sys.stderr)
        raise SystemExit(1)

    print(f"工作目录: {WORKSPACE}")
    print(f"技能目录: {SKILLS_DIR}")
    show_shape(agent)
    print()
    print("=== 装配后的系统提示 ===")
    print(agent.system_prompt)
    print("\n=== 第一轮：按 greet 写文件 ===")
    agent.run("按技能 greet 完成它描述的事。先读技能正文，再写文件。")

    print("\n\n=== 第二轮：核对文件 ===")
    agent.run("用 read_file 读出 hello.txt，只回答文件里的那一行。")

    print("\n\n=== hello.txt ===")
    print(hello.read_text(encoding="utf-8") if hello.is_file() else "(文件没有生成)")
    show_history(agent)
    print(f"\n历史消息数: {len(agent.get_history())}")


if __name__ == "__main__":
    main()
