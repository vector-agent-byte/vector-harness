import asyncio
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness.cli import DEFAULT_SYSTEM
from vector_harness.types import ProviderEvent
from vector_harness.web_server import WebServer, WebSettings
from vector_harness.web_sessions import create_session, is_session_id


@pytest.fixture(autouse=True)
def _drop_web_modules():
    yield
    for name in list(sys.modules):
        if name in {
            "vector_harness.web",
            "vector_harness.web_server",
            "vector_harness.web_sessions",
            "vector_harness.cli",
            "vector_harness.assembly",
        } or name == "vector_harness.patterns" or name.startswith(
            "vector_harness.patterns."
        ):
            del sys.modules[name]


def test_lists_creates_and_reads_a_session(tmp_path: Path):
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            empty = client.get(f"{base}/api/sessions")
            assert empty.status_code == 200
            assert empty.json() == {"sessions": [], "running_id": None, "model": ""}
            assert "access-control-allow-origin" not in {k.lower() for k in empty.headers}
            created = client.post(f"{base}/api/sessions")
            assert created.status_code == 201
            session_id = created.json()["id"]
            assert is_session_id(session_id)
            escaped = client.get(f"{base}/api/sessions/%2e%2e%2fsecret")
            assert escaped.status_code == 400
            assert escaped.json() == {"error": "bad_session"}
            assert not (tmp_path / "secret").exists()
            missing = client.get(f"{base}/api/sessions/{'d' * 32}")
            assert missing.status_code == 404
            assert missing.json() == {"error": "not_found"}
            body = client.get(f"{base}/api/sessions/{session_id}")
            assert body.json() == {
                "id": session_id,
                "messages": [],
                "skill": None,
                "started_at": None,
                "duration_ms": None,
            }
            assert client.get(f"{base}/api/unknown").status_code == 404
    finally:
        server.shutdown()


def test_session_list_reports_the_provider_model(tmp_path: Path):
    class Named:
        model = "demo-model"

    server = WebServer(WebSettings(workspace=tmp_path), provider=Named())
    server.start()
    try:
        with httpx.Client(trust_env=False) as client:
            listed = client.get(f"http://127.0.0.1:{server.port}/api/sessions")
            assert listed.status_code == 200
            assert listed.json()["model"] == "demo-model"
    finally:
        server.shutdown()


def test_root_without_dist_is_503_and_api_still_works(tmp_path: Path):
    server = WebServer(
        WebSettings(workspace=tmp_path, dist_dir=tmp_path / "no-dist"),
        provider=object(),
    )
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            page = client.get(f"{base}/")
            assert page.status_code == 503
            assert "npm run build" in page.text
            assert client.get(f"{base}/api/sessions").status_code == 200
    finally:
        server.shutdown()


