"""Shared tool-calling loop used by both AgentEngine and SubagentManager."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Protocol

from loguru import logger

from hal.capabilities.tools.registry import ToolRegistry
from hal.core.message_payloads import build_assistant_message_payload
from hal.core.ports import ChatProviderPort

# Injected when the LLM returns an empty response (no tool calls, no text).
# Uses "user" role so it lands after the cached prefix and triggers a retry
# without being recorded in memory/daily-log (the loop handles it transiently).
_EMPTY_RESPONSE_NUDGE = (
    "[System] You completed tool calls but produced no visible reply. "
    "Respond to the user now — briefly confirm what you did or deliver the result."
)
_TOOL_EXECUTION_SKIPPED_MESSAGE = (
    "[Tool execution skipped: user sent new messages. "
    "Re-evaluate direction before continuing.]"
)
_USAGE_STANDARD_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
_USAGE_CACHE_KEYS = (
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "prompt_cache_miss_tokens",
)
_USAGE_PROMPT_ALIAS_KEY = "input_tokens"
_USAGE_COMPLETION_ALIAS_KEY = "output_tokens"
_USAGE_PROMPT_DETAILS_KEY = "prompt_tokens_details"
_USAGE_PROMPT_CACHED_KEY = "cached_tokens"


@dataclass
class LoopMetadata:
    """Metadata collected during a tool-calling loop execution."""

    iterations: int = 0
    tools_used: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    total_tool_calls: int = 0
    has_side_effects: bool = False
    skipped_tool_calls: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cache_miss_tokens: int = 0
    first_response_usage: dict[str, int] = field(default_factory=dict)
    total_usage: dict[str, int] = field(default_factory=dict)
    loop_messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def needs_summary(self) -> bool:
        return self.iterations >= 5 or self.has_side_effects


class LoopHooks(Protocol):
    """Optional hooks that callers can implement to customize loop behavior.

    All methods have default no-op implementations in ToolCallingLoop, so
    callers only need to override the hooks they care about.
    """

    def before_llm_call(
        self, messages: list[dict[str, Any]], meta: LoopMetadata
    ) -> None | Awaitable[None]:
        """Called before each LLM call. Modify messages in place (e.g. inject pending)."""
        ...

    def on_tool_result(
        self,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, Any],
        result: str,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> None | Awaitable[None]:
        """Called after each tool execution. Record memory, track side effects, etc."""
        ...

    async def on_no_tool_calls(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        meta: LoopMetadata,
    ) -> bool:
        """Called when LLM responds without tool calls.

        Return True to continue the loop (e.g. after injecting subagent results),
        False to break and finalize.
        """
        ...

    async def on_tool_calls_start(
        self,
        tool_calls: list[Any],
        assistant_content: str | None,
        meta: LoopMetadata,
    ) -> bool | None:
        """Called before tool execution begins.

        Return True to skip tool execution (e.g. user interrupt).
        Return None or False to proceed normally.
        """
        ...

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        """Called when max iterations reached while still making tool calls.

        Return a final result string, or None to use default behavior.
        """
        ...


class _NoOpHooks:
    """Default no-op hooks."""

    def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
        pass

    def on_tool_result(
        self,
        tool_name: str,
        tool_id: str,
        arguments: dict[str, Any],
        result: str,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> None:
        pass

    async def on_no_tool_calls(
        self,
        messages: list[dict[str, Any]],
        response: Any,
        meta: LoopMetadata,
    ) -> bool:
        return False

    async def on_tool_calls_start(
        self,
        tool_calls: list[Any],
        assistant_content: str | None,
        meta: LoopMetadata,
    ) -> None:
        return None

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        return None


_DEFAULT_HOOKS = _NoOpHooks()


def _update_usage_metadata(meta: LoopMetadata, usage: dict[str, int], iteration: int) -> None:
    """Accumulate token/cache counters from a single provider response."""
    if not usage:
        return
    if iteration == 1 and not meta.first_response_usage:
        meta.first_response_usage = dict(usage)

    for key, value in usage.items():
        meta.total_usage[key] = meta.total_usage.get(key, 0) + value

    meta.cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
    meta.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
    meta.cache_miss_tokens += usage.get("prompt_cache_miss_tokens", 0)


def _build_tool_call_dicts(tool_calls: list[Any]) -> list[dict[str, Any]]:
    """Convert provider tool calls to OpenAI-style tool-call payloads."""
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.name,
                "arguments": json.dumps(tc.arguments),
            },
        }
        for tc in tool_calls
    ]


def _append_assistant_tool_call_message(
    messages: list[dict[str, Any]],
    *,
    response: Any,
    tool_call_dicts: list[dict[str, Any]],
    add_assistant_message: Any | None,
) -> list[dict[str, Any]]:
    """Append assistant response containing tool-call declarations."""
    if add_assistant_message:
        return add_assistant_message(
            messages,
            response.content,
            tool_call_dicts,
            reasoning_content=response.reasoning_content,
        )

    messages.append(
        build_assistant_message_payload(
            content=response.content,
            tool_calls=tool_call_dicts,
            reasoning_content=response.reasoning_content,
        )
    )
    return messages


def _append_tool_result_message(
    messages: list[dict[str, Any]],
    *,
    add_tool_result: Any | None,
    tool_id: str,
    tool_name: str,
    result: str,
) -> list[dict[str, Any]]:
    """Append a tool result message using caller override when provided."""
    if add_tool_result:
        return add_tool_result(messages, tool_id, tool_name, result)

    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_id,
            "name": tool_name,
            "content": result,
        }
    )
    return messages


def _append_non_empty(items: list[str], values: list[str], *, unique: bool = False) -> None:
    """Append non-empty strings, optionally deduplicating existing values."""
    for value in values:
        if not value:
            continue
        if unique and value in items:
            continue
        items.append(value)


def _track_tool_call_metadata(
    *,
    tool_call: Any,
    tools: ToolRegistry,
    meta: LoopMetadata,
) -> None:
    """Track call counters and side effects for a single tool call."""
    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")

    meta.tool_call_counts[tool_call.name] = meta.tool_call_counts.get(tool_call.name, 0) + 1
    if tool_call.name not in meta.tools_used:
        meta.tools_used.append(tool_call.name)
    meta.total_tool_calls += 1

    tool_obj = tools.get(tool_call.name)
    if not tool_obj:
        return
    effects = tool_obj.get_side_effects(tool_call.arguments)
    if effects is None:
        return

    meta.has_side_effects = True
    _append_non_empty(meta.files_modified, effects.get("files_modified", []), unique=True)
    _append_non_empty(meta.commands_run, effects.get("commands_run", []))


async def _emit_tool_result_hook(
    *,
    hooks: LoopHooks,
    tool_call: Any,
    result: str,
    messages: list[dict[str, Any]],
    meta: LoopMetadata,
) -> None:
    """Run the on_tool_result hook for one tool call result."""
    await _maybe_await(
        hooks.on_tool_result(
            tool_call.name,
            tool_call.id,
            tool_call.arguments,
            result,
            messages,
            meta,
        )
    )


async def _handle_skipped_tool_calls(
    *,
    tool_calls: list[Any],
    messages: list[dict[str, Any]],
    add_tool_result: Any | None,
    hooks: LoopHooks,
    meta: LoopMetadata,
) -> list[dict[str, Any]]:
    """Write placeholder results when execution is skipped due to interrupts."""
    meta.skipped_tool_calls += len(tool_calls)
    for tool_call in tool_calls:
        messages = _append_tool_result_message(
            messages,
            add_tool_result=add_tool_result,
            tool_id=tool_call.id,
            tool_name=tool_call.name,
            result=_TOOL_EXECUTION_SKIPPED_MESSAGE,
        )
        await _emit_tool_result_hook(
            hooks=hooks,
            tool_call=tool_call,
            result=_TOOL_EXECUTION_SKIPPED_MESSAGE,
            messages=messages,
            meta=meta,
        )
    return messages


async def _execute_tool_calls(
    *,
    tool_calls: list[Any],
    tools: ToolRegistry,
) -> list[str]:
    """Execute tool calls concurrently and preserve call order in outputs."""
    return await asyncio.gather(*(tools.execute(tc.name, tc.arguments) for tc in tool_calls))


async def _handle_tool_call_response(
    *,
    response: Any,
    messages: list[dict[str, Any]],
    tools: ToolRegistry,
    hooks: LoopHooks,
    meta: LoopMetadata,
    add_assistant_message: Any | None,
    add_tool_result: Any | None,
) -> list[dict[str, Any]]:
    """Process a provider response that contains tool calls."""
    tool_calls = response.tool_calls
    tool_call_dicts = _build_tool_call_dicts(tool_calls)
    messages = _append_assistant_tool_call_message(
        messages,
        response=response,
        tool_call_dicts=tool_call_dicts,
        add_assistant_message=add_assistant_message,
    )

    for tool_call in tool_calls:
        _track_tool_call_metadata(tool_call=tool_call, tools=tools, meta=meta)

    skip = await hooks.on_tool_calls_start(tool_calls, response.content, meta)
    if skip:
        return await _handle_skipped_tool_calls(
            tool_calls=tool_calls,
            messages=messages,
            add_tool_result=add_tool_result,
            hooks=hooks,
            meta=meta,
        )

    results = await _execute_tool_calls(tool_calls=tool_calls, tools=tools)
    for tool_call, result in zip(tool_calls, results):
        messages = _append_tool_result_message(
            messages,
            add_tool_result=add_tool_result,
            tool_id=tool_call.id,
            tool_name=tool_call.name,
            result=result,
        )
        await _emit_tool_result_hook(
            hooks=hooks,
            tool_call=tool_call,
            result=result,
            messages=messages,
            meta=meta,
        )
    return messages


async def run_tool_loop(
    *,
    provider: ChatProviderPort,
    model: str,
    tools: ToolRegistry,
    messages: list[dict[str, Any]],
    max_iterations: int = 20,
    hooks: LoopHooks | None = None,
    add_assistant_message: Any | None = None,
    add_tool_result: Any | None = None,
) -> tuple[str | None, LoopMetadata]:
    """Execute the LLM tool-calling loop.

    This is the shared core loop used by both engine and subagent. Callers
    customize behavior via *hooks* and message-building callbacks.

    Args:
        provider: LLM provider for chat calls.
        model: Model identifier.
        tools: Tool registry with available tools.
        messages: Conversation messages (modified in place).
        max_iterations: Maximum loop iterations.
        hooks: Optional callbacks for customization.
        add_assistant_message: Callback(messages, content, tool_calls, reasoning) -> messages.
            If None, uses a default inline implementation.
        add_tool_result: Callback(messages, tool_id, tool_name, result) -> messages.
            If None, uses a default inline implementation.

    Returns:
        Tuple of (final_content, loop_metadata).
    """
    h = hooks or _DEFAULT_HOOKS
    iteration = 0
    final_content: str | None = None
    nudged = False
    meta = LoopMetadata()
    start_idx = len(messages)

    while iteration < max_iterations:
        iteration += 1
        meta.iterations = iteration

        # Hook: inject pending messages, etc.
        await _maybe_await(h.before_llm_call(messages, meta))

        response = await provider.chat(
            messages=messages, tools=tools.get_definitions(), model=model
        )
        usage = _normalize_usage(response.usage)
        _update_usage_metadata(meta, usage, iteration)

        if response.has_tool_calls:
            messages = await _handle_tool_call_response(
                response=response,
                messages=messages,
                tools=tools,
                hooks=h,
                meta=meta,
                add_assistant_message=add_assistant_message,
                add_tool_result=add_tool_result,
            )
            continue

        # No tool calls — check if caller wants to continue (e.g. subagent injection)
        should_continue = await h.on_no_tool_calls(messages, response, meta)
        if should_continue:
            continue

        # Guard: if content is empty after tool work, nudge the LLM once.
        if not response.content and meta.total_tool_calls > 0 and not nudged:
            nudged = True
            messages.append({"role": "user", "content": _EMPTY_RESPONSE_NUDGE})
            continue

        final_content = response.content
        break

    # Loop exhausted
    if final_content is None:
        result = await h.on_loop_exhausted(messages, meta)
        if result is not None:
            final_content = result

    meta.loop_messages = messages[start_idx:]

    return final_content, meta


async def _maybe_await(value: None | Awaitable[None]) -> None:
    """Await values that are awaitable; ignore plain None."""
    if value is None:
        return
    await value


def _normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Normalize response usage dict into integer counters.

    Extracts standard token counters and cache counters when available.
    """
    if not usage:
        return {}

    normalized = _collect_usage_counters(usage, _USAGE_STANDARD_KEYS + _USAGE_CACHE_KEYS)
    _set_missing_usage_alias(
        normalized=normalized,
        usage=usage,
        target_key="prompt_tokens",
        alias_key=_USAGE_PROMPT_ALIAS_KEY,
    )
    _set_missing_usage_alias(
        normalized=normalized,
        usage=usage,
        target_key="completion_tokens",
        alias_key=_USAGE_COMPLETION_ALIAS_KEY,
    )

    if "cache_read_input_tokens" not in normalized:
        prompt_details = usage.get(_USAGE_PROMPT_DETAILS_KEY)
        if isinstance(prompt_details, dict):
            cached_tokens = _read_counter(prompt_details, _USAGE_PROMPT_CACHED_KEY)
            if cached_tokens is not None:
                normalized["cache_read_input_tokens"] = cached_tokens

    if (
        "total_tokens" not in normalized
        and "prompt_tokens" in normalized
        and "completion_tokens" in normalized
    ):
        normalized["total_tokens"] = (
            normalized["prompt_tokens"] + normalized["completion_tokens"]
        )
    return normalized


def _collect_usage_counters(usage: dict[str, Any], keys: tuple[str, ...]) -> dict[str, int]:
    """Collect integer-compatible counters from a usage payload."""
    normalized: dict[str, int] = {}
    for key in keys:
        counter = _read_counter(usage, key)
        if counter is not None:
            normalized[key] = counter
    return normalized


def _set_missing_usage_alias(
    *,
    normalized: dict[str, int],
    usage: dict[str, Any],
    target_key: str,
    alias_key: str,
) -> None:
    """Populate target_key from alias_key if target_key is absent."""
    if target_key in normalized:
        return
    alias_value = _read_counter(usage, alias_key)
    if alias_value is not None:
        normalized[target_key] = alias_value


def _read_counter(values: dict[str, Any], key: str) -> int | None:
    """Read an int/float counter and normalize to int."""
    value = values.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
