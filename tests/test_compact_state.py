import asyncio

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn, summary_json
from vector_harness import Message, Session
from vector_harness.patterns.compact import Compaction
from vector_harness.patterns.compact_state import load_checkpoint


def history(session):
    for text in ("old evidence " * 200, "retained evidence " * 100, "latest"):
        session.append(Message(role="user", content=text))


def test_preserves_bytes_and_reloads_checkpoint(tmp_path):
    session = Session(tmp_path / "session.jsonl")
    history(session)
    before = session.path.read_bytes()
    provider = ScriptedProvider(turns=[ScriptedTurn(content=summary_json())])
    compact = Compaction(provider, max_chars=1000, keep_last=1, session=session)
    projection = asyncio.run(compact.apply(session.load()))
    assert projection[0].content.startswith("[任务摘要 v1]")
    assert session.path.read_bytes() == before
    assert session.path.with_suffix(".context.json").exists()
    restored = Session(session.path)
    unused = ScriptedProvider(turns=[])
    again = Compaction(unused, max_chars=1000, keep_last=1, session=restored)
    assert asyncio.run(again.apply(restored.load())) == projection
    assert unused.calls == []


def test_second_compaction_consumes_tail_and_rejects_mutation(tmp_path):
    session = Session(tmp_path / "s.jsonl")
    history(session)
    provider = ScriptedProvider(turns=[ScriptedTurn(content=summary_json()), ScriptedTurn(content=summary_json(goal=["second"]))])
    compact = Compaction(provider, max_chars=1000, keep_last=2, session=session)
    asyncio.run(compact.apply(session.load()))
    first = load_checkpoint(session).covered_count
    session.append(Message(role="user", content="new evidence " * 200))
    session.append(Message(role="user", content="keep"))
    asyncio.run(compact.apply(session.load()))
    assert load_checkpoint(session).covered_count > first
    body = provider.calls[1]["messages"][0]["content"]
    assert "retained evidence" in body
    assert "old evidence" not in body
    assert "[任务摘要 v1]" in body
    rewritten = session.load()
    rewritten[0].content = "changed"
    session.replace_all(rewritten)
    assert load_checkpoint(Session(session.path)) is None


@pytest.mark.parametrize("text", ["", "{}", summary_json(goal=["x" * 13000])])
def test_invalid_summary_attempted_once_per_run(text):
    session = Session.in_memory()
    history(session)
    provider = ScriptedProvider(turns=[ScriptedTurn(content=text), ScriptedTurn(content=text)])
    compact = Compaction(provider, max_chars=1000, keep_last=1, session=session)
    for unused in range(2):
        assert asyncio.run(compact.apply(session.load())) == session.load()
    assert len(provider.calls) == 1
    assert load_checkpoint(session) is None
    compact.on_run_start(len(session.load()))
    asyncio.run(compact.apply(session.load()))
    assert len(provider.calls) == 2


def test_new_user_protected_and_extra_context_counted():
    session = Session.in_memory()
    history(session)
    provider = ScriptedProvider(turns=[ScriptedTurn(content=summary_json())])
    compact = Compaction(provider, max_chars=6000, keep_last=0, session=session, extra_context_chars=lambda session: 5000)
    compact.on_run_start(3)
    result = asyncio.run(compact.apply(session.load()))
    assert result[-1].content == "latest"
    assert load_checkpoint(session).covered_count == 2


def test_save_failure_preserves_previous_checkpoint_and_does_not_retry(monkeypatch):
    from vector_harness.core.session_state import SessionArtifacts

    session = Session.in_memory()
    history(session)
    provider = ScriptedProvider(turns=[ScriptedTurn(content=summary_json()), ScriptedTurn(content=summary_json(goal=["new"]))])
    compact = Compaction(provider, max_chars=1000, keep_last=1, session=session)
    asyncio.run(compact.apply(session.load()))
    original = load_checkpoint(session)
    session.append(Message(role="user", content="more evidence " * 200))
    session.append(Message(role="user", content="latest"))

    def refuse(self, kind, changes):
        raise OSError("replace denied")

    monkeypatch.setattr(SessionArtifacts, "update", refuse)
    for unused in range(2):
        projection = asyncio.run(compact.apply(session.load()))
        assert "more evidence" in projection[-2].content
    assert len(provider.calls) == 2
    assert load_checkpoint(session) == original


def test_valid_but_larger_summary_does_not_replace_history():
    messages = [Message(role="user", content="tiny"), Message(role="user", content="latest")]
    provider = ScriptedProvider(turns=[ScriptedTurn(content=summary_json())])
    compact = Compaction(provider, max_chars=1, keep_last=1)
    assert asyncio.run(compact.apply(messages)) == messages
    assert compact.last_failure == "summary does not reduce context"


def test_rebinding_does_not_copy_failed_candidate():
    session = Session.in_memory()
    history(session)
    provider = ScriptedProvider(turns=[ScriptedTurn(content="{}"), ScriptedTurn(content=summary_json())])
    parent = Compaction(provider, max_chars=1000, keep_last=1, session=session)
    asyncio.run(parent.apply(session.load()))
    child_session = Session.in_memory()
    child_session.replace_all(session.load())
    child = parent.for_session(child_session)
    assert asyncio.run(child.apply(child_session.load()))[0].content.startswith("[任务摘要 v1]")
    assert load_checkpoint(session) is None
    assert load_checkpoint(child_session) is not None
