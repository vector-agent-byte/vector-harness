from __future__ import annotations

from dataclasses import dataclass, field, replace

from vector_harness.core.loop import Loop
from vector_harness.core.session import Session
from vector_harness.types import ProviderEvent


@dataclass
class _Delegate:
    provider: object
    tools: list
    system: str
    context_transforms: list | None = None
    tool_hooks: list | None = None
    max_steps: int = 50
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

        def on_event(event: ProviderEvent) -> None:
            """子循环的事件带上 child，终端才能和父循环分开。"""
            callback(replace(event, origin="child"))

        child = Loop(
            provider=self.provider,
            tools=child_tools,
            session=Session.in_memory(),
            system=self.system,
            context_transforms=self.context_transforms,
            tool_hooks=self.tool_hooks,
            max_steps=self.max_steps,
            on_event=on_event if callback is not None else None,
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
    tool_hooks: list | None = None,
    max_steps: int = 50,
) -> _Delegate:
    """构造委托工具。默认最多 50 步，调用方负责把它放进父循环的工具列表。"""
    return _Delegate(
        provider=provider,
        tools=tools,
        system=system,
        context_transforms=context_transforms,
        tool_hooks=tool_hooks,
        max_steps=max_steps,
    )


def attach_delegate(loop: Loop, *, provider, max_steps: int) -> None:
    """装上 ``delegate``。子循环拿不到这个工具，事件回到父循环的观察回调。"""
    child_tools = [tool for tool in loop.tools if tool.name != "delegate"]
    delegate = delegate_tool(
        provider=provider,
        tools=child_tools,
        system=loop.system,
        context_transforms=loop.context_transforms,
        tool_hooks=loop.tool_hooks,
        max_steps=max_steps,
    )
    loop.replace_tool(delegate)
    delegate.host = loop
