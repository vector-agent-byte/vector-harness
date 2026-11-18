from __future__ import annotations

import json
from pathlib import Path

from vector_harness.types import ProviderEvent


class ChildTrace:
    def __init__(self, session_path: Path) -> None:
        self.path = session_path.with_suffix(".children.jsonl")
        self.call_id: str | None = None

    def record(self, event: ProviderEvent) -> None:
        if event.origin != "child":
            if event.kind == "tool_execution_start":
                self.call_id = event.tool_call_id if event.name == "delegate" else None
            elif event.kind == "tool_result":
                self.call_id = None
            return
        if not self.call_id or event.kind not in {"thinking_delta", "text_delta", "tool_call_end"}:
            return
        row = {
            "call_id": self.call_id,
            "kind": event.kind,
            "text": event.text,
            "name": event.name,
            "arguments": event.arguments,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_children(session_path: Path) -> dict[str, dict]:
    path = session_path.with_suffix(".children.jsonl")
    if not path.is_file():
        return {}
    children: dict[str, dict] = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or not isinstance(row.get("call_id"), str):
                continue
            kind = row.get("kind")
            if not isinstance(kind, str) or kind not in {"thinking_delta", "text_delta", "tool_call_end"}:
                continue
            section = children.setdefault(row["call_id"], {"thinking": "", "text": "", "tools": []})
            if kind == "tool_call_end":
                if isinstance(row.get("name"), str):
                    section["tools"].append({
                        "name": row["name"],
                        "args": row.get("arguments") if isinstance(row.get("arguments"), dict) else None,
                    })
            elif isinstance(row.get("text"), str):
                section["thinking" if kind == "thinking_delta" else "text"] += row["text"]
    return children
