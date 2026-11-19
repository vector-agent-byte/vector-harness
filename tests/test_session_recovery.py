import json

import pytest

from vector_harness import Message, Session


def test_open_partial_utf8_is_read_only(tmp_path):
    from vector_harness.core.session_io import scan_session

    path = tmp_path / "session.jsonl"
    good = b'{"role":"user","content":"hello"}\n'
    before = good + b'{"role":"assistant","content":"' + "中".encode("utf-8")[:2]
    path.write_bytes(before)
    scan = scan_session(path)
    assert scan.issue == "partial_tail"
    assert [message.content for message in scan.messages] == ["hello"]
    assert path.read_bytes() == before
    assert len(list(tmp_path.iterdir())) == 1


def test_prepare_backs_up_tail_before_repair(tmp_path):
    path = tmp_path / "session.jsonl"
    good = b'{"role":"user","content":"hello"}\n'
    broken = b'{"role":"assistant"'
    path.write_bytes(good + broken)
    session = Session(path)
    session.prepare_for_run()
    backups = list(tmp_path.glob("session.recovery-*.bin"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == broken
    assert path.read_bytes() == good
    session.append(Message(role="user", content="continue"))
    assert [message.content for message in session.load()] == ["hello", "continue"]


def test_backup_failure_preserves_original(tmp_path, monkeypatch):
    from pathlib import Path

    path = tmp_path / "session.jsonl"
    before = b'{"role":"user","content":"hello"}\n{'
    path.write_bytes(before)
    original_open = Path.open

    def deny_backup(self, *args, **kwargs):
        if self.suffix == ".bin":
            raise PermissionError("backup denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_backup)
    with pytest.raises(PermissionError):
        Session(path).prepare_for_run()
    assert path.read_bytes() == before


def test_complete_last_record_without_newline(tmp_path):
    path = tmp_path / "session.jsonl"
    path.write_text('{"role":"user","content":"one"}', encoding="utf-8")
    session = Session(path)
    session.append(Message(role="assistant", content="two"))
    assert [json.loads(line)["content"] for line in path.read_text(encoding="utf-8").splitlines()] == ["one", "two"]


@pytest.mark.parametrize("body", [
    b'{"role":"user","content":"one"}\nbad\n{"role":"user","content":"two"}\n',
    b'{"role":"user","content":"one"}\nbad\n',
])
def test_middle_or_terminated_corruption_blocks_execution(tmp_path, body):
    from vector_harness.core.session_io import SessionCorruptionError

    path = tmp_path / "session.jsonl"
    path.write_bytes(body)
    with pytest.raises(SessionCorruptionError):
        Session(path).prepare_for_run()
    assert path.read_bytes() == body
