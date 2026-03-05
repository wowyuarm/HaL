from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from hal.infra.providers.base import LLMResponse
from hal.infra.providers.litellm import LiteLLMProvider


class _Usage:
    def __init__(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cache_creation_input_tokens: int | None = None,
        cache_read_input_tokens: int | None = None,
        prompt_cache_miss_tokens: int | None = None,
        prompt_tokens_details=None,
        _cache_creation_input_tokens: int | None = None,
        _cache_read_input_tokens: int | None = None,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.prompt_cache_miss_tokens = prompt_cache_miss_tokens
        self.prompt_tokens_details = prompt_tokens_details
        self._cache_creation_input_tokens = _cache_creation_input_tokens
        self._cache_read_input_tokens = _cache_read_input_tokens


class _PromptTokensDetails:
    def __init__(self, cached_tokens: int):
        self.cached_tokens = cached_tokens


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


# --- sanitize_messages tests ---


class TestSanitizeMessages:
    """Tests for _sanitize_messages static method."""

    def test_drops_unknown_keys(self) -> None:
        messages = [
            {"role": "assistant", "content": "hi", "reasoning_content": "thinking..."},
            {"role": "user", "content": "hello", "extra_field": True},
        ]
        result = LiteLLMProvider._sanitize_messages(messages)
        assert result[0] == {"role": "assistant", "content": "hi"}
        assert result[1] == {"role": "user", "content": "hello"}

    def test_preserves_reasoning_content_when_enabled(self) -> None:
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "fs"}}]
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": tool_calls,
                "reasoning_content": "thinking...",
            }
        ]
        result = LiteLLMProvider._sanitize_messages(messages, preserve_reasoning_content=True)
        assert result[0]["reasoning_content"] == "thinking..."

    def test_fills_missing_reasoning_content_for_assistant_tool_call_when_enabled(self) -> None:
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "fs"}}]
        messages = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
        result = LiteLLMProvider._sanitize_messages(messages, preserve_reasoning_content=True)
        assert result[0]["reasoning_content"] == ""

    def test_converts_null_content_to_empty_string(self) -> None:
        messages = [
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "system", "content": None},
        ]
        result = LiteLLMProvider._sanitize_messages(messages)
        assert result[0]["content"] == ""
        assert result[0]["tool_calls"] == []
        assert result[1]["content"] == ""

    def test_preserves_multimodal_content(self) -> None:
        content = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            {"type": "text", "text": "describe this"},
        ]
        messages = [{"role": "user", "content": content}]
        result = LiteLLMProvider._sanitize_messages(messages)
        assert result[0]["content"] is content

    def test_preserves_valid_tool_messages(self) -> None:
        messages = [
            {"role": "tool", "tool_call_id": "call_1", "name": "fs", "content": '{"ok": true}'},
        ]
        result = LiteLLMProvider._sanitize_messages(messages)
        assert result[0] == messages[0]

    def test_preserves_assistant_tool_calls(self) -> None:
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "fs"}}]
        messages = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
        result = LiteLLMProvider._sanitize_messages(messages)
        assert result[0]["tool_calls"] == tool_calls

    def test_unknown_role_passes_through(self) -> None:
        messages = [{"role": "developer", "content": "hello", "extra": True}]
        result = LiteLLMProvider._sanitize_messages(messages)
        assert result[0] == messages[0]

    def test_empty_messages_list(self) -> None:
        assert LiteLLMProvider._sanitize_messages([]) == []


def test_gateway_detection_and_env_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    # OpenRouter keys start with sk-or-
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    p = LiteLLMProvider(api_key="sk-or-test", api_base=None, default_model="anthropic/claude")

    assert p.is_openrouter is True
    assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-test"


def test_resolve_model_standard_provider_prefixing() -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    # DeepSeek should add deepseek/ prefix
    assert p._resolve_model("deepseek-chat") == "deepseek/deepseek-chat"

    # Already prefixed should not double-prefix
    assert p._resolve_model("deepseek/deepseek-chat") == "deepseek/deepseek-chat"

    # Zhipu skip_prefixes include openrouter/ so it should not add zai/
    assert p._resolve_model("openrouter/glm-4") == "openrouter/glm-4"


def test_provider_name_forces_gateway_on_local_anyrouter_base() -> None:
    p = LiteLLMProvider(
        api_key="test-key",
        api_base="http://127.0.0.1:3181",
        default_model="anthropic/claude-opus-4-5",
        provider_name="anyrouter",
    )

    assert p._gateway is not None
    assert p._gateway.name == "anyrouter"
    assert p._resolve_model("anthropic/claude-opus-4-5") == "anthropic/claude-opus-4-5"


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


