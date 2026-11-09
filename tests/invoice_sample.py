"""完整样例：配置、多工具、两轮对话、历史和落盘文件。

在仓库根目录运行：

    python tests/invoice_sample.py

这个文件不会被 pytest 收集。它会调用配置里的模型，并改写 demo/invoice-sample。
"""

from __future__ import annotations

from pathlib import Path

from vector_harness import (
    Calculator,
    EditFile,
    OpenAICompatibleProvider,
    ReadFile,
    Shell,
    VectorHarness,
)
from vector_harness.types import ProviderEvent

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "demo" / "invoice-sample"
SYSTEM = """你是账单助手。工作目录里只能读写相对路径。
算术必须调用 calculator，不要心算。
写文件用 edit_file：文件不存在时 old_string 用空字符串。
改已有文件前先用 read_file 读出原文，再替换唯一的一段。
需要看目录或核对文件时用 shell。
回答用中文，并给出最终应付金额。"""


def on_event(event: ProviderEvent) -> None:
    """边生成边打印，并在工具真正执行前打出调用。"""
    if event.kind == "text_delta" and event.text:
        print(event.text, end="", flush=True)
    elif event.kind == "tool_call_end":
        print(f"\n[tool] {event.name} {event.arguments}", flush=True)


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
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    invoice = WORKSPACE / "invoice.txt"
    if invoice.exists():
        invoice.unlink()

    agent = VectorHarness(
        name="账单助手",
        llm=OpenAICompatibleProvider(),
        system_prompt=SYSTEM,
        max_steps=12,
    )
    agent.loop.on_event = on_event
    for tool in (
        Calculator(),
        ReadFile(WORKSPACE),
        EditFile(WORKSPACE),
        Shell(WORKSPACE),
    ):
        agent.add_tool(tool)

    print(f"工作目录: {WORKSPACE}\n")
    print("=== 第一轮：开单 ===")
    agent.run(
        "给客户「北窗书店」开一张账单，写入 invoice.txt。"
        "《向量检索》单价 128 元、数量 7；"
        "《上下文工程》单价 86 元、数量 3。"
        "两本书分别用 calculator 算小计，再算合计。"
        "文件包含客户名、两行明细、合计。不要写税额。"
    )

    print("\n\n=== 第二轮：加税并核对 ===")
    agent.run(
        "在同一份 invoice.txt 上追加税额和应付。"
        "税额是合计的 6%，用 calculator 计算。"
        "先读文件再改，改完用 shell 确认文件还在，并告诉我应付金额。"
    )

    print("\n\n=== invoice.txt ===")
    print(invoice.read_text(encoding="utf-8") if invoice.is_file() else "(文件没有生成)")
    show_history(agent)
    print(f"\n历史消息数: {len(agent.get_history())}")


if __name__ == "__main__":
    main()
