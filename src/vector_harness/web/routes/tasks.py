"""Structured research and modeling HTTP endpoints."""

from vector_harness.agent.application.errors import ServiceError
from vector_harness.autoresearch.models import options
from vector_harness.web.http import object_body, read_body, segments, send_json
from vector_harness.web.routes.streaming import stream_run


def _service(app, handler):
    return app.tasks[segments(handler.path)[1]]


def create(app, handler, _variables):
    payload = object_body(read_body(handler))
    if payload is None:
        raise ServiceError("bad_request")
    service = _service(app, handler)
    if service.policy.kind == "deepresearch":
        value = service.create(payload)
    else:
        value = service.create(payload.get("config"), parent_session_id=payload.get("parentSessionId"),
                               parent_experiment_id=payload.get("parentExperimentId"))
    send_json(handler, 201, value)


def list_tasks(app, handler, _variables):
    send_json(handler, 200, _service(app, handler).list())


def detail(app, handler, variables):
    send_json(handler, 200, _service(app, handler).detail(variables[0]))


def run(app, handler, variables):
    payload = object_body(read_body(handler))
    if payload is None or payload:
        raise ServiceError("bad_request")
    service = _service(app, handler)
    stream_run(handler,
               lambda emit, ready, snapshot: service.execute(variables[0], emit=emit, ready=ready, snapshot=snapshot))


def messages(app, handler, variables):
    payload = object_body(read_body(handler))
    if payload is None or not isinstance(payload.get("text"), str):
        raise ServiceError("bad_request")
    service = _service(app, handler)
    stream_run(handler, lambda emit, ready, snapshot: service.execute(
        variables[0], text=payload["text"], emit=emit, ready=ready, snapshot=snapshot))


def stop(app, handler, variables):
    send_json(handler, 200, _service(app, handler).stop(variables[0]))


def delete(app, handler, variables):
    send_json(handler, 200, _service(app, handler).delete(variables[0]))


def modeling_options(app, handler, _variables):
    send_json(handler, 200, options())


def import_legacy(app, handler, _variables):
    payload = object_body(read_body(handler))
    if payload is None or not isinstance(payload.get("tasks"), list):
        raise ServiceError("bad_request")
    results = []
    for record in payload["tasks"]:
        session_id = record.get("id") if isinstance(record, dict) else None
        try:
            if not isinstance(record, dict) or not isinstance(record.get("kind"), str) or record[
                "kind"] not in app.tasks:
                raise ServiceError("bad_request")
            results.append(app.tasks[record["kind"]].import_legacy(session_id, record.get("config")))
        except (ServiceError, ValueError, OSError) as error:
            code = error.code if isinstance(error, ServiceError) else "invalid_metadata"
            results.append(
                {"id": session_id, "status": "not_found" if code == "not_found" else "invalid", "error": str(error)})
    send_json(handler, 200, {"results": results})


ROUTES = [
    ("GET", ("api", "autoresearch", "options"), modeling_options),
    ("POST", ("api", "tasks", "import-legacy"), import_legacy),
]
for kind in ("deepresearch", "autoresearch"):
    ROUTES.extend([
        ("GET", ("api", kind, "tasks"), list_tasks),
        ("POST", ("api", kind, "tasks"), create),
        ("GET", ("api", kind, "tasks", None), detail),
        ("DELETE", ("api", kind, "tasks", None), delete),
        ("POST", ("api", kind, "tasks", None, "run"), run),
        ("POST", ("api", kind, "tasks", None, "stop"), stop),
    ])
ROUTES.append(("POST", ("api", "deepresearch", "tasks", None, "messages"), messages))