def test_parse_response_usage_includes_cache_fields() -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")
    usage = _Usage(
        100,
        20,
        120,
        cache_creation_input_tokens=80,
        cache_read_input_tokens=16,
        prompt_cache_miss_tokens=24,
    )
    resp = _Resp(_Choice(_Msg("ok")), usage=usage)

    parsed = p._parse_response(resp)
    assert parsed.usage["prompt_tokens"] == 100
    assert parsed.usage["completion_tokens"] == 20
    assert parsed.usage["total_tokens"] == 120
    assert parsed.usage["cache_creation_input_tokens"] == 80
    assert parsed.usage["cache_read_input_tokens"] == 16
    assert parsed.usage["prompt_cache_miss_tokens"] == 24


def test_extract_usage_maps_anthropic_input_output_tokens() -> None:
    usage = SimpleNamespace(input_tokens=77, output_tokens=9)

    parsed = LiteLLMProvider._extract_usage(usage)
    assert parsed["prompt_tokens"] == 77
    assert parsed["completion_tokens"] == 9
    assert parsed["total_tokens"] == 86


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

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)

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
async def test_chat_preserves_reasoning_content_for_moonshot_tool_call_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = LiteLLMProvider(
        api_key=None,
        api_base=None,
        default_model="moonshot/kimi-k2.5",
    )
    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return _Resp(_Choice(_Msg("ok")))

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)

    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "fs", "arguments": '{"action":"list","path":"."}'},
        }
    ]
    await p.chat(
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": tool_calls,
                "reasoning_content": "thinking...",
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "fs", "content": "[]"},
            {"role": "user", "content": "continue"},
        ]
    )

    assistant_msg = called["messages"][0]
    assert assistant_msg["reasoning_content"] == "thinking..."


@pytest.mark.asyncio
@pytest.mark.parametrize("max_tokens", [0, -10])
async def test_chat_clamps_non_positive_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
    max_tokens: int,
) -> None:
    p = LiteLLMProvider(
        api_key=None,
        api_base=None,
        default_model="gpt-4o",
    )
    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return _Resp(_Choice(_Msg("ok")))

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)

    await p.chat(messages=[{"role": "user", "content": "hi"}], max_tokens=max_tokens)

    assert called["max_tokens"] == 1


@pytest.mark.asyncio
async def test_chat_passes_provider_request_params(monkeypatch: pytest.MonkeyPatch) -> None:
    p = LiteLLMProvider(
        api_key=None,
        api_base=None,
        default_model="gpt-4o",
        request_params={"prompt_cache_key": "k1", "prompt_cache_retention": "in_memory"},
    )
    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return _Resp(_Choice(_Msg("ok")))

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)

    await p.chat(messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])

    assert called["prompt_cache_key"] == "k1"
    assert called["prompt_cache_retention"] == "in_memory"


@pytest.mark.asyncio
async def test_chat_applies_cache_control_on_anthropic_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude-opus-4-6")
    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return _Resp(_Choice(_Msg("ok")))

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)

    tools = [
        {"type": "function", "function": {"name": "fs", "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "exec", "parameters": {"type": "object"}}},
    ]
    await p.chat(
        messages=[
            {"role": "system", "content": "stable system prompt"},
            {"role": "user", "content": "hi"},
        ],
        tools=tools,
    )

    assert isinstance(called["messages"][0]["content"], list)
    assert called["messages"][0]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert called["tools"][-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_chat_does_not_apply_cache_control_on_non_anthropic_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="gpt-4o-mini")
    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return _Resp(_Choice(_Msg("ok")))

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)

    await p.chat(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
    )

    assert called["messages"][0]["content"] == "sys"


@pytest.mark.asyncio
async def test_chat_openrouter_non_claude_skips_cache_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = LiteLLMProvider(
        api_key="sk-or-test",
        api_base="https://openrouter.ai/api/v1",
        default_model="deepseek-chat",
        provider_name="openrouter",
    )
    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return _Resp(_Choice(_Msg("ok")))

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)

    await p.chat(messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])

    assert called["model"].startswith("openrouter/")
    assert called["messages"][0]["content"] == "sys"


