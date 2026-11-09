"""非法参数从模型解析进入循环后，不得执行工具。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from vector_harness import Loop, Session
from tests.test_provider import RecordedHandler, make_provider, sse_response


@dataclass
class CountingTool:
    calls: list[dict] = field(default_factory=list)
    name: str = "read_file"
    description: str = "Reads a file"
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        self.calls.append(arguments)
        return "executed"


def test_invalid_json_from_provider_does_not_execute_tool():
    tool = CountingTool()
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
            ),
            sse_response(
                {"choices": [{"index": 0, "delta": {"content": "done"}}]}
            ),
        ]
    )
    provider, _ = make_provider(handler)
    session = Session.in_memory()
    loop = Loop(provider=provider, tools=[tool], session=session, system="sys")

    result = asyncio.run(loop.run("read it"))

    assert tool.calls == []
    assert result.status == "complete"
    assert result.text == "done"
    tool_message = session.load()[2]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "call_bad"
    assert tool_message.is_error is True
    assert tool_message.content == "Error: invalid arguments for read_file"
