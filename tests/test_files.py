from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from vector_harness import EditFile, ReadFile

PATH_OUTSIDE_ERROR = "Error: path is outside the workspace"
OUTSIDE_SECRET = "OUTSIDE_SECRET"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def workspace(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside.txt").write_text("inside\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(OUTSIDE_SECRET.encode("utf-8"))
    return root, outside


def test_read_outside_path_refused(workspace):
    root, outside = workspace
    tool = ReadFile(root)
    before = outside.read_bytes()
    result = run(tool.execute({"path": "../outside.txt"}))
    assert result == PATH_OUTSIDE_ERROR
    assert OUTSIDE_SECRET not in result
    assert outside.read_bytes() == before


def test_symlink_outside_refused(workspace):
    root, outside = workspace
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"cannot create symlink: {exc}")
    read_tool = ReadFile(root)
    edit_tool = EditFile(root)
    before = outside.read_bytes()
    read_result = run(read_tool.execute({"path": "link.txt"}))
    assert read_result == PATH_OUTSIDE_ERROR
    edit_result = run(
        edit_tool.execute(
            {"path": "link.txt", "old_string": OUTSIDE_SECRET, "new_string": "x"}
        )
    )
    assert edit_result == PATH_OUTSIDE_ERROR
    assert outside.read_bytes() == before


def test_read_truncates_after_200_lines(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    lines = [f"line{i}" for i in range(1, 202)]
    (root / "many.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    tool = ReadFile(root)
    result = run(tool.execute({"path": "many.txt"}))
    assert result.startswith("1|line1\n")
    assert "201|line201" not in result
    assert result.endswith("\n...[truncated, more lines remain]")


def test_read_offset_zero_returns_error_and_leaves_bytes(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "two.txt"
    path.write_bytes(b"one\ntwo\n")
    before = path.read_bytes()
    tool = ReadFile(root)
    result = run(tool.execute({"path": "two.txt", "offset": 0}))
    assert result == "Error: offset out of range"
    assert path.read_bytes() == before


def test_read_offset_out_of_range(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "one.txt").write_text("only\n", encoding="utf-8")
    tool = ReadFile(root)
    result = run(tool.execute({"path": "one.txt", "offset": 5}))
    assert result == "Error: offset out of range"


def test_edit_old_string_zero_or_two_times_unchanged(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "target.txt"
    path.write_text("aaa\n", encoding="utf-8")
    tool = EditFile(root)
    before = path.read_bytes()
    r0 = run(
        tool.execute({"path": "target.txt", "old_string": "missing", "new_string": "x"})
    )
    assert r0 == "Error: old_string must appear exactly once"
    assert path.read_bytes() == before
    path.write_text("aa\naa\n", encoding="utf-8")
    before = path.read_bytes()
    r2 = run(
        tool.execute({"path": "target.txt", "old_string": "aa", "new_string": "x"})
    )
    assert r2 == "Error: old_string must appear exactly once"
    assert path.read_bytes() == before


def test_edit_existing_file_empty_old_string_refused(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "exists.txt"
    path.write_text("keep\n", encoding="utf-8")
    tool = EditFile(root)
    before = path.read_bytes()
    result = run(
        tool.execute({"path": "exists.txt", "old_string": "", "new_string": "new"})
    )
    assert result == "Error: old_string must be non-empty when the file exists"
    assert path.read_bytes() == before


def test_edit_create_file_when_missing_and_empty_old_string(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    tool = EditFile(root)
    result = run(
        tool.execute(
            {
                "path": "nested/new.txt",
                "old_string": "",
                "new_string": "created content",
            }
        )
    )
    assert not str(result).startswith("Error:")
    assert (root / "nested" / "new.txt").read_text(encoding="utf-8") == "created content"


def test_edit_preserves_lf_bytes_outside_replacement(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "lf.txt"
    path.write_bytes(b"alpha\nbeta\n")
    tool = EditFile(root)
    result = run(
        tool.execute({"path": "lf.txt", "old_string": "alpha", "new_string": "ALPHA"})
    )
    assert result == ""
    raw = path.read_bytes()
    assert raw == b"ALPHA\nbeta\n"
    assert b"\r\n" not in raw


def test_edit_single_replacement(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "doc.txt"
    path.write_text("foo bar foo\n", encoding="utf-8")
    tool = EditFile(root)
    result = run(
        tool.execute({"path": "doc.txt", "old_string": "bar", "new_string": "baz"})
    )
    assert not str(result).startswith("Error:")
    assert path.read_text(encoding="utf-8") == "foo baz foo\n"
