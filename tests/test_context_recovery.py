import asyncio

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Loop, Message, Session, ToolCall


def test_transform_mutation_cannot_change_original_history():
    class Mutator:
        async def apply(self, messages):
            messages[0].content = "changed"
            return messages

    session = Session.in_memory()
    provider = ScriptedProvider([ScriptedTurn(content="done")])
    loop = Loop(provider=provider, session=session, system="sys", tools=[], context_transforms=[Mutator()])
    asyncio.run(loop.run("original"))
    assert session.load()[0].content == "original"
    assert provider.calls[0]["messages"][0]["content"] == "changed"


def test_missing_result_is_unknown_not_reexecuted(tmp_path):
    class Counter:
        name = "effect"
        description = "effect"
        parameters = {}
        calls = 0

        async def execute(self, arguments):
            self.calls += 1
            return "done"

    session = Session(tmp_path / "session.jsonl")
    session.append(Message(role="assistant", content="", tool_calls=[ToolCall("old", "effect", {})]))
    tool = Counter()
    provider = ScriptedProvider([ScriptedTurn(content="请核查")])
    loop = Loop(provider=provider, session=Session(session.path), system="sys", tools=[tool])
    assert provider.calls == []
    asyncio.run(loop.run("继续"))
    sent = provider.calls[0]["messages"]
    assert sent[1]["tool_call_id"] == "old"
    assert sent[1]["is_error"] is True
    assert "执行结果未知" in sent[1]["content"]
    assert sent[2]["content"] == "继续"
    assert tool.calls == 0
    assert len(session.load()) == 3
    assert all(message.role != "tool" for message in session.load())


def test_partial_batch_and_reused_ids_are_paired_locally():
    from vector_harness.core.context import repair_tool_pairs

    original = [
        Message(role="assistant", content="", tool_calls=[ToolCall("same", "fn", {}), ToolCall("missing", "fn", {})]),
        Message(role="tool", content="real one", tool_call_id="same"),
        Message(role="user", content="next"),
        Message(role="assistant", content="", tool_calls=[ToolCall("same", "fn", {})]),
        Message(role="tool", content="real two", tool_call_id="same"),
    ]
    projected = repair_tool_pairs(original)
    assert [message.content for message in projected if message.tool_call_id == "same"] == ["real one", "real two"]
    assert projected[2].tool_call_id == "missing"
    assert projected[2].is_error
    assert len(original) == 5


def test_orphan_result_blocks_new_input():
    session = Session.in_memory()
    session.append(Message(role="tool", content="orphan", tool_call_id="none"))
    provider = ScriptedProvider([])
    loop = Loop(provider=provider, session=session, system="sys", tools=[])
    result = asyncio.run(loop.run("next"))
    assert result.status == "error"
    assert provider.calls == []
    assert len(session.load()) == 1


@pytest.mark.parametrize("callback_fails", [False, True])
def test_persisted_callback_follows_append(callback_fails):
    session = Session.in_memory()

    class ObservedTool:
        name = "observed"
        description = "test"
        parameters = {}
        executions = 0
        observed = []

        async def execute(self, arguments):
            self.executions += 1
            return "committed"

        def after_result_persisted(self, call, result):
            assert session.load()[-1] == result
            self.observed.append(result.content)
            if callback_fails:
                raise OSError("cache failure")

    tool = ObservedTool()
    provider = ScriptedProvider([
        ScriptedTurn(tool_calls=[ToolCall("call", "observed", {})]), ScriptedTurn(content="done")
    ])
    result = asyncio.run(Loop(provider=provider, session=session, system="sys", tools=[tool]).run("go"))
    assert result.status == "complete"
    assert tool.executions == 1
    assert tool.observed == ["committed"]
    assert session.load()[2].is_error is False


def test_append_failure_does_not_notify_result(monkeypatch):
    from vector_harness.core.dispatch import ToolDispatcher

    session = Session.in_memory()

    class Tool:
        name = "tool"
        notified = False

        async def execute(self, arguments):
            return "done"

        def after_result_persisted(self, call, result):
            self.notified = True

    def fail_append(message):
        raise OSError("disk failure")

    tool = Tool()
    monkeypatch.setattr(session, "append", fail_append)
    with pytest.raises(OSError):
        asyncio.run(ToolDispatcher(session, [tool], []).dispatch([ToolCall("id", "tool", {})]))
    assert tool.notified is False
