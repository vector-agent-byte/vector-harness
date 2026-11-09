"""在工作目录里替换唯一的一段文本。

``old_string`` 必须正好出现一次，避免改错位置。文件不存在且 ``old_string``
为空时创建文件。读写使用 ``newline=""``，保留文件原有的换行，
避免在 Windows 上把 LF 整文件写成 CRLF。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vector_harness.tools.read import _resolve_in_workspace

_PATH_ERROR = "Error: path is outside the workspace"
_ONCE_ERROR = "Error: old_string must appear exactly once"
_EMPTY_EXISTS_ERROR = "Error: old_string must be non-empty when the file exists"


def _read_text(path: Path) -> str:
    """按原样读取换行。``Path.read_text(newline=)`` 要到 Python 3.13 才有。"""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text(path: Path, text: str) -> None:
    """按文本里已有的换行写回，不让文本模式再翻译一遍。"""
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


@dataclass
class EditFile:
    """用唯一字符串替换编辑一个文件。路径规则和读文件相同。"""

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
        """替换唯一的一段文本。成功时返回空字符串，失败时返回 ``Error:`` 开头的说明。"""
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
            # 空的 old_string 表示创建。文件已存在时不允许用空串替换。
            if old_string == "":
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_text(target, new_string)
                return ""
            return _ONCE_ERROR
        if old_string == "":
            return _EMPTY_EXISTS_ERROR
        content = _read_text(target)
        count = content.count(old_string)
        # 出现 0 次或多次都不改文件，避免改错位置。
        if count != 1:
            return _ONCE_ERROR
        _write_text(target, content.replace(old_string, new_string, 1))
        return ""
