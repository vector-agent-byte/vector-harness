from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from vector_harness import Loop, Message, OpenAICompatibleProvider, Session
from vector_harness.types import ProviderError


@dataclass
class ReadFileTool:
    name: str = "read_file"
    description: str = "Reads a file"
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }
    )

    async def execute(self, arguments: dict) -> str:
        return f"contents of {arguments.get('path')}"


class RecordedHandler:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses.pop(0)


def instant_sleep():
    calls: list[float] = []

    async def _sleep(delay):
        calls.append(delay)

    return _sleep, calls


def sse_response(*payloads: dict | str) -> httpx.Response:
    parts: list[str] = []
    for payload in payloads:
        if isinstance(payload, str):
            parts.append(f"data: {payload}\n\n")
        else:
            parts.append(f"data: {json.dumps(payload)}\n\n")
    parts.append("data: [DONE]\n\n")
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(parts).encode(),
    )


def error_response(status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": f"status {status}"}})


def make_provider(handler: RecordedHandler, **kwargs) -> tuple[OpenAICompatibleProvider, list[float]]:
    sleep, sleep_calls = instant_sleep()
    provider = OpenAICompatibleProvider(
        api_key=kwargs.get("api_key", "test-key"),
        base_url=kwargs.get("base_url", "http://example.test/v1/"),
        model=kwargs.get("model", "test-model"),
        sleep=sleep,
        transport=httpx.MockTransport(handler),
    )
    return provider, sleep_calls


def collect(provider: OpenAICompatibleProvider, **kwargs):
    system = kwargs.get("system", "sys")
    messages = kwargs.get("messages", [Message(role="user", content="hello")])
    tools = kwargs.get("tools", [ReadFileTool()])

    async def _collect():
        events = []
        async for event in provider.stream(system=system, messages=messages, tools=tools):
            events.append(event)
        return events

    return asyncio.run(_collect())


def test_from_env_missing_api_key_mentions_variable():
    with pytest.raises(ProviderError, match="VECTOR_API_KEY"):
        OpenAICompatibleProvider.from_env(
            env={"VECTOR_BASE_URL": "http://example.test", "VECTOR_MODEL": "m"}
        )


def test_from_env_missing_base_and_model_reports_api_key_first():
    with pytest.raises(ProviderError, match="VECTOR_API_KEY"):
        OpenAICompatibleProvider.from_env(env={})


def test_from_env_missing_base_url_mentions_variable():
    with pytest.raises(ProviderError, match="VECTOR_BASE_URL"):
        OpenAICompatibleProvider.from_env(
            env={"VECTOR_API_KEY": "k", "VECTOR_MODEL": "m"}
        )


def test_from_env_missing_model_mentions_variable():
    with pytest.raises(ProviderError, match="VECTOR_MODEL"):
        OpenAICompatibleProvider.from_env(
            env={"VECTOR_API_KEY": "k", "VECTOR_BASE_URL": "http://example.test"}
        )


def test_sse_assembles_text_and_tool_call_arguments():
    handler = RecordedHandler(
        [
            sse_response(
                {"choices": [{"index": 0, "delta": {"content": "hi"}}]},
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path":',
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '"a.txt"}'},
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        ]
    )
    provider, _ = make_provider(handler)
    events = collect(provider, system="be helpful", messages=[Message(role="user", content="read it")])

    text_events = [e for e in events if e.kind == "text_delta"]
    assert [e.text for e in text_events] == ["hi"]

    ends = [e for e in events if e.kind == "tool_call_end"]
    assert len(ends) == 1
    assert ends[0].name == "read_file"
    assert ends[0].tool_call_id == "call_1"
    assert ends[0].arguments == {"path": "a.txt"}

    assert len(handler.requests) == 1
    request = handler.requests[0]
    assert str(request.url) == "http://example.test/v1/chat/completions"
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "be helpful"}
    assert body["messages"][1]["role"] == "user"
    assert body["messages"][1]["content"] == "read it"
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Reads a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
    ]


