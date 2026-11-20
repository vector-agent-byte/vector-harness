"""Validation for the authoritative research configuration."""


def normalize_config(value: object) -> dict:
    """Return a fresh configuration; omitted engine defaults to standard."""
    if not isinstance(value, dict):
        raise ValueError("Research config must be an object")
    topic = value.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("Research topic must be a non-empty string")
    try:
        topic.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("Research topic must contain valid Unicode") from error
    engine = value.get("engine", "standard")
    if not isinstance(engine, str) or engine.strip() not in {"standard", "advanced"}:
        raise ValueError("Research engine must be standard or advanced")
    return {"topic": topic.strip(), "engine": engine.strip()}
