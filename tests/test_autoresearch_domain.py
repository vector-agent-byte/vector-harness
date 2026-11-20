import copy
import json

import pytest

from vector_harness.autoresearch.models import options
from vector_harness.autoresearch.prompts import build_prompt
from vector_harness.autoresearch.reports import metric_direction, parse_report, project
from vector_harness.autoresearch.validation import normalize_config


REQUIRED = {"dataPath": "train.csv", "target": "label", "description": "预测风险"}
DEFAULTS = {
    "name": "", "description": "", "dataPath": "", "target": "",
    "task": "二分类", "metric": "AUC-ROC", "threshold": 0.85,
    "split": "random", "timeColumn": "", "testRatio": 20, "maxSteps": 20,
    "hours": 2, "parallel": 3, "strategy": "多路择优",
    "algorithms": ["LightGBM", "XGBoost"], "constraints": "",
}


def report(*rows):
    return "```modeling-report\n" + json.dumps({"experiments": rows}) + "\n```"


def test_options_preserve_defaults_and_all_ui_choices_without_shared_mutation():
    result = options()
    assert result["defaults"] == DEFAULTS
    assert result["enums"] == {
        "task": ["二分类", "多分类", "回归"],
        "metric": ["AUC-ROC", "F1", "Accuracy", "Log Loss", "RMSE", "MAE"],
        "split": ["random", "time"],
        "strategy": ["多路择优", "顺序迭代"],
        "algorithms": ["LightGBM", "XGBoost", "CatBoost", "RandomForest"],
    }
    assert set(result["fields"]) == set(DEFAULTS)
    for field, minimum, maximum in (
        ("testRatio", 5, 40), ("maxSteps", 1, 500),
        ("hours", 0.1, 24), ("parallel", 1, 5),
    ):
        assert result["fields"][field]["minimum"] == minimum
        assert result["fields"][field]["maximum"] == maximum
    json.dumps(result, allow_nan=False)
    result["defaults"]["algorithms"].clear()
    result["enums"]["task"].clear()
    result["fields"]["hours"]["maximum"] = 999
    assert options()["defaults"] == DEFAULTS
    assert options()["enums"]["task"] == ["二分类", "多分类", "回归"]
    assert options()["fields"]["hours"]["maximum"] == 24


def test_config_fills_defaults_trims_strings_and_owns_mutable_values():
    value = {**REQUIRED, "dataPath": " train.csv ", "name": " 风险 ", "algorithms": []}
    original = copy.deepcopy(value)
    actual = normalize_config(value)
    assert actual == {**DEFAULTS, **REQUIRED, "name": "风险", "algorithms": []}
    assert value == original
    actual["algorithms"].append("CatBoost")
    assert value["algorithms"] == []
    assert normalize_config(REQUIRED)["algorithms"] == ["LightGBM", "XGBoost"]


@pytest.mark.parametrize("value", [None, True, 1, "config", [], ()])
def test_config_requires_an_object(value):
    with pytest.raises(ValueError, match="config"):
        normalize_config(value)


@pytest.mark.parametrize("field", ["dataPath", "target", "description"])
@pytest.mark.parametrize("value", [None, "", " \n ", 4, False, []])
def test_required_config_fields_reject_missing_or_invalid_text(field, value):
    with pytest.raises(ValueError, match=field):
        normalize_config({**REQUIRED, field: value})
    with pytest.raises(ValueError, match=field):
        normalize_config({key: text for key, text in REQUIRED.items() if key != field})


@pytest.mark.parametrize("field", ["name", "timeColumn", "constraints"])
@pytest.mark.parametrize("value", [None, False, 3, []])
def test_optional_text_fields_still_require_strings(field, value):
    with pytest.raises(ValueError, match=field):
        normalize_config({**REQUIRED, field: value})


@pytest.mark.parametrize("field", ["task", "metric", "split", "strategy"])
@pytest.mark.parametrize("value", ["unknown", None, True, [], {}])
def test_config_enums_reject_unrecognized_or_wrongly_typed_values(field, value):
    with pytest.raises(ValueError, match=field):
        normalize_config({**REQUIRED, field: value})


@pytest.mark.parametrize("value", ["LightGBM", None, True, ["Unknown"], [False], [{}]])
def test_algorithm_selection_requires_a_list_of_supported_names(value):
    with pytest.raises(ValueError, match="algorithms"):
        normalize_config({**REQUIRED, "algorithms": value})


