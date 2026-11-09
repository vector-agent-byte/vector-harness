from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from vector_harness.types import Tool


@dataclass
class RememberTool:
    path: Path
    name: str = "remember"
    description: str = "Append a line to long-term memory."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        """往记忆文件追加一行 ``- 日期: 文本``。成功时返回空字符串。"""
        text = arguments.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = f"- {date.today().isoformat()}: {text}\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
        return ""


@dataclass
class Memory:
    path: Path

    def prompt(self) -> str:
        """读出已有记忆，拼进系统提示。文件还不存在时返回空字符串。"""
        if not self.path.is_file():
            return ""
        return self.path.read_text(encoding="utf-8")

    def remember_tool(self) -> Tool:
        """返回追加记忆的工具，由调用方放进工具列表。"""
        return RememberTool(path=self.path)
