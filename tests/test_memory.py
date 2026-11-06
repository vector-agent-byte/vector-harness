from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

from vector_harness.patterns.memory import Memory


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def unload_patterns_modules():
    yield
    to_remove = [
        k
        for k in list(sys.modules)
        if k == "vector_harness.patterns" or k.startswith("vector_harness.patterns.")
    ]
    for key in to_remove:
        del sys.modules[key]


def test_remember_appends_line_and_prompt_reads_back(tmp_path: Path) -> None:
    mem_path = tmp_path / "nested" / "memory.md"
    memory = Memory(mem_path)

    assert memory.prompt() == ""

    tool = memory.remember_tool()
    run(tool.execute({"text": "remember me"}))

    full = mem_path.read_text(encoding="utf-8")
    assert re.match(r"^- \d{4}-\d{2}-\d{2}: remember me\n$", full)
    assert "remember me" in memory.prompt()

