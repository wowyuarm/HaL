from __future__ import annotations

import hal.cli.factory as factory
from hal.infra.config.schema import Config


def test_make_provider_passes_resolved_provider_name(monkeypatch) -> None:
    config = Config()
    config.agents.defaults.model = "anthropic/claude-opus-4-6"
    config.providers.anyrouter.api_key = "sk-test"
    config.providers.anyrouter.api_base = "http://127.0.0.1:3181"

    captured = {}

    class DummyProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("hal.infra.providers.litellm_provider.LiteLLMProvider", DummyProvider)

    provider = factory.make_provider(config)
    assert isinstance(provider, DummyProvider)
    assert captured["provider_name"] == "anyrouter"


def test_make_alternate_provider_passes_resolved_provider_name(monkeypatch) -> None:
    config = Config()
    config.agents.defaults.model = "gpt-4o"
    config.providers.openai.api_key = "openai-key"
    config.providers.anyrouter.api_key = "sk-test"
    config.providers.anyrouter.api_base = "http://127.0.0.1:3181"

    captured = {}

    class DummyProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("hal.infra.providers.litellm_provider.LiteLLMProvider", DummyProvider)

    provider = factory._make_alternate_provider(config, "anthropic/claude-opus-4-6")
    assert isinstance(provider, DummyProvider)
    assert captured["provider_name"] == "anyrouter"


def test_make_provider_passes_request_params(monkeypatch) -> None:
    config = Config()
    config.agents.defaults.model = "gpt-4o"
    config.providers.openai.api_key = "openai-key"
    config.providers.openai.request_params = {
        "prompt_cache_key": "hal-cache-key",
        "prompt_cache_retention": "24h",
    }

    captured = {}

    class DummyProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("hal.infra.providers.litellm_provider.LiteLLMProvider", DummyProvider)

    provider = factory.make_provider(config)
    assert isinstance(provider, DummyProvider)
    assert captured["request_params"] == {
        "prompt_cache_key": "hal-cache-key",
        "prompt_cache_retention": "24h",
    }


def test_make_memory_search_returns_none_when_pymilvus_missing(monkeypatch) -> None:
    config = Config()
    calls: list[str] = []

    def fake_module_available(name: str) -> bool:
        calls.append(name)
        return name != "pymilvus"

    monkeypatch.setattr(factory, "_module_available", fake_module_available)

    result = factory.make_memory_search(config)

    assert result is None
    assert "pymilvus" in calls


def test_make_memory_search_returns_none_when_milvus_lite_missing_on_local_uri(monkeypatch) -> None:
    config = Config()
    calls: list[str] = []

    def fake_module_available(name: str) -> bool:
        calls.append(name)
        return name != "milvus_lite"

    monkeypatch.setattr(factory, "_module_available", fake_module_available)

    result = factory.make_memory_search(config)

    assert result is None
    assert "milvus_lite" in calls
