"""把 Chat Completions 的流式分片收成循环认识的事件。

这里不做重试，也不创建客户端。模型类负责把响应流交进来。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from vector_harness.types import (
    INVALID_TOOL_ARGUMENTS,
    EventKind,
    Message,
    ProviderEvent,
)


def messages_payload(system: str, messages: list[Message]) -> list[dict]:
    """system 放在消息列表第一条。工具结果带上 ``tool_call_id``，助手的工具调用序列化成 JSON 字符串。"""
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


def tool_payload(tool: Any) -> dict:
    """收成 Chat Completions 的 function 工具。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": getattr(tool, "description", ""),
            "parameters": getattr(tool, "parameters", {}),
        },
    }


def error_text(exc: BaseException) -> str:
    """优先用底层原因的文本，这样超时信息能穿过 SDK 的包装。"""
    cause = exc.__cause__
    if cause is not None and str(cause):
        return str(cause)
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        return message
    return str(exc)


def is_httpx_transport_error(exc: BaseException) -> bool:
    """测试用的 httpx transport 抛出的超时和连接错误。生产客户端自己的错误已在上面接住。"""
    try:
        import httpx
    except ImportError:
        return False
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def delta_text(delta: Any, *names: str) -> str:
    """从分片上取一段文本。兼容网关把思考放在额外字段里，不在官方的 content 上。"""
    if delta is None:
        return ""
    for name in names:
        value = getattr(delta, name, None)
        if isinstance(value, str) and value:
            return value
    extra = getattr(delta, "__pydantic_extra__", None)
    if not isinstance(extra, dict):
        extra = getattr(delta, "model_extra", None)
    if isinstance(extra, dict):
        for name in names:
            value = extra.get(name)
            if isinstance(value, str) and value:
                return value
    if isinstance(delta, dict):
        for name in names:
            value = delta.get(name)
            if isinstance(value, str) and value:
                return value
    return ""


async def events_from_stream(stream: Any) -> AsyncIterator[ProviderEvent]:
    """把 SDK 的流式分片收成循环认识的事件。

    一次工具调用会拆成多个分片，用 ``index`` 拼回同一次调用。
    名字和 id 到齐就发出 ``tool_call_start``，参数要等流结束才解析。
    没有 choices 的用量分片直接跳过。参数不是合法 JSON 时放进
    ``INVALID_TOOL_ARGUMENTS``，交给循环拒绝执行。思考字段单独变成
    ``thinking_delta``，不并进正文。
    """
    buckets: dict[int, dict[str, str]] = {}
    started: set[int] = set()
    async for chunk in stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        thinking = delta_text(delta, "reasoning_content", "reasoning", "thinking")
        if thinking:
            yield ProviderEvent(kind=EventKind.THINKING_DELTA, text=thinking)
        content = delta_text(delta, "content")
        if content:
            yield ProviderEvent(kind=EventKind.TEXT_DELTA, text=content)
        for item in getattr(delta, "tool_calls", None) or []:
            idx = getattr(item, "index", 0) or 0
            bucket = buckets.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            call_id = getattr(item, "id", None)
            if call_id and not bucket["id"]:
                bucket["id"] = call_id
            function = getattr(item, "function", None)
            name = getattr(function, "name", None)
            if name and not bucket["name"]:
                bucket["name"] = name
            fragment = getattr(function, "arguments", None)
            if fragment:
                bucket["arguments"] += fragment
            if idx not in started and bucket["id"] and bucket["name"]:
                started.add(idx)
                yield ProviderEvent(
                    kind=EventKind.TOOL_CALL_START,
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
            parsed = {INVALID_TOOL_ARGUMENTS: raw}
        yield ProviderEvent(
            kind=EventKind.TOOL_CALL_END,
            name=bucket["name"],
            tool_call_id=bucket["id"],
            arguments=parsed,
        )
