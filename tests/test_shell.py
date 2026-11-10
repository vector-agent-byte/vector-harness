from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from vector_harness import Shell


def run(coro):
    return asyncio.run(coro)


def test_shell_default_timeout(tmp_path: Path):
    tool = Shell(tmp_path)
    assert tool.timeout == 120
    assert tool.name == "shell"


def test_shell_runs_in_workspace_root(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    tool = Shell(root)
    result = run(
        tool.execute(
            {"command": 'python -c "import pathlib; print(pathlib.Path.cwd())"'}
        )
    )
    assert "exit_code=0" in result
    assert str(root.resolve()) in result


def test_shell_stop_ends_a_long_command(tmp_path: Path):
    tool = Shell(tmp_path)
    tool.cancel = threading.Event()

    def trip() -> None:
        time.sleep(0.3)
        tool.cancel.set()

    threading.Thread(target=trip, daemon=True).start()
    started = time.monotonic()
    result = run(tool.execute({"command": 'python -c "import time; time.sleep(30)"'}))
    assert time.monotonic() - started < 5
    assert result == "Error: stopped"


def test_shell_times_out_within_five_seconds(tmp_path: Path):
    tool = Shell(tmp_path, timeout=1)
    started = time.monotonic()
    result = run(
        tool.execute({"command": 'python -c "import time; time.sleep(30)"'})
    )
    elapsed = time.monotonic() - started
    assert elapsed < 5
    assert result == "Error: command timed out after 1s"


def test_shell_replaces_bytes_the_console_encoding_rejects(tmp_path: Path):
    tool = Shell(tmp_path)
    result = run(
        tool.execute(
            {
                "command": (
                    "python -c \"import sys; "
                    "sys.stdout.buffer.write(bytes([255, 128, 129]))\""
                )
            }
        )
    )
    assert "exit_code=0" in result
    assert "\ufffd" in result
    assert "UnicodeDecodeError" not in result


def test_shell_truncates_output_over_max(tmp_path: Path):
    tool = Shell(tmp_path, max_output=100)
    result = run(tool.execute({"command": 'python -c "print(\'x\' * 9000)"'}))
    marker = "\n...[truncated]"
    assert marker in result
    prefix = result.split(marker, 1)[0]
    assert len(prefix) <= 100
