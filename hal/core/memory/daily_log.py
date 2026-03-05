"""Daily log — unified daily JSONL storage for all interactions.

Each day's conversations are stored in a separate JSONL file (YYYY-MM-DD.jsonl).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from hal.core.context.token_budget import estimate_content_tokens, trim_text_to_token_budget

_RESET_MARKER_ROLE = "system"
_RESET_MARKER_CONTENT = "conversation_reset"
_ROLE_USER = "user"
_ROLE_ASSISTANT = "assistant"
_ROLE_TOOL = "tool"
_ENTRY_TYPE_INJECTION = "injection"
_ENTRY_TYPE_SUMMARY = "summary"
_NO_RESPONSE_GENERATED_MESSAGE = "(No response generated.)"
_ERROR_CALLING_LLM_PREFIX = "Error calling LLM:"


class LogEntry(BaseModel):
    """A single entry in the daily log."""

    timestamp: str  # ISO format timestamp
    channel: str  # "telegram", "cli", "discord", etc.
    chat_id: str  # Chat identifier (e.g., "123456789" for Telegram, "cli" for CLI)
    role: str  # "user", "assistant", "tool"
    content: str
    tool_name: str | None = None  # Only for role="tool"
    tool_result: str | None = None  # Only for role="tool"
    entry_type: str = "message"  # "message" | "summary"
    origin: str = "user"


class DailyLog:
    """
    Unified daily log storing all interactions in daily JSONL files.

    Features:
    - Daily files: YYYY-MM-DD.jsonl
    - All channels unified (telegram, cli, discord, etc.)
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
            role=_RESET_MARKER_ROLE,
            content=_RESET_MARKER_CONTENT,
        )

    def append(
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
        Append a new entry to the daily log.

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
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            channel=channel,
            chat_id=chat_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_result=tool_result,
            entry_type=entry_type,
            origin=origin,
        )

        log_file = self._get_today_file()
        with log_file.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

        return entry

    def _load_entries_for_history_days(self, history_days: int) -> list[LogEntry]:
        """Load entries from today and up to ``history_days - 1`` previous days."""
        entries: list[LogEntry] = []
        days = max(history_days, 1)
        today = date.today()
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            day_file = self._get_file_for_date(day)
            if day_file.exists():
                entries.extend(self._read_file(day_file))
        return entries

    @staticmethod
    def _should_skip_entry(entry: LogEntry, include_tools: bool) -> bool:
        """Filter out normal tool entries when include_tools=False."""
        if include_tools:
            return False
        if entry.role != _ROLE_TOOL:
            return False
        return entry.entry_type not in (_ENTRY_TYPE_INJECTION, _ENTRY_TYPE_SUMMARY)

    @staticmethod
    def _is_context_pollution_entry(entry: LogEntry) -> bool:
        """Filter legacy assistant error placeholders from prompt history."""
        if entry.role != _ROLE_ASSISTANT:
            return False
        content = entry.content.strip()
        if content == _NO_RESPONSE_GENERATED_MESSAGE:
            return True
        return content.startswith(_ERROR_CALLING_LLM_PREFIX)

    @staticmethod
    def _collect_recent_entries(
        *,
        entries: list[LogEntry],
        channel: str,
        chat_id: str,
        include_tools: bool,
        max_messages: int,
    ) -> list[LogEntry]:
        """Keep newest messages until reset marker or max_messages is reached."""
        filtered = [
            entry for entry in entries if entry.channel == channel and entry.chat_id == chat_id
        ]

        result: list[LogEntry] = []
        for entry in reversed(filtered):
            if entry.role == _RESET_MARKER_ROLE and entry.content == _RESET_MARKER_CONTENT:
                break
            if DailyLog._is_context_pollution_entry(entry):
                continue
            if DailyLog._should_skip_entry(entry, include_tools):
                continue
            result.append(entry)
            if len(result) >= max_messages:
                break

        result.reverse()
        return result

    @staticmethod
    def _build_summary_lookup(entries: list[LogEntry]) -> tuple[dict[int, str], set[int]]:
        """Map assistant row index to paired summary content and indices to skip."""
        summary_for_assistant: dict[int, str] = {}
        skip_indices: set[int] = set()
        for i, entry in enumerate(entries):
            if (
                entry.entry_type == _ENTRY_TYPE_SUMMARY
                and entry.role == _ROLE_USER
                and i > 0
                and entries[i - 1].role == _ROLE_ASSISTANT
            ):
                summary_for_assistant[i - 1] = entry.content
                skip_indices.add(i)
        return summary_for_assistant, skip_indices

    @staticmethod
    def _resolve_assistant_content(
        *,
        entry_index: int,
        content: str,
        assistant_index: int,
        verbatim_threshold: int,
        summary_for_assistant: dict[int, str],
        assistant_truncate_tokens: int,
        token_model: str | None,
    ) -> str:
        """Return assistant content with summary/truncation policy applied."""
        if assistant_index > verbatim_threshold:
            return content

        summary_content = summary_for_assistant.get(entry_index)
        if summary_content is not None:
            return summary_content

        return _truncate_assistant(
            content,
            assistant_truncate_tokens,
            token_model=token_model,
        )

    @staticmethod
    def _build_messages(
        *,
        entries: list[LogEntry],
        recent_full_turns: int,
        assistant_truncate_tokens: int,
        token_model: str | None,
    ) -> list[dict[str, object]]:
        """Convert filtered entries to role/content messages with assistant truncation."""
        total_assistant = sum(1 for entry in entries if entry.role == _ROLE_ASSISTANT)
        verbatim_threshold = total_assistant - recent_full_turns
        summary_for_assistant, skip_indices = DailyLog._build_summary_lookup(entries)

        messages: list[dict[str, object]] = []
        assistant_index = 0
        for i, entry in enumerate(entries):
            if i in skip_indices:
                continue

            content = entry.content
            if entry.role == _ROLE_ASSISTANT:
                assistant_index += 1
                content = DailyLog._resolve_assistant_content(
                    entry_index=i,
                    content=content,
                    assistant_index=assistant_index,
                    verbatim_threshold=verbatim_threshold,
                    summary_for_assistant=summary_for_assistant,
                    assistant_truncate_tokens=assistant_truncate_tokens,
                    token_model=token_model,
                )

            messages.append({"role": entry.role, "content": content})

        return messages

    @staticmethod
    def _apply_max_tokens(
        *,
        messages: list[dict[str, object]],
        max_tokens: int,
        token_model: str | None,
    ) -> list[dict[str, object]]:
        """Keep the most recent suffix of messages within max_tokens."""
        if max_tokens <= 0 or not messages:
            return messages

        total = 0
        cutoff = 0
        for i in range(len(messages) - 1, -1, -1):
            total += estimate_content_tokens(messages[i].get("content", ""), model=token_model)
            if total > max_tokens:
                cutoff = i + 1
                break

        if cutoff >= len(messages):
            return [messages[-1]]
        if cutoff > 0:
            return messages[cutoff:]
        return messages

    def get_recent_conversation(
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

        Reads recent daily files based on ``history_days``.

        To reduce in-context learning contamination (where the model picks up
        formatting/style from its own earlier outputs), assistant messages beyond
        the most recent *recent_full_turns* are truncated to a short preview.
        User messages are always kept in full to preserve intent.

        Args:
            channel: Channel name
            chat_id: Chat identifier
            max_messages: Maximum number of messages to return
            include_tools: Whether to include tool messages
            recent_full_turns: Number of recent assistant messages to keep
                verbatim. Older assistant messages are truncated.
            assistant_truncate_tokens: Max tokens for older assistant messages.
            max_tokens: Hard cap on total output tokens (0 = unlimited).
            history_days: Number of days to include, counting today.
            token_model: Model id used for token counting.

        Returns:
            List of messages in LLM format (role, content)
        """
        entries = self._load_entries_for_history_days(history_days)
        recent_entries = self._collect_recent_entries(
            entries=entries,
            channel=channel,
            chat_id=chat_id,
            include_tools=include_tools,
            max_messages=max_messages,
        )
        messages = self._build_messages(
            entries=recent_entries,
            recent_full_turns=recent_full_turns,
            assistant_truncate_tokens=assistant_truncate_tokens,
            token_model=token_model,
        )
        return self._apply_max_tokens(
            messages=messages,
            max_tokens=max_tokens,
            token_model=token_model,
        )

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
        resolved_start, resolved_end = self._resolve_entry_date_range(
            start_date=start_date,
            end_date=end_date,
        )
        all_entries = self._load_entries_in_date_range(
            start_date=resolved_start,
            end_date=resolved_end,
        )
        return self._filter_entries(
            entries=all_entries,
            channel=channel,
            chat_id=chat_id,
        )

    @staticmethod
    def _resolve_entry_date_range(
        *, start_date: date | None, end_date: date | None
    ) -> tuple[date, date]:
        resolved_start = start_date or date.fromordinal(date.today().toordinal() - 30)
        resolved_end = end_date or date.today()
        return resolved_start, resolved_end

    def _load_entries_in_date_range(self, *, start_date: date, end_date: date) -> list[LogEntry]:
        entries: list[LogEntry] = []
        for ordinal in range(start_date.toordinal(), end_date.toordinal() + 1):
            log_file = self._get_file_for_date(date.fromordinal(ordinal))
            if log_file.exists():
                entries.extend(self._read_file(log_file))
        return entries

    @staticmethod
    def _filter_entries(
        *, entries: list[LogEntry], channel: str | None = None, chat_id: str | None = None
    ) -> list[LogEntry]:
        if channel is None and chat_id is None:
            return entries
        return [
            entry
            for entry in entries
            if (channel is None or entry.channel == channel)
            and (chat_id is None or entry.chat_id == chat_id)
        ]

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

    def get_stats(self) -> dict[str, object]:
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


def _truncate_assistant(content: str, max_tokens: int, token_model: str | None = None) -> str:
    """Truncate an assistant message to a factual preview.

    Strips style/formatting from older assistant outputs so the LLM sees
    *what was done* without picking up *how it was phrased*.
    """
    return trim_text_to_token_budget(
        content,
        max_tokens,
        model=token_model,
        suffix=" [...]",
        collapse_newlines=True,
    )
