"""Autonomous modeling application entrypoint."""

from vector_harness.agent.application.tasks import TaskService
from vector_harness.autoresearch.validation import normalize_config
from vector_harness.autoresearch.prompts import build_prompt
from vector_harness.autoresearch.reports import project


class ModelingPolicy:
    kind = "autoresearch"
    mode = "plan"
    continuable = False
    normalize_config = staticmethod(normalize_config)
    build_prompt = staticmethod(build_prompt)
    project = staticmethod(project)


class ModelingService(TaskService):
    def __init__(self, sessions):
        super().__init__(sessions, ModelingPolicy())
