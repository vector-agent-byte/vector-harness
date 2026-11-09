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
    host: Loop | None = field(default=None, repr=False, compare=False)
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
        """把任务交给一层子循环。子循环用不落盘的会话，并且拿不到 ``delegate``。"""
        task = arguments.get("task", "")
        if not isinstance(task, str):
            task = str(task)
        child_tools = [tool for tool in self.tools if tool.name != "delegate"]
        callback = self.host.on_event if self.host is not None else None
        child = Loop(
            provider=self.provider,
            tools=child_tools,
            session=Session.in_memory(),
            system=self.system,
            context_transforms=self.context_transforms,
            max_steps=self.max_steps,
            on_event=callback,
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
    """构造委托工具。默认最多 10 步，调用方负责把它放进父循环的工具列表。"""
    return _Delegate(
        provider=provider,
        tools=tools,
        system=system,
        context_transforms=context_transforms,
        max_steps=max_steps,
    )
