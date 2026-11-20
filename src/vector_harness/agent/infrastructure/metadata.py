"""Versioned task metadata stored beside the original session records."""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from uuid import uuid4

from vector_harness.agent.infrastructure.sessions import session_path

KINDS = frozenset({"agent", "deepresearch", "autoresearch"})
STATUSES = frozenset({"idle", "running", "completed", "stopped", "error", "interrupted"})


def _timestamp(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


class MetadataStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._lock = threading.RLock()

    def _path(self, session_id: str) -> Path:
        return session_path(self.workspace, session_id).with_suffix(".metadata.json")

    def read(self, session_id: str) -> dict | None:
        path = self._path(session_id)
        with self._lock:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (ValueError, UnicodeError) as error:
                raise ValueError("invalid_metadata") from error
            if (
                    not isinstance(value, dict)
                    or type(value.get("schema_version")) is not int
                    or value.get("schema_version") != 1
                    or not isinstance(value.get("kind"), str)
                    or value.get("kind") not in KINDS
                    or not isinstance(value.get("status"), str)
                    or value.get("status") not in STATUSES
                    or value.get("id") != session_id
                    or not isinstance(value.get("config"), dict)
                    or type(value.get("revision")) is not int
                    or value["revision"] < 0
                    or not _timestamp(value.get("created_at"))
                    or not _timestamp(value.get("updated_at"))
            ):
                raise ValueError("invalid_metadata")
            return value

    def create(self, session_id: str, kind: str, config: dict, *, status: str = "idle", **extra) -> dict:
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("invalid_kind")
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError("invalid_status")
        with self._lock:
            if not session_path(self.workspace, session_id).is_file():
                raise FileNotFoundError(session_id)
            if self._path(session_id).exists():
                raise FileExistsError(session_id)
            now = time.time()
            value = dict(extra, schema_version=1, id=session_id, kind=kind, config=config,
                         status=status, created_at=now, updated_at=now, revision=0)
            self._write(session_id, value)
            return value

    def update(self, session_id: str, **changes) -> dict:
        with self._lock:
            value = self.read(session_id)
            if value is None:
                raise FileNotFoundError(session_id)
            if "status" in changes and (not isinstance(changes["status"], str) or changes["status"] not in STATUSES):
                raise ValueError("invalid_status")
            value.update(changes)
            value["updated_at"] = time.time()
            value["revision"] = value.get("revision", 0) + 1
            self._write(session_id, value)
            return value

    def _write(self, session_id: str, value: dict) -> None:
        path = self._path(session_id)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def recover(self) -> None:
        directory = self.workspace / ".vector" / "sessions"
        for path in directory.glob("*.metadata.json"):
            session_id = path.name.removesuffix(".metadata.json")
            try:
                value = self.read(session_id)
            except ValueError:
                continue
            if value is not None and value["status"] == "running":
                self.update(session_id, status="interrupted")

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._path(session_id).unlink(missing_ok=True)
