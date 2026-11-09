from __future__ import annotations

import io
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness.types import ToolCall


@pytest.fixture(scope="module", autouse=True)
def _unload_patterns_after_module():
    yield
    for name in list(sys.modules):
        if (
            name == "vector_harness.patterns"
            or name.startswith("vector_harness.patterns.")
            or name == "vector_harness.cli"
        ):
            del sys.modules[name]


def _drop_patterns() -> None:
    for name in list(sys.modules):
        if name == "vector_harness.patterns" or name.startswith(
            "vector_harness.patterns."
        ):
            del sys.modules[name]


class RecordingProvider(ScriptedProvider):
    def __init__(self, turns: list[ScriptedTurn]) -> None:
        super().__init__(turns)
        self.seen_tools: list = []

    async def stream(self, *, system: str, messages: list, tools: list):
        self.seen_tools = list(tools)
        async for event in super().stream(
            system=system, messages=messages, tools=tools
        ):
            yield event


def test_package_import_does_not_load_patterns():
    _drop_patterns()
    from vector_harness import (
        EditFile,
        Loop,
        OpenAICompatibleProvider,
        ReadFile,
        Session,
        Shell,
    )

    import vector_harness

    assert Loop and Session and OpenAICompatibleProvider and ReadFile and EditFile and Shell
    assert vector_harness is not None
    assert "vector_harness.patterns" not in sys.modules


def test_build_agent_without_patterns_is_a_plain_loop(tmp_path: Path):
    from vector_harness.cli import DEFAULT_SYSTEM, build_agent
    from vector_harness.core.loop import Loop
    from vector_harness.core.session import Session

    workspace = tmp_path / "ws"
    workspace.mkdir()
    agent = build_agent(
        provider=ScriptedProvider(turns=[]),
        workspace=workspace,
        session=Session.in_memory(),
    )
    assert [tool.name for tool in agent.tools] == ["read_file", "edit_file", "shell"]
    assert agent.context_transforms == []
    assert agent.system == DEFAULT_SYSTEM
    assert type(agent) is Loop


def test_build_agent_wires_all_five_patterns(tmp_path: Path):
    from vector_harness.cli import build_agent
    from vector_harness.core.session import Session
    from vector_harness.patterns.plan import PlanThenExecute

    workspace = tmp_path / "ws"
    workspace.mkdir()
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "atlas.md").write_text(
        "---\nname: skillalpha\ndescription: recognizable skill\n---\nBODY\n",
        encoding="utf-8",
    )
    memory = tmp_path / "MEMORY.md"
    memory.write_text("memorybeta sentence\n", encoding="utf-8")
    agent = build_agent(
        provider=ScriptedProvider(turns=[]),
        workspace=workspace,
        session=Session.in_memory(),
        skills_dir=skills,
        memory_path=memory,
        compact=True,
        plan=True,
        subagents=True,
    )
    assert type(agent) is PlanThenExecute
    assert [tool.name for tool in agent.loop.tools] == [
        "read_file",
        "edit_file",
        "shell",
        "read_skill",
        "remember",
        "delegate",
    ]
    system = agent.loop.system
    assert system.index("skillalpha") < system.index("memorybeta sentence")
    assert agent.loop.context_transforms[0].max_chars == 80000
    assert agent.loop.context_transforms[0].keep_last == 8


def test_help_mentions_compaction_bounds_and_not_api_key():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "vector_harness.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    assert proc.returncode == 0
    assert "80000" in proc.stdout
    assert "8" in proc.stdout
    assert "api-key" not in proc.stdout


def test_merged_env_overrides_model_and_base_url_only():
    from vector_harness.cli import merged_env

    merged = merged_env(
        {"VECTOR_API_KEY": "k", "VECTOR_MODEL": "old"},
        model="new",
        base_url="http://example",
    )
    assert merged["VECTOR_MODEL"] == "new"
    assert merged["VECTOR_BASE_URL"] == "http://example"
    assert merged["VECTOR_API_KEY"] == "k"


