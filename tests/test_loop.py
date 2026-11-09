from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Loop, Message, ProviderEvent, RunResult, Session, ToolCall
from vector_harness.types import ToolHook, ToolHookResult


@dataclass
class ReadFileTool:
    name: str = "read_file"
    description: str = "Reads a file"
    parameters: dict = field(default_factory=dict)

    async def execute(self, arguments: dict) -> str:
        return f"contents of {arguments.get('path')}"


@dataclass
class BoomTool:
    name: str = "boom"
    description: str = "Boom"
    parameters: dict = field(default_factory=dict)

    async def execute(self, arguments: dict) -> str:
        raise RuntimeError("boom")


@dataclass
class RoleRecorder:
    seen_roles: list[str] = field(default_factory=list)

    async def apply(self, messages: list[Message]) -> list[Message]:
        self.seen_roles.extend(m.role for m in messages)
        return [replace(m) for m in messages]


class SpySession(Session):
    replace_count: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        self.replace_count = 0

    def replace_all(self, messages: list[Message]) -> None:
        self.replace_count += 1
        super().replace_all(messages)


class BadArgsProvider:
    def __init__(self) -> None:
        self.stage = 0
        self.calls: list[dict] = []

    async def stream(self, *, system: str, messages: list[Message], tools: list):
        self.stage += 1
        self.calls.append({"system": system, "messages": messages, "tools": [t.name for t in tools]})
        if self.stage == 1:
            yield ProviderEvent(
                kind="tool_call_end",
                name="read_file",
                tool_call_id="1",
                arguments=["not-a-dict"],
            )
        else:
            yield ProviderEvent(kind="text_delta", text="ok")


class NoneArgsProvider:
    def __init__(self) -> None:
        self.stage = 0

    async def stream(self, *, system: str, messages: list[Message], tools: list):
        self.stage += 1
        if self.stage == 1:
            yield ProviderEvent(
                kind="tool_call_end",
                name="read_file",
                tool_call_id="1",
                arguments=None,
            )
        else:
            yield ProviderEvent(kind="text_delta", text="ok")


def run(coro):
    return asyncio.run(coro)


def test_loop_defaults():
    provider = ScriptedProvider(turns=[])
    loop = Loop(
        provider=provider,
        tools=[ReadFileTool()],
        session=Session.in_memory(),
        system="sys",
    )
    assert loop.max_steps == 25
    assert loop.system == "sys"
    assert loop.context_transforms == []
    assert loop.tool_hooks == []
    assert loop.tools == [ReadFileTool()]


def test_complete_tool_then_text():
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "x"})]),
            ScriptedTurn(content="done"),
        ]
    )
    tool = ReadFileTool()
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[tool], session=session, system="sys")
    result = run(loop.run("read"))

    assert result.status == "complete"
    assert result.text == "done"
    assert result.steps == 2
    assert result.session_path is None
    assert tool in loop.tools

    messages = session.load()
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert messages[1].tool_calls == [ToolCall(id="1", name="read_file", arguments={"path": "x"})]
    assert messages[2].content == "contents of x"
    assert messages[2].tool_call_id == "1"
    assert messages[2].is_error is False

    assert provider.calls[0]["system"] == "sys"
    assert provider.calls[0]["tools"] == ["read_file"]


def test_max_steps_one_and_tool_every_time():
    provider = ScriptedProvider(
        turns=[ScriptedTurn(tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "y"})])]
    )
    tool = ReadFileTool()
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[tool], session=session, system="sys", max_steps=1)
    result = run(loop.run("read"))

    assert result.status == "max_steps"
    assert result.text == ""
    assert result.steps == 1

    assert len(provider.calls) == 1
    messages = session.load()
    assert messages[-1].role == "tool"
    assert "y" in messages[-1].content


def test_thinking_is_not_stored_as_the_reply():
    provider = ScriptedProvider(
        turns=[ScriptedTurn(thinking="先看目录", content="hello.txt")]
    )
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    result = run(loop.run("list"))

    assert result.status == "complete"
    assert result.text == "hello.txt"
    assert session.load()[-1].content == "hello.txt"


