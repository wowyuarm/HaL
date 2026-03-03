"""Async message queue for decoupled channel-agent communication."""

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable

from loguru import logger

from hal.bus.events import Event, InboundMessage, OutboundMessage

EventHandler = Callable[[Event], Awaitable[None] | None]


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.

    Event-driven extension points:
    1. Define a typed event dataclass in ``hal.bus.events``.
    2. Emit that event from the producer (channel, engine hook, or tool) via
       ``await bus.emit(MyEvent(...))``.
    3. Register subscribers with ``bus.subscribe(MyEvent, handler)``.
    4. Keep core queue flow unchanged unless the feature needs new routing.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._subscribers: dict[type[Event], list[EventHandler]] = defaultdict(list)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    def subscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Subscribe a handler to a specific event type."""
        handlers = self._subscribers[event_type]
        if handler not in handlers:
            handlers.append(handler)

    def unsubscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Remove a previously registered event handler."""
        handlers = self._subscribers.get(event_type)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            return
        if not handlers:
            self._subscribers.pop(event_type, None)

    async def emit(self, event: Event) -> None:
        """Emit a typed event to all matching subscribers (fanout)."""
        handlers = self._matching_handlers(event)
        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.warning(
                    f"MessageBus event handler failed for {type(event).__name__}: {e}"
                )

    def emit_nowait(self, event: Event) -> None:
        """Schedule event emission without blocking the current call stack."""
        try:
            task = asyncio.create_task(self.emit(event))
        except RuntimeError:
            # No running loop; drop silently to keep queue-only flows unaffected.
            return
        task.add_done_callback(self._log_emit_failure)

    def _matching_handlers(self, event: Event) -> list[EventHandler]:
        handlers: list[EventHandler] = []
        for subscribed_type, type_handlers in self._subscribers.items():
            if isinstance(event, subscribed_type):
                handlers.extend(type_handlers)
        return handlers

    @staticmethod
    def _log_emit_failure(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception as e:
            logger.warning(f"MessageBus emit task failed: {e}")

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
