"""Per-request SSE sinks; execution never retains an HTTP handler."""

from vector_harness.web.http import begin_event_stream, event_payload, write_event


def stream_run(handler, execute):
    started = False

    def ready():
        nonlocal started
        started = True
        try:
            begin_event_stream(handler)
        except OSError:
            pass

    def emit(event):
        write_event(handler, event_payload(event))

    try:
        status, content = execute(emit, ready, lambda payload: write_event(handler, payload))
    except Exception as error:
        if not started:
            raise
        status, content = "error", str(error)
    write_event(handler, {"kind": "run_result", "status": status, "text": content,
                          "name": "", "tool_call_id": "", "arguments": None, "origin": ""})
