import ast
import copy
from pathlib import Path
import sys

import pytest

from vector_harness.deepresearch.models import normalize_config
from vector_harness.deepresearch.prompts import build_prompt
from vector_harness.deepresearch.projection import project


CONFIG = {"topic": "机器学习", "engine": "standard"}


def call_message(*calls):
    return {"role": "assistant", "content": "", "tool_calls": list(calls)}


def delegate(call_id, task="方向：说明", status="complete", **child):
    return {
        "id": call_id,
        "name": "delegate",
        "arguments": {"task": task},
        "child": {"status": status, "text": "", "tools": [], **child},
    }


def test_normalize_config_trims_defaults_and_copies():
    original = {"topic": "  机器学习\n"}
    assert normalize_config(original) == CONFIG
    assert original == {"topic": "  机器学习\n"}
    assert normalize_config({"topic": "主题", "engine": " advanced "}) == {
        "topic": "主题", "engine": "advanced",
    }


@pytest.mark.parametrize("value", [
    None, [], "topic", 1, True, {}, {"topic": " \n"}, {"topic": 1},
    {"topic": None}, {"topic": "topic", "engine": "other"},
    {"topic": "topic", "engine": None}, {"topic": "topic", "engine": []},
])
def test_invalid_config_raises_value_error(value):
    with pytest.raises(ValueError):
        normalize_config(value)


@pytest.mark.parametrize("engine, preference", [
    ("standard", "标准搜索"), ("advanced", "高级搜索，优先学术和权威来源"),
])
def test_prompt_preserves_research_instructions(engine, preference):
    prompt = build_prompt({"topic": "  海洋  ", "engine": engine})
    for text in ["主题：海洋", preference, "简单主题2-3个", "复杂主题4-6个",
                 "实际检索词和来源URL", "2-4个可靠来源", "发布日期", "笔记", "结构化研究报告"]:
        assert text in prompt
    assert "不得编造" in prompt


def test_parent_report_is_context_and_inputs_are_unchanged():
    parent = {"topic": "旧主题", "report": "已有报告：结果有待核实"}
    original = copy.deepcopy(parent)
    prompt = build_prompt(CONFIG, parent)
    assert parent["report"] in prompt
    assert parent["topic"] in prompt
    assert parent == original
    with pytest.raises(ValueError):
        build_prompt({"topic": ""})


def test_empty_projection_uses_authoritative_config():
    assert project([], CONFIG) == {
        "topic": "机器学习", "tasks": [], "details": {}, "report": "",
        "progress": {"done": 0, "total": 0},
    }


def test_delegate_details_follow_ids_despite_todo_and_result_order():
    messages = [
        {"role": "user", "content": "主题：不应采用的主题"},
        call_message({"name": "update_todos", "args": {"todos": [
            {"id": "todo-b", "content": "计划B", "status": "completed"},
            {"id": "todo-a", "content": "计划A", "status": "completed"},
        ]}}),
        call_message(delegate("call-a", "方向A\n描述A", "running"),
                     delegate("call-b", "方向B：描述B")),
        {"role": "tool", "tool_call_id": "call-b", "content": "B [来源B](https://b.test/paper)"},
        {"role": "tool", "tool_call_id": "unrelated", "content": "https://wrong.test"},
        {"role": "tool", "tool_call_id": "call-a", "content": "A https://a.test/paper."},
        {"role": "assistant", "content": "最终主报告"},
        {"role": "assistant", "origin": "child", "content": "子代理报告"},
        call_message({"name": "shell", "id": "shell", "arguments": {}}),
    ]
    before = copy.deepcopy(messages)
    result = project(messages, CONFIG)
    assert result["topic"] == CONFIG["topic"]
    assert result["tasks"] == [
        {"id": "call-a", "index": 0, "title": "方向A", "description": "描述A", "status": "in_progress"},
        {"id": "call-b", "index": 1, "title": "方向B", "description": "描述B", "status": "completed"},
    ]
    assert result["details"]["call-a"]["summary"].startswith("A ")
    assert result["details"]["call-b"]["summary"].startswith("B ")
    assert result["details"]["call-a"]["sources"] == [
        {"title": "https://a.test/paper", "url": "https://a.test/paper", "inferred": True},
    ]
    assert result["report"] == "最终主报告"
    assert result["progress"] == {"done": 1, "total": 2}
    assert messages == before


@pytest.mark.parametrize("raw, expected", [
    ("queued", "pending"), ("running", "in_progress"), ("complete", "completed"),
    ("stopped", "skipped"), ("max_steps", "error"), ("error", "error"),
    ("pending", "pending"), ("in_progress", "in_progress"), ("completed", "completed"),
    ("skipped", "skipped"), (None, "unknown"), ("new_status", "unknown"), ([], "unknown"),
])
def test_child_status_mapping_never_assumes_success(raw, expected):
    result = project([call_message(delegate("stable", status=raw))], CONFIG)
    assert result["tasks"][0]["status"] == expected
    assert result["progress"]["done"] == int(expected in {"completed", "skipped"})


def test_delegate_without_trace_is_unknown_even_with_tool_result():
    result = project([
        call_message({"id": "raw-id", "name": "delegate", "args": {"task": "Raw: details"}}),
        {"role": "tool", "tool_call_id": "raw-id", "content": "partial output"},
    ], CONFIG)
    assert result["tasks"][0] == {
        "id": "raw-id", "index": 0, "title": "Raw", "description": "details", "status": "unknown",
    }
    assert result["details"]["raw-id"]["summary"] == "partial output"


