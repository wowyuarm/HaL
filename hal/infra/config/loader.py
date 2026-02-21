"""Configuration loading utilities with YAML support and auth separation."""

from pathlib import Path
from typing import Any

import yaml

from hal.infra.config.schema import Config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".hal" / "config.yaml"


def get_auth_path() -> Path:
    """Get the auth credentials file path."""
    return Path.home() / ".hal" / "auth.yaml"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from YAML files.

    Loads config.yaml for structure, then deep-merges auth.yaml for secrets.
    """
    path = config_path or get_config_path()
    auth_path = get_auth_path()

    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            print(f"Warning: Failed to parse {path}: {e}")
            print("Using default configuration.")
            return Config()

    # Merge auth secrets
    if auth_path.exists():
        try:
            with open(auth_path) as f:
                auth_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, auth_data)
        except yaml.YAMLError as e:
            print(f"Warning: Failed to parse {auth_path}: {e}")

    if data:
        try:
            config = Config.model_validate(data)
        except ValueError as e:
            print(f"Warning: Invalid config: {e}")
            print("Using default configuration.")
            return Config()
    else:
        config = Config()

    # Warn about old workspace layout
    old_workspace = Path.home() / ".hal" / "workspace"
    new_soul = config.workspace_path / "SOUL.md"
    if old_workspace.is_dir() and not new_soul.exists():
        print(
            f"Warning: Detected old layout {old_workspace}.\n"
            f"  Run: mv {old_workspace}/* {config.workspace_path}/ "
            f"&& rmdir {old_workspace}"
        )

    return config


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to YAML files.

    Splits secrets into auth.yaml, structure into config.yaml.
    """
    path = config_path or get_config_path()
    auth_path = get_auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump()
    auth_data = _extract_auth(data)

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    if _has_values(auth_data):
        with open(auth_path, "w") as f:
            yaml.dump(auth_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_data_dir() -> Path:
    """Get the HaL data directory."""
    from hal.utils.helpers import get_data_path

    return get_data_path()


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _extract_auth(data: dict) -> dict:
    """Extract auth-sensitive fields from config data, removing them from data in-place."""
    auth: dict[str, Any] = {}

    # Extract provider api_keys
    providers = data.get("providers", {})
    for provider_name, provider_cfg in providers.items():
        if isinstance(provider_cfg, dict) and provider_cfg.get("api_key"):
            auth.setdefault("providers", {}).setdefault(provider_name, {})["api_key"] = (
                provider_cfg.pop("api_key")
            )

    # Extract channel tokens/secrets
    channels = data.get("channels", {})
    channel_auth_fields = {
        "telegram": ["token"],
        "feishu": ["app_secret", "encrypt_key"],
        "discord": ["token"],
    }
    for ch_name, fields in channel_auth_fields.items():
        ch_cfg = channels.get(ch_name, {})
        if isinstance(ch_cfg, dict):
            for field in fields:
                if ch_cfg.get(field):
                    auth.setdefault("channels", {}).setdefault(ch_name, {})[field] = ch_cfg.pop(
                        field
                    )

    # Extract tool api_keys
    tools = data.get("tools", {})
    web = tools.get("web", {})
    search = web.get("search", {})
    if isinstance(search, dict) and search.get("api_key"):
        auth.setdefault("tools", {}).setdefault("web", {}).setdefault("search", {})["api_key"] = (
            search.pop("api_key")
        )

    return auth


def _has_values(d: dict) -> bool:
    """Check if a nested dict has any non-empty leaf values."""
    for v in d.values():
        if isinstance(v, dict):
            if _has_values(v):
                return True
        elif v:
            return True
    return False
