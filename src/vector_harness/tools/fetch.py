"""通过 HTTP 获取 URL 内容。

只支持 GET / POST，不跟随超过 5 次重定向。响应体超过 max_chars 时截断。
不做沙箱，调用方负责判断是否应该开放这个工具。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WebFetch:
    """发出一条 HTTP 请求并返回响应文本。"""

    max_chars: int = 20000
    timeout: float = 30.0
    name: str = "web_fetch"
    description: str = (
        "Fetch a URL and return the response body as text. "
        "Use for reading web pages, APIs, or any public HTTP resource."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch."},
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST"],
                    "description": "HTTP method, default GET.",
                },
                "body": {
                    "type": "string",
                    "description": "Request body for POST.",
                },
                "headers": {
                    "type": "object",
                    "description": "Extra HTTP headers as key-value pairs.",
                },
            },
            "required": ["url"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        try:
            import httpx
        except ImportError:
            return "Error: httpx is not installed. Run: pip install httpx"

        url = arguments.get("url", "")
        if not isinstance(url, str) or not url.strip():
            return "Error: url is required"

        method = str(arguments.get("method", "GET")).upper()
        if method not in ("GET", "POST"):
            return "Error: method must be GET or POST"

        body = arguments.get("body")
        headers = arguments.get("headers") or {}
        if not isinstance(headers, dict):
            headers = {}

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=5,
                timeout=self.timeout,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    content=body.encode() if isinstance(body, str) else None,
                    headers=headers,
                )
        except httpx.TimeoutException:
            return f"Error: request timed out after {self.timeout}s"
        except httpx.RequestError as exc:
            return f"Error: {exc}"

        text = response.text
        truncated = ""
        if len(text) > self.max_chars:
            text = text[: self.max_chars]
            truncated = "\n...[truncated]"

        return f"status={response.status_code}\n{text}{truncated}"