def test_tool_error_overrides_successful_child_status():
    result = project([
        call_message(delegate("failed")),
        {"role": "tool", "tool_call_id": "failed", "content": "failed", "is_error": True},
    ], CONFIG)
    assert result["tasks"][0]["status"] == "error"


def test_latest_todo_plan_has_empty_details_and_unknown_status():
    messages = [
        call_message({"name": "update_todos", "arguments": {"todos": [
            {"id": "old", "content": "旧任务", "status": "completed"},
        ]}}),
        call_message({"name": "update_todos", "args": {"todos": [
            {"id": "plan-a", "content": "任务A：说明", "status": "skipped"},
            {"content": "任务B", "status": "unrecognized"},
        ]}}),
        {"role": "tool", "tool_call_id": "plan-a", "content": "https://unrelated.test"},
    ]
    result = project(messages, CONFIG)
    assert [task["status"] for task in result["tasks"]] == ["skipped", "unknown"]
    assert result["tasks"][0]["title"] == "任务A"
    assert result["progress"] == {"done": 1, "total": 2}
    for task in result["tasks"]:
        detail = result["details"][task["id"]]
        assert detail["queries"] == []
        assert detail["notePath"] is None
        assert detail["sources"] == []
        assert detail["summary"] == ""


def test_trace_clues_and_all_source_links_are_inferred_and_deduplicated():
    summary = "[论文](https://paper.test/a) https://other.test/b. [重复](https://paper.test/a)"
    task = delegate("trace", text=summary, tools=[
        {"name": "shell", "arguments": {"command": "curl https://paper.test/a"}},
        {"name": "shell", "args": {"command": "search climate"}},
        {"name": "shell", "args": {"command": "pwd"}},
        {"name": "write_file", "arguments": {"path": "notes/climate.md"}},
        {"name": "write", "args": {"path": "latest.md"}},
        {"name": "write", "args": {"path": "data.csv"}},
    ])
    detail = project([call_message(task)], CONFIG)["details"]["trace"]
    assert detail["queries"] == ["curl https://paper.test/a", "search climate"]
    assert detail["notePath"] == "latest.md"
    assert detail["inferred"] is True
    assert detail["summary"] == summary
    assert detail["sources"] == [
        {"title": "论文", "url": "https://paper.test/a", "inferred": True},
        {"title": "https://other.test/b", "url": "https://other.test/b", "inferred": True},
    ]


def test_duplicate_delegate_snapshots_update_same_stable_task():
    messages = [call_message(delegate("same", status="running")),
                call_message(delegate("same", status="complete", text="done"))]
    result = project(messages, CONFIG)
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["status"] == "completed"
    assert result["details"]["same"]["summary"] == "done"


def test_malformed_optional_logs_do_not_invent_tasks_or_completion():
    messages = [
        {"role": "assistant", "content": None, "tool_calls": None},
        call_message(None, {"name": "delegate", "id": None},
                     {"name": "delegate", "id": "broken", "arguments": [],
                      "child": {"text": 4, "tools": [None, {"name": []}], "status": {}}}),
    ]
    result = project(messages, CONFIG)
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["id"] == "broken"
    assert result["tasks"][0]["status"] == "unknown"
    assert result["details"]["broken"]["summary"] == ""
    assert result["progress"] == {"done": 0, "total": 1}


def test_missing_delegate_id_does_not_fall_back_to_unrelated_todos():
    messages = [call_message(
        {"name": "update_todos", "args": {"todos": [
            {"id": "plan", "content": "计划", "status": "completed"},
        ]}},
        {"name": "delegate", "child": {"status": "complete", "text": "无ID"}},
    )]
    result = project(messages, CONFIG)
    assert result["tasks"] == []
    assert result["details"] == {}
    assert result["progress"] == {"done": 0, "total": 0}


def test_arguments_null_uses_args_and_reordering_preserves_details():
    first = delegate("first", text="First", tools=[
        {"name": "shell", "arguments": None, "args": {"command": "wget https://first.test"}},
    ])
    first["arguments"] = None
    first["args"] = {"task": "First task"}
    second = delegate("second", text="Second")
    result = project([call_message(first, second)], CONFIG)
    reordered = project([call_message(second, first)], CONFIG)
    assert result["details"] == reordered["details"]
    assert result["tasks"][0]["title"] == "First task"
    assert result["details"]["first"]["queries"] == ["wget https://first.test"]


def test_empty_latest_plan_clears_previous_tasks():
    messages = [
        call_message({"name": "update_todos", "arguments": {"todos": [
            {"content": "旧计划", "status": "pending"},
        ]}}),
        call_message({"name": "update_todos", "args": {"todos": []}}),
    ]
    assert project(messages, CONFIG)["tasks"] == []


def test_domain_modules_only_import_stdlib_and_each_other():
    domain = Path(__file__).parents[1] / "src" / "vector_harness" / "deepresearch"
    for module in ("__init__", "models", "prompts", "projection"):
        tree = ast.parse((domain / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    assert node.level == 1
                    assert node.module in {"models", "prompts", "projection"}
                else:
                    assert node.module is not None
                    assert node.module.split(".")[0] in sys.stdlib_module_names
            elif isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
