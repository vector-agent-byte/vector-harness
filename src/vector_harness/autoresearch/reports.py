"""Project agent-reported experiments without claiming independent evaluation."""

import json
import re
from collections.abc import Iterable, Iterator

from .models import ENUMS, MINIMIZE_METRICS, is_finite_number, normalize_experiment


_OPENING = re.compile(r" {0,3}```modeling-report[ \t]*\r?")
_CLOSING = re.compile(r" {0,3}```[ \t]*\r?")


def _report_blocks(text: str) -> Iterator[str]:
    body = None
    for line in text.split("\n"):
        if _OPENING.fullmatch(line):
            body = []
        elif body is not None:
            if _CLOSING.fullmatch(line):
                yield "\n".join(body)
                body = None
            else:
                body.append(line)


def _opening_prefix(line: str) -> bool:
    candidate = line.lstrip(" ")
    return bool(candidate) and len(line) - len(candidate) <= 3 and (
        "```modeling-report".startswith(candidate) or _OPENING.fullmatch(line) is not None
    )


def _join_fragments(fragments: Iterable[str]) -> str:
    """Preserve partial report tokens and separate complete assistant messages."""
    chunks = []
    tail = ""
    in_report = False
    for fragment in fragments:
        if not fragment:
            continue
        continuing = (
            in_report and _CLOSING.fullmatch(tail) is None
            or not in_report and _opening_prefix(tail)
        )
        first_line, newline, _ = fragment.partition("\n")
        restarting = in_report and bool(newline) and _OPENING.fullmatch(first_line) is not None
        if chunks and (not continuing or restarting):
            chunks.append("\n\n" if not fragment.startswith("\n") else "")
            tail = ""
            in_report = False
        chunks.append(fragment)
        lines = (tail + fragment).split("\n")
        for line in lines[:-1]:
            if _OPENING.fullmatch(line):
                in_report = True
            elif _CLOSING.fullmatch(line):
                in_report = False
        tail = lines[-1]
    return "".join(chunks)


def metric_direction(metric: str) -> str:
    if metric not in ENUMS["metric"]:
        raise ValueError("metric: unsupported evaluation metric")
    return "minimize" if metric in MINIMIZE_METRICS else "maximize"


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def parse_report(text: str) -> list[dict]:
    """Read standalone fenced blocks, recovering at each new report opener."""
    experiments = {}
    for block in _report_blocks(text):
        try:
            parsed = json.loads(block, parse_constant=_invalid_constant)
        except (ValueError, RecursionError):
            continue
        if not isinstance(parsed, dict) or not isinstance(parsed.get("experiments"), list):
            continue
        for row in parsed["experiments"]:
            experiment = normalize_experiment(row)
            if experiment is not None:
                experiments[experiment["id"]] = experiment
    return [experiments[experiment_id] for experiment_id in sorted(experiments)]


def project(messages: list[dict], config: dict) -> dict:
    """Rank reported scores; an improvement outside finite range is None."""
    output = _join_fragments(
        message["content"] for message in messages
        if message.get("role") == "assistant"
        and message.get("origin", "main") != "child"
        and isinstance(message.get("content"), str)
    )
    direction = metric_direction(config.get("metric", "AUC-ROC"))
    experiments = parse_report(output)
    baseline = experiments[0] if experiments else None
    best = None
    for experiment in experiments:
        improvement = experiment["score"] - experiments[0]["score"]
        if direction == "minimize":
            improvement = -improvement
        experiment["improvement"] = improvement if is_finite_number(improvement) else None
        experiment["improved"] = improvement > 0
        if best is None or (
            experiment["score"] < best["score"] if direction == "minimize"
            else experiment["score"] > best["score"]
        ):
            best = experiment
    return {
        "experiments": experiments,
        "baselineId": baseline["id"] if baseline is not None else None,
        "bestId": best["id"] if best is not None else None,
        "metricDirection": direction,
        "improvement": best["improvement"] if best is not None else None,
        "output": output,
    }
