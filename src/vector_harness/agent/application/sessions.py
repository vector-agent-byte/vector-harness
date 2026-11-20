"""Transport-independent session use cases and run admission."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from vector_harness.agent.application.errors import ServiceError
from vector_harness.agent.application.ports import RunCoordinator, SessionRepository, TaskMetadataRepository

MODES = {
    "react": (False, False, False),
    "plan": (True, False, False),
    "reflect": (False, True, False),
    "subagents": (False, False, True),
}


class SessionService:
    def __init__(self, workspace: Path, runs: RunCoordinator, metadata: TaskMetadataRepository,
                 catalog: Callable[[], list[dict]] = lambda: [], *, repository: SessionRepository):
        self.workspace = workspace
        self.runs = runs
        self.metadata = metadata
        self.catalog = catalog
        self.repository = repository

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        if not self.runs.acquire():
            raise ServiceError("busy")
        try:
            yield
        finally:
            self.runs.release()

    def require(self, session_id: str) -> Path:
        if not self.repository.is_session_id(session_id):
            raise ServiceError("bad_session")
        path = self.repository.session_path(self.workspace, session_id)
        if not path.is_file():
            raise ServiceError("not_found")
        return path

    def create(self) -> dict:
        session_id = self.repository.create_session(self.workspace)
        try:
            self.repository.set_session_mode(self.workspace, session_id, "react")
            self.metadata.create(session_id, "agent", {})
        except Exception:
            self.repository.delete_session(self.workspace, session_id)
            raise
        return {"id": session_id}

    def list(self, kind: str | None = None) -> list[dict]:
        result = []
        for item in self.repository.list_sessions(self.workspace):
            try:
                metadata = self.metadata.read(item["id"])
            except ValueError:
                if kind is None:
                    result.append(item)
                continue
            if kind is None or (metadata or {}).get("kind", "agent") == kind:
                if metadata and metadata["kind"] != "agent":
                    item["mode"] = metadata.get("mode", item["mode"])
                result.append(item)
        return result

    def detail(self, session_id: str) -> dict:
        self.require(session_id)
        view = self.repository.read_session_view(self.workspace, session_id)
        started_at, duration_ms = self.repository.session_run(self.workspace, session_id)
        mode = self.repository.session_mode(self.workspace, session_id) or "react"
        metadata = self.metadata.read(session_id)
        if metadata and metadata["kind"] != "agent":
            mode = metadata.get("mode", mode)
        plan, reflect, subagents = MODES[mode]
        from vector_harness.agent.assembly import runner_chain_for_flags
        return {
            "id": session_id, **view,
            "skill": self.repository.session_skill(self.workspace, session_id),
            "skills": self.repository.session_skills(self.workspace, session_id),
            "mode": mode, "runner_chain": runner_chain_for_flags(plan=plan, reflect=reflect),
            "subagents": subagents, "started_at": started_at, "duration_ms": duration_ms,
        }

    def delete(self, session_id: str) -> dict:
        with self.exclusive():
            self.require(session_id)
            self.repository.delete_session(self.workspace, session_id)
            self.metadata.remove(session_id)
        return {"deleted": True}

    def stop(self, session_id: str) -> dict:
        if not self.repository.is_session_id(session_id):
            raise ServiceError("bad_session")
        return {"stopped": self.runs.stop(session_id)}

    def set_mode(self, session_id: str, mode: object) -> dict:
        if not isinstance(mode, str) or mode not in MODES:
            raise ServiceError("bad_request")
        with self.exclusive():
            self.require(session_id)
            metadata = self.metadata.read(session_id)
            if metadata and metadata["kind"] != "agent" and mode != metadata.get("mode"):
                raise ServiceError("domain_mode")
            self.repository.set_session_mode(self.workspace, session_id, mode)
        return {"id": session_id, "mode": mode}

    def set_skills(self, session_id: str, names: object, *, single: bool = False) -> dict:
        if names is not None:
            if not isinstance(names, list) or not all(isinstance(name, str) and name.strip() for name in names):
                raise ServiceError("bad_request")
            if set(names) - {item["name"] for item in self.catalog()}:
                raise ServiceError("unknown_skill")
            names = list(dict.fromkeys(names))
        with self.exclusive():
            self.require(session_id)
            try:
                self.repository.set_session_skills(self.workspace, session_id, names)
            except OSError as error:
                raise ServiceError("skills_save_failed") from error
        if single:
            return {"id": session_id, "skill": names[0] if names else None}
        return {"id": session_id, "skills": names}

    def execute(self, session_id: str, text: str, mode: str | None, emit: Callable,
                ready: Callable[[], None] = lambda: None) -> tuple[str, str]:
        if not isinstance(text, str):
            raise ServiceError("bad_request")
        if not text.strip():
            raise ServiceError("empty")
        if mode is not None and mode not in MODES:
            raise ServiceError("bad_request")
        with self.exclusive():
            self.require(session_id)
            metadata = self.metadata.read(session_id)
            if metadata and metadata["kind"] != "agent":
                raise ServiceError("domain_task")
            selected = mode or self.repository.session_mode(self.workspace, session_id)
            if selected:
                self.repository.set_session_mode(self.workspace, session_id, selected)
            return self.execute_reserved(session_id, text, selected, emit, ready)

    def execute_reserved(self, session_id: str, text: str, mode: str | None, emit: Callable,
                         ready: Callable[[], None]) -> tuple[str, str]:
        path = self.require(session_id)
        settings = self.runs.settings
        flags = MODES[mode] if mode else (settings.plan, settings.reflect, settings.subagents)
        metadata = self.metadata.read(session_id)
        status = "error"
        if metadata:
            self.metadata.update(session_id, status="running")
        try:
            status, content = self.runs.run(session_id, path, text, plan=flags[0], reflect=flags[1],
                                            subagents=flags[2], emit=emit, ready=ready)
            return status, content
        finally:
            if metadata:
                final_status = {"complete": "completed", "stopped": "stopped"}.get(status, "error")
                self.metadata.update(session_id, status=final_status, outcome=status)
