import asyncio
from dataclasses import dataclass, field

import pytest

from vector_harness.core.dispatch import ToolDispatcher, current_tool_call_id
from vector_harness.core.loop import Loop
from vector_harness.core.session import Session
from vector_harness.patterns.subagent import attach_delegate, delegate_tool
from vector_harness.types import Message, ProviderEvent, ToolCall, ToolHookResult
from vector_harness.web.children import ChildTrace, read_children
from vector_harness.web.http import event_payload


@dataclass
class ParallelTool:
    name: str = "delegate"
    description: str = "test"
    parameters: dict = field(default_factory=dict)
    max_concurrency: int = 2
    active: int = 0
    peak: int = 0
    started: list = field(default_factory=list)
    cancelled: list = field(default_factory=list)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute(self, arguments):
        task = arguments["task"]
        self.started.append((task, current_tool_call_id.get()))
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == self.max_concurrency:
            self.ready.set()
        try:
            await self.release.wait()
            if task == "fail":
                raise ValueError("child failed")
            return task
        except asyncio.CancelledError:
            self.cancelled.append(task)
            raise
        finally:
            self.active -= 1


def calls(*tasks):
    return [ToolCall(id=f"call-{index}", name="delegate", arguments={"task": task}) for index, task in enumerate(tasks)]


def test_parallel_dispatch_bounds_concurrency_and_isolates_errors():
    async def scenario():
        tool = ParallelTool()
        session = Session.in_memory()
        events = []
        dispatcher = ToolDispatcher(session, [tool], [], events.append)
        task = asyncio.create_task(dispatcher.dispatch(calls("first", "fail", "third", "fourth", "fifth")))
        await asyncio.wait_for(tool.ready.wait(), 2)
        assert len(tool.started) == 2
        assert not task.done()
        tool.release.set()
        await asyncio.wait_for(task, 2)
        assert tool.peak == 2
        assert tool.active == 0
        assert len(session.load()) == 5
        results = {message.tool_call_id: message for message in session.load()}
        assert results["call-1"].is_error
        assert results["call-4"].content == "fifth"
        assert tool.started == [(value, f"call-{index}") for index, value in enumerate(["first", "fail", "third", "fourth", "fifth"])]
        assert len([event for event in events if event.kind == "tool_result"]) == 5
        assert current_tool_call_id.get() == ""

    asyncio.run(scenario())


def test_parallel_dispatch_cancel_joins_children_and_does_not_start_queue():
    async def scenario():
        tool = ParallelTool()
        task = asyncio.create_task(ToolDispatcher(Session.in_memory(), [tool], []).dispatch(calls("first", "second", "queued")))
        await asyncio.wait_for(tool.ready.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert tool.active == 0
        assert sorted(tool.cancelled) == ["first", "second"]
        assert len(tool.started) == 2

    asyncio.run(scenario())


def test_normal_tool_is_a_barrier_between_parallel_groups():
    async def scenario():
        order = []
        parallel = ParallelTool()
        parallel.release.set()

        class Barrier:
            name = "barrier"
            description = "test"
            parameters = {}

            async def execute(self, arguments):
                assert parallel.active == 0
                order.append(len(parallel.started))
                return "ok"

        batch = calls("first", "second", "third", "fourth")
        batch.insert(2, ToolCall(id="barrier", name="barrier", arguments={}))
        await ToolDispatcher(Session.in_memory(), [parallel, Barrier()], []).dispatch(batch)
        assert order == [2]
        assert len(parallel.started) == 4

    asyncio.run(scenario())


def test_parallel_hooks_rewrite_and_reject_before_launch():
    async def scenario():
        tool = ParallelTool()
        tool.release.set()
        batch = calls("rewrite", "deny", "ok")
        session = Session.in_memory()
        session.append(Message(role="assistant", content="", tool_calls=batch))
        events = []

        class Hook:
            async def before_execute(self, call, messages):
                if call.arguments["task"] == "deny":
                    return ToolHookResult(deny="denied")
                if call.arguments["task"] == "rewrite":
                    return ToolHookResult(arguments={"task": "rewritten"})

        await ToolDispatcher(session, [tool], [Hook()], events.append).dispatch(batch)
        assert tool.started == [("rewritten", "call-0"), ("ok", "call-2")]
        assert session.load()[0].tool_calls[0].arguments == {"task": "rewritten"}
        assert any(event.kind == "tool_result" and event.tool_call_id == "call-1" and event.name == "error" for event in events)

    asyncio.run(scenario())


def test_real_parallel_children_keep_event_identity_and_persist_status(tmp_path):
    async def scenario():
        both_started = asyncio.Event()
        started = []

        class Provider:
            async def stream(self, *, system, messages, tools):
                if any(tool.name == "delegate" for tool in tools):
                    if messages[-1].role == "tool":
                        yield ProviderEvent(kind="text_delta", text="parent done")
                    else:
                        for call in calls("first", "second"):
                            yield ProviderEvent(kind="tool_call_end", name=call.name, tool_call_id=call.id, arguments=call.arguments)
                    return
                task = messages[0].content
                if messages[-1].role == "tool":
                    yield ProviderEvent(kind="text_delta", text=f"result {task}")
                    return
                started.append(task)
                yield ProviderEvent(kind="thinking_delta", text=f"thinking {task}")
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), 2)
                yield ProviderEvent(kind="tool_call_end", name="echo", tool_call_id=f"nested-{task}", arguments={"text": task})

        class Echo:
            name = "echo"
            description = "test"
            parameters = {}

            async def execute(self, arguments):
                await asyncio.sleep(0)
                return arguments["text"]

        provider = Provider()
        trace = ChildTrace(tmp_path / "session.jsonl")
        events = []

        def on_event(event):
            events.append(event)
            trace.record(event)

        loop = Loop(provider=provider, tools=[Echo()], session=Session.in_memory(), system="test", on_event=on_event)
        attach_delegate(loop, provider=provider, max_steps=5)
        result = await loop.run("go")
        assert result.text == "parent done"
        assert started == ["first", "second"]
        children = read_children(tmp_path / "session.jsonl")
        for index, task in enumerate(started):
            child = children[f"call-{index}"]
            assert child["thinking"] == f"thinking {task}"
            assert child["text"] == f"result {task}"
            assert child["status"] == "complete"
            assert child["tools"] == [{"name": "echo", "args": {"text": task}}]
        child_events = [event for event in events if event.origin == "child"]
        assert all(event.parent_tool_call_id in {"call-0", "call-1"} for event in child_events)
        nested_events = [event for event in child_events if event.tool_call_id.startswith("nested-")]
        assert {event.tool_call_id for event in nested_events} == {"nested-first", "nested-second"}
        assert all(event.parent_tool_call_id == ("call-0" if event.tool_call_id == "nested-first" else "call-1") for event in nested_events)
        assert event_payload(child_events[0])["parent_tool_call_id"] == child_events[0].parent_tool_call_id

    asyncio.run(scenario())


def test_delegate_concurrency_defaults_and_validation():
    assert delegate_tool(provider=object(), tools=[], system="test").max_concurrency == 4
    with pytest.raises(ValueError, match="positive"):
        delegate_tool(provider=object(), tools=[], system="test", max_concurrency=0)
