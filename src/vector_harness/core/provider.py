from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

import httpx

from vector_harness.types import Message, ProviderError, ProviderEvent


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_attempts: int = 3,
        sleep: Callable = asyncio.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.transport = transport

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> OpenAICompatibleProvider:
        source = os.environ if env is None else env
        api_key = source.get("VECTOR_API_KEY") or ""
        if not api_key:
            raise ProviderError("VECTOR_API_KEY is not set")
        base_url = source.get("VECTOR_BASE_URL") or ""
        if not base_url:
            raise ProviderError("VECTOR_BASE_URL is not set")
        model = source.get("VECTOR_MODEL") or ""
        if not model:
            raise ProviderError("VECTOR_MODEL is not set")
        return cls(api_key=api_key, base_url=base_url, model=model)

    async def stream(
        self, *, system: str, messages: list[Message], tools: list
    ) -> AsyncIterator[ProviderEvent]:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": True,
            "messages": _messages_payload(system, messages),
            "tools": [_tool_payload(tool) for tool in tools],
        }

        for attempt in range(1, self.max_attempts + 1):
            retry_status: int | None = None
            async with httpx.AsyncClient(transport=self.transport) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    status = response.status_code
                    if 400 <= status < 500 and status != 429:
                        await response.aread()
                        raise ProviderError(f"HTTP {status}")
                    if status == 429 or status >= 500:
                        await response.aread()
                        retry_status = status
                    else:
                        async for event in _parse_sse(response):
                            yield event
            if retry_status is None:
                return
            if attempt >= self.max_attempts:
                raise ProviderError(f"HTTP {retry_status}")
            await self.sleep(0.5)


def _messages_payload(system: str, messages: list[Message]) -> list[dict]:
    payload: list[dict] = [{"role": "system", "content": system}]
    for message in messages:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "tool":
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        payload.append(item)
    return payload


def _tool_payload(tool: Any) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": getattr(tool, "description", ""),
            "parameters": getattr(tool, "parameters", {}),
        },
    }


async def _parse_sse(response: httpx.Response) -> AsyncIterator[ProviderEvent]:
    buckets: dict[int, dict[str, str]] = {}
    started: set[int] = set()
    async for line in response.aiter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if content:
            yield ProviderEvent(kind="text_delta", text=content)
        for item in delta.get("tool_calls") or []:
            idx = item.get("index", 0)
            bucket = buckets.setdefault(
                idx, {"id": "", "name": "", "arguments": ""}
            )
            if item.get("id") and not bucket["id"]:
                bucket["id"] = item["id"]
            function = item.get("function") or {}
            if function.get("name") and not bucket["name"]:
                bucket["name"] = function["name"]
            fragment = function.get("arguments")
            if fragment:
                bucket["arguments"] += fragment
            if idx not in started and bucket["id"] and bucket["name"]:
                started.add(idx)
                yield ProviderEvent(
                    kind="tool_call_start",
                    name=bucket["name"],
                    tool_call_id=bucket["id"],
                    arguments=None,
                )
    for idx in sorted(buckets):
        bucket = buckets[idx]
        raw = bucket["arguments"]
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"_invalid_json": raw}
        yield ProviderEvent(
            kind="tool_call_end",
            name=bucket["name"],
            tool_call_id=bucket["id"],
            arguments=parsed,
        )
