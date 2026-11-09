"""在工作目录里执行一条命令。

这一版没有沙箱，也没有执行前确认。命令拥有当前进程的权限。
工具自己不打印。终端要展示命令时，听循环在执行前发出的 ``tool_call_end``。
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Shell:
    """跑一条 shell 命令。工作目录固定为 ``root``，超时默认 120 秒。"""

    root: Path
    timeout: int = 120
    max_output: int = 8000
    name: str = "shell"
    description: str = "Run a shell command inside the workspace."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
            },
            "required": ["command"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        """执行命令并返回退出码和输出。超时后结束进程，输出过长时截断。"""
        command = arguments.get("command", "")
        if not isinstance(command, str):
            command = str(command)
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # 控制台编码解不开的字节换成替换符，避免读线程抛 UnicodeDecodeError。
            errors="replace",
        )
        try:
            out, err = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            # Windows 上 kill 不到整棵子进程树，用 taskkill /T 把子进程一起结束。
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            proc.communicate()
            return f"Error: command timed out after {self.timeout}s"
        formatted = f"exit_code={proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
        if len(formatted) > self.max_output:
            return formatted[: self.max_output] + "\n...[truncated]"
        return formatted
