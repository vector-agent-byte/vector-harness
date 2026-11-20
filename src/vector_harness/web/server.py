"""HTTP lifecycle and composition root for agent and research services."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vector_harness.agent.application.errors import ServiceError
from vector_harness.agent.application.runs import RunManager, RunSettings
from vector_harness.agent.application.sessions import SessionService
from vector_harness.agent.infrastructure.metadata import MetadataStore
from vector_harness.agent.infrastructure import sessions as session_repository
from vector_harness.autoresearch.service import ModelingService
from vector_harness.deepresearch.service import ResearchService
from vector_harness.agent.patterns.skills import Skills
from vector_harness.web.config import configured_workdir, save_workdir
from vector_harness.web.http import segments, send_error, send_json
from vector_harness.web.routes import agent, files, tasks

_logger = logging.getLogger("vector_harness.web")
_ROUTES = [*agent.ROUTES, *tasks.ROUTES, *files.ROUTES]
_ERROR_STATUS = {
    "not_found": 404,
    "busy": 409,
    "already_run": 409,
    "domain_mode": 409,
    "domain_task": 409,
    "skills_save_failed": 500,
    "invalid_metadata": 500,
}


def _setup_log(log_path: Path) -> logging.Handler:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG)
    provider_logger = logging.getLogger("vector_harness.provider")
    provider_logger.addHandler(handler)
    provider_logger.setLevel(logging.DEBUG)
    return handler


@dataclass(frozen=True, kw_only=True)
class WebSettings:
    workspace: Path
    config_file: Path | None = None
    skills_dir: Path | None = None
    memory_path: Path | None = None
    compact: bool = False
    plan: bool = False
    reflect: bool = False
    subagents: bool = False
    max_steps: int = 50
    dist_dir: Path | None = None


class WebServer:
    def __init__(self, settings: WebSettings, provider: object) -> None:
        self.settings = settings
        self.provider = provider
        self.workdir = configured_workdir(settings.config_file,
                                          settings.workspace) if settings.config_file else settings.workspace.resolve()
        self._log_handler = _setup_log(settings.workspace / ".vector" / "server.log")
        self.port = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.runs = RunManager(RunSettings(
            workspace=settings.workspace, workdir=lambda: self.workdir,
            skills_dir=settings.skills_dir, memory_path=settings.memory_path,
            compact=settings.compact, plan=settings.plan, reflect=settings.reflect,
            subagents=settings.subagents, max_steps=settings.max_steps,
        ), provider)
        self.metadata = MetadataStore(settings.workspace)
        self.metadata.recover()
        self.sessions = SessionService(settings.workspace, self.runs, self.metadata, self.skill_catalog,
                                       repository=session_repository)
        self.tasks = {"deepresearch": ResearchService(self.sessions), "autoresearch": ModelingService(self.sessions)}

    def skill_catalog(self) -> list[dict]:
        return [] if self.settings.skills_dir is None else Skills(self.settings.skills_dir).catalog()

    def save_workdir(self, path: Path) -> None:
        if self.settings.config_file is not None:
            save_workdir(self.settings.config_file, path)

    @property
    def running_id(self) -> str | None:
        return self.runs.running_id

    def request_stop(self, session_id: str) -> bool:
        return self.runs.stop(session_id)

    def start(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._bind(host, port)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def listen(self, host: str, port: int) -> int:
        self._bind(host, port)
        return self.port

    def serve_forever(self, host: str, port: int) -> None:
        if self._httpd is None:
            self._bind(host, port)
        self._serve()

    def shutdown(self) -> None:
        if self.running_id is not None:
            self.request_stop(self.running_id)
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        _logger.removeHandler(self._log_handler)
        logging.getLogger("vector_harness.provider").removeHandler(self._log_handler)
        self._log_handler.close()

    def _bind(self, host: str, port: int) -> None:
        self._httpd = _BoundServer((host, port), self)
        self.port = int(self._httpd.server_address[1])

    def _serve(self) -> None:
        assert self._httpd is not None
        self._httpd.serve_forever()


class _BoundServer(ThreadingHTTPServer):
    def __init__(self, address, app: WebServer):
        self.app = app
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        _route(self, "GET")

    def do_POST(self) -> None:
        _route(self, "POST")

    def do_DELETE(self) -> None:
        _route(self, "DELETE")

    def log_message(self, format: str, *args: object) -> None:
        _logger.info(format, *args)


def _match(method: str, parts: list[str]):
    for route_method, shape, endpoint in _ROUTES:
        if route_method == method and len(shape) == len(parts):
            if all(expected is None or expected == actual for expected, actual in zip(shape, parts)):
                return endpoint, [actual for expected, actual in zip(shape, parts) if expected is None]
    return None, []


def _route(handler: BaseHTTPRequestHandler, method: str) -> None:
    app = handler.server.app
    parts = segments(handler.path)
    try:
        if parts[:1] != ["api"] and method == "GET":
            files.serve_static(app, handler)
            return
        endpoint, variables = _match(method, parts)
        if endpoint is None:
            send_error(handler, 404, "not_found")
            return
        endpoint(app, handler, variables)
    except ServiceError as error:
        payload = {"error": error.code}
        if str(error) != error.code:
            payload["message"] = str(error)
        if error.fields:
            payload["fields"] = error.fields
        send_json(handler, _ERROR_STATUS.get(error.code, 400), payload)
    except (ValueError, OSError):
        _logger.exception("Request failed: %s %s", method, handler.path)
        send_error(handler, 500, "storage_error")