def test_tool_execute_error_is_seen_by_model():
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(tool_calls=[ToolCall(id="1", name="boom", arguments={})]),
            ScriptedTurn(content="recovered"),
        ]
    )
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[BoomTool()], session=session, system="sys")
    result = run(loop.run("go"))

    assert result.status == "complete"
    assert result.text == "recovered"

    messages = session.load()
    tool_msg = messages[-2]
    assert tool_msg.role == "tool"
    assert "boom" in tool_msg.content
    assert tool_msg.is_error is True

    second_request = provider.calls[1]["messages"]
    assert second_request[-1]["role"] == "tool"
    assert "boom" in second_request[-1]["content"]
    assert second_request[-1]["is_error"] is True


def test_unknown_tool():
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(tool_calls=[ToolCall(id="1", name="missing", arguments={})]),
            ScriptedTurn(content="done"),
        ]
    )
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[], session=session, system="sys")
    result = run(loop.run("call"))

    assert result.status == "complete"
    assert result.text == "done"

    messages = session.load()
    tool_msg = messages[-2]
    assert tool_msg.role == "tool"
    assert tool_msg.content == "Error: Unknown tool: missing"
    assert tool_msg.is_error is True


def test_invalid_arguments():
    provider = BadArgsProvider()
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[ReadFileTool()], session=session, system="sys")
    result = run(loop.run("run"))

    assert result.status == "complete"
    assert result.text == "ok"

    messages = session.load()
    tool_msg = messages[-2]
    assert tool_msg.role == "tool"
    assert tool_msg.content == "Error: invalid arguments for read_file"
    assert tool_msg.is_error is True


def test_on_event_order_and_run_end():
    events: list[ProviderEvent] = []
    executed = {"before": False, "after": False}

    @dataclass
    class FlagTool:
        name: str = "flag"
        description: str = "flag"
        parameters: dict = field(default_factory=dict)

        async def execute(self, arguments: dict) -> str:
            executed["after"] = True
            return "ok"

    def on_event(event: ProviderEvent) -> None:
        events.append(event)
        if event.kind == "tool_call_start":
            assert executed["after"] is False

    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(tool_calls=[ToolCall(id="1", name="flag", arguments={})]),
            ScriptedTurn(content="done"),
        ]
    )
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[FlagTool()], session=session, system="sys", on_event=on_event)
    result = run(loop.run("go"))

    assert result.status == "complete"
    assert events[-1].kind == "run_end"
    start_index = next(i for i, e in enumerate(events) if e.kind == "tool_call_start")
    assert events[start_index].name == "flag"


def test_transform_does_not_see_system_and_spares_file_when_content_unchanged(tmp_path: Path):
    path = tmp_path / "session.jsonl"
    session = SpySession(path)
    transform = RoleRecorder()
    provider = ScriptedProvider(turns=[ScriptedTurn(content="hi")])
    loop = Loop(
        provider=provider,
        tools=[ReadFileTool()],
        session=session,
        system="system-prompt",
        context_transforms=[transform],
    )
    result = run(loop.run("hello"))

    assert result.status == "complete"
    assert "system" not in transform.seen_roles
    assert provider.calls[0]["system"] == "system-prompt"
    assert session.replace_count == 0

    raw = path.read_bytes()
    assert b"system-prompt" not in raw
    assert raw.count(b"\n") == 2


def test_transform_content_change_triggers_replace_all(tmp_path: Path):
    @dataclass
    class PrefixTool:
        async def apply(self, messages: list[Message]) -> list[Message]:
            return [replace(m, content="[" + m.content + "]") for m in messages]

    path = tmp_path / "session.jsonl"
    session = SpySession(path)
    provider = ScriptedProvider(turns=[ScriptedTurn(content="hi")])
    loop = Loop(
        provider=provider,
        tools=[ReadFileTool()],
        session=session,
        system="sys",
        context_transforms=[PrefixTool()],
    )
    result = run(loop.run("hello"))

    assert result.status == "complete"
    assert session.replace_count >= 1
    messages = session.load()
    assert messages[0].content == "[hello]"


def test_none_arguments_skip_execute_and_produce_error():
    provider = NoneArgsProvider()
    tool = ReadFileTool()
    calls = 0
    original_execute = tool.execute

    async def wrapped_execute(arguments: dict) -> str:
        nonlocal calls
        calls += 1
        return await original_execute(arguments)

    tool.execute = wrapped_execute
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[tool], session=session, system="sys")
    result = run(loop.run("go"))

    assert result.status == "complete"
    assert result.text == "ok"
    assert calls == 0

    messages = session.load()
    tool_msg = messages[-2]
    assert tool_msg.role == "tool"
    assert tool_msg.content == "Error: invalid arguments for read_file"
    assert tool_msg.is_error is True


