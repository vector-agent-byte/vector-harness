"""Authoritative validation of the browser's camelCase configuration."""

from copy import deepcopy

from .models import DEFAULTS, ENUMS, FIELDS, REGRESSION_METRICS, is_finite_number


def normalize_config(value: object) -> dict:
    """Fill defaults and return owned values, or raise ValueError naming a field."""
    if not isinstance(value, dict):
        raise ValueError("config: expected an object")
    for field in value:
        if field not in DEFAULTS:
            raise ValueError(f"{field}: unknown configuration field")
    config = deepcopy(DEFAULTS)
    for field, rules in FIELDS.items():
        item = value.get(field, config[field])
        kind = rules["type"]
        if kind == "string":
            if not isinstance(item, str):
                raise ValueError(f"{field}: expected a string")
            try:
                item.encode("utf-8")
            except UnicodeError as error:
                raise ValueError(f"{field}: expected valid Unicode") from error
            item = item.strip()
            if rules.get("required") and not item:
                raise ValueError(f"{field}: must not be empty")
            if "enum" in rules and item not in rules["enum"]:
                raise ValueError(f"{field}: expected one of {', '.join(rules['enum'])}")
        elif kind in ("number", "integer"):
            if not is_finite_number(item):
                raise ValueError(f"{field}: expected a finite number, not a boolean")
            if kind == "integer":
                if int(item) != item:
                    raise ValueError(f"{field}: expected an integer")
                item = int(item)
            if item < rules["minimum"] or ("maximum" in rules and item > rules["maximum"]):
                maximum = rules.get("maximum")
                bounds = f"{rules['minimum']}–{maximum}" if maximum is not None else f">= {rules['minimum']}"
                raise ValueError(f"{field}: expected {bounds}")
        elif kind == "array":
            if not isinstance(item, list):
                raise ValueError(f"{field}: expected a list of algorithm names")
            for index, algorithm in enumerate(item):
                if not isinstance(algorithm, str) or algorithm not in ENUMS["algorithms"]:
                    raise ValueError(f"{field}[{index}]: unsupported algorithm")
            item = list(item)
        config[field] = item
    if config["split"] == "time" and not config["timeColumn"]:
        raise ValueError("timeColumn: required for time split")
    if (config["task"] == "回归") != (config["metric"] in REGRESSION_METRICS):
        raise ValueError("metric: regression requires RMSE or MAE; classification requires a classification metric")
    maximum = FIELDS["threshold"]["maximumByMetric"].get(config["metric"])
    if maximum is not None and config["threshold"] > maximum:
        raise ValueError(f"threshold: expected 0–{maximum} for {config['metric']}")
    return config
