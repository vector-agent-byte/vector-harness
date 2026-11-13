"""连接配置。

终端和模型构造读的是同一份文件，但补进环境变量的顺序不同。
这个模块只负责把 TOML 收成三项字符串，不创建客户端。
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vector_harness.types import ProviderError

_CONFIG_KEYS = {
    "api_key": "VECTOR_API_KEY",
    "base_url": "VECTOR_BASE_URL",
    "model": "VECTOR_MODEL",
}


def default_config_path() -> Path:
    """连接配置的默认位置：家目录下的 ``.vector-harness/config.toml``。"""
    return Path.home() / ".vector-harness" / "config.toml"


def apply_config(env: Mapping[str, str], path: Path) -> dict:
    """用配置文件填上环境里还没有的连接项。文件不存在就原样返回。

    终端用这个顺序：已经设好的环境变量保留，文件只补空缺。
    """
    merged = dict(env)
    data = _load_config(path)
    for key, env_name in _CONFIG_KEYS.items():
        if merged.get(env_name):
            continue
        if key not in data:
            continue
        merged[env_name] = _config_value(path, key, data[key])
    return merged


def settings_from_config_then_env(env: Mapping[str, str], path: Path) -> dict:
    """先读配置文件。某一项文件里没有时，再用同名环境变量。"""
    found: dict[str, str] = {}
    data = _load_config(path)
    for key, env_name in _CONFIG_KEYS.items():
        if key in data:
            found[env_name] = _config_value(path, key, data[key])
            continue
        env_value = env.get(env_name) or ""
        if env_value:
            found[env_name] = env_value
    return found


def log_settings_from_config(path: Path) -> dict[str, bool]:
    """读配置文件里的日志开关。文件不存在或没写该键时返回空字典。"""
    data = _load_config(path)
    result: dict[str, bool] = {}
    key = "log_llm_messages"
    if key in data:
        value = data[key]
        if not isinstance(value, bool):
            raise ProviderError(f"invalid config {path}: {key} must be a boolean")
        result[key] = value
    return result


def _load_config(path: Path) -> dict:
    """读配置文件。文件不存在时当作空配置。"""
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ProviderError(f"invalid config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"invalid config {path}: root must be a table")
    return data


def _config_value(path: Path, key: str, value: Any) -> str:
    """配置项必须是非空字符串。"""
    if not isinstance(value, str) or not value:
        raise ProviderError(f"invalid config {path}: {key} must be a non-empty string")
    return value