def test_scripted_provider_runs_out_raises_assertion_error():
    provider = ScriptedProvider(turns=[])
    loop = Loop(provider=provider, tools=[], session=Session.in_memory(), system="sys", max_steps=1)

    with pytest.raises(AssertionError, match="no scripted turns left"):
        run(loop.run("go"))


@dataclass
class ArgumentRecordingTool:
    name: str = "read_file"
    description: str = "Reads a file"
    parameters: dict = field(default_factory=dict)
    seen: list = field(default_factory=list)

    async def execute(self, arguments: dict) -> str:
        self.seen.append(arguments)
        return "ok"


def _tool_then_text(*tool_calls: ToolCall, text: str = "done") -> ScriptedProvider:
    return ScriptedProvider(
        turns=[
            ScriptedTurn(tool_calls=list(tool_calls)),
            ScriptedTurn(content=text),
        ]
    )


def test_tool_hook_result_defaults_and_protocol():
    result = ToolHookResult()
    assert result.arguments is None
    assert result.deny is None

    class Hook:
        async def before_execute(self, call, messages):
            return None

    assert isinstance(Hook(), ToolHook)


@dataclass
class RecordingHook:
    result: ToolHookResult | None = None
    calls: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    error: Exception | None = None

    async def before_execute(self, call, messages):
        self.calls.append(call)
        self.messages.append(list(messages))
        if self.error is not None:
            raise self.error
        return self.result


def test_hook_none_allows_original_arguments():
    tool = ArgumentRecordingTool()
    hook = RecordingHook(result=None)
    provider = _tool_then_text(ToolCall(id="1", name="read_file", arguments={"path": "x"}))
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=Session.in_memory(),
        system="SECRET",
        tool_hooks=[hook],
    )

    result = run(loop.run("read"))

    assert result.status == "complete"
    assert tool.seen == [{"path": "x"}]
    assert [message.role for message in hook.messages[0]] == ["user", "assistant"]
    assert all("SECRET" not in message.content for message in hook.messages[0])


def test_empty_hook_result_allows():
    tool = ArgumentRecordingTool()
    hook = RecordingHook(result=ToolHookResult())
    provider = _tool_then_text(ToolCall(id="1", name="read_file", arguments={"path": "x"}))
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=Session.in_memory(),
        system="sys",
        tool_hooks=[hook],
    )

    run(loop.run("read"))

    assert tool.seen == [{"path": "x"}]


def test_hook_rewrites_arguments_for_the_next_hook():
    tool = ArgumentRecordingTool()
    first = RecordingHook(result=ToolHookResult(arguments={"path": "y"}))
    second = RecordingHook()
    provider = _tool_then_text(ToolCall(id="1", name="read_file", arguments={"path": "x"}))
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=session,
        system="sys",
        tool_hooks=[first, second],
    )

    run(loop.run("read"))

    assert second.calls[0].arguments == {"path": "y"}
    assert tool.seen == [{"path": "y"}]
    assistant = next(message for message in session.load() if message.tool_calls)
    assert assistant.tool_calls[0].arguments == {"path": "y"}


def test_hook_deny_skips_tool_and_later_hooks():
    tool = ArgumentRecordingTool()
    first = RecordingHook(result=ToolHookResult(deny="blocked"))
    second = RecordingHook()
    provider = _tool_then_text(
        ToolCall(id="1", name="read_file", arguments={"path": "x"}),
        text="done",
    )
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=session,
        system="sys",
        tool_hooks=[first, second],
    )

    result = run(loop.run("read"))

    assert result.status == "complete"
    assert result.text == "done"
    assert second.calls == []
    assert tool.seen == []
    tool_message = next(message for message in session.load() if message.role == "tool")
    assert tool_message.is_error is True
    assert tool_message.content == "blocked"


def test_hook_deny_after_rewrite_persists_arguments():
    tool = ArgumentRecordingTool()
    hook = RecordingHook(result=ToolHookResult(arguments={"path": "y"}, deny="blocked"))
    provider = _tool_then_text(ToolCall(id="1", name="read_file", arguments={"path": "x"}))
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=session,
        system="sys",
        tool_hooks=[hook],
    )

    run(loop.run("read"))

    assert tool.seen == []
    assistant = next(message for message in session.load() if message.tool_calls)
    assert assistant.tool_calls[0].arguments == {"path": "y"}
    tool_message = next(message for message in session.load() if message.role == "tool")
    assert tool_message.content == "blocked"


