from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hal.workspace.threads import (
    ThreadRepository,
    collect_thread_episode_paths,
    collect_thread_registry_entries,
    episode_path_for_thread,
    thread_metadata_path,
)


def test_collect_thread_registry_entries_reads_metadata(tmp_path: Path) -> None:
    thread_dir = tmp_path / "threads" / "github-actions"
    thread_dir.mkdir(parents=True)
    (thread_dir / "STATE.md").write_text(
        "# GitHub Actions\n"
        "Status: active\n"
        "Pinned: true\n\n"
        "## Goal\n"
        "Ship the automation workflow.\n",
        encoding="utf-8",
    )

    entries = collect_thread_registry_entries(tmp_path, max_entries=20)

    assert len(entries) == 1
    assert entries[0].slug == "github-actions"
    assert entries[0].name == "GitHub Actions"
    assert entries[0].status == "active"
    assert entries[0].description == "Ship the automation workflow."
    assert entries[0].pinned is True


def test_collect_thread_registry_entries_prioritizes_active_then_recent(tmp_path: Path) -> None:
    active_dir = tmp_path / "threads" / "active"
    active_dir.mkdir(parents=True)
    (active_dir / "STATE.md").write_text(
        "# Active\nStatus: active\n\n## Goal\nCurrent work.\n",
        encoding="utf-8",
    )

    old_inactive = tmp_path / "threads" / "old"
    old_inactive.mkdir(parents=True)
    (old_inactive / "STATE.md").write_text(
        "# Old\nStatus: inactive\n\n## Goal\nOlder work.\n",
        encoding="utf-8",
    )

    new_inactive = tmp_path / "threads" / "new"
    new_inactive.mkdir(parents=True)
    (new_inactive / "STATE.md").write_text(
        "# New\nStatus: inactive\n\n## Goal\nNewer work.\n",
        encoding="utf-8",
    )

    entries = collect_thread_registry_entries(tmp_path, max_entries=2)

    assert [entry.slug for entry in entries] == ["active", "new"]


def test_thread_yaml_overrides_machine_metadata(tmp_path: Path) -> None:
    thread_dir = tmp_path / "threads" / "hal-architecture"
    thread_dir.mkdir(parents=True)
    (thread_dir / "STATE.md").write_text(
        "# HaL Architecture\nStatus: inactive\nPinned: false\n\n## Goal\nLegacy goal.\n",
        encoding="utf-8",
    )
    (thread_dir / "THREAD.yaml").write_text(
        "name: HaL Context System\n"
        "status: active\n"
        "pinned: true\n"
        "description: Machine-readable thread metadata.\n"
        "related_threads:\n"
        "  - github-actions\n"
        "updated_at: 2026-03-06T16:00:00+08:00\n",
        encoding="utf-8",
    )

    entries = collect_thread_registry_entries(tmp_path, max_entries=20)

    assert len(entries) == 1
    assert entries[0].name == "HaL Context System"
    assert entries[0].status == "active"
    assert entries[0].pinned is True
    assert entries[0].description == "Machine-readable thread metadata."
    assert entries[0].related_threads == ("github-actions",)
    assert entries[0].updated_at == "2026-03-06T16:00:00+08:00"
    assert entries[0].metadata_path == "threads/hal-architecture/THREAD.yaml"


def test_episode_path_for_thread(tmp_path: Path) -> None:
    path = episode_path_for_thread(tmp_path, "hal-architecture", "episode.md")
    assert path == tmp_path / "threads" / "hal-architecture" / "episodes" / "episode.md"


def test_thread_metadata_path(tmp_path: Path) -> None:
    path = thread_metadata_path(tmp_path, "hal-architecture")
    assert path == tmp_path / "threads" / "hal-architecture" / "THREAD.yaml"


def test_thread_repository_reads_and_writes_state_and_episode(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)

    state_path = repo.write_state("hal-architecture", "# HaL Architecture\nStatus: active\n")
    episode_path = repo.write_episode("hal-architecture", "episode.md", "# Episode\n")

    assert state_path == tmp_path / "threads" / "hal-architecture" / "STATE.md"
    assert episode_path == tmp_path / "threads" / "hal-architecture" / "episodes" / "episode.md"
    assert repo.read_state("hal-architecture") == "# HaL Architecture\nStatus: active\n"


def test_thread_repository_records_debrief_episode_and_advances_state(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)
    repo.write_state(
        "github-actions",
        "# GitHub Actions\nStatus: active\n\n## Current State\n- Existing status\n",
    )
    episode = (
        "# 2026-03-06: Workflow update\n\n"
        "Threads: [github-actions]\n"
        "Primary: github-actions\n"
        "Session: s_1\n\n"
        "## What Happened\n"
        "- Updated workflow draft.\n"
        "- Added review step.\n\n"
        "## Decisions\n"
        "- Use label-based routing.\n\n"
        "## Open\n"
        "- [ ] Verify in CI.\n"
    )

    result = repo.record_debrief_episode(
        thread_slug="github-actions",
        session_id="s_1",
        episode_markdown=episode,
        now=datetime(2026, 3, 6, 9, 0, 0),
    )
    assert result is not None
    assert result.episode_rel_path == "episodes/2026-03-06-github-actions-s_1.md"
    assert result.episode_title == "2026-03-06: Workflow update"
    assert result.episode_path == (
        tmp_path / "threads" / "github-actions" / "episodes" / "2026-03-06-github-actions-s_1.md"
    )
    assert "### 2026-03-06: Workflow update" in result.state_content
    assert "- Use label-based routing." in result.state_content
    assert "- [ ] Verify in CI." in result.state_content
    assert "## Recent Episodes" in result.state_content
    assert "### 2026-03-06: Workflow update" in repo.read_state("github-actions")


def test_thread_repository_records_debrief_episode_updates_state_status(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)
    repo.write_state(
        "github-actions",
        "# GitHub Actions\nStatus: active\n\n## Current State\n- Existing status\n",
    )
    episode = (
        "# 2026-03-06: Workflow pause\n\n"
        "Threads: [github-actions]\n"
        "Primary: github-actions\n"
        "Session: s_2\n\n"
        "## What Happened\n"
        "- Work paused pending decision.\n\n"
        "## Decisions\n"
        "- Wait for architecture update.\n\n"
        "## Status\n"
        "- paused\n\n"
        "## Open\n"
        "- [ ] Resume after architecture decision.\n"
    )

    result = repo.record_debrief_episode(
        thread_slug="github-actions",
        session_id="s_2",
        episode_markdown=episode,
        now=datetime(2026, 3, 6, 9, 30, 0),
    )
    assert result is not None
    assert "Status: paused" in result.state_content
    assert result.state_content.count("Status:") == 1
    assert "Status: paused" in (repo.read_state("github-actions") or "")


def test_collect_thread_episode_paths_wrapper_uses_repository(tmp_path: Path) -> None:
    episode_dir = tmp_path / "threads" / "github-actions" / "episodes"
    episode_dir.mkdir(parents=True)
    (episode_dir / "2026-03-06-actions.md").write_text("# Episode\n", encoding="utf-8")

    assert collect_thread_episode_paths(tmp_path) == [episode_dir / "2026-03-06-actions.md"]