@pytest.mark.parametrize("field", ["threshold", "testRatio", "maxSteps", "hours", "parallel"])
@pytest.mark.parametrize("value", [True, False, None, "2", float("nan"), float("inf"), -float("inf"), [], {}])
def test_numeric_config_fields_reject_coercion_and_nonfinite_values(field, value):
    with pytest.raises(ValueError, match=field):
        normalize_config({**REQUIRED, field: value})


@pytest.mark.parametrize("field,value", [
    ("threshold", -0.1), ("threshold", 1.01),
    ("testRatio", 4.99), ("testRatio", 40.01),
    ("maxSteps", 0), ("maxSteps", 501), ("maxSteps", 1.5),
    ("hours", 0.09), ("hours", 24.01),
    ("parallel", 0), ("parallel", 6), ("parallel", 1.5),
])
def test_config_rejects_out_of_range_and_fractional_integer_fields(field, value):
    with pytest.raises(ValueError, match=field):
        normalize_config({**REQUIRED, field: value})


@pytest.mark.parametrize("overrides", [
    {"testRatio": 5, "maxSteps": 1, "hours": 0.1, "parallel": 1, "threshold": 0},
    {"testRatio": 40, "maxSteps": 500, "hours": 24, "parallel": 5, "threshold": 1},
    {"testRatio": 20.5, "hours": 1.5, "maxSteps": 2.0, "parallel": 3.0},
    {"task": "回归", "metric": "RMSE", "threshold": 100},
    {"task": "回归", "metric": "MAE", "threshold": 100},
    {"task": "多分类", "metric": "Log Loss", "threshold": 100},
    {"task": "多分类", "metric": "Accuracy"},
    {"metric": "F1", "strategy": "顺序迭代"},
    {"algorithms": ["LightGBM", "XGBoost", "CatBoost", "RandomForest"]},
    {"split": "time", "timeColumn": "created_at"},
])
def test_config_accepts_supported_ui_settings_and_range_boundaries(overrides):
    result = normalize_config({**REQUIRED, **overrides})
    for field, value in overrides.items():
        assert result[field] == value
    assert type(result["maxSteps"]) is int
    assert type(result["parallel"]) is int


@pytest.mark.parametrize("overrides,field", [
    ({"task": "回归", "metric": "F1"}, "metric"),
    ({"task": "二分类", "metric": "MAE"}, "metric"),
    ({"task": "多分类", "metric": "RMSE"}, "metric"),
    ({"split": "time", "timeColumn": "  "}, "timeColumn"),
    ({"unexpected": 1}, "unexpected"),
])
def test_config_enforces_cross_field_constraints_and_rejects_unknown_fields(overrides, field):
    with pytest.raises(ValueError, match=field):
        normalize_config({**REQUIRED, **overrides})


@pytest.mark.parametrize("metric,direction", [
    ("RMSE", "minimize"), ("MAE", "minimize"), ("Log Loss", "minimize"),
    ("AUC-ROC", "maximize"), ("F1", "maximize"), ("Accuracy", "maximize"),
])
def test_metric_direction(metric, direction):
    assert metric_direction(metric) == direction


def test_prompt_carries_full_config_parent_and_evaluation_rules_without_granting_permissions():
    config = normalize_config({**REQUIRED, "constraints": "禁止联网", "maxSteps": 8})
    parent = {"id": 2, "title": "旧方案", "score": 0.7, "code": "print('parent')"}
    prompt = build_prompt(config, parent)
    decoder = json.JSONDecoder()
    embedded, _ = decoder.raw_decode(prompt[prompt.index("{"):])
    assert embedded == config
    for text in ("不得编造训练结果", "预处理仅在训练集拟合", "只使用验证集", "最终一次评估", "score 一律为验证集指标", "modeling-report", "8 步", "3 个候选", "2 小时", "指标越高越好", "在当前数据上重新验证", "旧方案", "print('parent')"):
        assert text in prompt
    assert "用户授予你全部权限" not in prompt
    assert "执行任何必要操作" not in prompt
    assert "不需要询问确认" not in prompt
    assert parse_report(prompt) == []
    regression = normalize_config({**REQUIRED, "task": "回归", "metric": "MAE"})
    assert "指标越低越好" in build_prompt(regression)
    with pytest.raises(ValueError, match="dataPath"):
        build_prompt({**REQUIRED, "dataPath": ""})


@pytest.mark.parametrize("field,value", [("id", True), ("score", False), ("score", float("inf"))])
def test_prompt_rejects_invalid_parent_experiment(field, value):
    with pytest.raises(ValueError, match="parent"):
        build_prompt(normalize_config(REQUIRED), {"id": 0, "title": "parent", "score": 0.5, field: value})


