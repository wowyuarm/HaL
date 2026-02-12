"""Daily log — unified daily JSONL storage for all interactions.

Each day's conversations are stored in a separate JSONL file (YYYY-MM-DD.jsonl).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel


class LogEntry(BaseModel):
    """A single entry in the daily log."""

    timestamp: str  # ISO format timestamp
    channel: str  # "telegram", "cli", "cron", "discord", etc.
    chat_id: str  # Chat identifier (e.g., "123456789" for Telegram, "cli" for CLI)
    role: str  # "user", "assistant", "tool"
    content: str
    tool_name: str | None = None  # Only for role="tool"
    tool_result: str | None = None  # Only for role="tool"


class DailyLog:
    """
    Unified daily log storing all interactions in daily JSONL files.

    Features:
    - Daily files: YYYY-MM-DD.jsonl
    - All channels unified (telegram, cli, cron, etc.)
    - Tool messages are recorded but can be filtered out for context building
    - Simple append-only format
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_today_file(self) -> Path:
        """Get the log file path for today."""
        today = date.today().isoformat()
        return self.data_dir / f"{today}.jsonl"

    def _get_file_for_date(self, log_date: date) -> Path:
        """Get the log file path for a specific date."""
        return self.data_dir / f"{log_date.isoformat()}.jsonl"

    def mark_reset(self, channel: str, chat_id: str) -> LogEntry:
        """
        Mark a reset point for a conversation. Messages before this point will be ignored.

        Args:
            channel: Channel name
            chat_id: Chat identifier

        Returns:
            The created reset marker entry
        """
        return self.append(
            channel=channel,
            chat_id=chat_id,
            role="system",
            content="conversation_reset",
        )

    def append(
        self,
        channel: str,
        chat_id: str,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_result: str | None = None,
    ) -> LogEntry:
        """
        Append a new entry to the daily log.

        Args:
            channel: Channel name (e.g., "telegram", "cli", "cron")
            chat_id: Chat identifier
            role: "user", "assistant", or "tool"
            content: Message content
            tool_name: Tool name (only for role="tool")
            tool_result: Tool result (only for role="tool")

        Returns:
            The created log entry
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            channel=channel,
            chat_id=chat_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_result=tool_result,
        )

        log_file = self._get_today_file()
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

        return entry

    def get_recent_conversation(
        self,
        channel: str,
        chat_id: str,
        max_messages: int = 50,
        include_tools: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get recent conversation history for a specific channel/chat.

        Only reads today's file — conversations don't span days.

        Args:
            channel: Channel name
            chat_id: Chat identifier
            max_messages: Maximum number of messages to return
            include_tools: Whether to include tool messages

        Returns:
            List of messages in LLM format (role, content)
        """
        entries: list[LogEntry] = []

        today_file = self._get_today_file()
        if today_file.exists():
            entries.extend(self._read_file(today_file))

        # Filter by channel and chat_id
        filtered = [
            entry for entry in entries if entry.channel == channel and entry.chat_id == chat_id
        ]

        # Process from newest to oldest, stopping at reset markers
        result: list[LogEntry] = []
        for entry in reversed(filtered):
            if entry.role == "system" and entry.content == "conversation_reset":
                break

            if not include_tools and entry.role == "tool":
                continue

            result.append(entry)
            if len(result) >= max_messages:
                break

        # Reverse back to chronological order (oldest to newest)
        result.reverse()

        return [{"role": entry.role, "content": entry.content} for entry in result]

    def get_all_entries(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[LogEntry]:
        """
        Get all log entries with optional filtering.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            channel: Filter by channel
            chat_id: Filter by chat_id

        Returns:
            List of log entries
        """
        all_entries: list[LogEntry] = []

        if start_date is None:
            start_date = date.fromordinal(date.today().toordinal() - 30)
        if end_date is None:
            end_date = date.today()

        current = start_date
        while current <= end_date:
            log_file = self._get_file_for_date(current)
            if log_file.exists():
                all_entries.extend(self._read_file(log_file))
            current = date.fromordinal(current.toordinal() + 1)

        if channel:
            all_entries = [entry for entry in all_entries if entry.channel == channel]
        if chat_id:
            all_entries = [entry for entry in all_entries if entry.chat_id == chat_id]

        return all_entries

    def _read_file(self, file_path: Path) -> list[LogEntry]:
        """Read all entries from a JSONL file."""
        entries = []
        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = LogEntry.model_validate_json(line)
                            entries.append(entry)
                        except Exception as e:
                            logger.warning(f"Failed to parse log entry: {e}")
        except Exception as e:
            logger.warning(f"Failed to read log file {file_path}: {e}")

        return entries

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the daily log."""
        stats = {
            "total_entries": 0,
            "by_channel": {},
            "by_date": {},
            "by_role": {"user": 0, "assistant": 0, "tool": 0},
        }

        log_files = list(self.data_dir.glob("*.jsonl"))
        for log_file in log_files:
            date_str = log_file.stem
            entries = self._read_file(log_file)
            stats["total_entries"] += len(entries)
            stats["by_date"][date_str] = len(entries)

            for entry in entries:
                stats["by_channel"][entry.channel] = stats["by_channel"].get(entry.channel, 0) + 1
                if entry.role in stats["by_role"]:
                    stats["by_role"][entry.role] += 1

        return stats
