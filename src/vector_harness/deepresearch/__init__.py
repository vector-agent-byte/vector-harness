"""Pure configuration, prompt generation, and research log projection."""

from .models import normalize_config
from .projection import project
from .prompts import build_prompt

__all__ = ["normalize_config", "build_prompt", "project"]