def test_static_request_cannot_read_outside_dist(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("APP", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    server = WebServer(WebSettings(workspace=tmp_path, dist_dir=dist), provider=object())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            assert client.get(f"{base}/").text == "APP"
            escaped = client.get(f"{base}/%2e%2e/secret.txt")
            assert "SECRET" not in escaped.text
            assert escaped.text == "APP"
    finally:
        server.shutdown()


def test_streams_the_first_delta_before_the_turn_finishes(tmp_path: Path):
    session_id = create_session(tmp_path)
    gate = threading.Event()

    class HoldAfterDelta:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def stream(self, *, system: str, messages: list, tools: list):
            self.calls.append({"system": system, "tools": [tool.name for tool in tools]})
            yield ProviderEvent(kind="text_delta", text="好")
            yield ProviderEvent(kind="thinking_delta", text="不落盘")
            await asyncio.to_thread(gate.wait)

    provider = HoldAfterDelta()
    server = WebServer(WebSettings(workspace=tmp_path), provider)
    server.start()
    seen = threading.Event()

    def read() -> None:
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
            json={"text": "你好"},
            timeout=None,
            trust_env=False,
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if "好" in line and "\\u" not in line:
                    seen.set()
                if '"kind": "run_result"' in line:
                    assert '"status": "complete"' in line
                    break

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    try:
        assert seen.wait(2)
        gate.set()
        thread.join(2)
        assert not thread.is_alive()
        assert server.running_id is None
        stored = (tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl").read_text(encoding="utf-8")
        assert "你好" in stored
        assert "好" in stored
        assert "不落盘" not in stored
        assert provider.calls[0]["tools"] == ["read_file", "edit_file", "shell"]
        assert provider.calls[0]["system"] == DEFAULT_SYSTEM
    finally:
        gate.set()
        server.shutdown()


def test_blank_text_does_not_append_a_user_message(tmp_path: Path):
    session_id = create_session(tmp_path)
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        with httpx.Client(trust_env=False) as client:
            base = f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages"
            blank = client.post(base, json={"text": " \n "})
            assert blank.status_code == 400
            assert blank.json() == {"error": "empty"}
            missing = client.post(base, json={})
            assert missing.status_code == 400
            assert missing.json() == {"error": "bad_request"}
            garbage = client.post(base, content=b"nope")
            assert garbage.status_code == 400
            assert garbage.json() == {"error": "bad_request"}
        assert (tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl").read_text(encoding="utf-8") == ""
    finally:
        server.shutdown()


def test_plan_flag_uses_the_plan_system_before_the_answer(tmp_path: Path):
    session_id = create_session(tmp_path)
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content='{"steps": ["look"]}'),
            ScriptedTurn(content="做完了"),
        ]
    )
    server = WebServer(WebSettings(workspace=tmp_path, plan=True), provider)
    server.start()
    try:
        with httpx.Client(trust_env=False, timeout=None) as client:
            response = client.post(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
                json={"text": "去做"},
            )
        assert response.status_code == 200
        assert '"status": "complete"' in response.text
        assert provider.calls[0]["system"] == 'Reply with JSON only, of the form {"steps": ["..."]}.'
        stored = (tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl").read_text(encoding="utf-8")
        assert "做完了" in stored
    finally:
        server.shutdown()


def test_page_mode_overrides_the_startup_flags(tmp_path: Path):
    session_id = create_session(tmp_path)
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content='{"steps": ["look"]}'),
            ScriptedTurn(content="做完了"),
        ]
    )
    server = WebServer(WebSettings(workspace=tmp_path, reflect=True), provider)
    server.start()
    try:
        with httpx.Client(trust_env=False, timeout=None) as client:
            response = client.post(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
                json={"text": "去做", "mode": "plan"},
            )
        assert response.status_code == 200
        assert provider.calls[0]["system"] == 'Reply with JSON only, of the form {"steps": ["..."]}.'
    finally:
        server.shutdown()


def test_react_mode_skips_plan_even_when_the_server_started_with_it(tmp_path: Path):
    session_id = create_session(tmp_path)
    provider = ScriptedProvider(turns=[ScriptedTurn(content="直接答")])
    server = WebServer(WebSettings(workspace=tmp_path, plan=True), provider)
    server.start()
    try:
        with httpx.Client(trust_env=False, timeout=None) as client:
            response = client.post(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
                json={"text": "你好", "mode": "react"},
            )
        assert response.status_code == 200
        assert provider.calls[0]["system"] == DEFAULT_SYSTEM
    finally:
        server.shutdown()


def test_reflect_mode_asks_for_a_critique_after_the_answer(tmp_path: Path):
    session_id = create_session(tmp_path)
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="初稿"),
            ScriptedTurn(content='{"ok": true}'),
        ]
    )
    server = WebServer(WebSettings(workspace=tmp_path), provider)
    server.start()
    try:
        with httpx.Client(trust_env=False, timeout=None) as client:
            response = client.post(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
                json={"text": "写一下", "mode": "reflect"},
            )
        assert response.status_code == 200
        assert provider.calls[0]["system"] == DEFAULT_SYSTEM
        assert provider.calls[1]["system"].startswith("Reply with JSON only")
    finally:
        server.shutdown()


