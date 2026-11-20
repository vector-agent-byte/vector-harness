"""Shared task lifecycle, parameterized by a domain policy."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Protocol

from vector_harness.agent.application.errors import ServiceError
from vector_harness.agent.application.sessions import SessionService


class TaskPolicy(Protocol):
    kind: str
    mode: str
    continuable: bool

    def normalize_config(self, value: object) -> dict: ...

    def build_prompt(self, config: dict, parent: dict | None = None) -> str: ...

    def project(self, messages: list[dict], config: dict) -> dict: ...


class TaskService:
    def __init__(self, sessions: SessionService, policy: TaskPolicy):
        self.sessions = sessions
        self.policy = policy
        self.metadata = sessions.metadata
        self.repository = sessions.repository
        self._cache: dict[str, tuple[tuple, dict]] = {}

    def _normalize(self, value: object) -> dict:
        try:
            return self.policy.normalize_config(value)
        except ValueError as error:
            raise ServiceError("bad_request", str(error)) from error

    def require(self, session_id: str) -> dict:
        self.sessions.require(session_id)
        try:
            metadata = self.metadata.read(session_id)
        except ValueError as error:
            raise ServiceError("invalid_metadata") from error
        if not metadata or metadata["kind"] != self.policy.kind:
            raise ServiceError("not_found")
        return metadata

    def create(self, value: object, *, parent_session_id: str | None = None,
               parent_experiment_id: int | None = None) -> dict:
        config = self._normalize(value)
        parent = None
        if parent_session_id is not None or parent_experiment_id is not None:
            if self.policy.kind != "autoresearch" or not isinstance(parent_session_id, str) or type(
                    parent_experiment_id) is not int:
                raise ServiceError("bad_request", "Invalid parent experiment reference")
            with self.sessions.exclusive():
                source = self.detail(parent_session_id)["task"]
                parent = next((item for item in source["experiments"] if item["id"] == parent_experiment_id), None)
                if parent is None:
                    raise ServiceError("not_found", "Parent experiment not found")
                parent = deepcopy(parent)
        session_id = self.repository.create_session(self.sessions.workspace)
        try:
            self.repository.set_session_mode(self.sessions.workspace, session_id, self.policy.mode)
            value = self.metadata.create(session_id, self.policy.kind, config, mode=self.policy.mode,
                                         parentSessionId=parent_session_id, parentExperimentId=parent_experiment_id,
                                         parent=parent)
        except Exception:
            self.repository.delete_session(self.sessions.workspace, session_id)
            raise
        return self._summary(value)

    def _summary(self, metadata: dict) -> dict:
        config = metadata["config"]
        return {
            "id": metadata["id"], "kind": metadata["kind"], "config": config,
            "status": metadata["status"], "updated_at": metadata["updated_at"],
            "revision": metadata["revision"], "topic": config.get("topic", ""),
            "title": config.get("topic") or config.get("name") or config.get("description") or metadata["id"],
        }

    def list(self) -> dict:
        tasks = []
        for session in self.sessions.list(self.policy.kind):
            try:
                tasks.append(self._summary(self.require(session["id"])))
            except ServiceError:
                continue
        tasks.sort(key=lambda task: (-task["updated_at"], task["id"]))
        return {"tasks": tasks, "running_id": self.sessions.runs.running_id}

    def detail(self, session_id: str) -> dict:
        metadata = self.require(session_id)
        version = (metadata["revision"], self.repository.session_version(self.sessions.workspace, session_id))
        cached = self._cache.get(session_id)
        if cached is not None and cached[0] == version:
            return deepcopy(cached[1])
        view = self.repository.read_session_view(self.sessions.workspace, session_id)
        task = {**self._summary(metadata), **self.policy.project(view["messages"], metadata["config"])}
        task["outcome"] = metadata.get("outcome")
        result = {"task": task, **view}
        if len(self._cache) >= 128:
            self._cache.clear()
        self._cache[session_id] = (version, deepcopy(result))
        return result

    def execute(self, session_id: str, *, text: str | None = None, emit: Callable,
                snapshot: Callable[[dict], None] = lambda _value: None,
                ready: Callable[[], None] = lambda: None) -> tuple[str, str]:
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise ServiceError("bad_request")
        with self.sessions.exclusive():
            metadata = self.require(session_id)
            if text is None and metadata["status"] != "idle":
                raise ServiceError("already_run")
            if text is not None and not self.policy.continuable:
                raise ServiceError("already_run", "Create a derived task to continue this experiment")
            history = self.repository.read_session_view(self.sessions.workspace, session_id)["messages"]
            initialized = any(message.get("role") == "user" for message in history)
            prompt = self.policy.build_prompt(metadata["config"], metadata.get("parent")) if not initialized else ""
            if text is not None:
                prompt = f"{prompt}\n\n{text}".strip()

            def publish() -> None:
                self.metadata.update(session_id)
                task = self.detail(session_id)["task"]
                snapshot({"kind": "task_snapshot", "task": task, "revision": task["revision"]})

            def on_event(event) -> None:
                emit(event)
                if event.kind in {"tool_result", "run_end"}:
                    publish()

            def on_ready() -> None:
                ready()
                publish()

            try:
                return self.sessions.execute_reserved(session_id, prompt, self.policy.mode, on_event, on_ready)
            finally:
                publish()

    def delete(self, session_id: str) -> dict:
        with self.sessions.exclusive():
            self.require(session_id)
            self.repository.delete_session(self.sessions.workspace, session_id)
            self.metadata.remove(session_id)
            self._cache.pop(session_id, None)
        return {"deleted": True}

    def stop(self, session_id: str) -> dict:
        self.require(session_id)
        return self.sessions.stop(session_id)

    def import_legacy(self, session_id: str, value: object) -> dict:
        config = self._normalize(value)
        with self.sessions.exclusive():
            self.sessions.require(session_id)
            current = self.metadata.read(session_id)
            if current is not None:
                matches = current["kind"] == self.policy.kind and current["config"] == config
                return {"id": session_id, "status": "already_imported" if matches else "conflict"}
            view = self.repository.read_session_view(self.sessions.workspace, session_id)
            started_at, duration_ms = self.repository.session_run(self.sessions.workspace, session_id)
            status = "interrupted" if started_at is not None and duration_ms is None else "completed" if view[
                "messages"] else "idle"
            self.metadata.create(session_id, self.policy.kind, config, mode=self.policy.mode, status=status)
        return {"id": session_id, "status": "imported"}
