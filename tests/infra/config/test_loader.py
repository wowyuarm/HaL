from __future__ import annotations

from pathlib import Path

import yaml

from hal.infra.config.loader import (
    _deep_merge,
    _extract_auth,
    get_auth_path,
    get_config_path,
    load_config,
    save_config,
)
from hal.infra.config.schema import Config


def test_deep_merge_overrides_nested() -> None:
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"b": 10}, "e": 5}
    result = _deep_merge(base, override)
    assert result == {"a": {"b": 10, "c": 2}, "d": 3, "e": 5}


def test_extract_auth_separates_secrets() -> None:
    data = {
        "providers": {
            "anthropic": {"api_key": "sk-test", "api_base": None},
            "openai": {"api_key": "", "api_base": None},
        },
        "channels": {
            "telegram": {"enabled": True, "token": "abc123"},
        },
        "tools": {"web": {"search": {"api_key": "tvly-xxx", "max_results": 5}}},
    }
    auth = _extract_auth(data)

    # Secrets extracted
    assert auth["providers"]["anthropic"]["api_key"] == "sk-test"
    assert auth["channels"]["telegram"]["token"] == "abc123"
    assert auth["tools"]["web"]["search"]["api_key"] == "tvly-xxx"

    # Removed from original data
    assert "api_key" not in data["providers"]["anthropic"]
    assert "token" not in data["channels"]["telegram"]
    assert "api_key" not in data["tools"]["web"]["search"]

    # Empty api_key not extracted
    assert "openai" not in auth.get("providers", {})


def test_save_and_load_config_roundtrip(tmp_home: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.model = "openrouter/anthropic/claude-sonnet-4"
    cfg.providers.openrouter.api_key = "sk-or-test"

    save_config(cfg)

    config_path = get_config_path()
    auth_path = get_auth_path()
    assert config_path.exists()
    assert auth_path.exists()

    # Config file should use snake_case natively
    config_data = yaml.safe_load(config_path.read_text())
    assert "restrict_to_workspace" in config_data.get("tools", {})
    # api_key should NOT be in config.yaml (extracted to auth.yaml)
    assert not config_data.get("providers", {}).get("openrouter", {}).get("api_key")

    # Auth file should have the secret
    auth_data = yaml.safe_load(auth_path.read_text())
    assert auth_data["providers"]["openrouter"]["api_key"] == "sk-or-test"

    # Full roundtrip
    loaded = load_config()
    assert loaded.agents.defaults.model == "openrouter/anthropic/claude-sonnet-4"
    assert loaded.providers.openrouter.api_key == "sk-or-test"


def test_load_config_invalid_yaml_falls_back_to_default(tmp_home: Path, capsys) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{{not: valid: yaml: [", encoding="utf-8")

    cfg = load_config()
    assert isinstance(cfg, Config)

    out = capsys.readouterr().out.lower()
    assert "failed to parse" in out
    assert "default" in out
