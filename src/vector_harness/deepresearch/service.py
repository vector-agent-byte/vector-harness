"""Research application entrypoint."""

from vector_harness.agent.application.tasks import TaskService
from vector_harness.deepresearch.models import normalize_config
from vector_harness.deepresearch.prompts import build_prompt
from vector_harness.deepresearch.projection import project


class ResearchPolicy:
    kind = "deepresearch"
    mode = "subagents"
    continuable = True
    normalize_config = staticmethod(normalize_config)
    build_prompt = staticmethod(build_prompt)
    project = staticmethod(project)


class ResearchService(TaskService):
    def __init__(self, sessions):
        super().__init__(sessions, ResearchPolicy())