def test_main_missing_secrets_reports_env_names(tmp_path: Path, capsys):
    from vector_harness.cli import main

    missing = tmp_path / "missing.toml"
    assert main(["do it"], environ={}, config_file=missing) == 1
    assert "VECTOR_API_KEY" in capsys.readouterr().err
    assert (
        main(
            ["do it"],
            environ={"VECTOR_API_KEY": "k", "VECTOR_BASE_URL": "http://example"},
            config_file=missing,
        )
        == 1
    )
    assert "VECTOR_MODEL" in capsys.readouterr().err


def _write_config(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_config_file_supplies_connection_settings(tmp_path: Path, monkeypatch):
    from vector_harness.cli import main

    config = _write_config(
        tmp_path / ".vector-harness" / "config.toml",
        'api_key = "file-key"\nbase_url = "http://example.test/v1"\nmodel = "file-model"\n',
    )
    seen: dict = {}

    def fake_from_env(env=None):
        seen.update(env or {})
        return ScriptedProvider(turns=[ScriptedTurn(content="ok")])

    monkeypatch.setattr(
        "vector_harness.cli.OpenAICompatibleProvider.from_env", fake_from_env
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    code = main(
        ["--workspace", str(workspace), "hi"],
        environ={},
        config_file=config,
    )
    assert code == 0
    assert seen["VECTOR_API_KEY"] == "file-key"
    assert seen["VECTOR_BASE_URL"] == "http://example.test/v1"
    assert seen["VECTOR_MODEL"] == "file-model"


def test_env_and_cli_override_config_file(tmp_path: Path, monkeypatch):
    from vector_harness.cli import main

    config = _write_config(
        tmp_path / ".config.toml",
        'api_key = "file-key"\nbase_url = "http://file.test/v1"\nmodel = "file-model"\n',
    )
    seen: dict = {}

    def fake_from_env(env=None):
        seen.update(env or {})
        return ScriptedProvider(turns=[ScriptedTurn(content="ok")])

    monkeypatch.setattr(
        "vector_harness.cli.OpenAICompatibleProvider.from_env", fake_from_env
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    code = main(
        ["--workspace", str(workspace), "--model", "cli-model", "hi"],
        environ={
            "VECTOR_API_KEY": "env-key",
            "VECTOR_BASE_URL": "http://env.test/v1",
            "VECTOR_MODEL": "env-model",
        },
        config_file=config,
    )
    assert code == 0
    assert seen["VECTOR_API_KEY"] == "env-key"
    assert seen["VECTOR_BASE_URL"] == "http://env.test/v1"
    assert seen["VECTOR_MODEL"] == "cli-model"


def test_main_runs_task_and_writes_session(tmp_path: Path, capsys):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider = ScriptedProvider(turns=[ScriptedTurn(content="MODEL_SAYS_FIX")])
    code = main(
        ["--workspace", str(workspace), "fix it"],
        environ={},
        provider=provider,
    )
    assert code == 0
    user_texts = [
        message["content"]
        for call in provider.calls
        for message in call["messages"]
        if message["role"] == "user"
    ]
    assert user_texts == ["fix it"]
    assert "MODEL_SAYS_FIX" in capsys.readouterr().out
    sessions = list((workspace / ".vector" / "sessions").glob("*.jsonl"))
    assert len(sessions) == 1


def test_memory_flag_without_path_uses_workspace_default(tmp_path: Path):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    enabled = RecordingProvider(turns=[ScriptedTurn(content="ok")])
    assert (
        main(
            ["--workspace", str(workspace), "note", "--memory"],
            environ={},
            provider=enabled,
        )
        == 0
    )
    names = [tool.name for tool in enabled.seen_tools]
    assert "remember" in names
    remember = next(tool for tool in enabled.seen_tools if tool.name == "remember")
    assert remember.path == workspace / ".vector" / "MEMORY.md"

    disabled = RecordingProvider(turns=[ScriptedTurn(content="ok")])
    assert (
        main(
            ["--workspace", str(workspace), "note"],
            environ={},
            provider=disabled,
        )
        == 0
    )
    assert "remember" not in [tool.name for tool in disabled.seen_tools]


def test_memory_flag_before_the_task_does_not_wait_for_stdin(tmp_path: Path):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider = RecordingProvider(turns=[ScriptedTurn(content="vector-harness")])
    code = main(
        ["--workspace", str(workspace), "--memory", "项目代号是什么"],
        environ={},
        provider=provider,
        stdin_lines=[],
    )
    assert code == 0
    user_texts = [
        message["content"]
        for call in provider.calls
        for message in call["messages"]
        if message["role"] == "user"
    ]
    assert user_texts == ["项目代号是什么"]
    remember = next(tool for tool in provider.seen_tools if tool.name == "remember")
    assert remember.path == workspace / ".vector" / "MEMORY.md"


def test_shell_command_is_printed_before_execute(tmp_path: Path, monkeypatch):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    monkeypatch.setattr(
        "vector_harness.cli._now", lambda: datetime(2026, 11, 9, 17, 1, 3)
    )

    seen: dict[str, str] = {}

    class ProbeShell:
        def __init__(self, root: Path, timeout: int = 120, max_output: int = 8000) -> None:
            self.root = root
            self.name = "shell"
            self.description = "Run a shell command inside the workspace."
            self.parameters = {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            }

        async def execute(self, arguments: dict) -> str:
            seen["before"] = buffer.getvalue()
            return "ok"

    monkeypatch.setattr("vector_harness.cli.Shell", ProbeShell)
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="shell", arguments={"command": "echo hi"})
                ]
            ),
            ScriptedTurn(content="done"),
        ]
    )
    code = main(
        ["--workspace", str(workspace), "run"],
        environ={},
        provider=provider,
    )
    assert code == 0
    assert seen["before"] == "17:01:03 [tool] shell        echo hi\n"