def test_hook_exception_is_a_failed_tool_message():
    tool = ArgumentRecordingTool()
    first = RecordingHook(error=RuntimeError("nope"))
    second = RecordingHook()
    provider = _tool_then_text(
        ToolCall(id="1", name="read_file", arguments={"path": "x"}),
        text="done",
    )
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=session,
        system="sys",
        tool_hooks=[first, second],
    )

    result = run(loop.run("read"))

    assert result.status == "complete"
    assert second.calls == []
    assert tool.seen == []
    tool_message = next(message for message in session.load() if message.role == "tool")
    assert tool_message.is_error is True
    assert tool_message.content == "nope"


def test_unknown_and_invalid_calls_skip_hooks():
    cases = [
        ToolCall(id="1", name="missing", arguments={"path": "x"}),
        ToolCall(id="1", name="read_file", arguments=None),
        ToolCall(id="1", name="read_file", arguments={"_invalid_json": "x"}),
    ]
    for call in cases:
        tool = ArgumentRecordingTool()
        hook = RecordingHook()
        provider = _tool_then_text(call)
        session = Session.in_memory()
        loop = Loop(
            provider=provider,
            tools=[tool],
            session=session,
            system="sys",
            tool_hooks=[hook],
        )
        run(loop.run("read"))
        assert hook.calls == []
        tool_message = next(message for message in session.load() if message.role == "tool")
        assert tool_message.is_error is True


def test_empty_deny_does_not_block():
    tool = ArgumentRecordingTool()
    hook = RecordingHook(result=ToolHookResult(deny=""))
    provider = _tool_then_text(ToolCall(id="1", name="read_file", arguments={"path": "x"}))
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=Session.in_memory(),
        system="sys",
        tool_hooks=[hook],
    )

    run(loop.run("read"))

    assert tool.seen == [{"path": "x"}]


def test_non_dict_rewrite_does_not_execute():
    tool = ArgumentRecordingTool()
    hook = RecordingHook(result=ToolHookResult(arguments=["nope"]))
    provider = _tool_then_text(ToolCall(id="1", name="read_file", arguments={"path": "x"}))
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=session,
        system="sys",
        tool_hooks=[hook],
    )

    run(loop.run("read"))

    assert tool.seen == []
    tool_message = next(message for message in session.load() if message.role == "tool")
    assert tool_message.content == "Error: invalid arguments for read_file"
    assistant = next(message for message in session.load() if message.tool_calls)
    assert assistant.tool_calls[0].arguments == {"path": "x"}


def test_rewrite_persists_in_file_session(tmp_path: Path):
    tool = ArgumentRecordingTool()
    hook = RecordingHook(result=ToolHookResult(arguments={"path": "y"}))
    path = tmp_path / "s.jsonl"
    provider = _tool_then_text(ToolCall(id="1", name="read_file", arguments={"path": "x"}))
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=Session(path=path),
        system="sys",
        tool_hooks=[hook],
    )

    run(loop.run("read"))

    assistant = next(message for message in Session(path=path).load() if message.tool_calls)
    assert assistant.tool_calls[0].arguments == {"path": "y"}


def test_denying_one_call_still_runs_the_next():
    tool = ArgumentRecordingTool()

    class DenyFirst:
        def __init__(self) -> None:
            self.messages: list = []

        async def before_execute(self, call, messages):
            self.messages.append(list(messages))
            if call.id == "1":
                return ToolHookResult(deny="blocked")
            return None

    hook = DenyFirst()
    provider = _tool_then_text(
        ToolCall(id="1", name="read_file", arguments={"path": "a"}),
        ToolCall(id="2", name="read_file", arguments={"path": "b"}),
    )
    session = Session.in_memory()
    loop = Loop(
        provider=provider,
        tools=[tool],
        session=session,
        system="sys",
        tool_hooks=[hook],
    )

    run(loop.run("read"))

    assert tool.seen == [{"path": "b"}]
    tool_messages = [message for message in session.load() if message.role == "tool"]
    assert tool_messages[0].tool_call_id == "1"
    assert tool_messages[0].is_error is True
    assert any(message.tool_call_id == "1" for message in hook.messages[1])
