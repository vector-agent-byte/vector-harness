"""JSON-compatible AutoResearch configuration and experiment records."""

from copy import deepcopy
from math import isfinite
from typing import TypeGuard


MINIMIZE_METRICS = ("RMSE", "MAE", "Log Loss")
REGRESSION_METRICS = ("RMSE", "MAE")
ENUMS = {
    "task": ["二分类", "多分类", "回归"],
    "metric": ["AUC-ROC", "F1", "Accuracy", "Log Loss", "RMSE", "MAE"],
    "split": ["random", "time"],
    "strategy": ["多路择优", "顺序迭代"],
    "algorithms": ["LightGBM", "XGBoost", "CatBoost", "RandomForest"],
}
DEFAULTS = {
    "name": "",
    "description": "",
    "dataPath": "",
    "target": "",
    "task": "二分类",
    "metric": "AUC-ROC",
    "threshold": 0.85,
    "split": "random",
    "timeColumn": "",
    "testRatio": 20,
    "maxSteps": 20,
    "hours": 2,
    "parallel": 3,
    "strategy": "多路择优",
    "algorithms": ["LightGBM", "XGBoost"],
    "constraints": "",
}
FIELDS = {
    "name": {"type": "string"},
    "description": {"type": "string", "required": True},
    "dataPath": {"type": "string", "required": True},
    "target": {"type": "string", "required": True},
    "task": {"type": "string", "enum": ENUMS["task"]},
    "metric": {
        "type": "string",
        "enum": ENUMS["metric"],
        "enumByTask": {
            "二分类": ["AUC-ROC", "F1", "Accuracy", "Log Loss"],
            "多分类": ["AUC-ROC", "F1", "Accuracy", "Log Loss"],
            "回归": list(REGRESSION_METRICS),
        },
    },
    "threshold": {
        "type": "number", "minimum": 0,
        "maximumByMetric": {"AUC-ROC": 1, "F1": 1, "Accuracy": 1},
        "defaultByTask": {"二分类": 0.85, "多分类": 0.85, "回归": 1},
    },
    "split": {"type": "string", "enum": ENUMS["split"]},
    "timeColumn": {"type": "string", "requiredWhen": {"split": "time"}},
    "testRatio": {"type": "number", "minimum": 5, "maximum": 40},
    "maxSteps": {"type": "integer", "minimum": 1, "maximum": 500},
    "hours": {"type": "number", "minimum": 0.1, "maximum": 24},
    "parallel": {"type": "integer", "minimum": 1, "maximum": 5},
    "strategy": {"type": "string", "enum": ENUMS["strategy"]},
    "algorithms": {"type": "array", "items": {"type": "string", "enum": ENUMS["algorithms"]}},
    "constraints": {"type": "string"},
}


def options() -> dict:
    """Return independent form defaults, enums and field constraints."""
    return deepcopy({"defaults": DEFAULTS, "fields": FIELDS, "enums": ENUMS})


def is_finite_number(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def normalize_experiment(value: object) -> dict | None:
    """Accept only reported numeric results; optional text defaults to empty."""
    if not isinstance(value, dict):
        return None
    experiment_id = value.get("id")
    if not is_finite_number(experiment_id) or experiment_id < 0 or int(experiment_id) != experiment_id:
        return None
    if not isinstance(value.get("title"), str) or not is_finite_number(value.get("score")):
        return None
    result = {"id": int(experiment_id), "title": value["title"], "score": value["score"]}
    for field in ("algorithm", "plan", "result", "code", "duration"):
        result[field] = value[field] if isinstance(value.get(field), str) else ""
    return result