def test_sse_merges_tool_calls_by_index():
    handler = RecordedHandler(
        [
            sse_response(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_a",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path":',
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 1,
                                        "id": "call_b",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path":',
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": '"a.txt"}'},
                                    }
                                ]
                            },
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 1,
                                        "function": {"arguments": '"b.txt"}'},
                                    }
                                ]
                            },
                        }
                    ]
                },
            )
        ]
    )
    provider, _ = make_provider(handler)
    events = collect(provider)
    ends = [e for e in events if e.kind == "tool_call_end"]
    assert [(e.tool_call_id, e.arguments) for e in ends] == [
        ("call_a", {"path": "a.txt"}),
        ("call_b", {"path": "b.txt"}),
    ]


def test_invalid_tool_argument_json():
    handler = RecordedHandler(
        [
            sse_response(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_bad",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": "{not json",
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                }
            )
        ]
    )
    provider, _ = make_provider(handler)
    events = collect(provider)
    ends = [e for e in events if e.kind == "tool_call_end"]
    assert len(ends) == 1
    assert ends[0].arguments == {"_invalid_json": "{not json"}


def test_401_does_not_retry():
    handler = RecordedHandler([error_response(401)])
    provider, sleep_calls = make_provider(handler)
    with pytest.raises(ProviderError):
        collect(provider)
    assert len(handler.requests) == 1
    assert sleep_calls == []


def test_400_does_not_retry():
    handler = RecordedHandler([error_response(400)])
    provider, sleep_calls = make_provider(handler)
    with pytest.raises(ProviderError):
        collect(provider)
    assert len(handler.requests) == 1
    assert sleep_calls == []


def test_500_then_success_retries_once():
    handler = RecordedHandler(
        [
            error_response(500),
            sse_response({"choices": [{"index": 0, "delta": {"content": "ok"}}]}),
        ]
    )
    provider, sleep_calls = make_provider(handler)
    events = collect(provider)
    assert [e.text for e in events if e.kind == "text_delta"] == ["ok"]
    assert len(handler.requests) == 2
    assert len(sleep_calls) == 1


def test_429_then_success_retries_once():
    handler = RecordedHandler(
        [
            error_response(429),
            sse_response({"choices": [{"index": 0, "delta": {"content": "ok"}}]}),
        ]
    )
    provider, sleep_calls = make_provider(handler)
    events = collect(provider)
    assert [e.text for e in events if e.kind == "text_delta"] == ["ok"]
    assert len(handler.requests) == 2
    assert len(sleep_calls) == 1


def test_three_429s_raise_provider_error():
    handler = RecordedHandler(
        [error_response(429), error_response(429), error_response(429)]
    )
    provider, sleep_calls = make_provider(handler)
    with pytest.raises(ProviderError):
        collect(provider)
    assert len(handler.requests) == 3
    assert len(sleep_calls) == 2


class _RaiseProvider:
    def __init__(self, exc: BaseException):
        self.exc = exc

    async def stream(self, *, system: str, messages: list[Message], tools: list):
        raise self.exc
        yield  # noqa: unreachable — keeps this an async generator


def test_loop_provider_error_returns_error_result(tmp_path: Path):
    session = Session(tmp_path / "session.jsonl")
    loop = Loop(
        provider=_RaiseProvider(ProviderError("down")),
        tools=[],
        session=session,
        system="sys",
    )
    result = asyncio.run(loop.run("hello"))
    assert result.status == "error"
    assert result.text == "down"
    assert result.steps == 1
    assert result.session_path == session.path


def test_loop_runtime_error_propagates():
    loop = Loop(
        provider=_RaiseProvider(RuntimeError("boom")),
        tools=[],
        session=Session.in_memory(),
        system="sys",
    )
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(loop.run("hello"))
