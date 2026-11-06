from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from vector_harness.patterns.skills import Skills


@pytest.fixture(scope="module", autouse=True)
def _unload_patterns_after_module():
    yield
    for name in list(sys.modules):
        if name == "vector_harness.patterns" or name.startswith(
            "vector_harness.patterns."
        ):
            del sys.modules[name]


def run(coro):
    return asyncio.run(coro)


def _write_skill_tree(root: Path) -> Path:
    alpha_dir = root / "alpha"
    alpha_dir.mkdir()
    (alpha_dir / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: first skill\n---\nALPHA_BODY\n",
        encoding="utf-8",
    )
    (root / "beta.md").write_text(
        "---\nname: beta\ndescription: second skill\n---\nBETA_BODY\n",
        encoding="utf-8",
    )
    return root


def test_index_lists_skills_sorted_by_name(tmp_path: Path) -> None:
    skills = Skills(_write_skill_tree(tmp_path))
    index = skills.index_prompt()
    assert index == "Skills:\n- alpha: first skill\n- beta: second skill"


def test_read_skill_returns_body_without_frontmatter(tmp_path: Path) -> None:
    tool = Skills(_write_skill_tree(tmp_path)).read_tool()
    result = run(tool.execute({"name": "alpha"}))
    assert "ALPHA_BODY" in result
    assert "first skill" not in result
    assert tool.name == "read_skill"


def test_unknown_skill_returns_error(tmp_path: Path) -> None:
    tool = Skills(_write_skill_tree(tmp_path)).read_tool()
    result = run(tool.execute({"name": "missing"}))
    assert result == "Error: Unknown skill: missing"


def test_missing_directory_index_is_empty(tmp_path: Path) -> None:
    skills = Skills(tmp_path / "does-not-exist")
    assert skills.index_prompt() == ""
