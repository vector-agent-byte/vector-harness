from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, fields

from vector_harness.agent.core.session import Session
from vector_harness.agent.core.session_state import SessionArtifacts, prefix_digest

SUMMARY_MAX_CHARS = 12000
_logger = logging.getLogger(__name__)


@dataclass
class Summary:
    goal: list[str]
    constraints: list[str]
    decisions: list[str]
    completed: list[str]
    remaining: list[str]
    verification: list[str]
    references: list[str]


def parse_summary(text: str) -> Summary:
    payload = json.loads(text)
    if not isinstance(payload, dict) or set(payload) != {field.name for field in fields(Summary)}:
        raise ValueError("summary must contain exactly seven fields")
    if any(not isinstance(items, list) or any(not isinstance(item, str) for item in items) for items in payload.values()):
        raise ValueError("summary fields must be string lists")
    summary = Summary(**payload)
    if len(render_summary(summary)) > SUMMARY_MAX_CHARS:
        raise ValueError("summary exceeds character limit")
    return summary


def render_summary(summary: Summary) -> str:
    return "[任务摘要 v1]\n派生历史，可能不完整；最新用户要求优先，历史状态需核查。\n" + json.dumps(asdict(summary), ensure_ascii=False)


@dataclass
class Checkpoint:
    covered_count: int
    prefix_digest: str
    summary: Summary
    created_at: float
    model: str | None


def load_checkpoint(session: Session) -> Checkpoint | None:
    payload = (SessionArtifacts(session).load("context") or {}).get("checkpoint")
    if payload is None:
        return None
    try:
        count = payload["covered_count"]
        if type(count) is not int or count <= 0:
            raise ValueError("invalid checkpoint count")
        if payload["prefix_digest"] != prefix_digest(session.load(), count):
            raise ValueError("checkpoint history changed")
        summary = parse_summary(json.dumps(payload["summary"], ensure_ascii=False))
        timestamp = payload["created_at"]
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
            raise ValueError("invalid checkpoint timestamp")
        model = payload["model"]
        if model is not None and not isinstance(model, str):
            raise ValueError("invalid checkpoint model")
        return Checkpoint(count, payload["prefix_digest"], summary, timestamp, model)
    except (KeyError, TypeError, ValueError):
        _logger.warning("Ignoring invalid or stale context checkpoint")
        return None


def save_checkpoint(session: Session, checkpoint: Checkpoint) -> None:
    SessionArtifacts(session).update("context", {"checkpoint": asdict(checkpoint)})
