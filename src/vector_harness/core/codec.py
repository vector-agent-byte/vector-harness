"""消息和 JSON 对象之间的往返。

会话落盘，以及判断上下文变换有没有改内容，都用这一份。
键固定为 ``role``、``content``、``tool_calls``、``tool_call_id``、``is_error``。
有写下时间时再带上 ``created_at``。旧行没有这一项，读出来是 ``None``。
"""

from __future__ import annotations

import json

from vector_harness.types import Message, ToolCall


def message_to_dict(message: Message) -> dict:
    """收成可往返的 JSON 对象。没有工具调用时 ``tool_calls`` 写成 null。"""
    tool_calls: list[dict] | None
    if message.tool_calls is None:
        tool_calls = None
    else:
        tool_calls = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ]
    payload = {
        "role": message.role,
        "content": message.content,
        "tool_calls": tool_calls,
        "tool_call_id": message.tool_call_id,
        "is_error": message.is_error,
    }
    if isinstance(message.created_at, (int, float)) and not isinstance(message.created_at, bool):
        payload["created_at"] = float(message.created_at)
    return payload


def message_from_dict(data: dict) -> Message:
    """从一行 JSON 还原消息。缺 ``is_error`` 时当作成功的工具结果。"""
    raw_tool_calls = data.get("tool_calls")
    tool_calls: list[ToolCall] | None
    if raw_tool_calls is None:
        tool_calls = None
    else:
        tool_calls = [
            ToolCall(
                id=item["id"],
                name=item["name"],
                arguments=item["arguments"],
            )
            for item in raw_tool_calls
        ]
    created = data.get("created_at")
    created_at = (
        float(created)
        if isinstance(created, (int, float)) and not isinstance(created, bool)
        else None
    )
    return Message(
        role=data["role"],
        content=data["content"],
        tool_calls=tool_calls,
        tool_call_id=data.get("tool_call_id"),
        is_error=data.get("is_error", False),
        created_at=created_at,
    )


def messages_equal(left: list[Message], right: list[Message]) -> bool:
    """按序列化结果比较两份消息。

    变换如果原地改了列表再原样返回，两边是同一批对象，这里看不出差别，
    调用方也就不会重写会话文件。
    """
    left_payload = json.dumps(
        [message_to_dict(message) for message in left], sort_keys=True
    )
    right_payload = json.dumps(
        [message_to_dict(message) for message in right], sort_keys=True
    )
    return left_payload == right_payload
