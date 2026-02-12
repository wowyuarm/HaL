from __future__ import annotations

import os

import pytest

from hal.infra.providers.base import LLMResponse
from hal.infra.providers.litellm_provider import LiteLLMProvider


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class _Func:
    def __init__(self, name: str, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id_: str, function: _Func):
        self.id = id_
        self.function = function


class _Msg:
    def __init__(self, content: str | None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message: _Msg, finish_reason: str | None = "stop"):
        self.message = message
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, choice: _Choice, usage: _Usage | None = None):
        self.choices = [choice]
        self.usage = usage


def test_gateway_detection_and_env_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    # OpenRouter keys start with sk-or-
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    p = LiteLLMProvider(api_key="sk-or-test", api_base=None, default_model="anthropic/claude")

    assert p.is_openrouter is True
    assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-test"


def test_resolve_model_gateway_prefix_and_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    # aihubmix detected via api_base keyword, strips provider prefix then prefixes openai/
    p = LiteLLMProvider(
        api_key="k", api_base="https://aihubmix.com/v1", default_model="anthropic/claude"
    )

    assert p._resolve_model("anthropic/claude-3") == "openai/claude-3"
    assert p._resolve_model("openai/gpt-4o") == "openai/gpt-4o"


def test_resolve_model_standard_provider_prefixing() -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    # Dashscope should prefix qwen models
    assert p._resolve_model("qwen-max") == "dashscope/qwen-max"

    # Already prefixed should not double-prefix
    assert p._resolve_model("dashscope/qwen-max") == "dashscope/qwen-max"

    # Zhipu skip_prefixes include openrouter/ so it should not add zai/
    assert p._resolve_model("openrouter/glm-4") == "openrouter/glm-4"


def test_parse_response_tool_calls_and_usage() -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    tc1 = _ToolCall("1", _Func("fs", '{"action":"list","path":"/tmp"}'))
    tc2 = _ToolCall("2", _Func("exec", "not json"))

    resp = _Resp(
        _Choice(_Msg("hello", tool_calls=[tc1, tc2]), finish_reason="tool_calls"),
        usage=_Usage(1, 2, 3),
    )

    parsed = p._parse_response(resp)
    assert isinstance(parsed, LLMResponse)
    assert parsed.content == "hello"
    assert parsed.finish_reason == "tool_calls"
    assert parsed.usage == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}

    assert len(parsed.tool_calls) == 2
    assert parsed.tool_calls[0].name == "fs"
    assert parsed.tool_calls[0].arguments == {"action": "list", "path": "/tmp"}
    assert parsed.tool_calls[1].arguments == {"raw": "not json"}


@pytest.mark.asyncio
async def test_chat_applies_model_overrides_and_passes_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = LiteLLMProvider(
        api_key=None, api_base="http://localhost:8000/v1", default_model="moonshot/kimi-k2.5"
    )

    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return _Resp(_Choice(_Msg("ok")))

    monkeypatch.setattr("hal.infra.providers.litellm_provider.acompletion", fake_acompletion)

    tools = [{"type": "function", "function": {"name": "fs"}}]
    r = await p.chat(messages=[{"role": "user", "content": "hi"}], tools=tools, temperature=0.1)

    assert r.content == "ok"

    # Model override for kimi-k2.5 should set temperature >= 1.0
    assert called["temperature"] == 1.0

    # api_base passed through
    assert called["api_base"] == "http://localhost:8000/v1"

    # tool wiring
    assert called["tools"] == tools
    assert called["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_chat_exception_returns_error_content(monkeypatch: pytest.MonkeyPatch) -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    async def boom(**kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr("hal.infra.providers.litellm_provider.acompletion", boom)

    r = await p.chat(messages=[{"role": "user", "content": "hi"}])
    assert r.finish_reason == "error"
    assert r.content and r.content.startswith("Error calling LLM:")
