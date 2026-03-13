"""Session event models and type constants for event-sourced runtime flows.

Events are the evidence layer of the session-first architecture. Durable events
persist to per-session ``working-log.jsonl`` for UI reconstruction, brief input,
and audit. Transient events travel only over the live WebSocket connection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

EVENT_SCHEMA_VERSION = 1

ActorKind = Literal["user", "engine", "tool", "worker"]

# ---------------------------------------------------------------------------
# Event type constants — dot-notation for structured logging readability
# ---------------------------------------------------------------------------

# Session lifecycle
SESSION_CREATED = "session.created"
SESSION_SCOPE_UPDATED = "session.scope_updated"
SESSION_ENDED = "session.ended"
SESSION_COMPACTED = "session.compacted"

# Turn lifecycle
TURN_STARTED = "turn.started"
TURN_COMPLETED = "turn.completed"
TURN_FAILED = "turn.failed"

# User
USER_MESSAGE = "user.message"

# Context compilation
CONTEXT_COMPILED = "context.compiled"

# LLM tool loop
LOOP_STARTED = "loop.started"
LOOP_ITERATION_STARTED = "loop.iteration_started"
LLM_REQUEST_STARTED = "llm.request_started"
LLM_RESPONSE_COMPLETED = "llm.response_completed"

# Tool calls
TOOL_CALL_STARTED = "tool.call_started"
TOOL_CALL_COMPLETED = "tool.call_completed"
TOOL_CALL_FAILED = "tool.call_failed"

# Assistant output
ASSISTANT_MESSAGE_STARTED = "assistant.message_started"
ASSISTANT_MESSAGE_COMPLETED = "assistant.message_completed"

# Injections (hooks, reminders, subagent results)
HOOK_INJECTED = "hook.injected"
MESSAGE_INJECTED = "message.injected"

# Subagent
SUBAGENT_SPAWNED = "subagent.spawned"
SUBAGENT_COMPLETED = "subagent.completed"

# Brief worker
BRIEF_STARTED = "brief.started"
BRIEF_COMPLETED = "brief.completed"

# Transient (WebSocket only — never persisted to working-log)
ASSISTANT_CHUNK = "assistant.chunk"
STATUS_CHANGED = "status.changed"

TRANSIENT_TYPES: frozenset[str] = frozenset({ASSISTANT_CHUNK, STATUS_CHANGED})

# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


class SessionEvent(BaseModel):
    """One structured event emitted during a session's lifecycle.

    Events are the atomic unit of the working log. Each carries a monotonically
    increasing ``seq`` assigned by the owning ``SessionEventPublisher``, making
    the per-session event stream totally ordered.
    """

    v: int = EVENT_SCHEMA_VERSION
    seq: int
    ts: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: str
    turn_id: str | None = None
    type: str
    actor: ActorKind
    refs: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_durable(event_type: str) -> bool:
    """Return True when an event type should be persisted to durable storage."""
    return event_type not in TRANSIENT_TYPES
