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
        if not self.path.is_file():
            return ""
        return self.path.read_text(encoding="utf-8")

    def remember_tool(self) -> Tool:
        return RememberTool(path=self.path)
