"""Context advisor helpers for non-blocking skill/thread hint generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

_CONTEXT_HINT_HEADER = "[Context Hint]"
_CONTEXT_ADVISOR_SYSTEM_PROMPT = (
    "You are a context advisor. Given current task signals, suggest only likely-relevant "
    "skills or thread slugs to load next. Return JSON only:\n"
    '{"skills":["..."],"threads":["..."],"reason":"..."}\n'
    "Rules: be silence-biased; empty arrays when uncertain; prefer higher-priority units "
    "and follow related-thread links when relevant."
)


@dataclass(slots=True)
class ContextAdvisorSuggestion:
    """Structured advisor suggestion parsed from worker-model output."""

    skills: list[str]
    threads: list[str]
    reason: str


@dataclass(frozen=True, slots=True)
class ContextAdvisorInput:
    """Compact runtime snapshot used to request an advisor suggestion."""

    latest_user_message: str
    assistant_progress: str
    tool_calls: list[dict[str, Any]]
    skill_registry: list[dict[str, object]]
    thread_registry: list[dict[str, object]]
    context_unit_registry: list[dict[str, object]]

    def as_payload(self) -> dict[str, object]:
        """Return JSON-serializable advisor payload."""
        return {
            "latest_user_message": self.latest_user_message,
            "assistant_progress": self.assistant_progress,
            "tool_calls": self.tool_calls,
            "skill_registry": self.skill_registry,
            "thread_registry": self.thread_registry,
            "context_unit_registry": self.context_unit_registry,
        }


def has_substantive_tool_calls(tool_calls: list[Any]) -> bool:
    """Return True when at least one tool call is not a simple message send."""
    return any(getattr(tool_call, "name", "") != "message" for tool_call in tool_calls)


def extract_tool_call_preview(tool_calls: list[Any]) -> list[dict[str, Any]]:
    """Build lightweight tool-call preview for advisor prompt."""
    return [
        {
            "name": getattr(tool_call, "name", ""),
            "arguments": getattr(tool_call, "arguments", {}),
        }
        for tool_call in tool_calls
    ]


def build_context_advisor_input(
    *,
    latest_user_message: str,
    assistant_content: str | None,
    tool_calls: list[Any],
    skill_registry: list[dict[str, object]],
    thread_registry: list[dict[str, object]],
    context_unit_registry: list[dict[str, object]],
) -> ContextAdvisorInput:
    """Build the compact advisor input snapshot from loop/runtime state."""
    return ContextAdvisorInput(
        latest_user_message=latest_user_message[:2000],
        assistant_progress=(assistant_content or "")[:2000],
        tool_calls=extract_tool_call_preview(tool_calls),
        skill_registry=skill_registry,
        thread_registry=thread_registry,
        context_unit_registry=context_unit_registry,
    )


def build_context_advisor_messages(advisor_input: ContextAdvisorInput) -> list[dict[str, str]]:
    """Render provider request messages for the advisor model."""
    return [
        {"role": "system", "content": _CONTEXT_ADVISOR_SYSTEM_PROMPT},
        {"role": "user", "content": str(advisor_input.as_payload())},
    ]


async def request_context_advisor_suggestion(
    *,
    chat: Callable[..., Awaitable[Any]],
    model: str | None,
    advisor_input: ContextAdvisorInput,
) -> ContextAdvisorSuggestion | None:
    """Call the advisor model and parse its structured suggestion."""
    response = await chat(
        messages=build_context_advisor_messages(advisor_input),
        tools=[],
        model=model,
    )
    content = getattr(response, "content", None)
    if not isinstance(content, str):
        return None
    return parse_context_advisor_output(content)


def build_context_hint_keys(suggestion: ContextAdvisorSuggestion) -> list[str]:
    """Build stable deduplication keys for one advisor suggestion."""
    return [f"skill:{name}" for name in suggestion.skills] + [
        f"thread:{slug}" for slug in suggestion.threads
    ]


def filter_context_advisor_suggestion(
    suggestion: ContextAdvisorSuggestion,
    *,
    allowed_keys: set[str],
) -> ContextAdvisorSuggestion | None:
    """Keep only suggestion items whose deduplication keys are newly allowed."""
    allowed_skills = [name for name in suggestion.skills if f"skill:{name}" in allowed_keys]
    allowed_threads = [slug for slug in suggestion.threads if f"thread:{slug}" in allowed_keys]
    if not allowed_skills and not allowed_threads:
        return None
    return ContextAdvisorSuggestion(
        skills=allowed_skills,
        threads=allowed_threads,
        reason=suggestion.reason,
    )


def build_thread_path_map(thread_registry: list[dict[str, object]]) -> dict[str, str]:
    """Build slug -> STATE path mapping for hint rendering."""
    return {
        str(item["slug"]): str(item["state_path"])
        for item in thread_registry
        if item.get("slug") and item.get("state_path")
    }


def parse_context_advisor_output(raw: str) -> ContextAdvisorSuggestion | None:
    """Parse JSON advisor response. Returns None when payload is invalid or empty."""
    payload = _extract_json(raw)
    if payload is None:
        return None

    skills = _as_clean_list(payload.get("skills"))
    threads = _as_clean_list(payload.get("threads"))
    reason_value = payload.get("reason")
    reason = reason_value.strip() if isinstance(reason_value, str) else ""
    if not skills and not threads:
        return None
    return ContextAdvisorSuggestion(skills=skills, threads=threads, reason=reason)


def build_context_hint_text(
    suggestion: ContextAdvisorSuggestion,
    *,
    thread_path_map: dict[str, str],
) -> str:
    """Render user-visible context hint for loop injection."""
    lines = [_CONTEXT_HINT_HEADER, "Potentially relevant context for this task:"]
    for skill in suggestion.skills:
        lines.append(f"- Skill `{skill}` may help. Read its SKILL.md if needed.")
    for thread in suggestion.threads:
        state_path = thread_path_map.get(thread)
        if state_path:
            lines.append(f"- Thread `{thread}` may be relevant. Read `{state_path}` if needed.")
        else:
            lines.append(f"- Thread `{thread}` may be relevant. Check its STATE.md if needed.")
    if suggestion.reason:
        lines.append(f"Reason: {suggestion.reason}")
    lines.append("If you already have sufficient context, ignore this hint.")
    return "\n".join(lines)


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = _strip_code_fence(text)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return text


def _as_clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized_items = [
        normalized
        for normalized in (_normalize_string_item(item) for item in value)
        if normalized is not None
    ]
    return list(dict.fromkeys(normalized_items))


def _normalize_string_item(item: object) -> str | None:
    if not isinstance(item, str):
        return None
    normalized = item.strip()
    return normalized or None
