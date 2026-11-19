import asyncio
import json
import sys

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Message, Session
from vector_harness.core.loop import Loop
from vector_harness.core.session_state import SessionArtifacts
from vector_harness.web_sessions import create_session, delete_session, list_sessions, read_session_view, session_path


@pytest.fixture(autouse=True)
def restore_cli_import_state():
    previous = sys.modules.get("vector_harness.cli")
    yield
    if previous is None:
        sys.modules.pop("vector_harness.cli", None)
    else:
        sys.modules["vector_harness.cli"] = previous


def test_open_partial_tail_is_read_only_and_run_repairs(tmp_path):
    identifier = create_session(tmp_path)
    path = session_path(tmp_path, identifier)
    Session(path).append(Message(role="user", content="old"))
    with path.open("ab") as stream:
        stream.write(b'{"role":"user","content":"\xe4')
    before = path.read_bytes()
    view = read_session_view(tmp_path, identifier)
    assert view["warnings"] == ["session_partial_tail"]
    assert len(view["messages"]) == 1
    assert list_sessions(tmp_path)[0]["id"] == identifier
    assert path.read_bytes() == before
    assert not path.with_suffix(".context.json").exists()
    provider = ScriptedProvider(turns=[ScriptedTurn(content="status")])
    loop = Loop(provider=provider, tools=[], session=Session(path), system="", workdir=tmp_path)
    assert provider.calls == []
    assert asyncio.run(loop.run("progress?")).status == "complete"
    assert len(list(path.parent.glob(f"{identifier}.recovery-*.bin"))) == 1


def test_corrupt_middle_shows_valid_records_but_prevents_execution(tmp_path):
    identifier = create_session(tmp_path)
    path = session_path(tmp_path, identifier)
    path.write_text('{"role":"user","content":"first"}\nBROKEN\n{"role":"assistant","content":"last"}\n', encoding="utf-8")
    view = read_session_view(tmp_path, identifier)
    assert view["warnings"] == ["session_invalid_record"]
    assert len(view["messages"]) == 2
    provider = ScriptedProvider(turns=[])
    loop = Loop(provider=provider, tools=[], session=Session(path), system="")
    before = path.read_bytes()
    assert asyncio.run(loop.run("continue")).status == "error"
    assert path.read_bytes() == before
    assert provider.calls == []


def test_changed_workdir_is_runtime_context_only(tmp_path):
    session = Session(tmp_path / "s.jsonl")
    provider = ScriptedProvider(turns=[ScriptedTurn(content="ok"), ScriptedTurn(content="ok")])
    for name in ("first", "second"):
        loop = Loop(provider=provider, tools=[], session=Session(session.path), system="", workdir=tmp_path / name)
        asyncio.run(loop.run("progress"))
    text = json.dumps(provider.calls[-1]["messages"], ensure_ascii=False)
    assert "first" in text and "second" in text and "重新核查" in text
    assert "工作目录" not in session.path.read_text(encoding="utf-8")
    assert SessionArtifacts(session).load("context")["last_workdir"].endswith("second")


def test_delete_removes_only_owned_continuity_artifacts(tmp_path):
    identifier = create_session(tmp_path)
    path = session_path(tmp_path, identifier)
    owned = [path.with_suffix(".context.json"), path.with_suffix(".task.json"), path.with_name(f"{identifier}.recovery-{'a' * 32}.bin")]
    other = path.with_name(f"{identifier}.recovery-not-a-uuid.bin")
    for target in [*owned, other]:
        target.write_bytes(b"data")
    delete_session(tmp_path, identifier)
    assert all(not target.exists() for target in owned)
    assert other.exists()


def test_cli_open_existing_without_input_is_idle(tmp_path):
    from vector_harness.cli import main

    path = tmp_path / "s.jsonl"
    path.write_bytes(b'{"role":"user","content":"old"}\n{"role":')
    provider = ScriptedProvider([])
    before = path.read_bytes()
    assert main(["--workspace", str(tmp_path), "--session", str(path), "--compact", "--plan"], environ={}, provider=provider, stdin_lines=[]) == 0
    assert provider.calls == []
    assert path.read_bytes() == before
    assert not path.with_suffix(".context.json").exists()


def test_web_get_is_idle_and_post_restores_checkpoint(tmp_path):
    import httpx

    from tests.scripted import summary_json
    from vector_harness.patterns.compact import Compaction
    from vector_harness.web_server import WebServer, WebSettings

    identifier = create_session(tmp_path)
    path = session_path(tmp_path, identifier)
    session = Session(path)
    session.append(Message(role="user", content="old evidence " * 200))
    session.append(Message(role="assistant", content="retained"))
    summarizer = ScriptedProvider([ScriptedTurn(content=summary_json())])
    asyncio.run(Compaction(summarizer, max_chars=500, keep_last=1, session=session).apply(session.load()))
    before = path.read_bytes(), path.with_suffix(".context.json").read_bytes()
    provider = ScriptedProvider([ScriptedTurn(content="progress only")])
    server = WebServer(WebSettings(workspace=tmp_path, compact=True), provider)
    server.start()
    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            url = f"http://127.0.0.1:{server.port}/api/sessions/{identifier}"
            body = client.get(url).json()
            assert body["warnings"] == []
            assert "old evidence" in body["messages"][0]["content"]
            assert provider.calls == []
            assert (path.read_bytes(), path.with_suffix(".context.json").read_bytes()) == before
            assert client.post(url + "/messages", json={"text": "progress?"}).status_code == 200
            assert len(provider.calls) == 1
            assert any(message["content"].startswith("[任务摘要 v1]") for message in provider.calls[0]["messages"])
    finally:
        server.shutdown()


def test_web_get_corruption_warnings_and_post_error(tmp_path):
    import httpx

    from vector_harness.web_server import WebServer, WebSettings

    identifier = create_session(tmp_path)
    path = session_path(tmp_path, identifier)
    path.write_bytes(b'{"role":"user","content":"valid"}\nBAD\n')
    before = path.read_bytes()
    provider = ScriptedProvider([])
    server = WebServer(WebSettings(workspace=tmp_path), provider)
    server.start()
    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            url = f"http://127.0.0.1:{server.port}/api/sessions/{identifier}"
            assert client.get(url).json()["warnings"] == ["session_invalid_record"]
            response = client.post(url + "/messages", json={"text": "continue"})
            assert '"status": "error"' in response.text
            assert provider.calls == []
            assert path.read_bytes() == before
    finally:
        server.shutdown()
