import asyncio
import json

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Loop, Message, Session, ToolCall
from vector_harness.patterns.plan import TodoPlan


def committed_update(session, todos, identifier="update", *, error=False):
    session.append(Message(role="assistant", content="", tool_calls=[ToolCall(identifier, "update_todos", {"todos": todos})]))
    session.append(Message(role="tool", content=json.dumps({"kind": "todo_snapshot", "version": 1, "todos": todos}), tool_call_id=identifier, is_error=error))


def test_restart_restores_only_committed_todos(tmp_path):
    from vector_harness.patterns.task_state import TaskState

    path = tmp_path / "session.jsonl"
    session = Session(path)
    expected = [{"id": 1, "content": "work", "status": "pending"}]
    committed_update(session, expected)
    committed_update(session, [{"id": 1, "content": "rejected", "status": "completed"}], error=True)
    session.append(Message(role="assistant", content="", tool_calls=[ToolCall("missing", "update_todos", {"todos": []})]))
    assert TaskState(Session(path)).restore() == expected


def test_progress_question_does_not_continue_old_plan(tmp_path):
    path = tmp_path / "session.jsonl"
    session = Session(path)
    committed_update(session, [{"id": 1, "content": "pending work", "status": "pending"}])
    provider = ScriptedProvider([ScriptedTurn(content="当前进度")])
    runner = TodoPlan(Loop(provider=provider, tools=[], session=Session(path), system="sys"))
    assert provider.calls == []
    result = asyncio.run(runner.run("只告诉我进度，不执行"))
    assert result.text == "当前进度"
    assert len(provider.calls) == 1
    assert "pending work" in "\n".join(message["content"] for message in provider.calls[0]["messages"])
    assert runner._tool.todos == [{"id": 1, "content": "pending work", "status": "pending"}]


def test_snapshot_is_saved_only_after_result_and_can_be_rebuilt(tmp_path):
    from vector_harness.patterns.task_state import TaskState

    path = tmp_path / "session.jsonl"
    todos = [{"id": 1, "content": "finished", "status": "completed"}]
    provider = ScriptedProvider([
        ScriptedTurn(tool_calls=[ToolCall("update", "update_todos", {"todos": todos})]),
        ScriptedTurn(content="done"),
    ])
    asyncio.run(TodoPlan(Loop(provider=provider, tools=[], session=Session(path), system="sys")).run("work"))
    snapshot = path.with_suffix(".task.json")
    assert snapshot.is_file()
    assert json.loads(snapshot.read_text(encoding="utf-8"))["todos"] == todos
    snapshot.unlink()
    assert TaskState(Session(path)).restore() == todos


def test_snapshot_write_failure_keeps_committed_state(tmp_path, monkeypatch):
    from vector_harness.patterns.task_state import TaskState
    from vector_harness.core.session_state import SessionArtifacts

    def fail_write(self, kind, changes):
        raise OSError("unwritable")

    monkeypatch.setattr(SessionArtifacts, "update", fail_write)
    session = Session(tmp_path / "session.jsonl")
    expected = [{"id": 1, "content": "done", "status": "completed"}]
    provider = ScriptedProvider([
        ScriptedTurn(tool_calls=[ToolCall("update", "update_todos", {"todos": expected})]), ScriptedTurn(content="done")
    ])
    runner = TodoPlan(Loop(provider=provider, tools=[], session=session, system="sys"))
    assert asyncio.run(runner.run("work")).status == "complete"
    assert TaskState(Session(session.path)).restore() == expected
    assert len([message for message in session.load() if message.role == "tool"]) == 1


def test_legacy_success_and_error_are_distinguished():
    from vector_harness.patterns.task_state import TaskState

    session = Session.in_memory()
    todos = [{"id": 1, "content": "work", "status": "pending"}]
    session.append(Message(role="assistant", content="", tool_calls=[ToolCall("same", "update_todos", {"todos": todos})]))
    session.append(Message(role="tool", tool_call_id="same", content="todos updated: total=1, completed=0, in_progress=0, pending=1\n\n当前列表：\n  [ ] 1. work"))
    session.append(Message(role="assistant", content="", tool_calls=[ToolCall("same", "update_todos", {"todos": []})]))
    session.append(Message(role="tool", tool_call_id="same", content="Error: rejected"))
    assert TaskState(session).restore() == todos


def test_new_task_replaces_previous_todos():
    from vector_harness.patterns.task_state import TaskState

    session = Session.in_memory()
    committed_update(session, [{"id": 1, "content": "old", "status": "pending"}])
    new = [{"id": 1, "content": "new", "status": "completed"}]
    committed_update(session, new)
    assert TaskState(session).restore() == new


def test_failed_update_does_not_change_confirmed_todos():
    session = Session.in_memory()
    expected = [{"id": 1, "content": "old", "status": "completed"}]
    committed_update(session, expected)
    invalid = [{"id": 1, "content": "a", "status": "in_progress"}, {"id": 2, "content": "b", "status": "in_progress"}]
    provider = ScriptedProvider([ScriptedTurn(tool_calls=[ToolCall("bad", "update_todos", {"todos": invalid})]), ScriptedTurn(content="rejected")])
    runner = TodoPlan(Loop(provider=provider, tools=[], session=session, system="sys"))
    asyncio.run(runner.run("update"))
    assert runner._tool.todos == expected
    assert session.load()[-2].is_error is True
