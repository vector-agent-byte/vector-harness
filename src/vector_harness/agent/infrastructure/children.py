from __future__ import annotations

import json
from pathlib import Path

from vector_harness.types import ProviderEvent


class ChildTrace:
    def __init__(self, session_path: Path) -> None:
        self.path = session_path.with_suffix(".children.jsonl")
        self.active_calls: set[str] = set()
        self.statuses: dict[str, str] = {}

    def record(self, event: ProviderEvent) -> None:
        if event.origin != "child":
            if event.name == "delegate" and event.kind == "tool_call_end":
                self._status(event.tool_call_id, "queued")
            elif event.name == "delegate" and event.kind == "tool_execution_start":
                self.active_calls.add(event.tool_call_id)
                self._status(event.tool_call_id, "running")
            elif event.kind == "tool_result" and event.tool_call_id in self.statuses:
                self.active_calls.discard(event.tool_call_id)
                if self.statuses[event.tool_call_id] in {"queued", "running"}:
                    self._status(event.tool_call_id, "error" if event.name == "error" else "complete")
            return
        call_id = event.parent_tool_call_id
        if not call_id and len(self.active_calls) == 1:
            call_id = next(iter(self.active_calls))
        if not call_id:
            return
        if event.kind == "run_end":
            if event.status in {"complete", "error", "max_steps"}:
                self._status(call_id, event.status)
            return
        if event.kind not in {"thinking_delta", "text_delta", "tool_call_end"}:
            return
        self._write({
            "call_id": call_id,
            "kind": event.kind,
            "text": event.text,
            "name": event.name,
            "arguments": event.arguments,
        })

    def finish(self, status: str) -> None:
        for call_id, current in list(self.statuses.items()):
            if current in {"queued", "running"}:
                self._status(call_id, "error" if status == "error" else "stopped")
        self.active_calls.clear()

    def _status(self, call_id: str, status: str) -> None:
        if not call_id:
            return
        self.statuses[call_id] = status
        self._write({"call_id": call_id, "kind": "status", "status": status})

    def _write(self, row: dict) -> None:
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
            if not isinstance(kind, str) or kind not in {"thinking_delta", "text_delta", "tool_call_end", "status"}:
                continue
            section = children.setdefault(row["call_id"], {"thinking": "", "text": "", "tools": []})
            if kind == "status":
                if isinstance(row.get("status"), str) and row["status"] in {"queued", "running", "complete", "error", "max_steps", "stopped"}:
                    section["status"] = row["status"]
            elif kind == "tool_call_end":
                if isinstance(row.get("name"), str):
                    section["tools"].append({
                        "name": row["name"],
                        "args": row.get("arguments") if isinstance(row.get("arguments"), dict) else None,
                    })
            elif isinstance(row.get("text"), str):
                section["thinking" if kind == "thinking_delta" else "text"] += row["text"]
    return children
