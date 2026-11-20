"""Pure configuration, prompt and report handling for AutoResearch."""

from .models import options
from .prompts import build_prompt
from .reports import metric_direction, parse_report, project
from .validation import normalize_config

__all__ = [
    "build_prompt",
    "metric_direction",
    "normalize_config",
    "options",
    "parse_report",
    "project",
]
