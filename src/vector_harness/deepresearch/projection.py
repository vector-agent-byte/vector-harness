"""Project research logs without execution, IO, or positional task association."""

import re

from .models import normalize_config


_STATUSES = {"pending", "in_progress", "completed", "skipped", "error", "unknown"}
_CHILD_STATUSES = {
    "queued": "pending", "running": "in_progress", "complete": "completed",
    "stopped": "skipped", "max_steps": "error",
}
_MARKDOWN_LINK = re.compile(r"\[([^]]+)]\((https?://[^\s)]+)\)")
_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _records(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _arguments(call: dict) -> dict:
    for key in ("arguments", "args"):
        if isinstance(call.get(key), dict):
            return call[key]
    return {}


def _status(value: object, *, child: bool = False) -> str:
    if not isinstance(value, str):
        return "unknown"
    if child:
        value = _CHILD_STATUSES.get(value, value)
    return value if value in _STATUSES else "unknown"


def _task(task_id: str, index: int, content: str, status: str) -> dict:
    title, description = content.strip(), ""
    for separator in ("\n", "：", ": "):
        position = content.find(separator)
        if position >= 0 and (separator != ": " or position < 30):
            title, description = content.split(separator, 1)
            break
    return {
        "id": task_id, "index": index, "title": title.strip(),
        "description": description.strip(), "status": status,
    }


def _sources(content: str) -> list[dict]:
    sources = {}
    for match in _MARKDOWN_LINK.finditer(content):
        title, url = match.groups()
        sources.setdefault(url, {"title": title, "url": url, "inferred": True})
    for match in _URL.finditer(content):
        url = match.group().rstrip(".,;:!?")
        sources.setdefault(url, {"title": url, "url": url, "inferred": True})
    return list(sources.values())


def _empty_detail() -> dict:
    return {"queries": [], "notePath": None, "sources": [], "summary": ""}


def _detail(child: dict, results: list[dict]) -> dict:
    """Queries, note paths, and links are log clues, not verified evidence."""
    detail = _empty_detail()
    detail["inferred"] = True
    result_texts = [_text(result.get("content")) for result in results]
    detail["summary"] = _text(child.get("text")) or next(
        (text for text in reversed(result_texts) if text), "",
    )
    source_text = "\n".join([*result_texts, detail["summary"]])
    detail["sources"] = _sources(source_text)
    for tool in _records(child.get("tools")):
        name = _text(tool.get("name"))
        arguments = _arguments(tool)
        command = _text(arguments.get("command"))
        if name == "shell" and any(word in command for word in ("search", "curl", "wget")):
            if command not in detail["queries"]:
                detail["queries"].append(command)
        path = _text(arguments.get("path"))
        if name in {"write_file", "edit", "write"} and ("note" in path or path.endswith(".md")):
            detail["notePath"] = path
    return detail


def project(messages: list[dict], config: dict) -> dict:
    """Use delegate IDs when present, otherwise show the latest unbound todo plan.

    Calls without a stable ID cannot be associated and are omitted. Unknown
    status remains unknown, even when a tool result contains output. Detail
    ``inferred`` labels query and note-path clues; each source also carries it.
    """
    config = normalize_config(config)
    delegates = {}
    results = {}
    todos = []
    report = ""
    has_delegates = False
    for message in _records(messages):
        if message.get("origin") == "child":
            continue
        role = message.get("role")
        if role == "tool":
            call_id = message.get("tool_call_id")
            if isinstance(call_id, str) and call_id:
                results.setdefault(call_id, []).append(message)
        if role != "assistant":
            continue
        content = _text(message.get("content"))
        if content.strip():
            report = content
        for call in _records(message.get("tool_calls")):
            if call.get("name") == "update_todos":
                candidate = _arguments(call).get("todos")
                if isinstance(candidate, list):
                    todos = _records(candidate)
            if call.get("name") != "delegate":
                continue
            has_delegates = True
            call_id = call.get("id")
            if isinstance(call_id, str) and call_id.strip():
                delegates[call_id] = call

    tasks = []
    details = {}
    if has_delegates:
        for call_id, call in delegates.items():
            child = call.get("child") if isinstance(call.get("child"), dict) else {}
            task_text = _text(_arguments(call).get("task"))
            if not task_text.strip():
                task_text = _text(child.get("text")).split("\n")[0].strip() or f"子任务 {len(tasks) + 1}"
            matching_results = results.get(call_id, [])
            status = _status(child.get("status"), child=True)
            if any(result.get("is_error") is True for result in matching_results):
                status = "error"
            tasks.append(_task(call_id, len(tasks), task_text, status))
            details[call_id] = _detail(child, matching_results)
    else:
        for todo in todos:
            content = _text(todo.get("content"))
            if not content.strip():
                continue
            task_id = _text(todo.get("id")) or f"task-{len(tasks)}"
            while task_id in details:
                task_id += "-duplicate"
            tasks.append(_task(task_id, len(tasks), content, _status(todo.get("status"))))
            details[task_id] = _empty_detail()
    return {
        "topic": config["topic"], "tasks": tasks, "details": details, "report": report,
        "progress": {
            "done": sum(task["status"] in {"completed", "skipped"} for task in tasks),
            "total": len(tasks),
        },
    }
