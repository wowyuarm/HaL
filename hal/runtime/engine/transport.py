"""Thin transport registry for adapter-facing session lookups.

Native session state remains session-first: durable transport metadata lives on
the session manifest itself. This registry only answers the adapter question
"given a transport key, which active session should receive it?".
"""

from __future__ import annotations

from dataclasses import dataclass


def build_transport_session_key(channel: str, chat_id: str) -> str:
    """Build the adapter-facing session key for one transport endpoint."""
    return f"{channel}:{chat_id}"


@dataclass(frozen=True, slots=True)
class SessionTransportContext:
    """Resolved transport metadata for one session."""

    channel: str
    chat_id: str

    @property
    def session_key(self) -> str:
        """Return the transport session key for this context."""
        return build_transport_session_key(self.channel, self.chat_id)


class SessionTransportRegistry:
    """Maintain active transport-key -> session-id bindings for adapters."""

    def __init__(self) -> None:
        self._session_ids_by_key: dict[str, str] = {}

    def bind(self, *, session_id: str, channel: str, chat_id: str) -> None:
        """Bind one transport endpoint to a session, replacing stale mappings."""
        self.unbind_session(session_id)
        self._session_ids_by_key[build_transport_session_key(channel, chat_id)] = session_id

    def unbind_session(self, session_id: str) -> None:
        """Remove every transport binding that points at *session_id*."""
        for key, value in list(self._session_ids_by_key.items()):
            if value == session_id:
                self._session_ids_by_key.pop(key, None)

    def resolve_session_id(self, session_key: str) -> str | None:
        """Resolve the active session id for one adapter session key."""
        return self._session_ids_by_key.get(session_key)

    def has_binding(self, *, channel: str, chat_id: str) -> bool:
        """Return True when a binding already exists for this endpoint."""
        return build_transport_session_key(channel, chat_id) in self._session_ids_by_key
