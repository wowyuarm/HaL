"""Helpers for session debrief lifecycle and episode generation."""

from __future__ import annotations

import re
from typing import Any

from hal.workspace.events import EventEntry

_THREAD_STATE_PATH_RE = re.compile(r"(?:^|/)threads/([^/]+)/STATE\.md$")
_CONFIRM_TEXTS = {"yes", "y", "ok", "confirm", "确认", "继续", "开始", "👍", "✅"}
_MAX_EVENT_PREVIEW = 200


def build_debrief_confirmation_message(*, threads: list[str], confirm_timeout_s: float) -> str:
    """Build user-visible confirmation text before starting session debrief."""
    thread_text = ", ".join(threads)
    timeout_m = max(int(confirm_timeout_s // 60), 1)
    return (
        "This session touched threads: "
        f"{thread_text}. I will update episodes/STATE in about {timeout_m} minute(s). "
        "Reply to continue chatting and cancel this debrief, or reply 'confirm' to start now."
    )


def is_debrief_confirm_message(content: str) -> bool:
    """Return True when user message should immediately confirm debrief."""
    normalized = content.strip().lower()
    if not normalized:
        return False
    if normalized.startswith("/debrief"):
        return True
    return normalized in _CONFIRM_TEXTS


def extract_thread_slug_from_value(value: Any) -> str | None:
    """Extract thread slug from arbitrary string value containing threads/.../STATE.md."""
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    match = _THREAD_STATE_PATH_RE.search(normalized)
    if not match:
        return None
    return match.group(1)


def extract_touched_threads(arguments: dict[str, Any]) -> set[str]:
    """Recursively collect thread slugs from tool call arguments."""
    found: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for val in obj.values():
                _walk(val)
            return
        if isinstance(obj, list):
            for val in obj:
                _walk(val)
            return
        slug = extract_thread_slug_from_value(obj)
        if slug:
            found.add(slug)

    _walk(arguments)
    return found


def format_session_events_for_prompt(events: list[EventEntry]) -> str:
    """Render compact event stream for worker-model debrief input."""
    lines: list[str] = []
    for event in events:
        payload = event.payload or {}
        preview = _event_preview(payload)
        lines.append(f"- [{event.ts}] {event.type}: {preview}")
    return "\n".join(lines) if lines else "- (no events)"


def _event_preview(payload: dict[str, Any]) -> str:
    if not payload:
        return "(empty)"
    for key in ("content", "tool", "label", "status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip().replace("\n", " ")
            if len(text) > _MAX_EVENT_PREVIEW:
                return text[:_MAX_EVENT_PREVIEW] + "..."
            return text
    return str(payload)[:_MAX_EVENT_PREVIEW]
