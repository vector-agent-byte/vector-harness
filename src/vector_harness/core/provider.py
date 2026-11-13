"""用官方 OpenAI 客户端调用 Chat Completions。

生产路径是 ``AsyncOpenAI.chat.completions.create(stream=True)``。
循环是异步的，所以用 ``AsyncOpenAI``，它和同步的 ``OpenAI()`` 是同一个包。
兼容网关只要提供 ``/chat/completions`` 就能用，基址放在 ``base_url``。

重试由这里自己做：429 和 5xx 最多 3 次，其它 4xx 不重试。
客户端的 ``max_retries`` 设为 0，避免和这层重试叠在一起。
分片如何变成事件，见 ``openai_events``。连接文件见 ``config``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

_provider_logger = logging.getLogger("vector_harness.provider")

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from vector_harness.core.config import (
    apply_config,
    default_config_path,
    log_settings_from_config,
    settings_from_config_then_env,
)
from vector_harness.core.openai_events import (
    error_text,
    events_from_stream,
    is_httpx_transport_error,
    messages_payload,
    tool_payload,
)
from vector_harness.types import Message, ProviderError, ProviderEvent

__all__ = [
    "OpenAICompatibleProvider",
    "apply_config",
    "default_config_path",
]


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
        log_messages: bool = False,
    ) -> None:
        """保存连接信息。没传入的连接项先读配置文件，缺的再读环境变量。

        三项都传入时不再读配置文件。``transport`` 只在测试里注入，用来伪造 HTTP 响应。
        ``log_messages`` 为 True 时把完整请求和响应写进日志。
        """
        cfg_path = default_config_path() if config_file is None else config_file
        if api_key is None or base_url is None or model is None:
            filled = settings_from_config_then_env(os.environ, cfg_path)
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
        self.sleep = sleep
        self.transport = transport
        self.log_messages = log_messages

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        log_messages: bool = False,
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
        return cls(api_key=api_key, base_url=base_url, model=model, log_messages=log_messages)

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
            "messages": messages_payload(system, messages),
        }
        if tools:
            payload["tools"] = [tool_payload(tool) for tool in tools]

        if self.log_messages:
            _provider_logger.debug(
                "llm_request %s",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )

        for attempt in range(1, self.max_attempts + 1):
            retry_status: int | None = None
            client, http_client = self._client()
            resp_text: list[str] = []
            resp_tools: list[dict] = []
            try:
                async with client:
                    try:
                        response = await client.chat.completions.create(**payload)
                        async for event in events_from_stream(response):
                            if self.log_messages:
                                if event.kind == "text_delta" and event.text:
                                    resp_text.append(event.text)
                                elif event.kind == "tool_call_end":
                                    resp_tools.append(
                                        {"name": event.name, "arguments": event.arguments}
                                    )
                            yield event
                        if self.log_messages:
                            _provider_logger.debug(
                                "llm_response text=%r tools=%s",
                                "".join(resp_text),
                                json.dumps(resp_tools, ensure_ascii=False, separators=(",", ":")),
                            )
                    except APIStatusError as exc:
                        status = exc.status_code
                        if status == 429 or status >= 500:
                            retry_status = status
                        else:
                            raise ProviderError(f"HTTP {status}") from exc
                    except (APITimeoutError, APIConnectionError, APIError) as exc:
                        raise ProviderError(error_text(exc)) from exc
                    except Exception as exc:
                        if is_httpx_transport_error(exc):
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