def test_stop_ends_the_turn_and_keeps_the_partial_reply(tmp_path: Path):
    session_id = create_session(tmp_path)
    wrote = threading.Event()

    class HangAfterADelta:
        async def stream(self, *, system: str, messages: list, tools: list):
            yield ProviderEvent(kind="text_delta", text="写到一半")
            wrote.set()
            await asyncio.Event().wait()

    server = WebServer(WebSettings(workspace=tmp_path), HangAfterADelta())
    server.start()
    holder: dict = {}

    def post() -> None:
        with httpx.Client(trust_env=False, timeout=None) as client:
            holder["response"] = client.post(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
                json={"text": "开始", "mode": "react"},
            )

    worker = threading.Thread(target=post)
    worker.start()
    try:
        with httpx.Client(trust_env=False, timeout=5) as client:
            base = f"http://127.0.0.1:{server.port}"
            assert wrote.wait(5)
            stopped = client.post(f"{base}/api/sessions/{session_id}/stop")
            assert stopped.json() == {"stopped": True}
        worker.join(5)
        assert not worker.is_alive()
        assert '"status": "stopped"' in holder["response"].text
        stored = (tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl").read_text(
            encoding="utf-8"
        )
        assert "写到一半" in stored
        with httpx.Client(trust_env=False, timeout=5) as client:
            listed = client.get(f"http://127.0.0.1:{server.port}/api/sessions")
        assert listed.json()["running_id"] is None
    finally:
        if worker.is_alive():
            server.request_stop(session_id)
            worker.join(2)
        server.shutdown()


def test_stop_when_idle_reports_false(tmp_path: Path):
    session_id = create_session(tmp_path)
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        with httpx.Client(trust_env=False) as client:
            response = client.post(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/stop"
            )
        assert response.status_code == 200
        assert response.json() == {"stopped": False}
    finally:
        server.shutdown()


def test_unknown_mode_is_a_bad_request(tmp_path: Path):
    session_id = create_session(tmp_path)
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        with httpx.Client(trust_env=False) as client:
            response = client.post(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
                json={"text": "你好", "mode": "other"},
            )
        assert response.status_code == 400
        assert response.json() == {"error": "bad_request"}
        stored = tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl"
        assert stored.read_text(encoding="utf-8") == ""
    finally:
        server.shutdown()


