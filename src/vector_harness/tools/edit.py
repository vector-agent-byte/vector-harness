from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vector_harness.tools.read import _resolve_in_workspace

_PATH_ERROR = "Error: path is outside the workspace"
_ONCE_ERROR = "Error: old_string must appear exactly once"
_EMPTY_EXISTS_ERROR = "Error: old_string must be non-empty when the file exists"


@dataclass
class EditFile:
    root: Path
    name: str = "edit_file"
    description: str = "Edit a file inside the workspace by replacing a unique string."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        rel_path = arguments.get("path", "")
        if not isinstance(rel_path, str):
            rel_path = str(rel_path)
        target = _resolve_in_workspace(self.root, rel_path)
        if target is None:
            return _PATH_ERROR
        old_string = arguments.get("old_string", "")
        new_string = arguments.get("new_string", "")
        if not isinstance(old_string, str):
            old_string = str(old_string)
        if not isinstance(new_string, str):
            new_string = str(new_string)
        if not target.is_file():
            if old_string == "":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(new_string, encoding="utf-8")
                return ""
            return _ONCE_ERROR
        if old_string == "":
            return _EMPTY_EXISTS_ERROR
        content = target.read_text(encoding="utf-8")
        count = content.count(old_string)
        if count != 1:
            return _ONCE_ERROR
        target.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return ""
