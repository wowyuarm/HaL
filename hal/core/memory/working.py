"""Working memory — current session context."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hal.session.manager import Session


class WorkingMemory:
    """
    Current conversation context.

    Wraps Session to provide a memory-oriented interface.
    """

    def __init__(self, session: "Session"):
        self._session = session

    def get_history(self, max_messages: int = 50) -> list[dict[str, Any]]:
        """Get recent conversation messages."""
        history = self._session.get_history()
        if len(history) > max_messages:
            return history[-max_messages:]
        return history

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation."""
        self._session.add_message(role, content)

    @property
    def message_count(self) -> int:
        """Number of messages in the session."""
        return len(self._session.messages)