def test_color_paints_reply_and_shell_command(tmp_path: Path, monkeypatch):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    buffer = io.StringIO()
    monkeypatch.setenv("VECTOR_COLOR", "always")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(
        "vector_harness.cli._now", lambda: datetime(2026, 11, 9, 17, 1, 3)
    )
    monkeypatch.setattr(sys, "stdout", buffer)
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                content="hello",
                tool_calls=[
                    ToolCall(id="1", name="shell", arguments={"command": "echo hi"})
                ],
            ),
            ScriptedTurn(content="done"),
        ]
    )
    code = main(
        ["--workspace", str(workspace), "run"],
        environ={},
        provider=provider,
    )
    assert code == 0
    output = buffer.getvalue()
    assert "\033[36mhello" not in output
    assert (
        "\033[2m17:01:03\033[0m "
        "\033[1;35m[tool]\033[0m "
        "\033[1;36mshell       \033[0m "
        "\033[33mecho hi\033[0m\n"
    ) in output
    assert output.endswith("\ndone\n")


def test_read_file_is_printed_on_the_same_tool_column(tmp_path: Path, monkeypatch):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    monkeypatch.setattr(
        "vector_harness.cli._now", lambda: datetime(2026, 11, 9, 17, 1, 3)
    )
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="read_file", arguments={"path": "notes.txt"})
                ]
            ),
            ScriptedTurn(content="done"),
        ]
    )
    code = main(
        ["--workspace", str(workspace), "run"],
        environ={},
        provider=provider,
    )
    assert code == 0
    assert "17:01:03 [tool] read_file    notes.txt\n" in buffer.getvalue()


def test_thinking_is_printed_before_the_reply(tmp_path: Path, monkeypatch):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    monkeypatch.setattr(
        "vector_harness.cli._now", lambda: datetime(2026, 11, 9, 17, 1, 3)
    )
    provider = ScriptedProvider(
        turns=[ScriptedTurn(thinking="先看目录", content="hello.txt")]
    )
    code = main(
        ["--workspace", str(workspace), "run"],
        environ={},
        provider=provider,
    )
    assert code == 0
    assert buffer.getvalue() == "17:01:03 [think] 先看目录\nhello.txt\n"


