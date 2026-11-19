import tomllib
from pathlib import Path

import pytest

from vector_harness.web.config import CONFIG_ERRORS, configured_workdir, save_workdir


def test_missing_workdir_uses_workspace_without_creating_config(tmp_path: Path):
    config = tmp_path / "config.toml"
    assert configured_workdir(config, tmp_path) == tmp_path.resolve()
    assert not config.exists()
    config.write_text('model = "demo"\n', encoding="utf-8")
    assert configured_workdir(config, tmp_path) == tmp_path.resolve()


def test_relative_workdir_is_based_on_config_directory(tmp_path: Path, monkeypatch):
    target = tmp_path / "project"
    target.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    config = tmp_path / "config.toml"
    config.write_text("workdir = 'project'\n", encoding="utf-8")
    monkeypatch.chdir(elsewhere)
    assert configured_workdir(config, elsewhere) == target.resolve()


@pytest.mark.parametrize("value", ['""', "42", "[]", "'missing'", "'config.toml'"])
def test_invalid_workdir_is_not_silently_replaced(tmp_path: Path, value: str):
    config = tmp_path / "config.toml"
    config.write_text(f"workdir = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="workdir"):
        configured_workdir(config, tmp_path)


def test_save_preserves_connection_settings_unknown_sections_and_comments(tmp_path: Path):
    config = tmp_path / "config.toml"
    original = '# connection\napi_key = "test-key" # keep this\nmodel = "demo"\n[custom]\nvalue = [1, 2]\n'
    config.write_text(original, encoding="utf-8")
    for name in ["项目", "second"]:
        target = tmp_path / name
        target.mkdir()
        save_workdir(config, target)
        text = config.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        assert data == {"api_key": "test-key", "model": "demo", "custom": {"value": [1, 2]}, "workdir": str(target.resolve())}
        assert '# connection\napi_key = "test-key" # keep this' in text
        assert configured_workdir(config, tmp_path) == target.resolve()


def test_save_creates_config_and_preserves_existing_file_on_replace_failure(tmp_path: Path, monkeypatch):
    config = tmp_path / "settings" / "config.toml"
    save_workdir(config, tmp_path)
    original = config.read_bytes()

    def fail_replace(self, target):
        raise PermissionError("read only")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError):
        save_workdir(config, tmp_path / "another")
    assert config.read_bytes() == original
    assert not list(config.parent.glob("*.tmp"))


def test_malformed_config_is_not_overwritten(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('api_key = "unfinished', encoding="utf-8")
    original = config.read_bytes()
    with pytest.raises(CONFIG_ERRORS):
        save_workdir(config, tmp_path)
    assert config.read_bytes() == original
