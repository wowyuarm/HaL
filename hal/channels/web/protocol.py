"""Wire protocol helpers for the web channel.

All functions are pure — no side effects, no I/O.  They translate between
the domain event types and the JSON shapes defined in the WebSocket protocol
spec (see docs/specs/2026-03-11-web-client-design.md, section "WebSocket protocol").
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

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
        "id": _outbound_message_id(msg),
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


def build_history(messages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize persisted session snapshot messages into web wire history."""
    history: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        normalized = _normalize_history_message(message, index=index)
        if normalized is not None:
            history.append(normalized)
    return history


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


def _outbound_message_id(msg: OutboundMessage) -> str:
    message_id = str(msg.metadata.get("message_id", "")).strip()
    if message_id:
        return message_id
    return f"msg_{uuid4().hex}"


def _normalize_history_message(
    message: dict[str, Any], *, index: int
) -> dict[str, Any] | None:
    role = str(message.get("role", "")).strip()
    if role not in {"user", "assistant"}:
        return None

    content = message.get("content", "")
    if not isinstance(content, str):
        content = str(content)

    raw_tool_calls = message.get("tool_calls")
    metadata = _normalize_history_metadata(message)
    normalized: dict[str, Any] = {
        "id": _history_message_id(message, index=index),
        "role": role,
        "content": content,
        "ts": _normalize_timestamp(message.get("ts")),
    }
    if metadata:
        normalized["metadata"] = metadata
    elif role == "assistant" and isinstance(raw_tool_calls, list) and raw_tool_calls:
        normalized["metadata"] = {
            "tool_calls": [_serialize_tool_call(tool_call, idx) for idx, tool_call in enumerate(raw_tool_calls)]
        }
    return normalized


def _normalize_history_metadata(message: dict[str, Any]) -> dict[str, Any] | None:
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return None
    tool_calls = metadata.get("tool_calls")
    if not isinstance(tool_calls, list):
        return dict(metadata)
    normalized_tool_calls = [
        tc for tc in (_normalize_wire_tool_call(item) for item in tool_calls) if tc is not None
    ]
    next_metadata = dict(metadata)
    next_metadata["tool_calls"] = normalized_tool_calls
    return next_metadata


def _normalize_wire_tool_call(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    call_id = str(item.get("id", "")).strip() or f"tc_{uuid4().hex[:8]}"
    name = str(item.get("name", "")).strip() or "tool"
    args_summary = str(item.get("args_summary", "")).strip()
    status = str(item.get("status", "completed")).strip() or "completed"
    normalized = {
        "id": call_id,
        "name": name,
        "args_summary": args_summary,
        "status": status,
    }
    error = item.get("error")
    if isinstance(error, str) and error.strip():
        normalized["error"] = error.strip()
    return normalized


def _serialize_tool_call(tool_call: Any, index: int) -> dict[str, Any]:
    if not isinstance(tool_call, dict):
        return {
            "id": f"tc_{index}",
            "name": "tool",
            "args_summary": str(tool_call),
            "status": "completed",
        }

    function = tool_call.get("function", {}) if isinstance(tool_call.get("function"), dict) else {}
    arguments = function.get("arguments", "")
    args_summary = _summarize_tool_args(arguments)
    return {
        "id": str(tool_call.get("id", "")).strip() or f"tc_{index}",
        "name": str(function.get("name", "")).strip() or f"tool_{index + 1}",
        "args_summary": args_summary,
        "status": "completed",
    }


def _summarize_tool_args(arguments: Any) -> str:
    if isinstance(arguments, str):
        raw = arguments.strip()
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
        except Exception:
            return raw[:80]
        return _summarize_tool_args(parsed)
    if isinstance(arguments, dict):
        if not arguments:
            return ""
        key = next(iter(arguments))
        value = arguments[key]
        preview = str(value)
        if len(preview) > 80:
            preview = preview[:77] + "..."
        return f"{key}={preview}"
    return str(arguments)


def _history_message_id(message: dict[str, Any], *, index: int) -> str:
    existing = str(message.get("id", "")).strip()
    if existing:
        return existing
    digest = hashlib.sha1(
        json.dumps(message, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    return f"hist_{index}_{digest}"


def _normalize_timestamp(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return datetime.now(tz=timezone.utc).isoformat()
