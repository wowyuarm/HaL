"""Session event sink protocol and fan-out publisher.

The publisher owns monotonic sequence assignment for one session and distributes
events to registered sinks (working-log writer, WebSocket broadcaster, etc.).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from .events import ActorKind, SessionEvent


class SessionEventSink:
    """Base class / structural type for session event consumers.

    Subclass and override ``on_event`` to handle events. Using a concrete base
    rather than a Protocol keeps sink registration straightforward while still
    allowing duck-typed implementations.
    """

    async def on_event(self, event: SessionEvent) -> None:
        """Handle one emitted session event."""


class SessionEventPublisher:
    """Fan-out publisher that assigns monotonic sequence numbers per session.

    Exactly one publisher exists per active session. It is the sole authority
    for ``seq`` assignment, guaranteeing total order within one session's
    event stream.
    """

    def __init__(self, session_id: str, *, initial_seq: int = 0) -> None:
        self.session_id = session_id
        self._seq = initial_seq
        self._sinks: list[SessionEventSink] = []

    @property
    def last_seq(self) -> int:
        """Return the last assigned sequence number."""
        return self._seq

    def add_sink(self, sink: SessionEventSink) -> None:
        """Register an event sink. Duplicates are silently ignored."""
        if sink not in self._sinks:
            self._sinks.append(sink)

    def remove_sink(self, sink: SessionEventSink) -> None:
        """Unregister an event sink. Missing sinks are silently ignored."""
        try:
            self._sinks.remove(sink)
        except ValueError:
            pass

    async def emit(
        self,
        event_type: str,
        *,
        turn_id: str | None = None,
        actor: ActorKind,
        refs: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> SessionEvent:
        """Create an event, assign the next seq, and fan out to all sinks.

        Returns the fully constructed event for caller convenience (e.g. to
        update manifest.last_event_seq).
        """
        self._seq += 1
        event = SessionEvent(
            seq=self._seq,
            session_id=self.session_id,
            turn_id=turn_id,
            type=event_type,
            actor=actor,
            refs=refs or {},
            payload=payload or {},
        )
        for sink in list(self._sinks):
            try:
                await sink.on_event(event)
            except Exception:
                logger.warning(
                    "event sink error | session={} seq={} type={}",
                    self.session_id,
                    event.seq,
                    event_type,
                )
        return event

    async def close(self) -> None:
        """Detach all sinks. Call when session ends or engine shuts down."""
        self._sinks.clear()
