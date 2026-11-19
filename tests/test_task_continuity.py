import asyncio
import json

from tests.scripted import ScriptedProvider, ScriptedTurn, summary_json
from vector_harness import Message, Session, ToolCall, VectorHarness, attach
from vector_harness.core.loop import Loop
from vector_harness.patterns.compact import Compaction
from vector_harness.patterns.compact_state import load_checkpoint
from vector_harness.patterns.plan import TodoPlan
from vector_harness.patterns.task_state import TaskState
from vector_harness.tools.history import ReadSessionHistory


def test_long_task_compact_restart_query_and_continue(tmp_path):
    path = tmp_path / "long.jsonl"
    session = Session(path)
    pending = [{"id": 1, "content": "verified", "status": "completed"}, {"id": 2, "content": "remaining", "status": "pending"}]
    provider = ScriptedProvider([ScriptedTurn(tool_calls=[ToolCall("todo", "update_todos", {"todos": pending})])])
    runner = TodoPlan(Loop(provider=provider, tools=[], session=session, system="", max_steps=1))
    assert asyncio.run(runner.run("original task evidence " * 300)).status == "max_steps"
    session.append(Message(role="user", content="retained evidence " * 200))
    summary_provider = ScriptedProvider([ScriptedTurn(content=summary_json(remaining=["remaining"])), ScriptedTurn(content=summary_json(remaining=["remaining"], verification=["verified"]))])
    compact = Compaction(summary_provider, max_chars=2000, keep_last=2, session=session)
    asyncio.run(compact.apply(session.load()))
    first = load_checkpoint(session).covered_count
    session.append(Message(role="assistant", content="more evidence " * 200))
    session.append(Message(role="user", content="latest request"))
    asyncio.run(compact.apply(session.load()))
    assert load_checkpoint(session).covered_count > first
    before = path.read_bytes()
    finished = [{**item, "status": "completed"} for item in pending]
    resumed_provider = ScriptedProvider([
        ScriptedTurn(content="当前进度"),
        ScriptedTurn(tool_calls=[ToolCall("finish", "update_todos", {"todos": finished})]),
        ScriptedTurn(content="完成"),
    ])
    resumed_session = Session(path)
    resumed_loop = Loop(provider=resumed_provider, tools=[ReadSessionHistory(resumed_session)], session=resumed_session, system="")
    resumed_loop.context_transforms.append(Compaction(summary_provider, max_chars=100000, keep_last=2, session=resumed_session))
    resumed = TodoPlan(resumed_loop)
    assert resumed_provider.calls == [] and path.read_bytes() == before
    assert asyncio.run(resumed.run("只告诉我进度")).text == "当前进度"
    assert len(resumed_provider.calls) == 1
    assert TaskState(resumed_session).restore() == pending
    projected = json.dumps(resumed_provider.calls[0]["messages"], ensure_ascii=False)
    assert "[任务摘要 v1]" in projected and "[当前会话待办]" in projected
    assert "original task evidence" not in projected
    recalled = json.loads(asyncio.run(ReadSessionHistory(resumed_session).execute({"start": 1, "end": 1})))
    assert "original task evidence" in recalled["entries"][0]["text"]
    assert asyncio.run(resumed.run("继续完成剩余任务")).text == "完成"
    assert TaskState(Session(path)).restore() == finished
    assert path.read_bytes().startswith(before)


def test_partial_result_restart_does_not_duplicate_effect(tmp_path):
    calls = []

    class Effect:
        name = "effect"
        description = "effect"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, arguments):
            calls.append("executed")
            return "done"

    path = tmp_path / "effect.jsonl"
    session = Session(path)
    session.append(Message(role="assistant", content="", tool_calls=[ToolCall("effect", "effect", {})]))
    effect = Effect()
    asyncio.run(effect.execute({}))
    provider = ScriptedProvider([ScriptedTurn(content="需要核查")])
    loop = Loop(provider=provider, tools=[effect], session=Session(path), system="")
    assert calls == ["executed"] and provider.calls == []
    assert asyncio.run(loop.run("查询执行状态")).text == "需要核查"
    assert calls == ["executed"]
    assert "执行结果未知" in provider.calls[0]["messages"][1]["content"]
    assert not any(message.role == "tool" for message in Session(path).load())


def test_disabled_compact_legacy_and_repeated_attach(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text('{"role":"user","content":"legacy"}\n', encoding="utf-8")
    provider = ScriptedProvider([ScriptedTurn(content="ok")])
    loop = Loop(provider=provider, tools=[], session=Session(path), system="")
    asyncio.run(loop.run("hello"))
    assert len(provider.calls) == 1
    assert not path.with_suffix(".context.json").exists()
    agent = VectorHarness(name="memory", llm=ScriptedProvider([ScriptedTurn(content="ok")]), system_prompt="")
    attach(agent, compact=True, plan=True)
    attach(agent, compact=True, plan=True)
    assert len(agent.loop.context_transforms) == 2
    assert agent.run("hello") == "ok"
    assert agent.loop.session.path is None
