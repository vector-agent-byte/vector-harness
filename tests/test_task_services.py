import gc

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness.agent.application.errors import ServiceError
from vector_harness.agent.application.runs import RunManager, RunSettings
from vector_harness.agent.application.sessions import SessionService
from vector_harness.agent.infrastructure import sessions as repository
from vector_harness.agent.infrastructure.metadata import MetadataStore
from vector_harness.deepresearch.service import ResearchService


def services(workspace, provider=None):
    metadata = MetadataStore(workspace)
    runs = RunManager(RunSettings(workspace=workspace, workdir=lambda: workspace), provider or object())
    sessions = SessionService(workspace, runs, metadata, repository=repository)
    return sessions, ResearchService(sessions)


def test_research_runs_without_http_and_queries_persisted_projection(tmp_path):
    provider = ScriptedProvider([ScriptedTurn(content="independent service")])
    sessions, research = services(tmp_path, provider)
    task = research.create({"topic": "research"})
    snapshots = []
    status, content = research.execute(task["id"], emit=lambda _event: None, snapshot=snapshots.append)
    assert (status, content) == ("complete", "independent service")
    assert research.detail(task["id"])["task"]["report"] == content
    assert snapshots[-1]["task"]["status"] == "completed"
    assert snapshots[-1]["revision"] > snapshots[0]["revision"]
    assert sessions.runs.running_id is None


def test_cancel_from_ready_prevents_provider_execution_and_leaks_no_coroutine(tmp_path, recwarn):
    provider = ScriptedProvider([])
    sessions, research = services(tmp_path, provider)
    task = research.create({"topic": "cancel immediately"})

    def stop_when_ready():
        assert sessions.stop(task["id"]) == {"stopped": True}

    result = research.execute(task["id"], emit=lambda _event: None, ready=stop_when_ready)
    gc.collect()
    assert result[0] == "stopped"
    assert provider.calls == []
    assert not [item for item in recwarn if "was never awaited" in str(item.message)]
    assert research.detail(task["id"])["task"]["status"] == "stopped"


def test_failed_create_rolls_back_new_session_but_keeps_existing(tmp_path, monkeypatch):
    sessions, research = services(tmp_path)
    existing = sessions.create()["id"]

    def fail_write(*_args, **_kwargs):
        raise OSError("full disk")

    monkeypatch.setattr(sessions.metadata, "create", fail_write)
    with pytest.raises(OSError):
        research.create({"topic": "cannot persist"})
    assert [item["id"] for item in sessions.list()] == [existing]


def test_session_initialization_failure_leaves_no_orphan(tmp_path, monkeypatch):
    def fail_save(*_args):
        raise OSError("full disk")

    monkeypatch.setattr(repository, "set_session_skills", fail_save)
    with pytest.raises(OSError):
        repository.create_session(tmp_path)
    assert repository.list_sessions(tmp_path) == []


def test_unexpected_provider_failure_marks_error_and_releases_admission(tmp_path):
    sessions, research = services(tmp_path, ScriptedProvider([]))
    task = research.create({"topic": "failure"})
    with pytest.raises(AssertionError, match="scripted"):
        research.execute(task["id"], emit=lambda _event: None)
    assert research.detail(task["id"])["task"]["status"] == "error"
    assert sessions.runs.running_id is None
    assert sessions.runs.acquire()
    sessions.runs.release()


def test_domain_session_cannot_be_run_as_unrestricted_agent(tmp_path):
    sessions, research = services(tmp_path)
    task = research.create({"topic": "typed task"})
    with pytest.raises(ServiceError, match="domain_task"):
        sessions.execute(task["id"], "bypass", "react", lambda _event: None)


def test_research_continuation_after_early_stop_keeps_authoritative_instructions(tmp_path):
    provider = ScriptedProvider([ScriptedTurn(content="continued")])
    sessions, research = services(tmp_path, provider)
    task = research.create({"topic": "distinctive research topic", "engine": "advanced"})
    research.execute(task["id"], emit=lambda _event: None, ready=lambda: sessions.stop(task["id"]))
    research.execute(task["id"], text="continue", emit=lambda _event: None)
    first_user_request = provider.calls[0]["messages"][-1]["content"]
    assert "distinctive research topic" in first_user_request
    assert "高级搜索" in first_user_request
    assert "continue" in first_user_request


def test_interrupted_legacy_import_commits_final_state_without_changing_old_mode(tmp_path, monkeypatch):
    from vector_harness.agent.core.session import Session
    from vector_harness.types import Message
    session_id = repository.create_session(tmp_path)
    repository.set_session_mode(tmp_path, session_id, "reflect")
    Session(repository.session_path(tmp_path, session_id)).append(Message(role="user", content="old research"))
    sessions, research = services(tmp_path)
    create = sessions.metadata.create

    def interrupt_after_commit(*args, **kwargs):
        create(*args, **kwargs)
        raise RuntimeError("process interrupted after atomic commit")

    monkeypatch.setattr(sessions.metadata, "create", interrupt_after_commit)
    with pytest.raises(RuntimeError, match="interrupted"):
        research.import_legacy(session_id, {"topic": "old"})
    restarted_sessions, restarted = services(tmp_path)
    restarted_sessions.metadata.recover()
    assert restarted.import_legacy(session_id, {"topic": "old"})["status"] == "already_imported"
    assert restarted.detail(session_id)["task"]["status"] == "completed"
    assert repository.session_mode(tmp_path, session_id) == "reflect"
    assert restarted_sessions.detail(session_id)["mode"] == "subagents"
