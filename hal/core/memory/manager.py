"""Unified memory manager coordinating all memory subsystems."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal.core.memory.daily_log import DailyLog, LogEntry

if TYPE_CHECKING:
    from hal.core.memory.search import MemorySearch
    from hal.core.memory.store import SearchResult


class MemoryManager:
    """
    Central coordinator for all memory subsystems.

    Provides a unified interface for:
    - Recording conversations (daily log)
    - Reading/writing persistent knowledge (long-term)
    - Assembling memory context for prompt injection
    - Semantic search over past conversations (optional)
    """

    def __init__(
        self,
        workspace: Path,
        data_dir: Path | None = None,
        memory_search: MemorySearch | None = None,
    ):
        from hal.core.memory.long_term import LongTermMemory

        memory_dir = workspace / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        self.long_term = LongTermMemory(memory_dir / "MEMORY.md")

        log_dir = (data_dir or workspace) / "logs"
        self.daily_log = DailyLog(log_dir)

        self._search = memory_search

    def get_context(self, budget: int | None = None) -> str:
        """
        Assemble memory context for prompt injection.

        Args:
            budget: Approximate token limit for memory section (not yet enforced).
        """
        lt = self.long_term.read()
        if lt:
            return f"## Long-term Memory\n\n{lt}"
        return ""

    def record_conversation(
        self,
        channel: str,
        chat_id: str,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_result: str | None = None,
        entry_type: str = "message",
        origin: str = "user",
    ) -> LogEntry:
        """
        Record a conversation entry in the daily log.

        Args:
            channel: Channel name (e.g., "telegram", "cli", "cron")
            chat_id: Chat identifier
            role: "user", "assistant", or "tool"
            content: Message content
            tool_name: Tool name (only for role="tool")
            tool_result: Tool result (only for role="tool")
            entry_type: Entry type ("message" or "summary")

        Returns:
            The created log entry
        """
        return self.daily_log.append(
            channel=channel,
            chat_id=chat_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_result=tool_result,
            entry_type=entry_type,
            origin=origin,
        )

    def get_conversation_history(
        self,
        channel: str,
        chat_id: str,
        max_messages: int = 50,
        include_tools: bool = False,
        recent_full_turns: int = 3,
        assistant_truncate_chars: int = 200,
    ) -> list[dict[str, Any]]:
        """
        Get recent conversation history for a specific channel/chat.

        Args:
            channel: Channel name
            chat_id: Chat identifier
            max_messages: Maximum number of messages to return
            include_tools: Whether to include tool messages
            recent_full_turns: Number of recent assistant messages kept verbatim.
            assistant_truncate_chars: Max chars for older assistant messages.

        Returns:
            List of messages in LLM format (role, content)
        """
        return self.daily_log.get_recent_conversation(
            channel=channel,
            chat_id=chat_id,
            max_messages=max_messages,
            include_tools=include_tools,
            recent_full_turns=recent_full_turns,
            assistant_truncate_chars=assistant_truncate_chars,
        )

    def get_conversation_stats(self) -> dict[str, Any]:
        """Get statistics about conversation logs."""
        return self.daily_log.get_stats()

    def clear_conversation_history(
        self,
        channel: str,
        chat_id: str,
    ) -> LogEntry:
        """
        Clear conversation history for a specific channel/chat by marking a reset point.

        Args:
            channel: Channel name
            chat_id: Chat identifier

        Returns:
            The reset marker entry
        """
        return self.daily_log.mark_reset(
            channel=channel,
            chat_id=chat_id,
        )

    async def search_memories(self, query: str, top_k: int = 3) -> list[SearchResult]:
        """Semantic search over indexed past conversations.

        Returns empty list if memory search is not configured.
        """
        if self._search:
            return await self._search.search(query, top_k=top_k)
        return []
