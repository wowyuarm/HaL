"""Event and message types for the message bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from hal.domain.ports import SubagentArtifactMetadata, SubagentUsageMetadata


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # telegram, discord, feishu
    sender_id: str  # User identifier
    chat_id: str  # Chat/channel identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # Media URLs
    attachments: list[dict[str, Any]] = field(default_factory=list)  # Structured user attachments
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data
    origin: Literal["user"] = "user"  # Message source
    session_id: str | None = None  # Session-first identity (set by transport adapter)

    @property
    def session_key(self) -> str:
        """Unique key for session identification (transport-level)."""
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class Event:
    """Base class for typed bus events."""

    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ToolCallEvent(Event):
    """A tool call finished and produced a result."""

    tool_name: str
    tool_id: str
    arguments: dict[str, Any]
    result: str
    total_tool_calls: int
    messages: list[dict[str, Any]]
    turn_id: str | None = None
    session_id: str | None = None
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


@dataclass
class ReminderEvent(Event):
    """A system reminder is injected into the current loop context."""

    content: str
    total_tool_calls: int
    messages: list[dict[str, Any]]
    turn_id: str | None = None
    session_id: str | None = None
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


@dataclass
class MessageInjectEvent(Event):
    """A user follow-up message was injected during an active tool loop."""

    message: InboundMessage
    prefixed_content: str
    messages: list[dict[str, Any]]
    turn_id: str | None = None
    session_id: str | None = None
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


@dataclass
class SubagentCompleteEvent(Event, SubagentArtifactMetadata[str], SubagentUsageMetadata):
    """A background/sync subagent result was injected back into the loop."""

    label: str
    status: str
    content: str
    background: bool
    messages: list[dict[str, Any]]
    turn_id: str | None = None
    session_id: str | None = None
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


__all__ = [
    "Event",
    "InboundMessage",
    "OutboundMessage",
    "ToolCallEvent",
    "ReminderEvent",
    "MessageInjectEvent",
    "SubagentCompleteEvent",
]
