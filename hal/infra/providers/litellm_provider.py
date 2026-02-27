"""LiteLLM provider implementation for multi-provider support."""

import json
import logging
import os
from typing import Any

import litellm
from litellm import acompletion

from hal.infra.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from hal.infra.providers.registry import find_by_model, find_by_name, find_gateway

logger = logging.getLogger(__name__)


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.  Provider-specific logic is driven by the registry
    (see providers/registry.py) — no if-elif chains needed here.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        compat_mode: str = "",
        provider_name: str = "",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._compat_mode = compat_mode
        self.provider_name = provider_name

        # In compat_mode, skip gateway detection — the user explicitly declared
        # the protocol, so auto-detection (vLLM fallback etc.) is unnecessary.
        if compat_mode:
            self._gateway = None
        else:
            forced = find_by_name(provider_name) if provider_name else None
            if forced and (forced.is_gateway or forced.is_local):
                self._gateway = forced
            else:
                self._gateway = find_gateway(api_key, api_base, default_model)
        self._force_stream_aggregate = bool(
            self._compat_mode or (self._gateway and self._gateway.name == "anyrouter")
        )

        # Backwards-compatible flags (used by tests and possibly external code)
        self.is_openrouter = bool(self._gateway and self._gateway.name == "openrouter")
        self.is_vllm = bool(self._gateway and self._gateway.is_local)

        # Configure environment variables
        if api_key:
            self._setup_env(api_key, api_base, default_model)

        # NOTE: Never set litellm.api_base (global) — it pollutes other provider
        # instances sharing the same process.  Pass api_base per-request via kwargs.

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True
        # Drop unsupported params for unknown models (e.g. tool_choice for proxied models)
        litellm.drop_params = True

    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Set environment variables based on detected provider."""
        if self._gateway:
            # Gateway / local: direct set (not setdefault)
            os.environ[self._gateway.env_key] = api_key
            return

        # Standard provider: match by model name
        spec = find_by_model(model)
        if spec:
            os.environ.setdefault(spec.env_key, api_key)
            # Resolve env_extras placeholders:
            #   {api_key}  → user's API key
            #   {api_base} → user's api_base, falling back to spec.default_api_base
            effective_base = api_base or spec.default_api_base
            for env_name, env_val in spec.env_extras:
                resolved = env_val.replace("{api_key}", api_key)
                resolved = resolved.replace("{api_base}", effective_base)
                os.environ.setdefault(env_name, resolved)

    def _resolve_model(self, model: str) -> str:
        """Resolve model name by applying provider/gateway prefixes."""
        # compat_mode: model name is passed as-is to the endpoint.
        # custom_llm_provider (set in chat()) tells LiteLLM the protocol,
        # so no prefixing is needed.
        if self._compat_mode:
            return model

        if self._gateway:
            # Gateway mode: apply gateway prefix, skip provider-specific prefixes
            prefix = self._gateway.litellm_prefix
            if self._gateway.strip_model_prefix:
                model = model.split("/")[-1]
            if prefix and not model.startswith(f"{prefix}/"):
                model = f"{prefix}/{model}"
            return model

        # Standard mode: auto-prefix for known providers
        spec = find_by_model(model)
        if spec:
            prefix = spec.litellm_prefix
            # When using a custom api_base with a provider that has no litellm_prefix
            # (e.g. openai with a proxy), LiteLLM still needs "openai/" for unknown
            # model names like gpt-5.3-codex. Force "openai/" in this case.
            if not prefix and self.api_base:
                prefix = "openai"
            if prefix and not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{prefix}/{model}"

        return model

    def resolve_model(self, model: str | None = None) -> str:
        """Resolve model name for outbound requests and token estimation."""
        return self._resolve_model(model or self.default_model)

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = self.resolve_model(model)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Apply model-specific overrides (e.g. kimi-k2.5 temperature)
        self._apply_model_overrides(model, kwargs)

        # Pass api_base directly for custom endpoints (vLLM, etc.)
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # compat_mode: tell LiteLLM the exact protocol, bypassing its model
        # registry lookups, parameter support checks, and streaming quirks.
        if self._compat_mode:
            kwargs["custom_llm_provider"] = self._compat_mode

        # Pass provider-specific request headers when configured
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            # compat_mode proxies and AnyRouter bridge may always stream regardless
            # of the stream flag. Force streaming and aggregate chunks so
            # _parse_response always sees a complete response object.
            if self._force_stream_aggregate:
                kwargs["stream"] = True
                response = await acompletion(**kwargs)
                return await self._aggregate_stream(response)

            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            logger.exception("LLM request failed")
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling LLM: {self._sanitize_error_message(e)}",
                finish_reason="error",
            )

    @staticmethod
    def _sanitize_error_message(error: Exception) -> str:
        """Keep user-facing error concise and avoid leaking raw upstream payloads."""
        message = str(error).strip().replace("\n", " ")
        if "Original Response:" in message:
            message = message.split("Original Response:", 1)[0].strip()
        if len(message) > 300:
            message = f"{message[:297]}..."
        return message

    async def _aggregate_stream(self, stream: Any) -> LLMResponse:
        """Aggregate a streaming response into a single LLMResponse."""
        content_parts: list[str] = []
        # Prefer explicit tool-call IDs. Some LiteLLM /responses streams reuse
        # index=0 for every tool call, which can incorrectly merge calls.
        tool_calls_map: dict[str, dict[str, Any]] = {}
        tool_call_order: list[str] = []
        last_key_by_index: dict[int, str] = {}
        synthetic_key_counter = 0
        finish_reason = "stop"
        usage: dict[str, int] = {}
        reasoning_parts: list[str] = []

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta

            # Content
            if hasattr(delta, "content") and delta.content:
                content_parts.append(delta.content)

            # Reasoning content
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)

            # Tool calls (streamed incrementally)
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = getattr(tc_delta, "index", 0)
                    tc_id = getattr(tc_delta, "id", None)
                    tc_fn = getattr(tc_delta, "function", None)

                    if tc_id:
                        key = f"id:{tc_id}"
                        last_key_by_index[idx] = key
                    elif idx in last_key_by_index:
                        key = last_key_by_index[idx]
                    else:
                        key = f"idx:{idx}:{synthetic_key_counter}"
                        synthetic_key_counter += 1
                        last_key_by_index[idx] = key

                    if key not in tool_calls_map:
                        tool_calls_map[key] = {
                            "id": tc_id or "",
                            "name": getattr(tc_fn, "name", "") or "",
                            "arguments": "",
                        }
                        tool_call_order.append(key)

                    entry = tool_calls_map[key]
                    if tc_id:
                        entry["id"] = tc_id

                    fn_name = getattr(tc_fn, "name", None)
                    if fn_name:
                        entry["name"] = fn_name

                    fn_args = getattr(tc_fn, "arguments", None)
                    if fn_args:
                        entry["arguments"] += fn_args

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            # Usage (usually on the last chunk)
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                }

        # Build tool calls list preserving first-seen order
        tool_calls: list[ToolCallRequest] = []
        for pos, key in enumerate(tool_call_order):
            entry = tool_calls_map[key]
            args_str = entry["arguments"]
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {"raw": args_str}

            tool_call_id = entry["id"] or f"call_{pos}"
            tool_calls.append(
                ToolCallRequest(id=tool_call_id, name=entry["name"], arguments=args)
            )

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                tool_calls.append(
                    ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # Capture reasoning_content from thinking/reasoning models (e.g. kimi-k2.5,
        # DeepSeek-R1). LiteLLM unifies this across providers.
        reasoning_content = getattr(message, "reasoning_content", None)

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
