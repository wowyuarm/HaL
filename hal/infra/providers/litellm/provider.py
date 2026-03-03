"""LiteLLM provider implementation for multi-provider support."""

from __future__ import annotations

import logging
from typing import Any

import litellm
from litellm import acompletion

from hal.infra.providers.base import LLMProvider, LLMResponse
from hal.infra.providers.litellm import messages as message_helpers
from hal.infra.providers.litellm import parsing as parse_helpers
from hal.infra.providers.litellm import routing
from hal.infra.providers.litellm import usage as usage_helpers
from hal.infra.providers.registry import find_by_name, find_gateway

logger = logging.getLogger(__name__)


class LiteLLMProvider(LLMProvider):
    """LLM provider using LiteLLM for multi-provider support."""

    _MIN_MAX_TOKENS: int = 1

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        compat_mode: str = "",
        request_params: dict[str, Any] | None = None,
        provider_name: str = "",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._compat_mode = compat_mode
        self.request_params = request_params or {}
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
        # instances sharing the same process. Pass api_base per-request via kwargs.

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True
        # Drop unsupported params for unknown models (e.g. tool_choice for proxied models)
        litellm.drop_params = True

    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Set environment variables based on detected provider."""
        routing.setup_env(api_key=api_key, api_base=api_base, model=model, gateway=self._gateway)

    def _resolve_model(self, model: str) -> str:
        """Resolve model name by applying provider/gateway prefixes."""
        return routing.resolve_model(
            model=model,
            compat_mode=self._compat_mode,
            gateway=self._gateway,
            api_base=self.api_base,
        )

    def resolve_model(self, model: str | None = None) -> str:
        """Resolve model name for outbound requests and token estimation."""
        return self._resolve_model(model or self.default_model)

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        routing.apply_model_overrides(model, kwargs)

    def _supports_cache_control(self, model: str) -> bool:
        """Return True when this request path supports Anthropic-style cache_control."""
        return routing.supports_cache_control(
            model=model,
            gateway=self._gateway,
            provider_name=self.provider_name,
        )

    @staticmethod
    def _apply_cache_control(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Inject Anthropic-style cache_control breakpoints for stable prefixes."""
        return routing.apply_cache_control(messages, tools)

    @staticmethod
    def _coerce_usage_int(value: Any) -> int | None:
        return usage_helpers.coerce_usage_int(value)

    @classmethod
    def _read_usage_field(cls, usage: Any, key: str) -> int | None:
        return usage_helpers.read_usage_field(usage, key)

    @classmethod
    def _extract_usage(cls, usage: Any) -> dict[str, int]:
        return usage_helpers.extract_usage(usage)

    @staticmethod
    def _is_thinking_enabled(value: Any) -> bool:
        """Return True when a provider-level thinking flag is enabled."""
        return message_helpers.is_thinking_enabled(value)

    def _should_preserve_reasoning_content(self, model: str) -> bool:
        """Keep reasoning_content only for paths that rely on thinking tool-call replay."""
        gateway_name = self._gateway.name if self._gateway else None
        return message_helpers.should_preserve_reasoning_content(
            model=model,
            gateway_name=gateway_name,
            request_params=self.request_params,
        )

    @staticmethod
    def _sanitize_messages(
        messages: list[dict[str, Any]],
        preserve_reasoning_content: bool = False,
    ) -> list[dict[str, Any]]:
        """Sanitize messages before LLM dispatch."""
        return message_helpers.sanitize_messages(
            messages=messages,
            preserve_reasoning_content=preserve_reasoning_content,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request via LiteLLM."""
        model = self.resolve_model(model)
        preserve_reasoning_content = self._should_preserve_reasoning_content(model)
        messages = self._sanitize_messages(
            messages,
            preserve_reasoning_content=preserve_reasoning_content,
        )
        max_tokens = max(self._MIN_MAX_TOKENS, max_tokens)
        if self._supports_cache_control(model):
            messages, tools = self._apply_cache_control(messages, tools)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if self.request_params:
            reserved_keys = {"model", "messages", "tools", "tool_choice"}
            for key, value in self.request_params.items():
                if key in reserved_keys:
                    continue
                kwargs[key] = value

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
        except Exception as error:
            logger.exception("LLM request failed")
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling LLM: {self._sanitize_error_message(error)}",
                finish_reason="error",
            )

    @staticmethod
    def _sanitize_error_message(error: Exception) -> str:
        """Keep user-facing error concise and avoid leaking raw upstream payloads."""
        return parse_helpers.sanitize_error_message(error)

    async def _aggregate_stream(self, stream: Any) -> LLMResponse:
        """Aggregate a streaming response into a single LLMResponse."""
        return await parse_helpers.aggregate_stream(stream, usage_extractor=self._extract_usage)

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        return parse_helpers.parse_response(response, usage_extractor=self._extract_usage)

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
