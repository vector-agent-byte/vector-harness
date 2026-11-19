from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from pathlib import Path

from vector_harness.core.codec import message_to_dict
from vector_harness.core.session import Session
from vector_harness.core.session_io import atomic_write_bytes
from vector_harness.types import Message

_logger = logging.getLogger(__name__)


def prefix_digest(messages: list[Message], covered_count: int) -> str:
    if isinstance(covered_count, bool) or not 0 <= covered_count <= len(messages):
        raise ValueError("invalid covered_count")
    payload = [message_to_dict(message) for message in messages[:covered_count]]
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SessionArtifacts:
    def __init__(self, session: Session):
        self.session = session

    def path(self, kind: str) -> Path | None:
        if kind not in {"context", "task"}:
            raise ValueError("unknown session artifact")
        if self.session.path is None:
            return None
        return self.session.path.with_suffix(f".{kind}.json")

    def load(self, kind: str) -> dict | None:
        path = self.path(kind)
        if path is None:
            return deepcopy(self.session._derived_state.get(kind))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != 1:
                raise ValueError("unsupported artifact")
            return payload
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            _logger.warning("Session %s artifact unavailable or invalid; ignoring derived state", kind)
            return None

    def update(self, kind: str, changes: dict) -> None:
        path = self.path(kind)
        payload = self.load(kind) or {}
        payload.update(deepcopy(changes))
        payload["version"] = 1
        if path is None:
            self.session._derived_state[kind] = payload
        else:
            atomic_write_bytes(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
