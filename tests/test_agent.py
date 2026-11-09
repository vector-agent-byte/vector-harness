from __future__ import annotations

from vector_harness import Calculator, ProviderError, SimpleAgent
from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness.types import ToolCall


def test_run_returns_text_and_keeps_history():
    provider = ScriptedProvider(turns=[ScriptedTurn(content="我是助手")])
    agent = SimpleAgent(
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
    agent = SimpleAgent(name="AI助手", llm=provider, system_prompt="算一下")
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
    agent = SimpleAgent(name="AI助手", llm=provider, system_prompt="sys")

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

    agent = SimpleAgent(name="AI助手", llm=FailingProvider(), system_prompt="sys")

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
