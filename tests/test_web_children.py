import json
from pathlib import Path

from vector_harness.core.session import Session
from vector_harness.types import Message, ProviderEvent, Role, ToolCall
from vector_harness.web_children import ChildTrace, read_children
from vector_harness.web_sessions import create_session, delete_session, list_sessions, read_messages, session_path


def test_child_trace_is_readable_during_execution_and_kept_out_of_model_context(tmp_path: Path):
    session_id = create_session(tmp_path)
    path = session_path(tmp_path, session_id)
    Session(path).append(Message(role=Role.ASSISTANT, content="", tool_calls=[
        ToolCall(id="delegate-1", name="delegate", arguments={"task": "work"}),
    ]))
    trace = ChildTrace(path)
    trace.record(ProviderEvent(kind="tool_execution_start", name="delegate", tool_call_id="delegate-1"))
    trace.record(ProviderEvent(kind="thinking_delta", text="parent"))
    trace.record(ProviderEvent(kind="thinking_delta", text="child thought", origin="child"))
    trace.record(ProviderEvent(kind="tool_execution_start", name="shell", origin="child"))
    trace.record(ProviderEvent(kind="tool_call_end", name="shell", arguments={"command": "pwd"}, origin="child"))
    trace.record(ProviderEvent(kind="tool_result", text="ignored", origin="child"))
    trace.record(ProviderEvent(kind="text_delta", text="partial", origin="child"))
    expected = {"thinking": "child thought", "text": "partial", "tools": [{"name": "shell", "args": {"command": "pwd"}}]}
    assert read_messages(tmp_path, session_id)[0]["tool_calls"][0]["child"] == expected
    assert "child thought" not in path.read_text(encoding="utf-8")
    assert len(Session(path).load()) == 1
    assert len(list_sessions(tmp_path)) == 1
    trace.record(ProviderEvent(kind="tool_result", tool_call_id="delegate-1"))
    trace.record(ProviderEvent(kind="text_delta", text="not associated", origin="child"))
    assert read_children(path) == {"delegate-1": expected}
    delete_session(tmp_path, session_id)
    assert not trace.path.exists()


def test_child_trace_ignores_incomplete_or_invalid_records(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    assert read_children(path) == {}
    trace = ChildTrace(path)
    trace.record(ProviderEvent(kind="tool_execution_start", name="delegate", tool_call_id="call"))
    trace.record(ProviderEvent(kind="text_delta", text="kept", origin="child"))
    with trace.path.open("a", encoding="utf-8") as stream:
        for value in [None, [], {"call_id": []}, {"call_id": "call", "kind": []}, {"call_id": "call", "kind": "text_delta", "text": 5}]:
            stream.write(json.dumps(value) + "\n")
        stream.write('{"call_id": "call"')
    assert read_children(path) == {"call": {"thinking": "", "text": "kept", "tools": []}}
