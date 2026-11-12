from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from vector_harness.web_server import WebServer, WebSettings


def _drop_loaded_web_modules() -> None:
    """网页测试会连带导入 cli。卸掉后，包入口测试才看得到真实的导入边界。"""
    for name in list(sys.modules):
        if name in {
            "vector_harness.web",
            "vector_harness.web_server",
            "vector_harness.web_http",
            "vector_harness.web_files",
            "vector_harness.web_runs",
            "vector_harness.web_sessions",
            "vector_harness.bootstrap",
            "vector_harness.cli",
            "vector_harness.assembly",
        } or name == "vector_harness.patterns" or name.startswith(
            "vector_harness.patterns."
        ):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _drop_web_modules():
    yield
    _drop_loaded_web_modules()


def test_main_binds_loopback_on_the_default_port(tmp_path: Path):
    from vector_harness.web import main

    seen: dict = {}

    class Fake:
        def __init__(self, settings: WebSettings, provider: object) -> None:
            seen["settings"] = settings
            seen["provider"] = provider

        def serve_forever(self, host: str, port: int) -> None:
            seen["host"] = host
            seen["port"] = port

    code = main(
        ["--workspace", str(tmp_path), "--plan", "--memory", "--max-steps", "3"],
        provider=object(),
        server_factory=Fake,
    )
    assert code == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8787
    assert seen["settings"].plan is True
    assert seen["settings"].max_steps == 3
    assert seen["settings"].workspace == tmp_path
    assert seen["settings"].memory_path == tmp_path / ".vector" / "MEMORY.md"
    assert seen["settings"].dist_dir == Path.cwd() / "web" / "dist"


def test_missing_api_key_exits_before_bind(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    from vector_harness.web import main

    called = False

    class Fake:
        def __init__(self, settings: WebSettings, provider: object) -> None:
            nonlocal called
            called = True

        def serve_forever(self, host: str, port: int) -> None:
            pass

    code = main(
        ["--workspace", str(tmp_path)],
        environ={},
        config_file=tmp_path / "missing.toml",
        server_factory=Fake,
    )
    assert code == 1
    assert called is False
    assert "VECTOR_API_KEY is not set" in capsys.readouterr().err


def test_missing_workspace_exits_before_bind(tmp_path: Path):
    from vector_harness.web import main

    missing = tmp_path / "nope"
    called = False

    class Fake:
        def __init__(self, settings: WebSettings, provider: object) -> None:
            nonlocal called
            called = True

        def serve_forever(self, host: str, port: int) -> None:
            pass

    code = main(["--workspace", str(missing)], provider=object(), server_factory=Fake)
    assert code == 1
    assert called is False


def test_missing_skills_directory_uses_the_cli_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    from vector_harness.web import main

    code = main(
        ["--workspace", str(tmp_path), "--skills", str(tmp_path / "missing")],
        provider=object(),
        server_factory=lambda settings, provider: None,
    )
    assert code == 1
    assert capsys.readouterr().err.strip() == "skills directory not found"


def test_host_flag_is_rejected():
    from vector_harness.web import main

    with pytest.raises(SystemExit) as caught:
        main(["--host", "0.0.0.0", "--workspace", "."], provider=object())
    assert caught.value.code == 2


def test_open_failure_still_serves(tmp_path: Path):
    from vector_harness.web import main

    seen: dict = {}

    class Fake:
        def __init__(self, settings: WebSettings, provider: object) -> None:
            pass

        def serve_forever(self, host: str, port: int) -> None:
            seen["served"] = True

    def opener(url: str) -> None:
        seen["url"] = url
        raise OSError("no desktop")

    code = main(
        ["--workspace", str(tmp_path), "--open", "--port", "8791"],
        provider=object(),
        opener=opener,
        server_factory=Fake,
    )
    assert code == 0
    assert seen["url"] == "http://127.0.0.1:8791/"
    assert seen["served"] is True


def test_open_does_not_run_when_the_port_is_taken(tmp_path: Path):
    from vector_harness.web import main

    holder = WebServer(WebSettings(workspace=tmp_path), provider=object())
    holder.start()
    opened: list[str] = []

    def opener(url: str) -> None:
        opened.append(url)

    try:
        code = main(
            ["--workspace", str(tmp_path), "--open", "--port", str(holder.port)],
            provider=object(),
            opener=opener,
        )
        assert code == 1
        assert opened == []
    finally:
        holder.shutdown()


def test_taken_port_returns_1(tmp_path: Path):
    from vector_harness.web import main

    holder = WebServer(WebSettings(workspace=tmp_path), provider=object())
    holder.start()
    try:
        code = main(
            ["--workspace", str(tmp_path), "--port", str(holder.port)],
            provider=object(),
        )
        assert code == 1
    finally:
        holder.shutdown()


def test_open_connects_after_the_socket_is_listening(tmp_path: Path):
    from vector_harness.web import main
    from vector_harness.web_server import WebServer

    created: list[WebServer] = []

    def factory(settings: object, provider: object) -> WebServer:
        server = WebServer(settings, provider)
        created.append(server)
        return server

    def opener(url: str) -> None:
        parts = urlsplit(url)
        assert parts.hostname == "127.0.0.1"
        assert parts.port
        with socket.create_connection((parts.hostname, parts.port), timeout=2):
            pass

        def stop() -> None:
            # serve_forever 进入循环后再停。提前 shutdown 会一直等那个循环。
            time.sleep(0.2)
            created[0].shutdown()

        threading.Thread(target=stop, daemon=True).start()

    code = main(
        ["--workspace", str(tmp_path), "--open", "--port", "0"],
        provider=object(),
        opener=opener,
        server_factory=factory,
    )
    assert code == 0
