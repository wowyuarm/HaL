"""Event and message types for the message bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # telegram, discord, feishu
    sender_id: str  # User identifier
    chat_id: str  # Chat/channel identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # Media URLs
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data
    origin: Literal["user"] = "user"  # Message source

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
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
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


@dataclass
class ReminderEvent(Event):
    """A system reminder is injected into the current loop context."""

    content: str
    total_tool_calls: int
    messages: list[dict[str, Any]]
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


@dataclass
class MessageInjectEvent(Event):
    """A user follow-up message was injected during an active tool loop."""

    message: InboundMessage
    prefixed_content: str
    messages: list[dict[str, Any]]
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None


@dataclass
class SubagentCompleteEvent(Event):
    """A background/sync subagent result was injected back into the loop."""

    label: str
    status: str
    content: str
    background: bool
    messages: list[dict[str, Any]]
    channel: str | None = None
    chat_id: str | None = None
    session_key: str | None = None
    record_id: str | None = None
    artifact_path: str | None = None
    total_tokens: int = 0
    tools_used: list[str] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    has_side_effects: bool = False
    files_modified: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    missing_artifacts: list[str] = field(default_factory=list)


@dataclass
class SystemStartupEvent(Event):
    """HaL service startup signal for channels/integrations."""

    channel: str
    chat_id: str
    commit_info: str
    update_info: dict[str, str] | None = None


__all__ = [
    "Event",
    "InboundMessage",
    "OutboundMessage",
    "ToolCallEvent",
    "ReminderEvent",
    "MessageInjectEvent",
    "SubagentCompleteEvent",
    "SystemStartupEvent",
]
