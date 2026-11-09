"""用官方 OpenAI 客户端调用 Chat Completions。

生产路径是 ``AsyncOpenAI.chat.completions.create(stream=True)``。
循环是异步的，所以用 ``AsyncOpenAI``，它和同步的 ``OpenAI()`` 是同一个包。
兼容网关只要提供 ``/chat/completions`` 就能用，基址放在 ``base_url``。

重试由这里自己做：429 和 5xx 最多 3 次，其它 4xx 不重试。
客户端的 ``max_retries`` 设为 0，避免和这层重试叠在一起。
"""

from __future__ import annotations

import asyncio
import json
import os
import tomllib
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from vector_harness.types import Message, ProviderError, ProviderEvent

_CONFIG_KEYS = {
    "api_key": "VECTOR_API_KEY",
    "base_url": "VECTOR_BASE_URL",
    "model": "VECTOR_MODEL",
}


def default_config_path() -> Path:
    """连接配置的默认位置：家目录下的 ``.vector-harness/config.toml``。"""
    return Path.home() / ".vector-harness" / "config.toml"


def apply_config(env: Mapping[str, str], path: Path) -> dict:
    """用配置文件填上环境里还没有的连接项。文件不存在就原样返回。

    终端用这个顺序：已经设好的环境变量保留，文件只补空缺。
    """
    merged = dict(env)
    data = _load_config(path)
    for key, env_name in _CONFIG_KEYS.items():
        if merged.get(env_name):
            continue
        if key not in data:
            continue
        merged[env_name] = _config_value(path, key, data[key])
    return merged


def settings_from_config_then_env(env: Mapping[str, str], path: Path) -> dict:
    """先读配置文件。某一项文件里没有时，再用同名环境变量。"""
    found: dict[str, str] = {}
    data = _load_config(path)
    for key, env_name in _CONFIG_KEYS.items():
        if key in data:
            found[env_name] = _config_value(path, key, data[key])
            continue
        env_value = env.get(env_name) or ""
        if env_value:
            found[env_name] = env_value
    return found


def _load_config(path: Path) -> dict:
    """读配置文件。文件不存在时当作空配置。"""
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ProviderError(f"invalid config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"invalid config {path}: root must be a table")
    return data


def _config_value(path: Path, key: str, value: Any) -> str:
    """配置项必须是非空字符串。"""
    if not isinstance(value, str) or not value:
        raise ProviderError(f"invalid config {path}: {key} must be a non-empty string")
    return value


class OpenAICompatibleProvider:
    """一个可替换的模型实现。测试可以传入 ``transport`` 伪造 HTTP 响应。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_attempts: int = 3,
        sleep: Callable = asyncio.sleep,
        transport: Any = None,
        config_file: Path | None = None,
    ) -> None:
        """保存连接信息。没传入的连接项先读配置文件，缺的再读环境变量。

        三项都传入时不再读配置文件。``transport`` 只在测试里注入，用来伪造 HTTP 响应。
        """
        if api_key is None or base_url is None or model is None:
            filled = settings_from_config_then_env(
                os.environ,
                default_config_path() if config_file is None else config_file,
            )
            if api_key is None:
                api_key = filled.get("VECTOR_API_KEY") or ""
            if base_url is None:
                base_url = filled.get("VECTOR_BASE_URL") or ""
            if model is None:
                model = filled.get("VECTOR_MODEL") or ""
        if not api_key:
            raise ProviderError("VECTOR_API_KEY is not set")
        if not base_url:
            raise ProviderError("VECTOR_BASE_URL is not set")
        if not model:
            raise ProviderError("VECTOR_MODEL is not set")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_attempts = max_attempts
        # 测试注入立刻返回的 sleep，避免真的等待。
        self.sleep = sleep
        self.transport = transport

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> OpenAICompatibleProvider:
        """从环境变量构造。缺哪一项就报哪一项，密钥不来自命令行。

        终端会先把配置文件补进这组变量。这个方法本身不读配置文件。
        """
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

    def _client(self) -> tuple[AsyncOpenAI, Any]:
        """每次尝试建一个客户端。有 transport 时用 httpx 把它接进去，方便测试。"""
        http_client = None
        if self.transport is not None:
            import httpx

            http_client = httpx.AsyncClient(transport=self.transport, timeout=120)
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=0,
            timeout=120,
            http_client=http_client,
        )
        return client, http_client

    async def stream(
        self, *, system: str, messages: list[Message], tools: list
    ) -> AsyncIterator[ProviderEvent]:
        """流式产出文本增量和工具调用。空工具列表不放进请求体，避免兼容网关返回 400。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": True,
            "messages": _messages_payload(system, messages),
        }
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]

        for attempt in range(1, self.max_attempts + 1):
            retry_status: int | None = None
            client, http_client = self._client()
            try:
                async with client:
                    try:
                        response = await client.chat.completions.create(**payload)
                        async for event in _events_from_stream(response):
                            yield event
                    except APIStatusError as exc:
                        status = exc.status_code
                        # 限流和服务端错误留给外层重试。认证失败和其它 4xx 立刻失败。
                        if status == 429 or status >= 500:
                            retry_status = status
                        else:
                            raise ProviderError(f"HTTP {status}") from exc
                    except (APITimeoutError, APIConnectionError, APIError) as exc:
                        # 流里的 error 对象会被 SDK 收成 APIError，这里同样变成 ProviderError。
                        raise ProviderError(_error_text(exc)) from exc
                    except Exception as exc:
                        if _is_httpx_transport_error(exc):
                            raise ProviderError(str(exc)) from exc
                        raise
            finally:
                if http_client is not None:
                    await http_client.aclose()
            if retry_status is None:
                return
            if attempt >= self.max_attempts:
                raise ProviderError(f"HTTP {retry_status}")
            await self.sleep(0.5)


def _messages_payload(system: str, messages: list[Message]) -> list[dict]:
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


def _tool_payload(tool: Any) -> dict:
    """收成 Chat Completions 的 function 工具。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": getattr(tool, "description", ""),
            "parameters": getattr(tool, "parameters", {}),
        },
    }


def _error_text(exc: BaseException) -> str:
    """优先用底层原因的文本，这样超时信息能穿过 SDK 的包装。"""
    cause = exc.__cause__
    if cause is not None and str(cause):
        return str(cause)
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message:
        return message
    return str(exc)


def _is_httpx_transport_error(exc: BaseException) -> bool:
    """测试用的 httpx transport 抛出的超时和连接错误。生产客户端自己的错误已在上面接住。"""
    try:
        import httpx
    except ImportError:
        return False
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


async def _events_from_stream(stream: Any) -> AsyncIterator[ProviderEvent]:
    """把 SDK 的流式分片收成循环认识的事件。

    一次工具调用会拆成多个分片，用 ``index`` 拼回同一次调用。
    名字和 id 到齐就发出 ``tool_call_start``，参数要等流结束才解析。
    没有 choices 的用量分片直接跳过。参数不是合法 JSON 时放进 ``_invalid_json``，
    交给循环拒绝执行。
    """
    buckets: dict[int, dict[str, str]] = {}
    started: set[int] = set()
    async for chunk in stream:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)
        if content:
            yield ProviderEvent(kind="text_delta", text=content)
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
