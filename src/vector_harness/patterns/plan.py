from __future__ import annotations

import json

from vector_harness.core.loop import Loop
from vector_harness.types import Message, ProviderError, RunResult

_PLAN_SYSTEM = 'Reply with JSON only, of the form {"steps": ["..."]}.'


def format_plan(steps: list[str]) -> str:
    lines = ["Plan:"]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. {step}")
    return "\n".join(lines)


def _parse_steps(text: str) -> list[str] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    steps = data.get("steps")
    if not isinstance(steps, list):
        return None
    if not all(isinstance(item, str) for item in steps):
        return None
    return steps


class PlanThenExecute:
    def __init__(self, loop: Loop) -> None:
        self.loop = loop

    async def _collect_plan(self, user_content: str) -> str:
        text = ""
        async for event in self.loop.provider.stream(
            system=_PLAN_SYSTEM,
            messages=[Message(role="user", content=user_content)],
            tools=[],
        ):
            if self.loop.on_event is not None:
                self.loop.on_event(event)
            if event.kind == "text_delta":
                text += event.text
        return text

    async def run(self, user_text: str) -> RunResult:
        prompt = user_text
        last_text = ""
        for attempt in range(1, 3):
            try:
                last_text = await self._collect_plan(prompt)
            except ProviderError as exc:
                return RunResult(
                    status="error",
                    text=str(exc),
                    steps=attempt,
                    session_path=self.loop.session.path,
                )
            steps = _parse_steps(last_text)
            if steps is not None:
                self.loop.session.append(
                    Message(role="user", content=format_plan(steps))
                )
                result = await self.loop.run(user_text)
                return RunResult(
                    status=result.status,
                    text=result.text,
                    steps=result.steps + attempt,
                    session_path=result.session_path,
                )
            prompt = f"Invalid plan JSON: {last_text}"
        return RunResult(
            status="error",
            text=prompt,
            steps=2,
            session_path=self.loop.session.path,
        )
