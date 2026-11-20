from __future__ import annotations

import json

from vector_harness.agent.core.codec import message_to_dict
from vector_harness.agent.core.session import Session


class ReadSessionHistory:
    name = "read_session_history"
    description = "只读回查当前会话原文。消息序号从1开始；可用字面关键词搜索。续页传回next对象，保持through上界。"
    parameters = {
        "type": "object",
        "properties": {
            "start": {"type": "integer", "minimum": 1},
            "end": {"type": "integer", "minimum": 1},
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "offset": {"type": "integer", "minimum": 0},
            "through": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    }

    def __init__(self, session: Session):
        self.session = session

    def for_session(self, session: Session) -> ReadSessionHistory:
        return ReadSessionHistory(session)

    async def execute(self, arguments: dict) -> str:
        if not isinstance(arguments, dict) or set(arguments) - set(self.parameters["properties"]):
            raise ValueError("unsupported history arguments")
        for name in ("start", "end", "limit", "offset", "through"):
            if name in arguments and (type(arguments[name]) is not int or arguments[name] < (0 if name in {"offset", "through"} else 1)):
                raise ValueError("invalid history range")
        if "query" in arguments and (not isinstance(arguments["query"], str) or "end" in arguments):
            raise ValueError("query must be a string and cannot be combined with end")
        start, offset = arguments.get("start", 1), arguments.get("offset", 0)
        limit = arguments.get("limit", 20)
        if limit > 50 or arguments.get("end", start) < start:
            raise ValueError("invalid history range")
        messages = self.session.load()
        through = arguments.get("through", len(messages))
        if through > len(messages):
            raise ValueError("history upper bound exceeds current history")
        end = min(arguments.get("end", through), through)
        query = arguments.get("query")
        entries = []

        def cursor(index, position):
            value = {"start": index, "offset": position, "through": through, "limit": limit}
            if query is not None:
                value["query"] = query
            elif "end" in arguments:
                value["end"] = arguments["end"]
            return value

        def encode(next_page):
            return json.dumps({"entries": entries, "next": next_page, "truncated": next_page is not None}, ensure_ascii=False)

        def finish(next_page):
            result = encode(next_page)
            if len(result) > 16000:
                raise ValueError("history metadata exceeds output budget")
            return result

        for index in range(start, end + 1):
            message = messages[index - 1]
            text = json.dumps(message_to_dict(message), ensure_ascii=False, sort_keys=True)
            position = offset if index == start else 0
            if position > len(text):
                raise ValueError("history offset exceeds message length")
            if position == len(text):
                continue
            if query is not None and query not in text:
                continue
            if len(entries) >= limit:
                return finish(cursor(index, position))
            entry = {"message_index": index, "role": str(message.role), "tool_call_id": message.tool_call_id, "offset": position, "text": ""}
            entries.append(entry)
            low, high = 0, len(text) - position
            while low < high:
                midpoint = (low + high + 1) // 2
                entry["text"] = text[position:position + midpoint]
                if len(encode(cursor(index, position + midpoint))) <= 16000:
                    low = midpoint
                else:
                    high = midpoint - 1
            entry["text"] = text[position:position + low]
            if low == 0 and position < len(text):
                entries.pop()
                result = encode(cursor(index, position))
                if not entries or len(result) > 16000:
                    raise ValueError("history query metadata exceeds output budget")
                return finish(cursor(index, position))
            if position + low < len(text):
                return finish(cursor(index, position + low))
        return finish(None)