@pytest.mark.asyncio
async def test_chat_exception_returns_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    async def boom(**kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", boom)

    r = await p.chat(messages=[{"role": "user", "content": "hi"}])
    assert r.finish_reason == "error"
    assert r.content is None
    assert r.error_message == "fail"
    assert r.retryable is False


@pytest.mark.asyncio
async def test_chat_anyrouter_forces_stream_aggregation(monkeypatch: pytest.MonkeyPatch) -> None:
    p = LiteLLMProvider(
        api_key="test-key",
        api_base="http://127.0.0.1:3181",
        default_model="claude-opus-4-6",
        provider_name="anyrouter",
    )
    called = {}

    async def fake_acompletion(**kwargs):
        called.update(kwargs)
        return object()

    async def fake_aggregate(stream):
        return LLMResponse(content="ok")

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", fake_acompletion)
    monkeypatch.setattr(p, "_aggregate_stream", fake_aggregate)

    r = await p.chat(messages=[{"role": "user", "content": "hi"}])

    assert r.content == "ok"
    assert called["stream"] is True


@pytest.mark.asyncio
async def test_chat_exception_strips_raw_response_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    async def boom(**kwargs):
        raise RuntimeError(
            "AnthropicException - Unable to get json response. "
            "Original Response: event: message_start\\ndata:{...}"
        )

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", boom)

    r = await p.chat(messages=[{"role": "user", "content": "hi"}])
    assert r.error_message is not None
    assert "Original Response:" not in r.error_message
    assert "event: message_start" not in r.error_message
    assert r.retryable is True


@pytest.mark.asyncio
async def test_chat_retryable_error_sets_retryable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    async def boom(**kwargs):
        raise RuntimeError("litellm.APIConnectionError: AnthropicException - b''")

    monkeypatch.setattr("hal.infra.providers.litellm.provider.acompletion", boom)

    r = await p.chat(messages=[{"role": "user", "content": "hi"}])
    assert r.finish_reason == "error"
    assert r.retryable is True


@pytest.mark.asyncio
async def test_aggregate_stream_separates_tool_calls_when_index_is_reused() -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="openai/gpt-5.3-codex")

    def _tc(*, index: int, id_: str | None, name: str | None, arguments: str):
        return SimpleNamespace(
            index=index,
            id=id_,
            function=SimpleNamespace(name=name, arguments=arguments),
        )

    def _chunk(*, tool_calls: list[object], finish_reason: str | None = None):
        delta = SimpleNamespace(content=None, reasoning_content=None, tool_calls=tool_calls)
        choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
        return SimpleNamespace(choices=[choice], usage=None)

    async def _stream():
        # LiteLLM /responses path can emit every tool call with index=0.
        # Verify we still keep calls separate based on call ID + ordering.
        yield _chunk(tool_calls=[_tc(index=0, id_="call_fs", name="fs", arguments="")])
        yield _chunk(
            tool_calls=[
                _tc(
                    index=0,
                    id_=None,
                    name=None,
                    arguments='{"action":"list","path":"."}',
                )
            ]
        )
        yield _chunk(tool_calls=[_tc(index=0, id_="call_web", name="web_search", arguments="")])
        yield _chunk(
            tool_calls=[
                _tc(
                    index=0,
                    id_=None,
                    name=None,
                    arguments='{"query":"abc"}',
                )
            ],
            finish_reason="tool_calls",
        )

    result = await p._aggregate_stream(_stream())

    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].id == "call_fs"
    assert result.tool_calls[0].name == "fs"
    assert result.tool_calls[0].arguments == {"action": "list", "path": "."}
    assert result.tool_calls[1].id == "call_web"
    assert result.tool_calls[1].name == "web_search"
    assert result.tool_calls[1].arguments == {"query": "abc"}


@pytest.mark.asyncio
async def test_aggregate_stream_usage_includes_cache_fields() -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")

    async def _stream():
        delta = SimpleNamespace(content="hello", reasoning_content=None, tool_calls=None)
        choice = SimpleNamespace(delta=delta, finish_reason="stop")
        usage = _Usage(
            120,
            20,
            140,
            cache_creation_input_tokens=80,
            cache_read_input_tokens=16,
            prompt_cache_miss_tokens=30,
        )
        yield SimpleNamespace(choices=[choice], usage=usage)

    result = await p._aggregate_stream(_stream())

    assert result.usage["prompt_tokens"] == 120
    assert result.usage["completion_tokens"] == 20
    assert result.usage["total_tokens"] == 140
    assert result.usage["cache_creation_input_tokens"] == 80
    assert result.usage["cache_read_input_tokens"] == 16
    assert result.usage["prompt_cache_miss_tokens"] == 30


def test_parse_response_reads_cached_tokens_from_prompt_token_details() -> None:
    p = LiteLLMProvider(api_key=None, api_base=None, default_model="anthropic/claude")
    usage = _Usage(
        10,
        2,
        12,
        cache_creation_input_tokens=None,
        cache_read_input_tokens=None,
        prompt_tokens_details=_PromptTokensDetails(cached_tokens=6),
    )
    resp = _Resp(_Choice(_Msg("ok")), usage=usage)

    parsed = p._parse_response(resp)
    assert parsed.usage["cache_read_input_tokens"] == 6
