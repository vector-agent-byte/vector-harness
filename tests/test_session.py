from pathlib import Path

import pytest

from vector_harness import Message, Session, ToolCall


def test_load_missing_file_returns_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "session.jsonl"
    session = Session(path)
    assert session.load() == []


def test_append_and_load_round_trip_with_tool_calls_and_error(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    session = Session(path)

    assistant = Message(
        role="assistant",
        content="calling tool",
        tool_calls=[
            ToolCall(id="call_1", name="search", arguments={"q": "test"}),
        ],
    )
    tool_msg = Message(
        role="tool",
        content="error detail",
        tool_call_id="call_1",
        is_error=True,
    )
    session.append(assistant)
    session.append(tool_msg)

    loaded = session.load()
    assert len(loaded) == 2
    assert loaded[0].role == assistant.role
    assert loaded[0].content == assistant.content
    assert loaded[0].tool_calls is not None
    assert len(loaded[0].tool_calls) == 1
    assert loaded[0].tool_calls[0].id == "call_1"
    assert loaded[0].tool_calls[0].name == "search"
    assert loaded[0].tool_calls[0].arguments == {"q": "test"}
    assert loaded[1].role == tool_msg.role
    assert loaded[1].content == tool_msg.content
    assert loaded[1].tool_call_id == "call_1"
    assert loaded[1].is_error is True

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_replace_all_rewrites_file(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    session = Session(path)

    for i in range(3):
        session.append(Message(role="user", content=f"msg {i}"))

    replacement = [Message(role="user", content="only one")]
    session.replace_all(replacement)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert session.load() == replacement


def test_in_memory_session_has_no_path_and_no_file(tmp_path: Path) -> None:
    session = Session.in_memory()
    assert session.path is None

    session.append(Message(role="user", content="hello"))
    loaded = session.load()
    assert len(loaded) == 1
    assert loaded[0].content == "hello"

    assert list(tmp_path.iterdir()) == []
