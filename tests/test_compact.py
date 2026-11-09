from __future__ import annotations

import asyncio
import sys

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Message, Session, ToolCall
from vector_harness.patterns.compact import Compaction


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


class RaisingProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def stream(self, *, system: str, messages: list[Message], tools: list):
        self.calls.append(
            {
                "system": system,
                "messages": messages,
                "tools": list(tools),
            }
        )
        raise RuntimeError("summarizer down")
        yield  # pragma: no cover


def test_compaction_keeps_a_split_tool_group_together() -> None:
    messages = [
        Message(role="user", content="abcdefghij"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="c1", name="fn", arguments={"a": "1"}),
                ToolCall(id="c2", name="fn", arguments={"a": "2"}),
            ],
        ),
        Message(role="tool", content="one", tool_call_id="c1"),
        Message(role="tool", content="two", tool_call_id="c2"),
        Message(role="user", content="stay"),
    ]
    snapshot = [message.content for message in messages]
    provider = ScriptedProvider(turns=[ScriptedTurn(content="SUM")])
    compaction = Compaction(provider, max_chars=5, keep_last=2)

    result = run(compaction.apply(messages))

    assert [message.content for message in messages] == snapshot
    assert len(messages) == 5
    assert result[0].content == "[compacted context]\nSUM"
    assert [call.id for call in result[1].tool_calls or []] == ["c1", "c2"]
    assert [(message.role, message.tool_call_id) for message in result[1:]] == [
        ("assistant", None),
        ("tool", "c1"),
        ("tool", "c2"),
        ("user", None),
    ]
    assert result[1] is messages[1]
    assert result[4] is messages[4]


def test_compaction_leaves_input_when_keeping_the_group_empties_the_prefix() -> None:
    messages = [
        Message(
            role="assistant",
            content="abcdefghij",
            tool_calls=[ToolCall(id="c1", name="fn", arguments={"a": "1"})],
        ),
        Message(role="tool", content="one", tool_call_id="c1"),
    ]
    provider = ScriptedProvider(turns=[ScriptedTurn(content="SUM")])
    compaction = Compaction(provider, max_chars=5, keep_last=1)

    result = run(compaction.apply(messages))

    assert result == messages
    assert provider.calls == []
    assert [message.role for message in result] == ["assistant", "tool"]


def test_compacts_prefix_and_keeps_last_with_empty_tools() -> None:
    messages = [
        Message(role="user", content="aaaaaaaaaa"),
        Message(role="user", content="bbbbbbbbbb"),
        Message(role="user", content="cccccccccc"),
    ]
    provider = ScriptedProvider(turns=[ScriptedTurn(content="SHORT")])
    compaction = Compaction(provider, max_chars=25, keep_last=1)

    result = run(compaction.apply(messages))

    assert len(result) == 2
    assert result[0].role == "user"
    assert result[0].content == "[compacted context]\nSHORT"
    assert result[1] is messages[2]
    assert compaction.last_failure is None
    assert len(provider.calls) == 1
    assert provider.calls[0]["tools"] == []


def test_tool_call_arguments_count_toward_max_chars() -> None:
    messages = [
        Message(role="user", content=""),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="1", name="fn", arguments={"a": "12345"})],
        ),
    ]
    provider = ScriptedProvider(turns=[ScriptedTurn(content="SUM")])
    compaction = Compaction(provider, max_chars=5, keep_last=1)

    result = run(compaction.apply(messages))

    assert result[0].content.startswith("[compacted context]\n")
    assert result[1] is messages[1]
    assert len(provider.calls) == 1


def test_summary_request_includes_tool_name_and_path() -> None:
    messages = [
        Message(
            role="assistant",
            content="read",
            tool_calls=[
                ToolCall(
                    id="1",
                    name="read_file",
                    arguments={"path": "pkg/target.py"},
                )
            ],
        ),
        Message(role="user", content="keep"),
    ]
    provider = ScriptedProvider(turns=[ScriptedTurn(content="SUM")])
    compaction = Compaction(provider, max_chars=1, keep_last=1)

    run(compaction.apply(messages))

    body = provider.calls[0]["messages"][0]["content"]
    assert "read_file" in body
    assert "pkg/target.py" in body


def test_no_prefix_does_not_call_provider() -> None:
    messages = [Message(role="user", content="x" * 100)]
    provider = ScriptedProvider(turns=[ScriptedTurn(content="SHOULD_NOT_RUN")])
    compaction = Compaction(provider, max_chars=5, keep_last=1)

    result = run(compaction.apply(messages))

    assert result == messages
    assert provider.calls == []
    assert compaction.last_failure is None


def test_summarizer_failure_returns_original_messages(tmp_path) -> None:
    messages = [
        Message(role="user", content="abcdefghij"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="fn", arguments={"a": "12345"})],
        ),
        Message(role="tool", content="tool-output", tool_call_id="c1"),
    ]
    session = Session(tmp_path / "session.jsonl")
    session.replace_all(messages)
    before = session.load()

    provider = RaisingProvider()
    compaction = Compaction(provider, max_chars=5, keep_last=1)
    result = run(compaction.apply(messages))

    after = session.load()
    assert compaction.last_failure == "summarizer down"
    assert len(provider.calls) == 1
    assert len(result) == len(messages)
    for got, original in zip(result, messages, strict=True):
        assert got.role == original.role
        assert got.content == original.content
        assert got.tool_calls == original.tool_calls
        assert got.tool_call_id == original.tool_call_id
        assert "[compacted context]" not in got.content

    assert len(before) == len(after)
    for first, second in zip(before, after, strict=True):
        assert first.role == second.role
        assert first.content == second.content
        assert first.tool_calls == second.tool_calls
        assert first.tool_call_id == second.tool_call_id
        assert "[compacted context]" not in first.content
        assert "[compacted context]" not in second.content