def test_disconnect_finishes_the_turn_and_blocks_a_second_send(tmp_path: Path):
    session_id = create_session(tmp_path)
    gate = threading.Event()

    class WaitInStream:
        async def stream(self, *, system: str, messages: list, tools: list):
            await asyncio.to_thread(gate.wait)
            yield ProviderEvent(kind="text_delta", text="仍会写完")

    server = WebServer(WebSettings(workspace=tmp_path), WaitInStream())
    server.start()
    base = f"http://127.0.0.1:{server.port}"

    def post_and_close() -> None:
        sock = socket.create_connection(("127.0.0.1", server.port))
        payload = b'{"text":"\xe7\xbb\xa7\xe7\xbb\xad"}'
        head = (
            f"POST /api/sessions/{session_id}/messages HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(head + payload)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        # 状态行是 “HTTP/1.0 200 OK”。linger 0 让 close 发 RST，后续写入才会失败。
        assert data.split(b"\r\n", 1)[0].endswith(b"200 OK")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.close()

    thread = threading.Thread(target=post_and_close, daemon=True)
    thread.start()
    try:
        thread.join(2)
        assert server.running_id == session_id
        with httpx.Client(trust_env=False) as client:
            busy = client.post(
                f"{base}/api/sessions/{session_id}/messages",
                json={"text": "再来"},
            )
            assert busy.status_code == 409
            assert busy.json() == {"error": "busy"}
            listed = client.get(f"{base}/api/sessions")
            assert listed.json()["running_id"] == session_id
            current = client.get(f"{base}/api/sessions/{session_id}")
            assert current.json()["messages"][0]["content"] == "继续"
        gate.set()
        deadline = time.time() + 2
        while server.running_id is not None and time.time() < deadline:
            time.sleep(0.01)
        assert server.running_id is None
        stored = (tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl").read_text(encoding="utf-8")
        assert "仍会写完" in stored
    finally:
        gate.set()
        server.shutdown()


def _skill_file(directory: Path, name: str, description: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{name.upper()}_BODY\n",
        encoding="utf-8",
    )


def test_each_session_keeps_its_own_skill(tmp_path: Path):
    skills = tmp_path / "skills"
    _skill_file(skills, "alpha", "first skill")
    _skill_file(skills, "beta", "second skill")
    (skills / "skip.txt").write_text("nope", encoding="utf-8")
    server = WebServer(
        WebSettings(workspace=tmp_path, skills_dir=skills), provider=object()
    )
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            listed = client.get(f"{base}/api/skills")
            assert listed.status_code == 200
            assert listed.json() == {
                "skills": [
                    {"name": "alpha", "description": "first skill"},
                    {"name": "beta", "description": "second skill"},
                ]
            }
            first = client.post(f"{base}/api/sessions").json()["id"]
            second = client.post(f"{base}/api/sessions").json()["id"]
            chosen = client.post(
                f"{base}/api/sessions/{first}/skill",
                json={"name": "beta"},
            )
            assert chosen.status_code == 200
            assert chosen.json() == {"id": first, "skill": "beta"}
            unknown = client.post(
                f"{base}/api/sessions/{first}/skill",
                json={"name": "missing"},
            )
            assert unknown.status_code == 400
            assert unknown.json() == {"error": "unknown_skill"}
            assert client.get(f"{base}/api/sessions/{first}").json()["skill"] == "beta"
            assert client.get(f"{base}/api/sessions/{second}").json()["skill"] is None
            cleared = client.post(
                f"{base}/api/sessions/{first}/skill",
                json={"name": None},
            )
            assert cleared.status_code == 200
            assert cleared.json()["skill"] is None
    finally:
        server.shutdown()


def test_turn_prompt_contains_only_the_selected_skill(tmp_path: Path):
    skills = tmp_path / "skills"
    _skill_file(skills, "alpha", "first skill")
    _skill_file(skills, "beta", "second skill")
    session_id = create_session(tmp_path)
    provider = ScriptedProvider(turns=[ScriptedTurn(content="好"), ScriptedTurn(content="好")])
    server = WebServer(
        WebSettings(workspace=tmp_path, skills_dir=skills), provider=provider
    )
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            bare = client.post(
                f"{base}/api/sessions/{session_id}/messages",
                json={"text": "先不选"},
            )
            assert bare.status_code == 200
            chosen = client.post(
                f"{base}/api/sessions/{session_id}/skill",
                json={"name": "alpha"},
            )
            assert chosen.status_code == 200
            used = client.post(
                f"{base}/api/sessions/{session_id}/messages",
                json={"text": "用 alpha"},
            )
            assert used.status_code == 200
        bare_call, used_call = provider.calls
        assert "alpha" not in bare_call["system"]
        assert "read_skill" not in bare_call["tools"]
        assert "- alpha: first skill" in used_call["system"]
        assert "beta" not in used_call["system"]
        assert "ALPHA_BODY" not in used_call["system"]
        assert "read_skill" in used_call["tools"]
    finally:
        server.shutdown()


def test_workdir_change_keeps_the_session_and_moves_tools(tmp_path: Path):
    home = tmp_path / "home"
    other = tmp_path / "other"
    home.mkdir()
    other.mkdir()
    (other / "nested").mkdir()
    (other / "notes.txt").write_text("x", encoding="utf-8")
    (home / ".vector").mkdir()
    (home / ".vector" / "MEMORY.md").write_text("HOME_MEMORY\n", encoding="utf-8")
    session_id = create_session(home)

    class Capture:
        def __init__(self) -> None:
            self.system = ""
            self.roots: list[Path] = []

        async def stream(self, *, system: str, messages: list, tools: list):
            self.system = system
            self.roots = [tool.root.resolve() for tool in tools if hasattr(tool, "root")]
            yield ProviderEvent(kind="text_delta", text="好")

    provider = Capture()
    server = WebServer(
        WebSettings(workspace=home, memory_path=home / ".vector" / "MEMORY.md"),
        provider=provider,
    )
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            current = client.get(f"{base}/api/workdir")
            assert current.json()["path"] == str(home.resolve())
            listing = client.get(f"{base}/api/dirs", params={"path": str(other)})
            assert listing.status_code == 200
            body = listing.json()
            assert body["path"] == str(other.resolve())
            assert body["parent"] == str(tmp_path.resolve())
            assert body["dirs"] == [{"name": "nested", "path": str((other / "nested").resolve())}]
            assert body["files"] == [{"name": "notes.txt", "path": str((other / "notes.txt").resolve())}]
            missing = client.post(f"{base}/api/workdir", json={"path": str(other / "notes.txt")})
            assert missing.status_code == 400
            assert missing.json() == {"error": "not_a_directory"}
            changed = client.post(f"{base}/api/workdir", json={"path": str(other)})
            assert changed.status_code == 200
            assert changed.json() == {"path": str(other.resolve())}
            listed = client.get(f"{base}/api/sessions").json()["sessions"]
            assert any(item["id"] == session_id for item in listed)
            sent = client.post(
                f"{base}/api/sessions/{session_id}/messages",
                json={"text": "在新目录里干活"},
            )
            assert sent.status_code == 200
        assert "HOME_MEMORY" in provider.system
        assert provider.roots
        assert all(root == other.resolve() for root in provider.roots)
    finally:
        server.shutdown()


def test_workdir_change_is_refused_while_a_turn_is_running(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    session_id = create_session(first)
    gate = threading.Event()

    class HoldAfterDelta:
        async def stream(self, *, system: str, messages: list, tools: list):
            yield ProviderEvent(kind="text_delta", text="好")
            await asyncio.to_thread(gate.wait)

    server = WebServer(WebSettings(workspace=first), provider=HoldAfterDelta())
    server.start()
    seen = threading.Event()

    def read() -> None:
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
            json={"text": "卡住"},
            timeout=None,
            trust_env=False,
        ) as response:
            assert response.status_code == 200
            for chunk in response.iter_text():
                if "好" in chunk:
                    seen.set()
                    break

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    assert seen.wait(2)
    try:
        with httpx.Client(trust_env=False) as client:
            refused = client.post(
                f"http://127.0.0.1:{server.port}/api/workdir",
                json={"path": str(second)},
            )
            assert refused.status_code == 409
            assert refused.json() == {"error": "busy"}
            assert client.get(f"http://127.0.0.1:{server.port}/api/workdir").json()["path"] == str(
                first.resolve()
            )
    finally:
        gate.set()
        thread.join(2)
        server.shutdown()


def test_delete_removes_the_session_and_its_skill(tmp_path: Path):
    skills = tmp_path / "skills"
    _skill_file(skills, "alpha", "first skill")
    server = WebServer(
        WebSettings(workspace=tmp_path, skills_dir=skills), provider=object()
    )
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            session_id = client.post(f"{base}/api/sessions").json()["id"]
            other = client.post(f"{base}/api/sessions").json()["id"]
            assert client.post(
                f"{base}/api/sessions/{session_id}/skill", json={"name": "alpha"}
            ).status_code == 200
            escaped = client.delete(f"{base}/api/sessions/%2e%2e%2fsecret")
            assert escaped.status_code == 400
            assert not (tmp_path / "secret").exists()
            missing = client.delete(f"{base}/api/sessions/{'a' * 32}")
            assert missing.status_code == 404
            deleted = client.delete(f"{base}/api/sessions/{session_id}")
            assert deleted.status_code == 200
            assert deleted.json() == {"deleted": True}
            assert client.get(f"{base}/api/sessions/{session_id}").status_code == 404
            directory = tmp_path / ".vector" / "sessions"
            assert not (directory / f"{session_id}.jsonl").exists()
            assert not (directory / f"{session_id}.skill").exists()
            listed = client.get(f"{base}/api/sessions").json()["sessions"]
            assert [item["id"] for item in listed] == [other]
    finally:
        server.shutdown()


def test_delete_is_refused_while_the_session_is_running(tmp_path: Path):
    session_id = create_session(tmp_path)
    gate = threading.Event()

    class HoldAfterDelta:
        async def stream(self, *, system: str, messages: list, tools: list):
            yield ProviderEvent(kind="text_delta", text="好")
            await asyncio.to_thread(gate.wait)

    server = WebServer(WebSettings(workspace=tmp_path), provider=HoldAfterDelta())
    server.start()
    seen = threading.Event()

    def read() -> None:
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{server.port}/api/sessions/{session_id}/messages",
            json={"text": "卡住"},
            timeout=None,
            trust_env=False,
        ) as response:
            assert response.status_code == 200
            for chunk in response.iter_text():
                if "好" in chunk:
                    seen.set()
                    break

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    assert seen.wait(2)
    try:
        with httpx.Client(trust_env=False) as client:
            refused = client.delete(
                f"http://127.0.0.1:{server.port}/api/sessions/{session_id}"
            )
            assert refused.status_code == 409
            assert refused.json() == {"error": "busy"}
            assert (
                tmp_path / ".vector" / "sessions" / f"{session_id}.jsonl"
            ).is_file()
    finally:
        gate.set()
        thread.join(2)
        server.shutdown()


def test_user_text_and_reply_each_record_when_they_were_written(tmp_path: Path):
    session_id = create_session(tmp_path)
    provider = ScriptedProvider(turns=[ScriptedTurn(content="返回的文字")])
    server = WebServer(WebSettings(workspace=tmp_path), provider=provider)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        before = time.time()
        with httpx.Client(trust_env=False) as client:
            sent = client.post(
                f"{base}/api/sessions/{session_id}/messages",
                json={"text": "用户的文字"},
            )
            assert sent.status_code == 200
            after = time.time()
            messages = client.get(f"{base}/api/sessions/{session_id}").json()["messages"]
        user = messages[0]
        reply = messages[-1]
        assert user["role"] == "user" and user["content"] == "用户的文字"
        assert reply["role"] == "assistant" and reply["content"] == "返回的文字"
        assert before <= user["created_at"] <= reply["created_at"] <= after
    finally:
        server.shutdown()


def test_a_turn_records_when_it_started_and_how_long_it_took(tmp_path: Path):
    session_id = create_session(tmp_path)
    provider = ScriptedProvider(turns=[ScriptedTurn(content="好")])
    server = WebServer(WebSettings(workspace=tmp_path), provider=provider)
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        before = time.time()
        with httpx.Client(trust_env=False) as client:
            sent = client.post(
                f"{base}/api/sessions/{session_id}/messages",
                json={"text": "开始"},
            )
            assert sent.status_code == 200
            after = time.time()
            listed = client.get(f"{base}/api/sessions").json()["sessions"]
            body = client.get(f"{base}/api/sessions/{session_id}").json()
        assert len(listed) == 1
        started = listed[0]["started_at"]
        duration = listed[0]["duration_ms"]
        assert isinstance(started, float)
        assert before <= started <= after
        assert isinstance(duration, int) and duration >= 0
        assert body["started_at"] == started
        assert body["duration_ms"] == duration
    finally:
        server.shutdown()


def test_file_preview_and_image_inline(tmp_path: Path):
    notes = tmp_path / "notes.txt"
    notes.write_text("你好", encoding="utf-8")
    image = tmp_path / "pic.png"
    image.write_bytes(b"\x89PNG\r\n")
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            text = client.get(f"{base}/api/file", params={"path": str(notes)})
            assert text.status_code == 200
            assert text.json()["kind"] == "text"
            assert text.json()["text"] == "你好"
            meta = client.get(f"{base}/api/file", params={"path": str(image)})
            assert meta.json()["kind"] == "image"
            assert meta.json()["media_type"] == "image/png"
            inline = client.get(f"{base}/api/file/bytes", params={"path": str(image), "inline": "1"})
            assert inline.status_code == 200
            assert inline.headers["content-type"].startswith("image/png")
            assert inline.content == b"\x89PNG\r\n"
            assert "attachment" not in inline.headers.get("content-disposition", "")
    finally:
        server.shutdown()


def test_oversize_image_downloads_but_does_not_inline(tmp_path: Path):
    image = tmp_path / "big.png"
    image.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            meta = client.get(f"{base}/api/file", params={"path": str(image)})
            assert meta.json()["kind"] == "too_large"
            inline = client.get(f"{base}/api/file/bytes", params={"path": str(image), "inline": "1"})
            assert inline.status_code == 413
            assert inline.json() == {"error": "too_large"}
            saved = client.get(f"{base}/api/file/bytes", params={"path": str(image)})
            assert saved.status_code == 200
            assert saved.content == b"x" * (2 * 1024 * 1024 + 1)
            assert "attachment" in saved.headers["content-disposition"].lower()
    finally:
        server.shutdown()


def test_directory_and_other_file_are_not_preview_bytes(tmp_path: Path):
    (tmp_path / "data.bin").write_bytes(b"\x00\x01")
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            folder = client.get(f"{base}/api/file", params={"path": str(tmp_path)})
            assert folder.status_code == 400
            assert folder.json() == {"error": "not_a_file"}
            other = client.get(f"{base}/api/file", params={"path": str(tmp_path / "data.bin")})
            assert other.json()["kind"] == "unsupported"
            missing = client.get(f"{base}/api/file", params={"path": str(tmp_path / "nope.txt")})
            assert missing.status_code == 404
    finally:
        server.shutdown()


def test_rename_rejects_unsafe_names_and_moves_a_file(tmp_path: Path):
    source = tmp_path / "old.txt"
    source.write_text("x", encoding="utf-8")
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            for name in ("../x", "a/b", "a\\b", "", ".", ".."):
                rejected = client.post(f"{base}/api/file/rename", json={"path": str(source), "name": name})
                assert rejected.status_code == 400
                assert rejected.json() == {"error": "bad_name"}
            assert source.is_file()
            moved = client.post(f"{base}/api/file/rename", json={"path": str(source), "name": "new.txt"})
            assert moved.status_code == 200
            assert moved.json()["name"] == "new.txt"
            assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "x"
            nested = tmp_path / "nested"
            nested.mkdir()
            renamed_dir = client.post(f"{base}/api/file/rename", json={"path": str(nested), "name": "moved"})
            assert renamed_dir.status_code == 200
            assert (tmp_path / "moved").is_dir()
            again = client.post(
                f"{base}/api/file/rename",
                json={"path": str(tmp_path / "new.txt"), "name": "new.txt"},
            )
            assert again.status_code == 409
    finally:
        server.shutdown()


def test_delete_tree_symlink_and_root(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "inside.txt").write_text("x", encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")
    link = tmp_path / "link"
    link_ready = True
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        link_ready = False
    server = WebServer(WebSettings(workspace=tmp_path), provider=object())
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with httpx.Client(trust_env=False) as client:
            if link_ready:
                removed_link = client.request("DELETE", f"{base}/api/file", json={"path": str(link)})
                assert removed_link.status_code == 200
                assert not link.exists()
                assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
            removed = client.request("DELETE", f"{base}/api/file", json={"path": str(folder)})
            assert removed.status_code == 200
            assert not folder.exists()
            root = client.request("DELETE", f"{base}/api/file", json={"path": str(Path(tmp_path.anchor))})
            assert root.status_code == 400
            assert root.json() == {"error": "bad_path"}
            assert Path(tmp_path.anchor).exists()
    finally:
        server.shutdown()
