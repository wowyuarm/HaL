"""Rendering helpers for durable message injects.

Message injects are non-user-authored prompt inputs that still enter the model
working set and therefore must be replayable in later turns unless compaction
rewrites history.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hal.context.dynamic_context import build_dynamic_recall_block

SECTION_SESSION_STATE = "HaL Session State"
SECTION_TURN_CONTEXT = "HaL Turn Context"
SECTION_RUNTIME = "HaL Runtime"

KIND_PRIMARY_THREAD_SNAPSHOT = "primary_thread_snapshot"
KIND_SCOPE_ADD_SNAPSHOT = "scope_add_snapshot"
KIND_SCOPE_REMOVE = "scope_remove"
KIND_TURN_CONTEXT = "turn_context"
KIND_SYSTEM_REMINDER = "system_reminder"
KIND_USER_FOLLOW_UP = "user_follow_up"
KIND_SUBAGENT_RUNTIME = "subagent_runtime"
KIND_CONTEXT_HINT = "context_hint"


@dataclass(frozen=True, slots=True)
class MessageInject:
    """One durable synthetic message that enters the prompt and replay history."""

    kind: str
    content: str
    actor: str = "engine"
    source: str = "engine"
    refs: dict[str, object] = field(default_factory=dict)

    def as_history_message(self) -> dict[str, str]:
        return {"role": "user", "content": self.content}


def render_inject_block(
    section: str,
    *,
    kind: str,
    source: str,
    metadata: Mapping[str, object] | None = None,
    body: str = "",
) -> str:
    """Render one durable injected message block."""
    lines = [f"[{section}]", f"kind: {kind}", f"source: {source}"]
    for key, value in (metadata or {}).items():
        normalized = _format_metadata_value(value)
        if normalized:
            lines.append(f"{key}: {normalized}")
    body_text = body.strip()
    if body_text:
        lines.extend(["", body_text])
    return "\n".join(lines)


def build_thread_snapshot_inject(
    *,
    kind: str,
    thread_slug: str,
    brief_markdown: str,
    source: str,
) -> MessageInject:
    """Render one thread snapshot inject from a BRIEF.md snapshot."""
    content = render_inject_block(
        SECTION_SESSION_STATE,
        kind=kind,
        source=source,
        metadata={"thread": thread_slug},
        body=brief_markdown.strip(),
    )
    return MessageInject(
        kind=kind,
        content=content,
        actor="engine",
        source=source,
        refs={"threads": [thread_slug]},
    )


def build_scope_remove_inject(
    *,
    removed_threads: Iterable[str],
    mounted_threads: Iterable[str],
    source: str,
) -> MessageInject:
    """Render one scope-removal inject."""
    removed = [slug for slug in removed_threads if slug]
    mounted = [slug for slug in mounted_threads if slug]
    body_lines = [f"Removed from current scope: {', '.join(removed)}."]
    if mounted:
        body_lines.append(f"Scope: {', '.join(mounted)}.")
    body_lines.append("These threads are no longer part of the active session scope.")
    content = render_inject_block(
        SECTION_SESSION_STATE,
        kind=KIND_SCOPE_REMOVE,
        source=source,
        metadata={
            "removed_threads": removed,
            "scope": mounted,
        },
        body="\n".join(body_lines),
    )
    return MessageInject(
        kind=KIND_SCOPE_REMOVE,
        content=content,
        actor="engine",
        source=source,
        refs={"threads": removed, "mounted_threads": mounted},
    )


def build_turn_context_inject(
    *,
    channel: str | None,
    chat_id: str | None,
    mounted_threads: Iterable[str],
    memory_search_results: list[Any] | None,
    recall_max_total_tokens: int,
    recall_max_per_item_tokens: int,
    token_model: str | None,
    now: datetime | None = None,
) -> MessageInject:
    """Render one per-turn context inject for time, scope, and recalled memories."""
    ts = now or datetime.now()
    mounted = [slug for slug in mounted_threads if slug]
    recall_block = build_dynamic_recall_block(
        memory_search_results=memory_search_results,
        recall_max_total_tokens=recall_max_total_tokens,
        recall_max_per_item_tokens=recall_max_per_item_tokens,
        token_model=token_model,
    )
    metadata: dict[str, object] = {
        "time": ts.strftime("%Y-%m-%d %H:%M (%A)"),
        "scope": mounted,
    }
    if channel:
        metadata["channel"] = channel
    if chat_id:
        metadata["chat_id"] = chat_id
    body_parts: list[str] = []
    if recall_block:
        body_parts.append(recall_block)
    content = render_inject_block(
        SECTION_TURN_CONTEXT,
        kind=KIND_TURN_CONTEXT,
        source="engine",
        metadata=metadata,
        body="\n\n".join(body_parts),
    )
    return MessageInject(
        kind=KIND_TURN_CONTEXT,
        content=content,
        actor="engine",
        source="engine",
        refs={"mounted_threads": mounted},
    )


def build_runtime_inject(
    *,
    kind: str,
    source: str,
    body: str,
    metadata: Mapping[str, object] | None = None,
    actor: str = "engine",
) -> MessageInject:
    """Render one runtime inject block."""
    content = render_inject_block(
        SECTION_RUNTIME,
        kind=kind,
        source=source,
        metadata=metadata,
        body=body,
    )
    return MessageInject(kind=kind, content=content, actor=actor, source=source)


def _format_metadata_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set, frozenset)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts)
    return str(value).strip()


__all__ = [
    "KIND_CONTEXT_HINT",
    "KIND_PRIMARY_THREAD_SNAPSHOT",
    "KIND_SCOPE_ADD_SNAPSHOT",
    "KIND_SCOPE_REMOVE",
    "KIND_SUBAGENT_RUNTIME",
    "KIND_SYSTEM_REMINDER",
    "KIND_TURN_CONTEXT",
    "KIND_USER_FOLLOW_UP",
    "MessageInject",
    "build_runtime_inject",
    "build_scope_remove_inject",
    "build_thread_snapshot_inject",
    "build_turn_context_inject",
    "render_inject_block",
]
