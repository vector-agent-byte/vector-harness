"""TodoList 计划模式（工具方式）。

模型通过 update_todos 工具维护待办列表，不再通过独立的计划请求生成 JSON。
执行完成后若有未完成任务，自动推进直到全部办完。
"""
from __future__ import annotations

import json

from vector_harness.agent.core.loop import Loop
from vector_harness.agent.core.session import Session
from vector_harness.agent.patterns.task_state import TaskContext, TaskState, normalize_todos, render_todos
from vector_harness.types import Message, RunResult, ToolCall

VALID_STATUS = {"pending", "in_progress", "completed"}
STATUS_ICON = {"pending": "[ ]", "in_progress": "[~]", "completed": "[✓]"}

_PLAN_PROMPT = (
    "当请求需要多个步骤时，先调用 update_todos 把任务拆成待办列表，再按顺序执行。\n"
    "每步开始前把状态改为 in_progress，完成后改为 completed，同一时间只许一项 in_progress。\n"
    "简单的一句话问答不必生成待办列表。"
)

_CONTINUE_PROMPT = (
    "计划尚未完成，以下任务仍未完成，请继续执行，"
    "并用 update_todos 更新状态：\n{todos}"
)


def _render(todos: list[dict]) -> str:
    return render_todos(todos)


class UpdateTodosTool:
    """模型用来创建和更新 todolist 的工具。harness 侧维护状态，强制执行约束。"""

    name = "update_todos"
    description = (
        "创建或更新当前任务的待办列表（全量覆盖，非增量）。"
        "同一时间至多一个任务为 in_progress。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "完整的待办列表，按执行顺序排列",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":      {"type": "integer", "description": "序号，从 1 开始"},
                        "content": {"type": "string",  "description": "这一步要做什么"},
                        "status":  {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["id", "content", "status"],
                },
            }
        },
        "required": ["todos"],
    }

    def __init__(self, session: Session | None = None) -> None:
        self.session = session if session is not None else Session.in_memory()
        self.state = TaskState(self.session)
        self.updated_this_run = False

    @property
    def todos(self) -> list[dict]:
        return self.state.restore()

    async def execute(self, arguments: dict) -> str:
        todos = normalize_todos(arguments)
        return json.dumps({"kind": "todo_snapshot", "version": 1, "todos": todos}, ensure_ascii=False)

    def after_result_persisted(self, call: ToolCall, result: Message) -> None:
        if self.state.record(call, result):
            self.updated_this_run = True

    def for_session(self, session: Session) -> UpdateTodosTool:
        return UpdateTodosTool(session)

    def unfinished(self) -> list[dict]:
        return [t for t in self.todos if t["status"] != "completed"]

    def reset(self) -> None:
        self.updated_this_run = False


class TodoPlan:
    """工具化计划：模型调用 update_todos 维护 todolist，harness 自动推进未完成任务。"""

    def __init__(self, loop: Loop) -> None:
        self._tool = UpdateTodosTool(loop.session)
        loop.replace_tool(self._tool)
        loop.install_prompt(_PLAN_PROMPT)
        if not any(isinstance(transform, TaskContext) for transform in loop.context_transforms):
            loop.context_transforms.append(TaskContext(loop.session))
        self.loop = loop

    async def run(self, user_text: str) -> RunResult:
        self._tool.reset()
        result = await self.loop.run(user_text)
        total_steps = result.steps

        while result.status == "complete" and self._tool.updated_this_run and self._tool.unfinished():
            reminder = _CONTINUE_PROMPT.format(todos=_render(self._tool.unfinished()))
            result = await self.loop.run(reminder)
            total_steps += result.steps

        self._tool.reset()
        return RunResult(
            status=result.status,
            text=result.text,
            steps=total_steps,
            session_path=result.session_path,
        )
