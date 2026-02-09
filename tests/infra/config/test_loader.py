from __future__ import annotations

import json
from pathlib import Path

from hal.infra.config.loader import (
    _migrate_config,
    camel_to_snake,
    convert_keys,
    convert_to_camel,
    get_config_path,
    load_config,
    save_config,
    snake_to_camel,
)
from hal.infra.config.schema import Config


def test_camel_and_snake_conversions() -> None:
    assert camel_to_snake("apiKey") == "api_key"
    assert camel_to_snake("restrictToWorkspace") == "restrict_to_workspace"

    assert snake_to_camel("api_key") == "apiKey"
    assert snake_to_camel("restrict_to_workspace") == "restrictToWorkspace"


def test_convert_keys_nested_dict_and_list() -> None:
    raw = {"tools": {"restrictToWorkspace": True}, "items": [{"apiKey": "x"}]}
    converted = convert_keys(raw)
    assert converted == {"tools": {"restrict_to_workspace": True}, "items": [{"api_key": "x"}]}


def test_convert_to_camel_nested_dict_and_list() -> None:
    raw = {"tools": {"restrict_to_workspace": True}, "items": [{"api_key": "x"}]}
    converted = convert_to_camel(raw)
    assert converted == {"tools": {"restrictToWorkspace": True}, "items": [{"apiKey": "x"}]}


def test_migrate_config_moves_restrict_to_workspace() -> None:
    data = {"tools": {"exec": {"restrictToWorkspace": True}}}
    migrated = _migrate_config(data)
    assert migrated["tools"].get("restrictToWorkspace") is True
    assert "restrictToWorkspace" not in migrated["tools"].get("exec", {})


def test_save_and_load_config_roundtrip(tmp_home: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.model = "openrouter/anthropic/claude-sonnet-4"
    cfg.providers.openrouter.api_key = "sk-or-test"

    save_config(cfg)

    path = get_config_path()
    assert path.exists(), f"expected config at {path}"

    disk = json.loads(path.read_text(encoding="utf-8"))
    # Saved keys should be camelCase
    assert "restrictToWorkspace" in disk.get("tools", {})
    assert "apiKey" in disk.get("providers", {}).get("openrouter", {})

    loaded = load_config()
    assert loaded.agents.defaults.model == "openrouter/anthropic/claude-sonnet-4"
    assert loaded.providers.openrouter.api_key == "sk-or-test"


def test_load_config_invalid_json_falls_back_to_default(tmp_home: Path, capsys) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    cfg = load_config()
    assert isinstance(cfg, Config)

    out = capsys.readouterr().out.lower()
    assert "failed to load config" in out
    assert "default" in out
