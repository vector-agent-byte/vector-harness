import os

import pytest

from vector_harness import Message, Session


def test_prefix_hash_detects_same_length_edit():
    from vector_harness.core.session_state import prefix_digest

    messages = [Message(role="user", content="first"), Message(role="assistant", content="reply")]
    original = prefix_digest(messages, 2)
    assert original == prefix_digest([*messages, Message(role="user", content="next")], 2)
    assert original != prefix_digest([Message(role="user", content="other"), messages[1]], 2)


def test_context_update_keeps_checkpoint_and_workdir(tmp_path):
    from vector_harness.core.session_state import SessionArtifacts

    store = SessionArtifacts(Session(tmp_path / "session.jsonl"))
    store.update("context", {"checkpoint": {"covered_count": 2}})
    store.update("context", {"last_workdir": "project"})
    assert store.load("context") == {
        "version": 1, "checkpoint": {"covered_count": 2}, "last_workdir": "project"
    }


def test_sidecar_replace_failure_preserves_previous(tmp_path, monkeypatch):
    from vector_harness.core.session_state import SessionArtifacts

    store = SessionArtifacts(Session(tmp_path / "session.jsonl"))
    store.update("context", {"checkpoint": "before"})
    before = store.path("context").read_bytes()

    def fail_replace(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        store.update("context", {"checkpoint": "after"})
    assert store.path("context").read_bytes() == before
    assert len(list(tmp_path.iterdir())) == 1


def test_memory_artifacts_are_session_local(tmp_path):
    from vector_harness.core.session_state import SessionArtifacts

    session = Session.in_memory()
    SessionArtifacts(session).update("task", {"todos": []})
    assert SessionArtifacts(session).load("task") == {"version": 1, "todos": []}
    assert SessionArtifacts(Session.in_memory()).load("task") is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("text", ['{', '[]', '{"version":2}', '{"version":true}'])
def test_invalid_artifact_is_ignored(tmp_path, text):
    from vector_harness.core.session_state import SessionArtifacts

    store = SessionArtifacts(Session(tmp_path / "session.jsonl"))
    store.path("task").write_text(text, encoding="utf-8")
    assert store.load("task") is None


def test_artifact_kind_cannot_escape_session(tmp_path):
    from vector_harness.core.session_state import SessionArtifacts

    with pytest.raises(ValueError):
        SessionArtifacts(Session(tmp_path / "session.jsonl")).load("../secret")
