"""Unified memory manager coordinating all memory subsystems."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from hal.core.context.token_budget import estimate_text_tokens, trim_text_to_token_budget
from hal.core.memory.daily_log import DailyLog, LogEntry
from hal.workspace.events import EventEntry, EventLogRepository
from hal.workspace.logs import LogRepository


class _MemorySearchLike(Protocol):
    async def search(self, query: str, top_k: int = 3) -> list[object]: ...


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
        memory_search: _MemorySearchLike | None = None,
    ):
        from hal.workspace.memory import MemoryRepository

        logs_repository = LogRepository(data_dir or workspace)
        self.long_term = MemoryRepository(workspace)
        self.daily_log = DailyLog(logs_repository.logs_dir())
        self.event_log = EventLogRepository(data_dir or workspace)

        self._search = memory_search

    def get_context(self, budget_tokens: int | None = None, token_model: str | None = None) -> str:
        """
        Assemble memory context for prompt injection.

        Args:
            budget_tokens: Approximate token budget for memory section.
            token_model: Model id used for token counting.
        """
        lt = self.long_term.read()
        if not lt:
            return ""

        content = f"## Long-term Memory\n\n{lt}"
        if budget_tokens is None or budget_tokens <= 0:
            return content
        if estimate_text_tokens(content, model=token_model) <= budget_tokens:
            return content

        # Keep a valid markdown tail marker when truncation is required.
        return trim_text_to_token_budget(
            content,
            budget_tokens,
            model=token_model,
            suffix="\n\n[...truncated]",
        )

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
            channel: Channel name (e.g., "telegram", "cli")
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

    def record_event(
        self,
        *,
        session_id: str,
        event_type: str,
        channel: str | None = None,
        chat_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> EventEntry:
        """Append a unified session event to events.jsonl."""
        return self.event_log.append(
            session=session_id,
            event_type=event_type,
            channel=channel,
            chat_id=chat_id,
            payload=payload or {},
        )

    def get_conversation_history(
        self,
        channel: str,
        chat_id: str,
        max_messages: int = 50,
        include_tools: bool = False,
        recent_full_turns: int = 3,
        assistant_truncate_tokens: int = 50,
        max_tokens: int = 0,
        history_days: int = 1,
        token_model: str | None = None,
    ) -> list[dict[str, object]]:
        """
        Get recent conversation history for a specific channel/chat.

        Args:
            channel: Channel name
            chat_id: Chat identifier
            max_messages: Maximum number of messages to return
            include_tools: Whether to include tool messages
            recent_full_turns: Number of recent assistant messages kept verbatim.
            assistant_truncate_tokens: Max tokens for older assistant messages.

        Returns:
            List of messages in LLM format (role, content)
        """
        return self.daily_log.get_recent_conversation(
            channel=channel,
            chat_id=chat_id,
            max_messages=max_messages,
            include_tools=include_tools,
            recent_full_turns=recent_full_turns,
            assistant_truncate_tokens=assistant_truncate_tokens,
            max_tokens=max_tokens,
            history_days=history_days,
            token_model=token_model,
        )

    def get_conversation_stats(self) -> dict[str, object]:
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

    async def search_memories(self, query: str, top_k: int = 3) -> list[object]:
        """Semantic search over indexed past conversations.

        Returns empty list if memory search is not configured.
        """
        if self._search:
            return await self._search.search(query, top_k=top_k)
        return []
