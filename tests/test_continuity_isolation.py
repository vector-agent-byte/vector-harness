import asyncio

from tests.scripted import ScriptedProvider, ScriptedTurn
from vector_harness import Message, Session, ToolCall, VectorHarness, attach
from vector_harness.patterns.subagent import delegate_tool
from vector_harness.patterns.plan import UpdateTodosTool
from vector_harness.patterns.task_state import TaskContext
from vector_harness.tools.history import ReadSessionHistory


def test_parallel_children_rebind_session_components():
    parent = Session.in_memory()
    parent.append(Message(role="user", content="parent secret"))
    sessions = []

    class TrackingContext(TaskContext):
        def for_session(self, session):
            sessions.append(session)
            return TaskContext(session)

    provider = ScriptedProvider(turns=[
        ScriptedTurn(tool_calls=[ToolCall(id="todo", name="update_todos", arguments={"todos": [{"content": "child", "status": "completed"}]})]),
        ScriptedTurn(content="done"), ScriptedTurn(content="done"),
    ])
    tool = delegate_tool(provider=provider, tools=[UpdateTodosTool(parent), ReadSessionHistory(parent)], system="", context_transforms=[TrackingContext(parent)])

    async def children():
        return await asyncio.gather(tool.execute({"task": "child one"}), tool.execute({"task": "child two"}))

    asyncio.run(children())
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert all(session is not parent for session in sessions)
    assert UpdateTodosTool(parent).todos == []
    assert len(parent.load()) == 1


def test_attachment_order_and_budget_binding():
    agent = VectorHarness(name="test", llm=object(), system_prompt="")
    attach(agent, plan=True)
    attach(agent, compact=True)
    attach(agent, plan=True, compact=True)
    assert [type(item).__name__ for item in agent.loop.context_transforms] == ["Compaction", "TaskContext"]
    assert [tool.name for tool in agent.loop.tools].count("read_session_history") == 1
    assert agent.loop.context_transforms[0].extra_context_chars is not None
