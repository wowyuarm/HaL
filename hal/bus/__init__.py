"""Message bus module for decoupled channel-agent communication."""

from hal.bus.events import (
    Event,
    InboundMessage,
    MessageInjectEvent,
    OutboundMessage,
    ReminderEvent,
    SubagentCompleteEvent,
    ToolCallEvent,
)
from hal.bus.queue import MessageBus

__all__ = [
    "MessageBus",
    "Event",
    "InboundMessage",
    "OutboundMessage",
    "ToolCallEvent",
    "ReminderEvent",
    "SubagentCompleteEvent",
    "MessageInjectEvent",
]