@pytest.mark.parametrize("text", [
    "AUC 0.93", "```json\n{\"experiments\": []}\n```",
    "```modeling-report\ninvalid\n```", "```modeling-report\nnull\n```",
    "```modeling-report\n[]\n```", "```modeling-report\n{}\n```",
    '```modeling-report\n{"experiments": {}}\n```',
    report({"id": 0, "title": "incomplete", "score": 0.7})[:-3],
])
def test_parser_ignores_missing_malformed_or_incomplete_reports(text):
    assert parse_report(text) == []


@pytest.mark.parametrize("row", [
    None, [], {}, {"id": 0, "score": 0.9},
    {"id": True, "title": "bad", "score": 0.9},
    {"id": False, "title": "bad", "score": 0.9},
    {"id": -1, "title": "bad", "score": 0.9},
    {"id": 1.5, "title": "bad", "score": 0.9},
    {"id": "1", "title": "bad", "score": 0.9},
    {"id": 1, "title": False, "score": 0.9},
    *[{"id": 1, "title": "bad", "score": score} for score in (True, False, None, "0.9", float("nan"), float("inf"), -float("inf"))],
])
def test_parser_discards_invalid_rows_without_losing_valid_experiments(row):
    text = report(row) + "\n" + report({"id": 2, "title": "valid", "score": 0.5})
    assert [item["id"] for item in parse_report(text)] == [2]


def test_parser_sorts_deduplicates_last_valid_record_and_normalizes_optional_text():
    text = report(
        {"id": 4, "title": "later", "score": 0.9},
        {"id": 2, "title": "old", "score": 0.6},
    ) + "\n" + report({"id": 2.0, "title": "updated", "score": 0.7, "algorithm": "XGBoost", "plan": 5, "result": "真实结论", "code": None, "duration": "2s"})
    text += "\n" + report({"id": 2, "title": "invalid update", "score": "1.0"})
    result = parse_report(text)
    assert [item["id"] for item in result] == [2, 4]
    assert result[0] == {"id": 2, "title": "updated", "score": 0.7, "algorithm": "XGBoost", "plan": "", "result": "真实结论", "code": "", "duration": "2s"}
    assert type(result[0]["id"]) is int


def test_project_empty_results_and_only_main_assistant_output():
    fake = report({"id": 0, "title": "untrusted", "score": 0.99})
    messages = [
        {"role": "user", "content": fake},
        {"role": "tool", "content": fake},
        {"role": "assistant", "origin": "child", "content": fake},
        {"role": "assistant", "content": "开始", "tool_calls": [{"child": {"text": fake}}]},
        {"role": "assistant", "content": "尚无评估结果"},
    ]
    assert project(messages, {"metric": "AUC-ROC"}) == {
        "experiments": [], "baselineId": None, "bestId": None,
        "metricDirection": "maximize", "improvement": None,
        "output": "开始\n\n尚无评估结果",
    }
    assert project([], {"metric": "RMSE"})["output"] == ""


@pytest.mark.parametrize("metric,scores,best_id,improvements", [
    ("AUC-ROC", [0.5, 0.75, 0.75, 0.25], 3, [0, 0.25, 0.25, -0.25]),
    ("RMSE", [4, 2, 2, 8], 3, [0, 2, 2, -4]),
    ("MAE", [4, 4, 4, 8], 1, [0, 0, 0, -4]),
    ("Log Loss", [4, 2, 2, 8], 3, [0, 2, 2, -4]),
])
def test_projection_ranks_by_metric_uses_first_valid_baseline_and_breaks_ties_by_id(metric, scores, best_id, improvements):
    rows = [{"id": experiment_id, "title": str(experiment_id), "score": score} for experiment_id, score in zip([1, 3, 5, 7], scores)]
    text = report(*reversed(rows))
    messages = [{"role": "assistant", "content": text}]
    original = copy.deepcopy(messages)
    result = project(messages, {"metric": metric})
    assert result["baselineId"] == 1
    assert result["bestId"] == best_id
    assert result["improvement"] == max(improvements)
    assert [item["improvement"] for item in result["experiments"]] == improvements
    assert [item["improved"] for item in result["experiments"]] == [value > 0 for value in improvements]
    assert messages == original


def test_projection_waits_for_complete_report_across_assistant_text_fragments():
    messages = [{"role": "assistant", "content": '```modeling-report\n{"experiments": ['}]
    assert project(messages, {"metric": "AUC-ROC"})["bestId"] is None
    messages.append({"role": "assistant", "content": '{"id": 0, "title": "baseline", "score": 0.5}]}\n```'})
    result = project(messages, {"metric": "AUC-ROC"})
    assert result["baselineId"] == result["bestId"] == 0
    assert result["improvement"] == 0


