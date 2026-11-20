import json

import pytest

from vector_harness.agent.infrastructure.metadata import MetadataStore
from vector_harness.web.sessions import create_session, delete_session


def test_metadata_roundtrip_and_legacy_default(tmp_path):
    session_id = create_session(tmp_path)
    store = MetadataStore(tmp_path)
    assert store.read(session_id) is None
    saved = store.create(session_id, "deepresearch", {"topic": "agents", "engine": "standard"})
    assert saved["status"] == "idle"
    assert MetadataStore(tmp_path).read(session_id) == saved
    assert saved["schema_version"] == 1
    with pytest.raises(FileExistsError):
        store.create(session_id, "autoresearch", {})


def test_failed_metadata_replace_preserves_original(tmp_path, monkeypatch):
    session_id = create_session(tmp_path)
    store = MetadataStore(tmp_path)
    original = store.create(session_id, "deepresearch", {"topic": "agents"})

    def fail_replace(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(type(tmp_path), "replace", fail_replace)
    with pytest.raises(OSError):
        store.update(session_id, status="running")
    assert store.read(session_id) == original


def test_recovery_marks_only_running_tasks_interrupted(tmp_path):
    store = MetadataStore(tmp_path)
    running = create_session(tmp_path)
    idle = create_session(tmp_path)
    store.create(running, "deepresearch", {})
    store.create(idle, "deepresearch", {})
    store.update(running, status="running")
    MetadataStore(tmp_path).recover()
    assert store.read(running)["status"] == "interrupted"
    assert store.read(idle)["status"] == "idle"


def test_corrupt_metadata_does_not_become_an_agent_task(tmp_path):
    session_id = create_session(tmp_path)
    store = MetadataStore(tmp_path)
    path = tmp_path / ".vector" / "sessions" / f"{session_id}.metadata.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        store.read(session_id)
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        store.read(session_id)


def test_session_delete_removes_metadata_and_unsafe_ids_are_rejected(tmp_path):
    session_id = create_session(tmp_path)
    store = MetadataStore(tmp_path)
    store.create(session_id, "deepresearch", {})
    delete_session(tmp_path, session_id)
    assert not (tmp_path / ".vector" / "sessions" / f"{session_id}.metadata.json").exists()
    with pytest.raises(ValueError):
        store.read("../outside")


@pytest.mark.parametrize("field,value", [("kind", []), ("status", {}), ("schema_version", True),
                                         ("revision", "bad"), ("updated_at", "bad")])
def test_malformed_metadata_fields_raise_consistent_error(tmp_path, field, value):
    session_id = create_session(tmp_path)
    store = MetadataStore(tmp_path)
    record = store.create(session_id, "agent", {})
    record[field] = value
    path = tmp_path / ".vector" / "sessions" / f"{session_id}.metadata.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        store.read(session_id)
