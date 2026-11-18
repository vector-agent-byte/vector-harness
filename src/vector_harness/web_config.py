from __future__ import annotations

import os
import tempfile
from pathlib import Path

import tomlkit
from tomlkit.exceptions import ParseError


def _read_config(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    return tomlkit.parse(text)


def configured_workdir(path: Path, fallback: Path) -> Path:
    document = _read_config(path)
    value = document.get("workdir")
    if value is None:
        return fallback.resolve()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid config {path}: workdir must be a non-empty string")
    workdir = Path(value).expanduser()
    if not workdir.is_absolute():
        workdir = path.resolve().parent / workdir
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise ValueError(f"invalid config {path}: workdir is not a directory: {workdir}")
    return workdir


def save_workdir(path: Path, workdir: Path) -> None:
    document = _read_config(path)
    document["workdir"] = str(workdir.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(tomlkit.dumps(document))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


CONFIG_ERRORS = (OSError, ValueError, ParseError)
