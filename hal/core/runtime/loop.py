"""Shared tool-calling loop used by both AgentEngine and SubagentManager."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from loguru import logger

from hal.capabilities.tools.registry import ToolRegistry
from hal.infra.providers.base import LLMProvider


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

    def before_llm_call(self, messages: list[dict[str, Any]], meta: LoopMetadata) -> None:
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
    ) -> None:
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
    ) -> None:
        """Called before tool execution begins. Used for progress notifications."""
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
        pass

    async def on_loop_exhausted(
        self,
        messages: list[dict[str, Any]],
        meta: LoopMetadata,
    ) -> str | None:
        return None


_DEFAULT_HOOKS = _NoOpHooks()


async def run_tool_loop(
    *,
    provider: LLMProvider,
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
    meta = LoopMetadata()
    start_idx = len(messages)

    while iteration < max_iterations:
        iteration += 1
        meta.iterations = iteration

        # Hook: inject pending messages, etc.
        h.before_llm_call(messages, meta)

        response = await provider.chat(
            messages=messages, tools=tools.get_definitions(), model=model
        )
        usage = _normalize_usage(response.usage)
        if usage:
            if iteration == 1 and not meta.first_response_usage:
                meta.first_response_usage = dict(usage)
            for key, value in usage.items():
                meta.total_usage[key] = meta.total_usage.get(key, 0) + value

        if response.has_tool_calls:
            # Build assistant message with tool calls
            tool_call_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]

            if add_assistant_message:
                messages = add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )
            else:
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": tool_call_dicts,
                }
                if response.reasoning_content:
                    assistant_msg["reasoning_content"] = response.reasoning_content
                messages.append(assistant_msg)

            # Log and track tool usage
            for tool_call in response.tool_calls:
                args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                meta.tool_call_counts[tool_call.name] = (
                    meta.tool_call_counts.get(tool_call.name, 0) + 1
                )
                if tool_call.name not in meta.tools_used:
                    meta.tools_used.append(tool_call.name)

                meta.total_tool_calls += 1

                # Track side effects via tool interface
                tool_obj = tools.get(tool_call.name)
                if tool_obj:
                    effects = tool_obj.get_side_effects(tool_call.arguments)
                    if effects is not None:
                        meta.has_side_effects = True
                        for path in effects.get("files_modified", []):
                            if path and path not in meta.files_modified:
                                meta.files_modified.append(path)
                        for cmd in effects.get("commands_run", []):
                            if cmd:
                                meta.commands_run.append(cmd)

            # Hook: notify progress before execution
            await h.on_tool_calls_start(response.tool_calls, response.content, meta)

            # Execute tools in parallel
            results = await asyncio.gather(
                *(tools.execute(tc.name, tc.arguments) for tc in response.tool_calls)
            )

            # Add tool results to messages
            for tool_call, result in zip(response.tool_calls, results):
                if add_tool_result:
                    messages = add_tool_result(messages, tool_call.id, tool_call.name, result)
                else:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        }
                    )

                # Hook: record memory, persist spawn results, etc.
                h.on_tool_result(
                    tool_call.name, tool_call.id, tool_call.arguments, result, messages, meta
                )
        else:
            # No tool calls — check if caller wants to continue (e.g. subagent injection)
            should_continue = await h.on_no_tool_calls(messages, response, meta)
            if should_continue:
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


def _normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Normalize response usage dict into integer counters.

    Only standard OpenAI fields are extracted. Cache-specific fields
    (Anthropic's cache_creation_input_tokens / cache_read_input_tokens,
    OpenAI's prompt_tokens_details.cached_tokens) are NOT captured here
    because our current provider path (anyrouter bridge) does not
    reliably forward them. Revisit when switching to a direct provider.
    """
    if not usage:
        return {}

    normalized: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            normalized[key] = value
        elif isinstance(value, float):
            normalized[key] = int(value)
    return normalized
