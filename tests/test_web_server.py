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
            assert body.json() == {"id": session_id, "messages": []}
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
