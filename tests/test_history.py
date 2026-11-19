import asyncio
import json

import pytest

from vector_harness import Message, Session
from vector_harness.core.codec import message_to_dict
from vector_harness.tools.history import ReadSessionHistory


def test_long_history_cursor_is_bounded_and_stable(tmp_path):
    session = Session(tmp_path / "s.jsonl")
    session.append(Message(role="user", content=('中文"\\\n' * 10000)))
    original = json.dumps(message_to_dict(session.load()[0]), ensure_ascii=False, sort_keys=True)
    tool = ReadSessionHistory(session)
    arguments = {}
    pieces = []
    while True:
        text = asyncio.run(tool.execute(arguments))
        assert len(text) <= 16000
        payload = json.loads(text)
        pieces.extend(entry["text"] for entry in payload["entries"])
        session.append(Message(role="assistant", content="new search result"))
        if payload["next"] is None:
            break
        assert payload["truncated"]
        arguments = payload["next"]
    assert "".join(pieces) == original


def test_search_literal_read_only(tmp_path):
    session = Session(tmp_path / "s.jsonl")
    session.append(Message(role="user", content=".* evidence"))
    session.append(Message(role="user", content="anything else"))
    before = session.path.read_bytes()
    payload = json.loads(asyncio.run(ReadSessionHistory(session).execute({"query": ".*"})))
    assert len(payload["entries"]) == 1
    assert "evidence" in payload["entries"][0]["text"]
    assert session.path.read_bytes() == before


@pytest.mark.parametrize("arguments", [{"path": "other"}, {"session_id": "other"}, {"start": True}, {"offset": -1}, {"limit": 51}, {"query": "x", "end": 2}, {"start": 3, "end": 1}])
def test_invalid_history_scope(arguments):
    with pytest.raises(ValueError):
        asyncio.run(ReadSessionHistory(Session.in_memory()).execute(arguments))
