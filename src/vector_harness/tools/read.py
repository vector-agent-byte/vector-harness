"""读取工作目录里的文件。

路径先 ``resolve`` 再 ``relative_to``。解析后落在工作目录外的路径，包括
``..`` 和指向外部的符号链接，都拒绝。返回给模型的每一行带 1 开始的行号。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_PATH_ERROR = "Error: path is outside the workspace"
_OFFSET_ERROR = "Error: offset out of range"
_TRUNCATED_SUFFIX = "\n...[truncated, more lines remain]"


def _resolve_in_workspace(root: Path, rel_path: str) -> Path | None:
    """把相对路径定在工作目录内。出界时返回 None，调用方给出固定的错误文本。"""
    root_resolved = root.resolve()
    target = (root_resolved / rel_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        return None
    return target


@dataclass
class ReadFile:
    """按窗口读文件。``offset`` 从 1 开始，默认最多 200 行。"""

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
        """读取一个窗口。越界路径和小于 1 的 offset、limit 都返回固定错误文本。"""
        rel_path = arguments.get("path", "")
        if not isinstance(rel_path, str):
            rel_path = str(rel_path)
        target = _resolve_in_workspace(self.root, rel_path)
        if target is None:
            return _PATH_ERROR
        offset = int(arguments.get("offset", 1))
        limit = int(arguments.get("limit", 200))
        # 小于 1 的 offset 在切片里会变成负数，从末尾取行。这里直接拒绝。
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
        # 窗口后面还有行时告诉模型，避免它以为文件到此结束。
        if end < len(lines):
            body += _TRUNCATED_SUFFIX
        return body
