"""终端上的观察输出。

时刻、思考和工具调用的排版在这里。``cli`` 只负责参数、装配和退出码。
测试把 ``_now`` 换成固定时间，就能断言工具行上的时刻。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from vector_harness.types import INVALID_TOOL_ARGUMENTS, EventKind, ProviderEvent

_RESET = "\033[0m"
_DIM = "\033[2m"
_TAG = "\033[1;35m"
_NAME = "\033[1;36m"
_DETAIL = "\033[33m"
_THINK_TAG = "\033[35m"
_THINK_TEXT = "\033[2m"
_NAME_WIDTH = 12
# 时刻、空格、[tool]、空格、工具名、空格。续行从参数列开始。
_GUTTER = 8 + 1 + len("[tool]") + 1 + _NAME_WIDTH + 1


def _now() -> datetime:
    """工具行上的时刻。测试可以换成固定时间。"""
    return datetime.now()


def _color_enabled(stream) -> bool:
    """``NO_COLOR`` 或 ``VECTOR_COLOR=never`` 关闭颜色。``always`` 强制打开，否则只在终端里上色。"""
    if os.environ.get("NO_COLOR"):
        return False
    mode = os.environ.get("VECTOR_COLOR", "auto").strip().lower()
    if mode in {"always", "1", "true", "yes"}:
        return True
    if mode in {"never", "0", "false", "no"}:
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except OSError:
        return False


def _enable_windows_vt(stream) -> None:
    """让 Windows 控制台解释 ANSI 颜色。管道和旧控制台保持原样。"""
    if sys.platform != "win32":
        return
    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        return
    try:
        fileno()
    except (AttributeError, OSError, ValueError):
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except (AttributeError, OSError):
        return


def _paint(text: str, code: str, *, color: bool) -> str:
    """给一段文字套上颜色。不上色时原文返回。"""
    if not color or not text:
        return text
    return f"{code}{text}{_RESET}"


def _tool_detail(name: str, arguments) -> str:
    """取出一行里放得下的参数。shell 用整条命令，其它工具优先用路径或任务。"""
    if not isinstance(arguments, dict) or INVALID_TOOL_ARGUMENTS in arguments:
        return "invalid arguments"
    if name == "shell":
        command = arguments.get("command", "")
        return command if isinstance(command, str) else str(command)
    for key in ("path", "task", "name", "expression", "text", "command"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return value
    parts: list[str] = []
    for key, value in arguments.items():
        text = str(value)
        if len(text) > 80:
            text = text[:77] + "..."
        parts.append(f"{key}={text}")
    return " ".join(parts)


def _child_mark(*, color: bool) -> str:
    """子代理标记。只加在子循环的事件上。"""
    return _paint("[child]", _NAME, color=color) + " "


def _think_head(*, color: bool, origin: str = "") -> str:
    """思考段的行首：时刻和 [think]。子代理在中间多一个 [child]。"""
    stamp = _now().strftime("%H:%M:%S")
    mark = _child_mark(color=color) if origin == "child" else ""
    return (
        f"{_paint(stamp, _DIM, color=color)} "
        f"{mark}"
        f"{_paint('[think]', _THINK_TAG, color=color)} "
    )


def _tool_line(name: str, detail: str, *, color: bool, origin: str = "") -> str:
    """一行一个工具调用：时刻、[tool]、对齐后的名字、参数。子代理带 [child]。"""
    stamp = _now().strftime("%H:%M:%S")
    padded = name.ljust(_NAME_WIDTH)
    mark = _child_mark(color=color) if origin == "child" else ""
    head = (
        f"{_paint(stamp, _DIM, color=color)} "
        f"{mark}"
        f"{_paint('[tool]', _TAG, color=color)} "
        f"{_paint(padded, _NAME, color=color)} "
    )
    lines = detail.splitlines() or [""]
    rows = [head + _paint(lines[0], _DETAIL, color=color)]
    gutter = " " * (_GUTTER + (len("[child] ") if origin == "child" else 0))
    for extra in lines[1:]:
        rows.append(gutter + _paint(extra, _DETAIL, color=color))
    return "\n".join(rows) + "\n"


class _Printer:
    """把模型文本和工具调用写到标准输出。"""

    def __init__(self, stream) -> None:
        self.stream = stream
        self.color = _color_enabled(stream)
        if self.color:
            _enable_windows_vt(stream)
        self.line_open = False
        self.after_tool = False
        self.thinking = False
        self.child_reply = False

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _end_thinking(self) -> None:
        """思考结束时补上换行，避免回复粘在思考正文后面。"""
        if not self.thinking:
            return
        if self.line_open:
            self._write("\n")
            self.line_open = False
        self.thinking = False

    def on_event(self, event: ProviderEvent) -> None:
        """边收边打印模型文本。思考和工具调用各自占一行开头。"""
        if event.kind == EventKind.THINKING_DELTA and event.text:
            if self.after_tool:
                self._write("\n")
                self.after_tool = False
            if not self.thinking:
                if self.line_open:
                    self._write("\n")
                self.child_reply = False
                self._write(_think_head(color=self.color, origin=event.origin))
                self.thinking = True
            self._write(_paint(event.text, _THINK_TEXT, color=self.color))
            self.line_open = not event.text.endswith("\n")
        elif event.kind == EventKind.TEXT_DELTA and event.text:
            self._end_thinking()
            if event.origin != "child" and self.child_reply:
                if self.line_open:
                    self._write("\n")
                    self.line_open = False
                self.child_reply = False
            if self.after_tool:
                self._write("\n")
                self.after_tool = False
                self.line_open = False
            if event.origin == "child" and not self.child_reply:
                self._write(_child_mark(color=self.color))
                self.child_reply = True
            self._write(event.text)
            self.line_open = not event.text.endswith("\n")
        elif event.kind == EventKind.TOOL_CALL_END and event.name:
            self._end_thinking()
            self.child_reply = False
            if self.line_open:
                self._write("\n")
            self._write(
                _tool_line(
                    event.name,
                    _tool_detail(event.name, event.arguments),
                    color=self.color,
                    origin=event.origin,
                )
            )
            self.line_open = False
            self.after_tool = True

    def close_line(self) -> None:
        """一轮结束时补上缺少的换行，避免提示符粘在回复后面。"""
        if self.line_open:
            self._write("\n")
            self.line_open = False