@pytest.mark.parametrize("metric,scores", [
    ("AUC-ROC", [-1e308, 1e308]), ("RMSE", [1e308, -1e308]),
])
def test_projection_keeps_extreme_reported_scores_but_never_emits_infinite_improvement(metric, scores):
    text = report(
        {"id": 0, "title": "baseline", "score": scores[0]},
        {"id": 1, "title": "candidate", "score": scores[1]},
    )
    result = project([{"role": "assistant", "content": text}], {"metric": metric})
    assert result["bestId"] == 1
    assert result["improvement"] is None
    assert result["experiments"][1]["score"] == scores[1]
    assert result["experiments"][1]["improved"] is True
    assert result["experiments"][1]["improvement"] is None
    json.dumps(result, allow_nan=False)


FRAGMENTED_REPORT = report({"id": 12, "title": "实验", "score": 0.875, "code": "print(1)"})


@pytest.mark.parametrize("boundary", range(len(FRAGMENTED_REPORT) + 1))
def test_project_preserves_report_split_at_every_character_boundary(boundary):
    messages = [
        {"role": "assistant", "content": FRAGMENTED_REPORT[:boundary]},
        {"role": "assistant", "content": FRAGMENTED_REPORT[boundary:]},
    ]
    result = project(messages, {"metric": "AUC-ROC"})
    assert result["experiments"] == [{
        "id": 12, "title": "实验", "score": 0.875, "code": "print(1)",
        "algorithm": "", "plan": "", "result": "", "duration": "",
        "improvement": 0, "improved": False,
    }]
    assert result["baselineId"] == result["bestId"] == 12


def test_project_preserves_report_arriving_one_character_at_a_time():
    messages = [{"role": "assistant", "content": character} for character in FRAGMENTED_REPORT]
    result = project(messages, {"metric": "AUC-ROC"})
    assert result["output"] == FRAGMENTED_REPORT
    assert result["experiments"][0]["score"] == 0.875
    assert result["experiments"][0]["title"] == "实验"


def test_project_separates_distinct_prose_and_complete_report_messages():
    contents = [
        "开始训练",
        report({"id": 0, "title": "baseline", "score": 0.5}),
        report({"id": 1, "title": "candidate", "score": 0.75}),
        "训练完成",
    ]
    result = project([{"role": "assistant", "content": content} for content in contents], {"metric": "AUC-ROC"})
    assert result["output"] == "\n\n".join(contents)
    assert [item["id"] for item in result["experiments"]] == [0, 1]
    assert result["bestId"] == 1


def test_parser_keeps_literal_backticks_inside_json_strings():
    code = 'print("```")\nprint("```modeling-report")'
    text = report({"id": 0, "title": "backticks ```", "score": 0.5, "code": code})
    result = parse_report(text)
    assert len(result) == 1
    assert result[0]["code"] == code
    assert result[0]["title"] == "backticks ```"


def test_parser_recovers_at_new_opening_after_unclosed_malformed_report():
    text = '```modeling-report\n{"experiments": [\n'
    text += report({"id": 2, "title": "recovered", "score": 0.75})
    result = parse_report(text)
    assert len(result) == 1
    assert result[0]["id"] == 2
    assert result[0]["score"] == 0.75


@pytest.mark.parametrize("prefix_ending", ["", "\n"])
def test_project_recovers_when_a_new_report_message_follows_a_broken_report(prefix_ending):
    messages = [
        {"role": "assistant", "content": '```modeling-report\n{"experiments": [' + prefix_ending},
        {"role": "assistant", "content": report({"id": 2, "title": "recovered", "score": 0.75})},
    ]
    result = project(messages, {"metric": "AUC-ROC"})
    assert result["bestId"] == 2
    assert result["experiments"][0]["score"] == 0.75


def test_parser_requires_closing_fence_on_its_own_line():
    payload = json.dumps({"experiments": [{"id": 0, "title": "bad fence", "score": 0.5}]})
    assert parse_report("```modeling-report\n" + payload + " ```") == []


def test_parser_accepts_indented_fences_and_windows_line_endings():
    text = '  ```modeling-report\r\n{"experiments": [{"id": 0, "title": "windows", "score": 0.5}]}\r\n  ```  \r\n'
    assert parse_report(text)[0]["title"] == "windows"
