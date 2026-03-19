"""Wire protocol helpers for the native HaL web runtime."""

from __future__ import annotations

from typing import Any

from hal.domain.events import SessionEvent
from hal.domain.session import SessionManifest
from hal.workspace.threads import ThreadEpisodeDocument, ThreadEpisodeRef, ThreadRegistryEntry

SESSION_SNAPSHOT = "session_snapshot"
SESSION_EVENT = "session_event"

WS_SUBMIT_TURN = "submit_turn"
WS_END_SESSION = "end_session"
WS_UPDATE_SCOPE = "update_scope"


def serialize_manifest(manifest: SessionManifest) -> dict[str, Any]:
    """Convert one session manifest into a JSON-friendly dict."""
    return manifest.model_dump(mode="json")


def serialize_event(event: SessionEvent) -> dict[str, Any]:
    """Convert one session event into a JSON-friendly dict."""
    return event.model_dump(mode="json")


def serialize_snapshot(
    manifest: SessionManifest,
    recent_events: list[SessionEvent],
) -> dict[str, Any]:
    """Build the initial WebSocket snapshot frame for one session."""
    return {
        "type": SESSION_SNAPSHOT,
        "manifest": serialize_manifest(manifest),
        "recent_events": [serialize_event(event) for event in recent_events],
    }


def serialize_event_frame(event: SessionEvent) -> dict[str, Any]:
    """Build one incremental event frame for WebSocket delivery."""
    return {
        "type": SESSION_EVENT,
        "event": serialize_event(event),
    }


def serialize_thread_summary(
    entry: ThreadRegistryEntry,
    *,
    session_counts: dict[str, int],
) -> dict[str, Any]:
    """Serialize one thread registry entry plus session counters."""
    return {
        "slug": entry.slug,
        "name": entry.name,
        "status": entry.status,
        "scope": entry.scope,
        "description": entry.description,
        "updated_at": entry.updated_at,
        "session_counts": session_counts,
    }


def serialize_thread_episode_ref(ref: ThreadEpisodeRef) -> dict[str, Any]:
    """Serialize one thread episode reference."""
    return {
        "session_id": ref.session_id,
        "thread_slug": ref.thread_slug,
        "episode_rel_path": ref.episode_rel_path,
        "episode_title": ref.episode_title,
    }


def serialize_thread_episode_document(document: ThreadEpisodeDocument) -> dict[str, Any]:
    """Serialize one thread episode markdown document."""
    return {
        "thread_slug": document.thread_slug,
        "episode_rel_path": document.episode_rel_path,
        "episode_title": document.episode_title,
        "markdown": document.markdown,
    }


def parse_ws_message(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Validate one inbound WebSocket frame and return ``(type, payload)``."""
    message_type = str(data.get("type", "")).strip()
    if not message_type:
        raise ValueError("WebSocket frame requires a non-empty 'type'")

    if message_type == WS_SUBMIT_TURN:
        content = str(data.get("content", "")).strip()
        if not content:
            raise ValueError("submit_turn requires non-empty 'content'")
        return message_type, {"content": content}

    if message_type == WS_END_SESSION:
        reason = str(data.get("reason", "")).strip()
        if reason not in {"brief", "drop"}:
            raise ValueError("end_session requires reason 'brief' or 'drop'")
        user_prompt = str(data.get("user_prompt", "")).strip()
        return message_type, {"reason": reason, "user_prompt": user_prompt}

    if message_type == WS_UPDATE_SCOPE:
        add_threads = [
            str(item).strip() for item in data.get("add_threads", []) if str(item).strip()
        ]
        remove_threads = [
            str(item).strip() for item in data.get("remove_threads", []) if str(item).strip()
        ]
        return message_type, {
            "add_threads": add_threads,
            "remove_threads": remove_threads,
        }

    raise ValueError(f"Unsupported WebSocket frame type: {message_type}")
