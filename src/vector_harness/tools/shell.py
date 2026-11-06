from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Shell:
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
        )
        try:
            out, err = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
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
