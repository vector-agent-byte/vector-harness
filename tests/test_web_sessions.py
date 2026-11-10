import os
from pathlib import Path

import pytest

from vector_harness.web_sessions import (
    create_session,
    is_session_id,
    list_sessions,
    read_messages,
)


def test_list_uses_first_user_message_and_newest_mtime_first(tmp_path: Path):
    older = tmp_path / ".vector" / "sessions" / ("a" * 32 + ".jsonl")
    newer = tmp_path / ".vector" / "sessions" / ("b" * 32 + ".jsonl")
    older.parent.mkdir(parents=True)
    older.write_text(
        '{"role":"user","content":"  旧标题  ","tool_calls":null,"tool_call_id":null,"is_error":false}\n',
        encoding="utf-8",
    )
    newer.write_text(
        '{"role":"assistant","content":"先出现的助手"}\n'
        '{"role":"user","content":"新标题"}\n'
        "不是 json\n",
        encoding="utf-8",
    )
    os.utime(older, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))
    listed = list_sessions(tmp_path)
    assert [item["id"] for item in listed] == ["b" * 32, "a" * 32]
    assert listed[0]["title"] == "新标题"
    assert listed[1]["title"] == "旧标题"
    assert listed[0]["updated_at"] == newer.stat().st_mtime


def test_blank_user_text_falls_back_to_the_id(tmp_path: Path):
    session_id = "c" * 32
    path = tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"role":"user","content":"   "}\n', encoding="utf-8")
    assert list_sessions(tmp_path)[0]["title"] == session_id


def test_blank_first_user_message_does_not_use_a_later_one(tmp_path: Path):
    session_id = "1" * 32
    path = tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"role":"user","content":"   "}\n'
        '{"role":"user","content":"后面的标题"}\n',
        encoding="utf-8",
    )
    assert list_sessions(tmp_path)[0]["title"] == session_id


def test_list_ignores_names_that_are_not_session_ids(tmp_path: Path):
    directory = tmp_path / ".vector" / "sessions"
    directory.mkdir(parents=True)
    (directory / "notes.jsonl").write_text(
        '{"role":"user","content":"忽略"}\n',
        encoding="utf-8",
    )
    assert list_sessions(tmp_path) == []


def test_missing_directory_lists_nothing(tmp_path: Path):
    assert list_sessions(tmp_path) == []


def test_create_session_writes_an_empty_file(tmp_path: Path):
    session_id = create_session(tmp_path)
    assert is_session_id(session_id)
    path = tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl"
    assert path.read_text(encoding="utf-8") == ""


def test_read_messages_rejects_ids_that_escape_the_directory(tmp_path: Path):
    with pytest.raises(ValueError):
        read_messages(tmp_path, "../secret")
    assert not (tmp_path / "secret").exists()


def test_same_mtime_orders_ids_ascending(tmp_path: Path):
    later_name = tmp_path / ".vector" / "sessions" / ("f" * 32 + ".jsonl")
    earlier_name = tmp_path / ".vector" / "sessions" / ("a" * 32 + ".jsonl")
    later_name.parent.mkdir(parents=True)
    later_name.write_text("", encoding="utf-8")
    earlier_name.write_text("", encoding="utf-8")
    os.utime(later_name, (3_000, 3_000))
    os.utime(earlier_name, (3_000, 3_000))
    listed = list_sessions(tmp_path)
    assert [item["id"] for item in listed] == ["a" * 32, "f" * 32]


def test_read_messages_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        read_messages(tmp_path, "e" * 32)


def test_read_messages_skips_blank_and_non_object_lines(tmp_path: Path):
    session_id = "d" * 32
    path = tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n"
        "不是 json\n"
        "[1, 2]\n"
        '{"role":"user","content":"你好"}\n',
        encoding="utf-8",
    )
    assert read_messages(tmp_path, session_id) == [
        {"role": "user", "content": "你好"},
    ]
