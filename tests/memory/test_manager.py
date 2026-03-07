"""Tests for the HaL memory system (long-term memory, manager)."""

from __future__ import annotations

from pathlib import Path

from hal.context.token_budget import estimate_text_tokens
from hal.memory.manager import MemoryManager
from hal.workspace.memory import MemoryRepository

# ---------------------------------------------------------------------------
# MemoryRepository (long-term knowledge)
# ---------------------------------------------------------------------------


class TestMemoryRepository:
    """Tests for MemoryRepository — MEMORY.md backed persistent knowledge."""

    def test_read_returns_empty_for_nonexistent_file(self, tmp_path: Path):
        mem = MemoryRepository(tmp_path / "does_not_exist.md")
        assert mem.read() == ""

    def test_update_creates_and_writes_file(self, tmp_path: Path):
        mem_file = tmp_path / "subdir" / "MEMORY.md"
        mem = MemoryRepository(mem_file)
        mem.update("# My Memory\nSome facts.")

        assert mem_file.exists()
        assert mem_file.read_text(encoding="utf-8") == "# My Memory\nSome facts."

    def test_read_returns_content_after_write(self, tmp_path: Path):
        mem = MemoryRepository(tmp_path / "MEMORY.md")
        mem.update("hello world")
        assert mem.read() == "hello world"

    def test_get_section_extracts_markdown_section(self, tmp_path: Path):
        content = (
            "# Title\n\n## Preferences\nI like concise answers.\n\n## Facts\nThe sky is blue.\n"
        )
        mem = MemoryRepository(tmp_path / "MEMORY.md")
        mem.update(content)

        section = mem.get_section("Preferences")
        assert section == "I like concise answers."

        section2 = mem.get_section("Facts")
        assert section2 == "The sky is blue."

    def test_get_section_returns_none_for_missing_section(self, tmp_path: Path):
        mem = MemoryRepository(tmp_path / "MEMORY.md")
        mem.update("## Existing\nSome content.\n")

        assert mem.get_section("Nonexistent") is None

    def test_get_section_returns_none_for_empty_file(self, tmp_path: Path):
        mem = MemoryRepository(tmp_path / "MEMORY.md")
        assert mem.get_section("Anything") is None

    def test_update_section_updates_specific_section(self, tmp_path: Path):
        content = "## Alpha\nOld alpha content.\n\n## Beta\nOld beta content.\n"
        mem = MemoryRepository(tmp_path / "MEMORY.md")
        mem.update(content)

        mem.update_section("Alpha", "New alpha content.")
        result = mem.read()

        assert "New alpha content." in result
        assert "Old alpha content." not in result
        assert "Old beta content." in result

    def test_update_section_appends_when_not_found(self, tmp_path: Path):
        content = "## Existing\nSome content.\n"
        mem = MemoryRepository(tmp_path / "MEMORY.md")
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
