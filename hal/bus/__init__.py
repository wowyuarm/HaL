"""Message bus module for decoupled channel-agent communication."""

from hal.bus.events import InboundMessage, OutboundMessage
from hal.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
