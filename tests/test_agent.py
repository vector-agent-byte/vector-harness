from __future__ import annotations

from dataclasses import dataclass, field

from vector_harness import Calculator, ProviderError, VectorHarness
from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness.types import ToolCall


def test_runner_starts_as_the_loop():
    agent = VectorHarness(name="AI助手", llm=object(), system_prompt="sys")

    assert agent.runner is agent.loop


def test_run_returns_text_and_keeps_history():
    provider = ScriptedProvider(turns=[ScriptedTurn(content="我是助手")])
    agent = VectorHarness(
        name="AI助手",
        llm=provider,
        system_prompt="你是一个有用的AI助手",
    )

    response = agent.run("你好！请介绍一下自己")

    assert response == "我是助手"
    assert agent.name == "AI助手"
    history = agent.get_history()
    assert [message.role for message in history] == ["user", "assistant"]
    assert history[0].content == "你好！请介绍一下自己"
    assert history[1].content == "我是助手"
    assert provider.calls[0]["system"] == "你是一个有用的AI助手"
    assert provider.calls[0]["tools"] == []


def test_constructor_tools_are_copied_and_add_tool_appends():
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="calculator", arguments={"expression": "2 + 3 * 4"})
                ]
            ),
            ScriptedTurn(content="14"),
        ]
    )
    tools = [Calculator()]
    agent = VectorHarness(
        name="AI助手",
        llm=provider,
        system_prompt="算一下",
        tools=tools,
    )
    tools.clear()
    agent.add_tool(Calculator())

    response = agent.run("请帮我计算 2 + 3 * 4")

    assert response == "14"
    assert provider.calls[0]["tools"] == ["calculator", "calculator"]


def test_add_tool_is_available_on_the_next_run():
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ToolCall(id="1", name="calculator", arguments={"expression": "2 + 3 * 4"})
                ]
            ),
            ScriptedTurn(content="14"),
        ]
    )
    agent = VectorHarness(name="AI助手", llm=provider, system_prompt="算一下")
    agent.add_tool(Calculator())

    response = agent.run("请帮我计算 2 + 3 * 4")

    assert response == "14"
    assert provider.calls[0]["tools"] == ["calculator"]
    roles = [message.role for message in agent.get_history()]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert agent.get_history()[2].content == "14"


def test_second_run_appends_to_the_same_history():
    provider = ScriptedProvider(
        turns=[ScriptedTurn(content="第一句"), ScriptedTurn(content="第二句")]
    )
    agent = VectorHarness(name="AI助手", llm=provider, system_prompt="sys")

    agent.run("第一问")
    agent.run("第二问")

    assert len(agent.get_history()) == 4
    assert [message.content for message in agent.get_history()] == [
        "第一问",
        "第一句",
        "第二问",
        "第二句",
    ]


def test_run_raises_when_the_model_fails():
    class FailingProvider:
        async def stream(self, *, system: str, messages: list, tools: list):
            from vector_harness.types import ProviderError as Boom

            raise Boom("upstream down")
            yield  # pragma: no cover

    agent = VectorHarness(name="AI助手", llm=FailingProvider(), system_prompt="sys")

    try:
        agent.run("你好")
    except ProviderError as exc:
        assert str(exc) == "upstream down"
    else:
        raise AssertionError("expected ProviderError")


def test_calculator_evaluates_arithmetic():
    import asyncio

    tool = Calculator()
    assert asyncio.run(tool.execute({"expression": "2 + 3 * 4"})) == "14"
    assert asyncio.run(tool.execute({"expression": "(2 + 3) * 4"})) == "20"
    rejected = asyncio.run(tool.execute({"expression": "__import__('os').system('echo hi')"}))
    assert rejected.startswith("Error:")


@dataclass
class CountingReadTool:
    name: str = "read_file"
    description: str = "Reads a file"
    parameters: dict = field(default_factory=dict)
    calls: int = 0

    async def execute(self, arguments: dict) -> str:
        self.calls += 1
        return "contents"


@dataclass
class CountingHook:
    calls: int = 0

    async def before_execute(self, call, messages):
        self.calls += 1
        return None


def test_harness_tool_hooks_default_empty():
    agent = VectorHarness(name="AI助手", llm=object(), system_prompt="sys")
    assert agent.loop.tool_hooks == []


def test_harness_shares_tool_hooks_with_delegate():
    hooks: list = []
    agent = VectorHarness(
        name="AI助手",
        llm=object(),
        system_prompt="sys",
        tool_hooks=hooks,
        subagents=True,
    )
    delegate = next(tool for tool in agent.loop.tools if tool.name == "delegate")
    assert delegate.tool_hooks is agent.loop.tool_hooks
    assert delegate.tool_hooks is hooks


def test_plan_runs_tool_hooks_on_the_same_loop():
    hook = CountingHook()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content='{"steps": ["read"]}'),
            ScriptedTurn(
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "x"})]
            ),
            ScriptedTurn(content="done"),
        ]
    )
    agent = VectorHarness(
        name="AI助手",
        llm=provider,
        system_prompt="sys",
        tools=[CountingReadTool()],
        tool_hooks=[hook],
        plan=True,
    )

    assert agent.run("read") == "done"
    assert hook.calls == 1


def test_reflect_runs_tool_hooks_on_the_same_loop():
    hook = CountingHook()
    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "x"})]
            ),
            ScriptedTurn(content="done"),
            ScriptedTurn(content='{"ok": true}'),
        ]
    )
    agent = VectorHarness(
        name="AI助手",
        llm=provider,
        system_prompt="sys",
        tools=[CountingReadTool()],
        tool_hooks=[hook],
        reflect=True,
    )

    assert agent.run("read") == "done"
    assert hook.calls == 1


def test_constructor_loop_on_event_is_used_by_plan_and_loop():
    seen = []

    def record(event):
        seen.append(event)

    provider = ScriptedProvider(
        turns=[
            ScriptedTurn(content='{"steps": ["read"]}'),
            ScriptedTurn(content="done"),
        ]
    )
    agent = VectorHarness(
        name="AI助手",
        llm=provider,
        system_prompt="sys",
        loop_on_event=record,
        plan=True,
    )

    assert agent.loop.on_event is record
    assert agent.run("go") == "done"
    texts = [event.text for event in seen if event.kind == "text_delta"]
    assert '{"steps": ["read"]}' in texts
    assert "done" in texts
