from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hal.infra.config.loader import (
    _deep_merge,
    _extract_auth,
    get_auth_path,
    get_config_path,
    load_config,
    save_config,
)
from hal.infra.config.schema import (
    Config,
    EngineConfig,
    ExecToolConfig,
    WebFetchConfig,
    WebSearchConfig,
)


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


def test_load_config_invalid_yaml_raises(tmp_home: Path) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{{not: valid: yaml: [", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        load_config()


# ---------------------------------------------------------------------------
# Strict loading: unknown keys rejected (extra="forbid")
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_rejected(tmp_home: Path) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("bogus_section:\n  foo: 1\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="bogus_section"):
        load_config()


def test_unknown_nested_key_rejected(tmp_home: Path) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("engine:\n  inbound_poll_timeout_s: 2.0\n  typo_key: 42\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="typo_key"):
        load_config()


def test_invalid_config_value_rejected(tmp_home: Path) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("agents:\n  defaults:\n    temperature: not_a_number\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config()


# ---------------------------------------------------------------------------
# Field constraints: boundary validation
# ---------------------------------------------------------------------------


def test_timeout_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        EngineConfig(inbound_poll_timeout_s=0)


def test_timeout_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        ExecToolConfig(timeout=-1)


def test_max_redirects_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        WebFetchConfig(max_redirects=0)


def test_max_results_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        WebSearchConfig(max_results=0)
    with pytest.raises(ValidationError):
        WebSearchConfig(max_results=11)


def test_valid_constraints_accepted() -> None:
    """Sanity check that valid values pass validation."""
    assert EngineConfig(inbound_poll_timeout_s=0.1).inbound_poll_timeout_s == 0.1
    assert ExecToolConfig(timeout=1).timeout == 1
    assert WebFetchConfig(max_redirects=1).max_redirects == 1
    assert WebSearchConfig(max_results=10).max_results == 10


# ---------------------------------------------------------------------------
# Default values preserve existing behavior
# ---------------------------------------------------------------------------


def test_defaults_match_original_hardcoded_values() -> None:
    """Verify that default config values match the original hardcoded constants."""
    cfg = Config()

    # Engine
    assert cfg.engine.inbound_poll_timeout_s == 1.0
    assert cfg.engine.summary_barrier_timeout_s == 10.0

    # Web tools
    assert cfg.tools.web.search.max_results == 5
    assert cfg.tools.web.search.timeout_s == 10.0
    assert cfg.tools.web.fetch.default_max_chars == 50000
    assert cfg.tools.web.fetch.timeout_s == 30.0
    assert cfg.tools.web.fetch.max_redirects == 5

    # Exec
    assert cfg.tools.exec.timeout == 60
    assert cfg.tools.exec.kill_wait_s == 5

    # Memory search
    assert cfg.memory_search.embed_retry_attempts == 3
    assert cfg.memory_search.embed_retry_base_delay_s == 0.5
    assert cfg.memory_search.embed_timeout_s == 60.0
    assert cfg.memory_search.exclude_channels == []

    # Channels
    assert cfg.channels.outbound_poll_timeout_s == 1.0
