import asyncio
import json

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn, summary_json
from vector_harness import Message, Session, ToolCall
from vector_harness.core.codec import message_to_dict
from vector_harness.core.loop import Loop
from vector_harness.core.session_state import SessionArtifacts, prefix_digest
from vector_harness.patterns.compact import Compaction
from vector_harness.patterns.task_state import TaskState
from vector_harness.tools.history import ReadSessionHistory
from vector_harness.types import ProviderError
from vector_harness.web_sessions import create_session, read_session_view, session_path


@pytest.mark.parametrize("source", ["missing", "failed", "different"])
def test_task_snapshot_must_match_successful_source(source):
    session = Session.in_memory()
    actual = [{"id": 1, "content": "work", "status": "pending"}]
    fabricated = [{**actual[0], "status": "completed"}]
    session.append(Message(role="assistant", content="", tool_calls=[ToolCall("todo", "update_todos", {"todos": actual})]))
    if source != "missing":
        session.append(Message(role="tool", content=json.dumps({"kind": "todo_snapshot", "version": 1, "todos": actual}), tool_call_id="todo", is_error=source == "failed"))
    count = len(session.load())
    SessionArtifacts(session).update("task", {"covered_count": count, "prefix_digest": prefix_digest(session.load(), count), "todos": fabricated})
    assert TaskState(session).restore() == (actual if source == "different" else [])


def test_history_metadata_cannot_exceed_budget_at_end_offset():
    session = Session.in_memory()
    session.append(Message(role="tool", content="result", tool_call_id="x" * 16000))
    offset = len(json.dumps(message_to_dict(session.load()[0]), ensure_ascii=False, sort_keys=True))
    result = asyncio.run(ReadSessionHistory(session).execute({"offset": offset}))
    assert len(result) <= 16000
    assert json.loads(result)["entries"] == []


def test_malformed_result_id_warns_and_blocks_without_writing(tmp_path):
    identifier = create_session(tmp_path)
    path = session_path(tmp_path, identifier)
    Session(path).append(Message(role="assistant", content="", tool_calls=[ToolCall("call", "tool", {})]))
    with path.open("ab") as stream:
        stream.write(b'{"role":"tool","content":"ok","tool_call_id":[]}\n')
    assert read_session_view(tmp_path, identifier)["warnings"] == ["session_invalid_record"]
    before = path.read_bytes()
    provider = ScriptedProvider([])
    loop = Loop(provider=provider, tools=[], session=Session(path), system="")
    assert asyncio.run(loop.run("continue")).status == "error"
    assert path.read_bytes() == before
    assert provider.calls == []


def test_summary_preserves_tool_result_associations_and_errors():
    requests = []
    for identifier, is_error in [("a", False), ("b", False), ("b", True)]:
        messages = [
            Message(role="assistant", content="long evidence " * 100, tool_calls=[ToolCall("a", "tool", {}), ToolCall("b", "tool", {})]),
            Message(role="tool", content="done", tool_call_id=identifier, is_error=is_error),
            Message(role="user", content="keep"),
        ]
        provider = ScriptedProvider([ScriptedTurn(content=summary_json())])
        asyncio.run(Compaction(provider, max_chars=100, keep_last=1).apply(messages))
        requests.append(provider.calls[0]["messages"][0]["content"])
    assert len(set(requests)) == 3
    assert all("原始消息 2" in request for request in requests)


def test_workdir_change_survives_failed_request_and_restart(tmp_path):
    class FailingProvider:
        async def stream(self, **kwargs):
            raise ProviderError("offline")
            yield

    path = tmp_path / "s.jsonl"
    first = tmp_path / "first"
    second = tmp_path / "second"
    session = Session(path)
    session.append(Message(role="assistant", content="old verification"))
    SessionArtifacts(session).update("context", {"last_workdir": str(first.resolve())})
    failed = Loop(provider=FailingProvider(), tools=[], session=session, system="", workdir=second)
    assert asyncio.run(failed.run("continue")).status == "error"
    provider = ScriptedProvider([ScriptedTurn(content="recheck")])
    retried = Loop(provider=provider, tools=[], session=Session(path), system="", workdir=second)
    assert asyncio.run(retried.run("retry")).status == "complete"
    context = provider.calls[0]["messages"][0]["content"]
    assert str(first.resolve()) in context and "重新核查" in context
    assert SessionArtifacts(Session(path)).load("context")["last_workdir"] == str(second.resolve())