def test_interactive_run_starts_before_the_next_line_is_read(tmp_path: Path, monkeypatch):
    from vector_harness.cli import main
    from vector_harness.core.loop import Loop

    workspace = tmp_path / "ws"
    workspace.mkdir()
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)

    class PullCounter:
        def __init__(self, items: list[str]) -> None:
            self.items = items
            self.pulled = 0

        def __iter__(self):
            return self

        def __next__(self) -> str:
            if self.pulled == 1:
                assert "REPLY_ONE" in buffer.getvalue()
            if self.pulled >= len(self.items):
                raise StopIteration
            item = self.items[self.pulled]
            self.pulled += 1
            return item

    lines = PullCounter(["first task", "later task", "/exit"])
    original = Loop.run

    async def wrapped(self, user_text: str):
        if user_text == "first task":
            assert lines.pulled == 1
        return await original(self, user_text)

    monkeypatch.setattr(Loop, "run", wrapped)
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content="REPLY_ONE"),
            ScriptedTurn(content="REPLY_TWO"),
        ]
    )
    code = main(
        ["--workspace", str(workspace)],
        environ={},
        provider=provider,
        stdin_lines=lines,
    )
    assert code == 0
    assert [call["messages"][-1]["content"] for call in provider.calls] == [
        "first task",
        "later task",
    ]
    assert all(
        "/exit" not in message["content"]
        for call in provider.calls
        for message in call["messages"]
    )


def test_plan_and_child_events_reach_the_same_callback(tmp_path: Path, monkeypatch):
    import asyncio

    from vector_harness.cli import build_agent
    from vector_harness.core.session import Session

    workspace = tmp_path / "ws"
    workspace.mkdir()
    seen: list = []
    saw_shell = False

    class ProbeShell:
        def __init__(self, root: Path, timeout: int = 120, max_output: int = 8000) -> None:
            self.root = root
            self.name = "shell"
            self.description = "Run a shell command inside the workspace."
            self.parameters = {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            }

        async def execute(self, arguments: dict) -> str:
            nonlocal saw_shell
            ends = [
                event
                for event in seen
                if event.kind == "tool_call_end" and event.name == "shell"
            ]
            assert ends
            assert ends[0].arguments["command"] == "echo hi"
            assert any(
                event.kind == "text_delta" and event.text == '{"steps":["run"]}'
                for event in seen
            )
            child_calls = [
                call
                for call in provider.calls
                if "shell" in call["tools"] and "delegate" not in call["tools"]
            ]
            assert child_calls
            saw_shell = True
            return "ok"

    monkeypatch.setattr("vector_harness.cli.Shell", ProbeShell)
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content='{"steps":["run"]}'),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(
                        id="d1",
                        name="delegate",
                        arguments={"task": "do shell"},
                    )
                ]
            ),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="s1", name="shell", arguments={"command": "echo hi"})
                ]
            ),
            ScriptedTurn(content="child-done"),
            ScriptedTurn(content="parent-done"),
        ]
    )
    agent = build_agent(
        provider=provider,
        workspace=workspace,
        session=Session.in_memory(),
        plan=True,
        subagents=True,
    )
    agent.loop.on_event = seen.append
    result = asyncio.run(agent.run("go"))
    assert result.status == "complete"
    assert saw_shell


def test_stdin_stops_at_exit_and_skips_the_rest(tmp_path: Path):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    provider = ScriptedProvider(turns=[ScriptedTurn(content="hi")])
    code = main(
        ["--workspace", str(workspace)],
        environ={},
        provider=provider,
        stdin_lines=["hello", "/exit", "after"],
    )
    assert code == 0
    user_texts = [
        message["content"]
        for call in provider.calls
        for message in call["messages"]
        if message["role"] == "user"
    ]
    assert user_texts == ["hello"]


def test_max_steps_returns_one(tmp_path: Path):
    from vector_harness.cli import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    call = ToolCall(id="1", name="read_file", arguments={"path": "missing.txt"})
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(tool_calls=[call]),
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="2", name="read_file", arguments={"path": "missing.txt"})
                ]
            ),
        ]
    )
    code = main(
        ["--workspace", str(workspace), "--max-steps", "1", "loop"],
        environ={},
        provider=provider,
    )
    assert code == 1
