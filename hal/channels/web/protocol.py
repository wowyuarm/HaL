"""Wire protocol helpers for the web channel.

All functions are pure — no side effects, no I/O.  They translate between
the domain event types and the JSON shapes defined in the WebSocket protocol
spec (see docs/specs/2026-03-11-web-client-design.md, section "WebSocket protocol").
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hal.bus.events import OutboundMessage

# ---------------------------------------------------------------------------
# Inbound message types accepted from the client
# ---------------------------------------------------------------------------

_INBOUND_TYPES = frozenset({"message", "command", "select_thread"})

# ---------------------------------------------------------------------------
# Serialization: engine -> client
# ---------------------------------------------------------------------------


def serialize_outbound(msg: OutboundMessage) -> dict[str, Any]:
    """Convert an *OutboundMessage* to the ``message`` wire frame.

    Wire shape::

        { "type": "message", "id": ..., "role": "assistant", "content": ...,
          "ts": ..., "metadata": { ... } }

    All metadata from the engine is forwarded as-is so the web client can
    decide what to render.  Non-JSON-serializable values are the caller's
    responsibility (the engine currently only puts simple types in metadata).
    """
    return {
        "type": "message",
        "id": msg.metadata.get("message_id", ""),
        "role": "assistant",
        "content": msg.content,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "metadata": dict(msg.metadata),
    }


# ---------------------------------------------------------------------------
# Deserialization: client -> engine
# ---------------------------------------------------------------------------


def parse_inbound(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Parse one client JSON frame and return ``(type, payload)``.

    Raises *ValueError* when *type* is missing or unsupported.
    """
    msg_type = str(data.get("type", "")).strip()
    if msg_type not in _INBOUND_TYPES:
        raise ValueError(f"unsupported inbound type: {msg_type!r}")
    # The payload is the frame itself minus the ``type`` key.
    payload: dict[str, Any] = {k: v for k, v in data.items() if k != "type"}
    return msg_type, payload


# ---------------------------------------------------------------------------
# Snapshot and incremental update builders
# ---------------------------------------------------------------------------


def build_snapshot(
    *,
    threads: list[dict[str, Any]],
    history: list[dict[str, Any]],
    context_summary: dict[str, Any],
    status: str,
    active_thread: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Build the full ``snapshot`` frame sent on client connect / reconnect."""
    return {
        "type": "snapshot",
        "session_id": session_id,
        "active_thread": active_thread,
        "threads": threads,
        "history": history,
        "context_summary": context_summary,
        "status": status,
    }


def build_status(state: str) -> dict[str, str]:
    """Build an incremental ``status`` frame."""
    return {"type": "status", "state": state}


def build_threads(thread_entries: list[object]) -> list[dict[str, Any]]:
    """Serialize a list of *ThreadRegistryEntry* objects for the wire.

    Accepts either dataclass entries or plain dicts for testability.
    """
    return [_serialize_thread_entry(t) for t in thread_entries]


def build_context_summary(
    *,
    tokens: int = 0,
    tools: int = 0,
    history: int = 0,
) -> dict[str, Any]:
    """Build a ``context_summary`` payload (or the nested value inside snapshot)."""
    return {
        "tokens": tokens,
        "tools": tools,
        "history": history,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_thread_entry(entry: object) -> dict[str, Any]:
    """Normalize one thread registry entry to the wire shape."""
    if isinstance(entry, dict):
        return {
            "slug": entry.get("slug", ""),
            "name": entry.get("name", ""),
            "scope": entry.get("scope", ""),
            "last_active": entry.get("updated_at"),
        }
    return {
        "slug": getattr(entry, "slug", ""),
        "name": getattr(entry, "name", ""),
        "scope": getattr(entry, "scope", ""),
        "last_active": getattr(entry, "updated_at", None),
    }
