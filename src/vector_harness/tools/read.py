from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_PATH_ERROR = "Error: path is outside the workspace"
_OFFSET_ERROR = "Error: offset out of range"
_TRUNCATED_SUFFIX = "\n...[truncated, more lines remain]"


def _resolve_in_workspace(root: Path, rel_path: str) -> Path | None:
    root_resolved = root.resolve()
    target = (root_resolved / rel_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        return None
    return target


@dataclass
class ReadFile:
    root: Path
    name: str = "read_file"
    description: str = "Read a file inside the workspace."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        rel_path = arguments.get("path", "")
        if not isinstance(rel_path, str):
            rel_path = str(rel_path)
        target = _resolve_in_workspace(self.root, rel_path)
        if target is None:
            return _PATH_ERROR
        offset = int(arguments.get("offset", 1))
        limit = int(arguments.get("limit", 200))
        if offset < 1 or limit < 1:
            return _OFFSET_ERROR
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines()
        start = offset - 1
        if start >= len(lines):
            return _OFFSET_ERROR
        end = start + limit
        chunk = lines[start:end]
        numbered = [f"{offset + i}|{line}" for i, line in enumerate(chunk)]
        body = "\n".join(numbered)
        if end < len(lines):
            body += _TRUNCATED_SUFFIX
        return body
