"""Routing and request-shaping helpers for LiteLLM provider calls."""

from __future__ import annotations

import os
from typing import Any

from hal.infra.providers.registry import ProviderSpec, find_by_model, find_by_name


def setup_env(
    api_key: str,
    api_base: str | None,
    model: str,
    gateway: ProviderSpec | None,
    provider_name: str = "",
) -> None:
    """Set provider environment variables for LiteLLM dispatch."""
    if gateway:
        # Gateway / local: direct set (not setdefault)
        os.environ[gateway.env_key] = api_key
        return

    spec = find_by_name(provider_name) if provider_name else None
    if spec is None:
        # Standard provider: match by model name
        spec = find_by_model(model)
    if spec is None:
        return

    os.environ.setdefault(spec.env_key, api_key)

    # Resolve env_extras placeholders:
    #   {api_key}  → user's API key
    #   {api_base} → user's api_base, falling back to spec.default_api_base
    effective_base = api_base or spec.default_api_base
    for env_name, env_val in spec.env_extras:
        resolved = env_val.replace("{api_key}", api_key)
        resolved = resolved.replace("{api_base}", effective_base)
        os.environ.setdefault(env_name, resolved)


def resolve_model(
    model: str,
    compat_mode: str,
    gateway: ProviderSpec | None,
    api_base: str | None,
) -> str:
    """Resolve model name by applying provider/gateway prefixes."""
    # compat_mode: model name is passed as-is to the endpoint.
    # custom_llm_provider tells LiteLLM the protocol, so no prefixing is needed.
    if compat_mode:
        return model

    if gateway:
        # Gateway mode: apply gateway prefix, skip provider-specific prefixes.
        prefix = gateway.litellm_prefix
        if gateway.strip_model_prefix:
            model = model.split("/")[-1]
        if prefix and not model.startswith(f"{prefix}/"):
            model = f"{prefix}/{model}"
        return model

    # Standard mode: auto-prefix for known providers.
    spec = find_by_model(model)
    if spec:
        prefix = spec.litellm_prefix
        # When using a custom api_base with a provider that has no litellm_prefix
        # (e.g. OpenAI with a proxy), LiteLLM still needs "openai/" for unknown
        # model names like gpt-5.3-codex.
        if not prefix and api_base:
            prefix = "openai"
        if prefix and not any(model.startswith(s) for s in spec.skip_prefixes):
            model = f"{prefix}/{model}"

    return model


def apply_model_overrides(model: str, kwargs: dict[str, Any]) -> None:
    """Apply model-specific request overrides from provider registry."""
    model_lower = model.lower()
    spec = find_by_model(model)
    if spec is None:
        return

    for pattern, overrides in spec.model_overrides:
        if pattern in model_lower:
            kwargs.update(overrides)
            return


def supports_cache_control(
    model: str,
    gateway: ProviderSpec | None,
    provider_name: str,
) -> bool:
    """Return True when this request path supports Anthropic-style cache_control."""
    spec = gateway
    if spec is None and provider_name:
        spec = find_by_name(provider_name)
    if spec is None:
        spec = find_by_model(model)
    if not spec or not spec.supports_prompt_caching:
        return False

    # OpenRouter can route many providers. Restrict cache_control injection
    # to Anthropic-family models to avoid cross-provider schema issues.
    if spec.name == "openrouter":
        model_lower = model.lower()
        return "claude" in model_lower or "anthropic/" in model_lower
    return True


def _find_last_system_index(messages: list[dict[str, Any]]) -> int | None:
    """Return index of the last system message."""
    return next(
        (idx for idx in range(len(messages) - 1, -1, -1) if messages[idx].get("role") == "system"),
        None,
    )


def _to_text_block(value: Any) -> dict[str, Any]:
    """Normalize arbitrary value into Anthropic text content block."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        return {"type": "text", "text": value}
    return {"type": "text", "text": str(value)}


def _mark_last_block_ephemeral(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach ephemeral cache_control marker to the final block."""
    if not blocks:
        return [{"type": "text", "text": "", "cache_control": {"type": "ephemeral"}}]
    blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    return blocks


def _normalize_system_content(content: Any) -> list[dict[str, Any]]:
    """Normalize system content into Anthropic block list with cache marker."""
    if isinstance(content, str):
        return [
            {
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    if isinstance(content, list):
        return _mark_last_block_ephemeral([_to_text_block(item) for item in content])

    return [
        {
            "type": "text",
            "text": str(content),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _apply_system_cache_control(message: dict[str, Any]) -> dict[str, Any]:
    """Return a copied system message with cache_control-tagged content."""
    updated = dict(message)
    updated["content"] = _normalize_system_content(updated.get("content"))
    return updated


def _apply_tool_cache_control(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Attach ephemeral cache_control marker to the final tool definition."""
    if not tools:
        return tools
    updated_tools = [dict(tool) for tool in tools]
    updated_tools[-1]["cache_control"] = {"type": "ephemeral"}
    return updated_tools


def apply_cache_control(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Inject Anthropic-style cache_control breakpoints for stable prefixes."""
    if not messages:
        return messages, tools

    updated_messages = [dict(msg) for msg in messages]
    system_idx = _find_last_system_index(updated_messages)
    if system_idx is not None:
        updated_messages[system_idx] = _apply_system_cache_control(updated_messages[system_idx])

    updated_tools = _apply_tool_cache_control(tools)
    return updated_messages, updated_tools
