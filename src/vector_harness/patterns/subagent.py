from __future__ import annotations

from dataclasses import dataclass, field

from vector_harness.core.loop import Loop
from vector_harness.core.session import Session


@dataclass
class _Delegate:
    provider: object
    tools: list
    system: str
    context_transforms: list | None = None
    max_steps: int = 10
    name: str = "delegate"
    description: str = "Delegate a task to a child agent."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        task = arguments.get("task", "")
        if not isinstance(task, str):
            task = str(task)
        child_tools = [tool for tool in self.tools if tool.name != "delegate"]
        child = Loop(
            provider=self.provider,
            tools=child_tools,
            session=Session.in_memory(),
            system=self.system,
            context_transforms=self.context_transforms,
            max_steps=self.max_steps,
        )
        result = await child.run(task)
        if result.status == "complete":
            return result.text
        return f"[{result.status}] {result.text}"


def delegate_tool(
    *,
    provider,
    tools: list,
    system: str,
    context_transforms: list | None = None,
    max_steps: int = 10,
) -> _Delegate:
    return _Delegate(
        provider=provider,
        tools=tools,
        system=system,
        context_transforms=context_transforms,
        max_steps=max_steps,
    )
