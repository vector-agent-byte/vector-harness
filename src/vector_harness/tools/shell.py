"""在工作目录里执行一条命令。

这一版没有沙箱，也没有执行前确认。命令拥有当前进程的权限。
工具自己不打印。终端要展示命令时，听循环在执行前发出的 ``tool_call_end``。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Shell:
    """跑一条 shell 命令。工作目录固定为 ``root``，超时默认 120 秒。"""

    root: Path
    timeout: int = 120
    max_output: int = 8000
    cancel: threading.Event | None = None
    processes: list | None = None
    process_lock: threading.Lock | None = None
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

    def _track(self, proc: subprocess.Popen, present: bool) -> None:
        """让停止请求能看见正在跑的进程。没有登记表时什么也不做。"""
        if self.processes is None:
            return
        lock = self.process_lock
        if lock is not None:
            lock.acquire()
        try:
            if present:
                self.processes.append(proc)
            elif proc in self.processes:
                self.processes.remove(proc)
        finally:
            if lock is not None:
                lock.release()

    async def execute(self, arguments: dict) -> str:
        """执行命令并返回退出码和输出。超时或被停止时结束进程，输出过长时截断。"""
        if self.cancel is not None and self.cancel.is_set():
            return "Error: stopped"
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
        self._track(proc, True)
        started = time.monotonic()
        try:
            while True:
                if self.cancel is not None and self.cancel.is_set():
                    kill_process_tree(proc)
                    return "Error: stopped"
                remaining = self.timeout - (time.monotonic() - started)
                if remaining <= 0:
                    kill_process_tree(proc)
                    return f"Error: command timed out after {self.timeout}s"
                try:
                    # 短等一次，停止请求才能在超时之前结束命令。
                    out, err = proc.communicate(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            self._track(proc, False)
        formatted = f"exit_code={proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
        # 先读完再截断。返回给模型的文本有上限，读的过程本身不限内存。
        if len(formatted) > self.max_output:
            return formatted[: self.max_output] + "\n...[truncated]"
        return formatted


def signal_kill(proc: subprocess.Popen) -> None:
    """请进程退出，不等待它读完输出。停止请求在另一条线程上调用。"""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        proc.kill()


def kill_process_tree(proc: subprocess.Popen) -> None:
    """结束命令及其子进程，并读完剩余输出。"""
    signal_kill(proc)
    try:
        proc.communicate()
    except Exception:
        return
