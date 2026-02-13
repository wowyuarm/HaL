"""Tests for the HaL memory system (daily log, long-term, manager)."""

from __future__ import annotations

from pathlib import Path

from hal.core.memory.daily_log import DailyLog
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
        log_files = list((data_dir / "logs").glob("*.jsonl"))
        assert len(log_files) == 1

    def test_get_conversation_stats(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.record_conversation(channel="cli", chat_id="d", role="user", content="hi")

        stats = mgr.get_conversation_stats()
        assert stats["total_entries"] == 1


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
