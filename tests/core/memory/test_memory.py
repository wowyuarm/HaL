"""Tests for the HaL memory system (daily log, long-term, manager)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from hal.core.context.token_budget import estimate_text_tokens
from hal.core.memory.daily_log import DailyLog, LogEntry, _truncate_assistant
from hal.core.memory.long_term import LongTermMemory
from hal.core.memory.manager import MemoryManager

# ---------------------------------------------------------------------------
# DailyLog
# ---------------------------------------------------------------------------


class TestDailyLog:
    """Tests for DailyLog — daily JSONL conversation storage."""

    def test_append_creates_entry(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        entry = log.append(channel="cli", chat_id="direct", role="user", content="hello")

        assert entry.channel == "cli"
        assert entry.chat_id == "direct"
        assert entry.role == "user"
        assert entry.content == "hello"

    def test_get_recent_conversation_returns_messages(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="hi")
        log.append(channel="cli", chat_id="d", role="assistant", content="hello")

        history = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "hi"}
        assert history[1] == {"role": "assistant", "content": "hello"}

    def test_get_recent_conversation_filters_error_placeholders(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="hi")
        log.append(
            channel="cli", chat_id="d", role="assistant", content="Error calling LLM: timeout"
        )
        log.append(channel="cli", chat_id="d", role="assistant", content="(No response generated.)")
        log.append(channel="cli", chat_id="d", role="assistant", content="all good")

        history = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "hi"}
        assert history[1] == {"role": "assistant", "content": "all good"}

    def test_get_recent_conversation_filters_by_channel(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="cli msg")
        log.append(channel="telegram", chat_id="d", role="user", content="tg msg")

        history = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history) == 1
        assert history[0]["content"] == "cli msg"

    def test_get_recent_conversation_respects_reset(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="old msg")
        log.mark_reset(channel="cli", chat_id="d")
        log.append(channel="cli", chat_id="d", role="user", content="new msg")

        history = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history) == 1
        assert history[0]["content"] == "new msg"

    def test_get_recent_conversation_excludes_tools_by_default(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="run")
        log.append(channel="cli", chat_id="d", role="tool", content="result", tool_name="fs")
        log.append(channel="cli", chat_id="d", role="assistant", content="done")

        history = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history) == 2

        history_with_tools = log.get_recent_conversation(
            channel="cli", chat_id="d", include_tools=True
        )
        assert len(history_with_tools) == 3

    def test_get_recent_conversation_respects_max_messages(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        for i in range(10):
            log.append(channel="cli", chat_id="d", role="user", content=f"msg-{i}")

        history = log.get_recent_conversation(channel="cli", chat_id="d", max_messages=3)
        assert len(history) == 3
        # Should be the most recent 3
        assert history[0]["content"] == "msg-7"

    def test_get_recent_conversation_respects_max_tokens(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="short-1")
        log.append(channel="cli", chat_id="d", role="assistant", content="short-2")
        log.append(channel="cli", chat_id="d", role="user", content="X" * 100)

        history = log.get_recent_conversation(channel="cli", chat_id="d", max_tokens=20)
        assert len(history) == 1
        assert history[0]["content"] == "X" * 100

    def test_get_recent_conversation_reads_history_days(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        today = date.today()
        yesterday = today - timedelta(days=1)

        today_entry = LogEntry(
            timestamp=f"{today.isoformat()}T10:00:00",
            channel="cli",
            chat_id="d",
            role="assistant",
            content="today-msg",
        )
        yesterday_entry = LogEntry(
            timestamp=f"{yesterday.isoformat()}T10:00:00",
            channel="cli",
            chat_id="d",
            role="user",
            content="yesterday-msg",
        )

        (log.data_dir / f"{today.isoformat()}.jsonl").write_text(
            today_entry.model_dump_json() + "\n", encoding="utf-8"
        )
        (log.data_dir / f"{yesterday.isoformat()}.jsonl").write_text(
            yesterday_entry.model_dump_json() + "\n", encoding="utf-8"
        )

        history_default = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history_default) == 1
        assert history_default[0]["content"] == "today-msg"

        history_two_days = log.get_recent_conversation(channel="cli", chat_id="d", history_days=2)
        assert len(history_two_days) == 2
        assert history_two_days[0]["content"] == "yesterday-msg"
        assert history_two_days[1]["content"] == "today-msg"

    def test_get_stats(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="hi")
        log.append(channel="cli", chat_id="d", role="assistant", content="hello")

        stats = log.get_stats()
        assert stats["total_entries"] == 2
        assert stats["by_role"]["user"] == 1
        assert stats["by_role"]["assistant"] == 1


# ---------------------------------------------------------------------------
# LongTermMemory
# ---------------------------------------------------------------------------


class TestLongTermMemory:
    """Tests for LongTermMemory — MEMORY.md backed persistent knowledge."""

    def test_read_returns_empty_for_nonexistent_file(self, tmp_path: Path):
        mem = LongTermMemory(tmp_path / "does_not_exist.md")
        assert mem.read() == ""

    def test_update_creates_and_writes_file(self, tmp_path: Path):
        mem_file = tmp_path / "subdir" / "MEMORY.md"
        mem = LongTermMemory(mem_file)
        mem.update("# My Memory\nSome facts.")

        assert mem_file.exists()
        assert mem_file.read_text(encoding="utf-8") == "# My Memory\nSome facts."

    def test_read_returns_content_after_write(self, tmp_path: Path):
        mem = LongTermMemory(tmp_path / "MEMORY.md")
        mem.update("hello world")
        assert mem.read() == "hello world"

    def test_get_section_extracts_markdown_section(self, tmp_path: Path):
        content = (
            "# Title\n\n## Preferences\nI like concise answers.\n\n## Facts\nThe sky is blue.\n"
        )
        mem = LongTermMemory(tmp_path / "MEMORY.md")
        mem.update(content)

        section = mem.get_section("Preferences")
        assert section == "I like concise answers."

        section2 = mem.get_section("Facts")
        assert section2 == "The sky is blue."

    def test_get_section_returns_none_for_missing_section(self, tmp_path: Path):
        mem = LongTermMemory(tmp_path / "MEMORY.md")
        mem.update("## Existing\nSome content.\n")

        assert mem.get_section("Nonexistent") is None

    def test_get_section_returns_none_for_empty_file(self, tmp_path: Path):
        mem = LongTermMemory(tmp_path / "MEMORY.md")
        assert mem.get_section("Anything") is None

    def test_update_section_updates_specific_section(self, tmp_path: Path):
        content = "## Alpha\nOld alpha content.\n\n## Beta\nOld beta content.\n"
        mem = LongTermMemory(tmp_path / "MEMORY.md")
        mem.update(content)

        mem.update_section("Alpha", "New alpha content.")
        result = mem.read()

        assert "New alpha content." in result
        assert "Old alpha content." not in result
        assert "Old beta content." in result

    def test_update_section_appends_when_not_found(self, tmp_path: Path):
        content = "## Existing\nSome content.\n"
        mem = LongTermMemory(tmp_path / "MEMORY.md")
        mem.update(content)

        mem.update_section("NewSection", "Brand new content.")
        result = mem.read()

        assert "## NewSection" in result
        assert "Brand new content." in result
        assert "## Existing" in result
        assert "Some content." in result


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------


class TestMemoryManager:
    """Tests for MemoryManager — coordinator of all memory subsystems."""

    def test_get_context_includes_long_term_memory(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.long_term.update("## Knowledge\nImportant fact.\n")

        ctx = mgr.get_context()
        assert "Long-term Memory" in ctx
        assert "Important fact." in ctx

    def test_get_context_empty_when_no_data(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        ctx = mgr.get_context()
        assert ctx == ""

    def test_get_context_respects_budget_tokens(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.long_term.update("A" * 200)
        ctx = mgr.get_context(budget_tokens=20)
        assert estimate_text_tokens(ctx) <= 20
        assert "[...truncated]" in ctx

    def test_record_conversation_creates_entry(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        entry = mgr.record_conversation(
            channel="cli", chat_id="direct", role="user", content="hello"
        )
        assert entry.content == "hello"

    def test_get_conversation_history(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.record_conversation(channel="cli", chat_id="d", role="user", content="hi")
        mgr.record_conversation(channel="cli", chat_id="d", role="assistant", content="hello")

        history = mgr.get_conversation_history(channel="cli", chat_id="d")
        assert len(history) == 2

    def test_clear_conversation_history(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.record_conversation(channel="cli", chat_id="d", role="user", content="old")
        mgr.clear_conversation_history(channel="cli", chat_id="d")
        mgr.record_conversation(channel="cli", chat_id="d", role="user", content="new")

        history = mgr.get_conversation_history(channel="cli", chat_id="d")
        assert len(history) == 1
        assert history[0]["content"] == "new"

    def test_manager_uses_data_dir_for_logs(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        data_dir = tmp_path / "data"
        mgr = MemoryManager(workspace=workspace, data_dir=data_dir)

        mgr.record_conversation(channel="cli", chat_id="d", role="user", content="stored elsewhere")

        # Log files should be in data_dir, not workspace
        log_files = list((data_dir / "runtime" / "logs").glob("*.jsonl"))
        assert len(log_files) == 1

    def test_get_conversation_stats(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.record_conversation(channel="cli", chat_id="d", role="user", content="hi")

        stats = mgr.get_conversation_stats()
        assert stats["total_entries"] == 1

    def test_record_event_writes_unified_events_log(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        entry = mgr.record_event(
            session_id="s_test",
            event_type="user_message",
            channel="cli",
            chat_id="d",
            payload={"content": "hello"},
        )

        assert entry.session == "s_test"
        assert entry.type == "user_message"
        assert entry.payload["content"] == "hello"

        events_file = tmp_path / "runtime" / "logs" / "events.jsonl"
        assert events_file.exists()
        lines = [line for line in events_file.read_text(encoding="utf-8").splitlines() if line]
        assert len(lines) == 1
        assert '"session":"s_test"' in lines[0]
        assert '"type":"user_message"' in lines[0]


# ---------------------------------------------------------------------------
# DailyLog — entry_type and summary merging
# ---------------------------------------------------------------------------


class TestDailyLogEntryType:
    """Tests for entry_type field and summary merging logic."""

    def test_append_with_entry_type_summary(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        entry = log.append(
            channel="cli",
            chat_id="d",
            role="assistant",
            content="summary text",
            entry_type="summary",
        )
        assert entry.entry_type == "summary"

    def test_default_entry_type_is_message(self, tmp_path: Path):
        log = DailyLog(tmp_path / "logs")
        entry = log.append(channel="cli", chat_id="d", role="user", content="hi")
        assert entry.entry_type == "message"

    def test_injection_entries_persist_in_history(self, tmp_path: Path):
        """Injection entries (summaries, subagent results) are kept as role:user."""
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="do something")
        log.append(channel="cli", chat_id="d", role="assistant", content="Done!")
        log.append(
            channel="cli",
            chat_id="d",
            role="user",
            content="[System Summary]\nModified 3 files.",
            entry_type="injection",
        )

        history = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history) == 3
        assert history[2]["role"] == "user"
        assert "[System Summary]" in history[2]["content"]
        assert "Modified 3 files." in history[2]["content"]

    def test_injection_not_filtered_by_include_tools_false(self, tmp_path: Path):
        """Injection entries survive include_tools=False filtering."""
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="hi")
        log.append(channel="cli", chat_id="d", role="assistant", content="response")
        log.append(
            channel="cli",
            chat_id="d",
            role="user",
            content="[Subagent Result: research]\nFindings here.",
            entry_type="injection",
        )

        history = log.get_recent_conversation(channel="cli", chat_id="d", include_tools=False)
        assert len(history) == 3
        assert history[2]["role"] == "user"
        assert "[Subagent Result: research]" in history[2]["content"]

    def test_subagent_result_injection_ordering(self, tmp_path: Path):
        """Injection entries appear in correct chronological order."""
        log = DailyLog(tmp_path / "logs")
        log.append(channel="cli", chat_id="d", role="user", content="research X")
        log.append(channel="cli", chat_id="d", role="assistant", content="On it.")
        log.append(
            channel="cli",
            chat_id="d",
            role="user",
            content="[Subagent Result: X]\nResult of X.",
            entry_type="injection",
        )
        log.append(
            channel="cli",
            chat_id="d",
            role="user",
            content="[System Summary]\nResearched X.",
            entry_type="injection",
        )
        log.append(channel="cli", chat_id="d", role="user", content="what next?")

        history = log.get_recent_conversation(channel="cli", chat_id="d")
        assert len(history) == 5
        assert history[0]["content"] == "research X"
        assert "[Subagent Result: X]" in history[2]["content"]
        assert "[System Summary]" in history[3]["content"]
        assert history[4]["content"] == "what next?"


class TestMemoryManagerEntryType:
    """Tests for entry_type passthrough in MemoryManager."""

    def test_record_conversation_with_entry_type(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        entry = mgr.record_conversation(
            channel="cli",
            chat_id="d",
            role="assistant",
            content="summary",
            entry_type="summary",
        )
        assert entry.entry_type == "summary"

    def test_record_conversation_default_entry_type(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        entry = mgr.record_conversation(
            channel="cli",
            chat_id="d",
            role="user",
            content="hello",
        )
        assert entry.entry_type == "message"


# ---------------------------------------------------------------------------
# Assistant message truncation (in-context learning mitigation)
# ---------------------------------------------------------------------------


class TestAssistantTruncation:
    """Tests for truncation of older assistant messages."""

    def test_truncate_assistant_short_message_unchanged(self):
        assert _truncate_assistant("short reply", 50) == "short reply"

    def test_truncate_assistant_long_message_truncated(self):
        long_msg = "A" * 300
        result = _truncate_assistant(long_msg, 50)
        assert len(result) < 300
        assert result.endswith("[...]")
        assert result.startswith("A" * 180)
        assert estimate_text_tokens(result) <= 50

    def test_truncate_assistant_collapses_newlines(self):
        msg = "line1\nline2\nline3\n" * 50
        result = _truncate_assistant(msg, 25)
        assert "\n" not in result
        assert "[...]" in result

    def test_recent_turns_kept_verbatim(self, tmp_path: Path):
        """Most recent N assistant messages should not be truncated."""
        log = DailyLog(tmp_path / "logs")
        long_content = "X" * 500

        for i in range(5):
            log.append(channel="cli", chat_id="d", role="user", content=f"q{i}")
            log.append(channel="cli", chat_id="d", role="assistant", content=long_content)

        history = log.get_recent_conversation(
            channel="cli", chat_id="d", recent_full_turns=2, assistant_truncate_tokens=25
        )

        assistant_msgs = [m for m in history if m["role"] == "assistant"]
        assert len(assistant_msgs) == 5

        # Last 2 should be verbatim (full 500 chars)
        assert len(assistant_msgs[-1]["content"]) == 500
        assert len(assistant_msgs[-2]["content"]) == 500

        # Older 3 should be truncated
        for msg in assistant_msgs[:3]:
            assert len(msg["content"]) < 200
            assert "[...]" in msg["content"]

    def test_all_recent_no_truncation(self, tmp_path: Path):
        """When all messages are within recent_full_turns, nothing is truncated."""
        log = DailyLog(tmp_path / "logs")
        long_content = "Y" * 500

        log.append(channel="cli", chat_id="d", role="user", content="q1")
        log.append(channel="cli", chat_id="d", role="assistant", content=long_content)

        history = log.get_recent_conversation(channel="cli", chat_id="d", recent_full_turns=3)

        assert len(history) == 2
        assert history[1]["content"] == long_content

    def test_user_messages_never_truncated(self, tmp_path: Path):
        """User messages are always kept in full regardless of position."""
        log = DailyLog(tmp_path / "logs")
        long_user = "U" * 500

        for i in range(5):
            log.append(channel="cli", chat_id="d", role="user", content=long_user)
            log.append(channel="cli", chat_id="d", role="assistant", content="short")

        history = log.get_recent_conversation(
            channel="cli", chat_id="d", recent_full_turns=1, assistant_truncate_tokens=12
        )

        user_msgs = [m for m in history if m["role"] == "user"]
        for msg in user_msgs:
            assert msg["content"] == long_user
