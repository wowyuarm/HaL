"""Tests for the HaL memory system (episodic, long-term, manager)."""

from __future__ import annotations

import re
from pathlib import Path

from hal.core.memory.episodic import Episode, EpisodicMemory, InteractionTurn, MemoryTrace
from hal.core.memory.long_term import LongTermMemory
from hal.core.memory.manager import MemoryManager

# ---------------------------------------------------------------------------
# EpisodicMemory
# ---------------------------------------------------------------------------


class TestEpisodicMemory:
    """Tests for EpisodicMemory — JSONL-backed interaction records."""

    def test_record_creates_episode_with_correct_id_format(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        ep = mem.record(channel="cli", headline="hello world")

        # ID must match EP-YYYYMMDD-NNNN
        assert re.fullmatch(r"EP-\d{8}-\d{4}", ep.id)
        # First episode: counter = 1
        assert ep.id.endswith("-0001")

    def test_record_populates_all_fields(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        turns = [InteractionTurn(role="user", content="hi")]
        ep = mem.record(
            channel="telegram",
            headline="greeting",
            user_request="hi",
            agent_response="hello",
            tools_used=["web_search"],
            tags=["test"],
            turns=turns,
            duration_seconds=1.5,
            summary="user said hi",
        )

        assert ep.channel == "telegram"
        assert ep.headline == "greeting"
        assert ep.user_request == "hi"
        assert ep.agent_response == "hello"
        assert ep.tools_used == ["web_search"]
        assert ep.tags == ["test"]
        assert ep.turns == turns
        assert ep.duration_seconds == 1.5
        assert ep.summary == "user said hi"
        assert ep.timestamp > 0

    def test_record_defaults_summary_to_headline(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        ep = mem.record(channel="cli", headline="testing defaults")
        assert ep.summary == "testing defaults"

    def test_get_recent_returns_correct_number(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        for i in range(10):
            mem.record(channel="cli", headline=f"ep-{i}")

        recent = mem.get_recent(limit=3)
        assert len(recent) == 3
        # Should be the last 3 episodes
        assert recent[0].headline == "ep-7"
        assert recent[2].headline == "ep-9"

    def test_get_recent_returns_all_when_fewer_than_limit(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        mem.record(channel="cli", headline="only one")

        recent = mem.get_recent(limit=10)
        assert len(recent) == 1

    def test_get_recent_empty(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        assert mem.get_recent() == []

    def test_to_trace_creates_memory_trace(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        ep = mem.record(
            channel="cli",
            headline="trace test",
            summary="detailed summary",
            tools_used=["shell"],
            tags=["tag1"],
        )
        trace = mem.to_trace(ep)

        assert isinstance(trace, MemoryTrace)
        assert trace.episode_id == ep.id
        assert trace.timestamp == ep.timestamp
        assert trace.headline == "trace test"
        assert trace.summary == "detailed summary"
        assert trace.tools_used == ["shell"]
        assert trace.tags == ["tag1"]

    def test_persistence_across_object_recreation(self, tmp_path: Path):
        data_dir = tmp_path / "ep"

        # Record with first instance
        mem1 = EpisodicMemory(data_dir)
        mem1.record(channel="cli", headline="first")
        mem1.record(channel="cli", headline="second")

        # Recreate — data should survive
        mem2 = EpisodicMemory(data_dir)
        recent = mem2.get_recent()
        assert len(recent) == 2
        assert recent[0].headline == "first"
        assert recent[1].headline == "second"

    def test_counter_increments_across_recordings(self, tmp_path: Path):
        mem = EpisodicMemory(tmp_path / "ep")
        ep1 = mem.record(channel="cli", headline="a")
        ep2 = mem.record(channel="cli", headline="b")
        ep3 = mem.record(channel="cli", headline="c")

        assert ep1.id.endswith("-0001")
        assert ep2.id.endswith("-0002")
        assert ep3.id.endswith("-0003")

    def test_counter_resumes_after_recreation(self, tmp_path: Path):
        data_dir = tmp_path / "ep"

        mem1 = EpisodicMemory(data_dir)
        mem1.record(channel="cli", headline="a")
        mem1.record(channel="cli", headline="b")

        mem2 = EpisodicMemory(data_dir)
        ep3 = mem2.record(channel="cli", headline="c")
        # Counter should resume from 2 existing episodes, next is 3
        assert ep3.id.endswith("-0003")


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
        # Beta section should be preserved
        assert "Old beta content." in result

    def test_update_section_appends_when_not_found(self, tmp_path: Path):
        content = "## Existing\nSome content.\n"
        mem = LongTermMemory(tmp_path / "MEMORY.md")
        mem.update(content)

        mem.update_section("NewSection", "Brand new content.")
        result = mem.read()

        assert "## NewSection" in result
        assert "Brand new content." in result
        # Original content preserved
        assert "## Existing" in result
        assert "Some content." in result


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------


class TestMemoryManager:
    """Tests for MemoryManager — coordinator of all memory subsystems."""

    def test_record_interaction_creates_episode(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        ep = mgr.record_interaction(
            channel="cli",
            user_request="What is 2+2?",
            agent_response="4",
            tools_used=["calculator"],
        )

        assert isinstance(ep, Episode)
        assert ep.channel == "cli"
        assert ep.user_request == "What is 2+2?"
        assert ep.agent_response == "4"
        assert ep.tools_used == ["calculator"]

    def test_record_interaction_auto_headline_from_request(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        ep = mgr.record_interaction(channel="cli", user_request="Short request")
        assert ep.headline == "Short request"

    def test_record_interaction_truncates_long_headline(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        long_request = "x" * 100
        ep = mgr.record_interaction(channel="cli", user_request=long_request)
        assert ep.headline == "x" * 80 + "..."

    def test_record_interaction_default_headline(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        ep = mgr.record_interaction(channel="cron")
        assert ep.headline == "Background task"

    def test_get_context_includes_long_term_memory(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.long_term.update("## Knowledge\nImportant fact.\n")

        ctx = mgr.get_context()
        assert "Long-term Memory" in ctx
        assert "Important fact." in ctx

    def test_get_context_includes_recent_episodes(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        mgr.record_interaction(channel="cli", user_request="test query")

        ctx = mgr.get_context()
        assert "Recent Interactions" in ctx
        assert "test query" in ctx

    def test_get_context_empty_when_no_data(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        ctx = mgr.get_context()
        assert ctx == ""

    def test_format_episodes_all_detailed_when_5_or_fewer(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        episodes = []
        for i in range(4):
            ep = mgr.record_interaction(channel="cli", user_request=f"req-{i}")
            episodes.append(ep)

        formatted = mgr._format_episodes(episodes)

        # Should have "### Recent" but NOT "### Earlier"
        assert "### Recent" in formatted
        assert "### Earlier" not in formatted
        # All episodes present as detailed (bold timestamp format)
        for i in range(4):
            assert f"req-{i}" in formatted

    def test_format_episodes_split_when_more_than_5(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        episodes = []
        for i in range(8):
            ep = mgr.record_interaction(
                channel="cli",
                user_request=f"req-{i}",
            )
            episodes.append(ep)

        formatted = mgr._format_episodes(episodes)

        # Should have both sections
        assert "### Earlier" in formatted
        assert "### Recent" in formatted
        # Last 5 are detailed (bold), older 3 are traces (dash-prefixed)
        for i in range(3):
            assert f"req-{i}" in formatted
        for i in range(3, 8):
            assert f"req-{i}" in formatted

    def test_format_episodes_traces_use_dash_prefix(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        episodes = []
        for i in range(7):
            ep = mgr.record_interaction(channel="cli", user_request=f"item-{i}")
            episodes.append(ep)

        formatted = mgr._format_episodes(episodes)

        # Older episodes (indices 0, 1) should be trace lines starting with "- `"
        lines = formatted.split("\n")
        trace_lines = [ln for ln in lines if ln.startswith("- `")]
        assert len(trace_lines) == 2  # 7 - 5 = 2 older episodes

    def test_format_episodes_detailed_show_summary(self, tmp_path: Path):
        mgr = MemoryManager(workspace=tmp_path)
        ep = mgr.episodic.record(
            channel="cli",
            headline="short headline",
            summary="a longer summary that differs from headline",
        )

        formatted = mgr._format_episodes([ep])
        assert "a longer summary that differs from headline" in formatted

    def test_manager_uses_data_dir_for_episodes(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        data_dir = tmp_path / "data"
        mgr = MemoryManager(workspace=workspace, data_dir=data_dir)

        mgr.record_interaction(channel="cli", user_request="stored elsewhere")

        # Episodes file should be in data_dir, not workspace
        ep_file = data_dir / "episodes" / "episodes.jsonl"
        assert ep_file.exists()
        assert "stored elsewhere" in ep_file.read_text(encoding="utf-8")
