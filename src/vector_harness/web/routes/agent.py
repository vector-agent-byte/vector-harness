"""Compatibility HTTP endpoints for agent session use cases."""

from vector_harness.agent.application.errors import ServiceError
from vector_harness.web.http import object_body, query_first, read_body, send_json
from vector_harness.web.routes.streaming import stream_run


def skills(app, handler, _variables):
    send_json(handler, 200, {"skills": app.sessions.catalog()})


def create(app, handler, _variables):
    send_json(handler, 201, app.sessions.create())


def list_sessions(app, handler, _variables):
    model = getattr(app.provider, "model", "")
    send_json(handler, 200, {"sessions": app.sessions.list(query_first(handler.path, "kind")),
                             "running_id": app.running_id, "model": model if isinstance(model, str) else ""})


def detail(app, handler, variables):
    send_json(handler, 200, app.sessions.detail(variables[0]))


def delete(app, handler, variables):
    send_json(handler, 200, app.sessions.delete(variables[0]))


def stop(app, handler, variables):
    send_json(handler, 200, app.sessions.stop(variables[0]))


def mode(app, handler, variables):
    payload = object_body(read_body(handler))
    send_json(handler, 200, app.sessions.set_mode(variables[0], payload.get("mode") if payload else None))


def session_skills(app, handler, variables):
    payload = object_body(read_body(handler))
    if payload is None or "names" not in payload:
        raise ServiceError("bad_request")
    send_json(handler, 200, app.sessions.set_skills(variables[0], payload["names"]))


def skill(app, handler, variables):
    payload = object_body(read_body(handler))
    if payload is None or "name" not in payload:
        raise ServiceError("bad_request")
    name = payload["name"]
    if name is not None and not isinstance(name, str):
        raise ServiceError("bad_request")
    chosen = name.strip() if isinstance(name, str) else ""
    send_json(handler, 200, app.sessions.set_skills(variables[0], [chosen] if chosen else [], single=True))


def messages(app, handler, variables):
    session_id = variables[0]
    payload = object_body(read_body(handler))
    app.sessions.require(session_id)
    if payload is None or not isinstance(payload.get("text"), str):
        raise ServiceError("bad_request")
    if "mode" in payload and (
            not isinstance(payload["mode"], str) or payload["mode"] not in {"react", "plan", "reflect", "subagents"}):
        raise ServiceError("bad_request")
    metadata = app.metadata.read(session_id)
    service = app.tasks.get(metadata["kind"]) if metadata else None
    if service is not None:
        if "mode" in payload and payload["mode"] != metadata.get("mode"):
            raise ServiceError("domain_mode")
        stream_run(handler, lambda emit, ready, snapshot: service.execute(
            session_id, text=payload["text"], emit=emit, ready=ready, snapshot=snapshot))
    else:
        stream_run(handler, lambda emit, ready, _snapshot: app.sessions.execute(
            session_id, payload["text"], payload.get("mode"), emit, ready))


ROUTES = [
    ("GET", ("api", "skills"), skills),
    ("GET", ("api", "sessions"), list_sessions),
    ("POST", ("api", "sessions"), create),
    ("GET", ("api", "sessions", None), detail),
    ("DELETE", ("api", "sessions", None), delete),
    ("POST", ("api", "sessions", None, "messages"), messages),
    ("POST", ("api", "sessions", None, "stop"), stop),
    ("POST", ("api", "sessions", None, "mode"), mode),
    ("POST", ("api", "sessions", None, "skill"), skill),
    ("POST", ("api", "sessions", None, "skills"), session_skills),
]
