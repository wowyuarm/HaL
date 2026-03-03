"""Response parsing helpers for LiteLLM provider."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hal.infra.providers.base import LLMResponse, ToolCallRequest


def sanitize_error_message(error: Exception) -> str:
    """Keep user-facing error concise and avoid leaking raw upstream payloads."""
    message = str(error).strip().replace("\n", " ")
    if "Original Response:" in message:
        message = message.split("Original Response:", 1)[0].strip()
    if len(message) > 300:
        message = f"{message[:297]}..."
    return message


def parse_tool_arguments(args: Any) -> Any:
    """Parse JSON tool arguments, preserving malformed payloads as raw text."""
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {"raw": args}
    return args


@dataclass
class _ToolCallAggregationState:
    """Mutable state while reconstructing streamed tool calls."""

    tool_calls_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_call_order: list[str] = field(default_factory=list)
    last_key_by_index: dict[int, str] = field(default_factory=dict)
    synthetic_key_counter: int = 0


def _first_choice(chunk: Any) -> Any | None:
    """Return first stream choice, or None when chunk has no choices."""
    if not getattr(chunk, "choices", None):
        return None
    return chunk.choices[0]


def _append_delta_text(
    delta: Any,
    *,
    content_parts: list[str],
    reasoning_parts: list[str],
) -> None:
    """Collect streamed content/reasoning deltas."""
    content = getattr(delta, "content", None)
    if content:
        content_parts.append(content)

    reasoning = getattr(delta, "reasoning_content", None)
    if reasoning:
        reasoning_parts.append(reasoning)


def _resolve_tool_call_key(tc_delta: Any, state: _ToolCallAggregationState) -> str:
    """Resolve a stable map key for an incremental tool-call delta."""
    idx = getattr(tc_delta, "index", 0)
    tc_id = getattr(tc_delta, "id", None)

    if tc_id:
        key = f"id:{tc_id}"
        state.last_key_by_index[idx] = key
        return key

    if idx in state.last_key_by_index:
        return state.last_key_by_index[idx]

    key = f"idx:{idx}:{state.synthetic_key_counter}"
    state.synthetic_key_counter += 1
    state.last_key_by_index[idx] = key
    return key


def _ensure_tool_call_entry(
    *,
    key: str,
    tc_delta: Any,
    state: _ToolCallAggregationState,
) -> dict[str, Any]:
    """Create map entry for a tool call if needed and return it."""
    existing = state.tool_calls_map.get(key)
    if existing is not None:
        return existing

    tc_fn = getattr(tc_delta, "function", None)
    entry = {
        "id": getattr(tc_delta, "id", None) or "",
        "name": getattr(tc_fn, "name", "") or "",
        "arguments": "",
    }
    state.tool_calls_map[key] = entry
    state.tool_call_order.append(key)
    return entry


def _apply_tool_call_delta(entry: dict[str, Any], tc_delta: Any) -> None:
    """Apply one incremental tool-call delta to an accumulated entry."""
    tc_id = getattr(tc_delta, "id", None)
    if tc_id:
        entry["id"] = tc_id

    tc_fn = getattr(tc_delta, "function", None)
    fn_name = getattr(tc_fn, "name", None)
    if fn_name:
        entry["name"] = fn_name

    fn_args = getattr(tc_fn, "arguments", None)
    if fn_args:
        entry["arguments"] += fn_args


def _accumulate_tool_calls(delta: Any, state: _ToolCallAggregationState) -> None:
    """Accumulate streamed tool-call deltas into ordered full entries."""
    tool_calls = getattr(delta, "tool_calls", None)
    if not tool_calls:
        return

    for tc_delta in tool_calls:
        key = _resolve_tool_call_key(tc_delta, state)
        entry = _ensure_tool_call_entry(key=key, tc_delta=tc_delta, state=state)
        _apply_tool_call_delta(entry, tc_delta)


def _read_chunk_usage(
    chunk: Any,
    usage_extractor: Callable[[Any], dict[str, int]],
) -> dict[str, int] | None:
    """Read usage from stream chunk when present."""
    usage = getattr(chunk, "usage", None)
    if usage:
        return usage_extractor(usage)
    return None


def _build_tool_calls(state: _ToolCallAggregationState) -> list[ToolCallRequest]:
    """Build ordered ToolCallRequest objects from aggregation state."""
    tool_calls: list[ToolCallRequest] = []
    for pos, key in enumerate(state.tool_call_order):
        entry = state.tool_calls_map[key]
        args = parse_tool_arguments(entry["arguments"])
        if not isinstance(args, dict):
            args = {"raw": args}

        tool_call_id = entry["id"] or f"call_{pos}"
        tool_calls.append(ToolCallRequest(id=tool_call_id, name=entry["name"], arguments=args))
    return tool_calls


async def aggregate_stream(
    stream: Any,
    usage_extractor: Callable[[Any], dict[str, int]],
) -> LLMResponse:
    """Aggregate a streaming response into a single LLMResponse."""
    content_parts: list[str] = []
    state = _ToolCallAggregationState()
    finish_reason = "stop"
    usage: dict[str, int] = {}
    reasoning_parts: list[str] = []

    async for chunk in stream:
        choice = _first_choice(chunk)
        if not choice:
            continue

        delta = choice.delta
        _append_delta_text(delta, content_parts=content_parts, reasoning_parts=reasoning_parts)
        _accumulate_tool_calls(delta, state)

        if choice.finish_reason:
            finish_reason = choice.finish_reason

        chunk_usage = _read_chunk_usage(chunk, usage_extractor)
        if chunk_usage is not None:
            usage = chunk_usage

    return LLMResponse(
        content="".join(content_parts) or None,
        tool_calls=_build_tool_calls(state),
        finish_reason=finish_reason,
        usage=usage,
        reasoning_content="".join(reasoning_parts) or None,
    )


def parse_response(
    response: Any,
    usage_extractor: Callable[[Any], dict[str, int]],
) -> LLMResponse:
    """Parse LiteLLM response into the standard LLMResponse format."""
    choice = response.choices[0]
    message = choice.message

    tool_calls: list[ToolCallRequest] = []
    if hasattr(message, "tool_calls") and message.tool_calls:
        for tc in message.tool_calls:
            args = parse_tool_arguments(tc.function.arguments)
            if not isinstance(args, dict):
                args = {"raw": args}

            tool_calls.append(
                ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                )
            )

    usage: dict[str, int] = {}
    if hasattr(response, "usage") and response.usage:
        usage = usage_extractor(response.usage)

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
