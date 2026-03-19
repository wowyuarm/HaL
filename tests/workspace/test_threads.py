from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hal.workspace.threads import (
    ThreadRepository,
    collect_thread_episode_paths,
    collect_thread_registry_entries,
    episode_path_for_thread,
    thread_metadata_path,
)
from hal.workspace.thread_state import build_episode_file_name


def test_collect_thread_registry_entries_reads_metadata(tmp_path: Path) -> None:
    thread_dir = tmp_path / "work" / "threads" / "github-actions"
    thread_dir.mkdir(parents=True)
    (thread_dir / "BRIEF.md").write_text(
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
    active_dir = tmp_path / "work" / "threads" / "active"
    active_dir.mkdir(parents=True)
    (active_dir / "BRIEF.md").write_text(
        "# Active\nStatus: active\n\n## Goal\nCurrent work.\n",
        encoding="utf-8",
    )

    old_inactive = tmp_path / "work" / "threads" / "old"
    old_inactive.mkdir(parents=True)
    (old_inactive / "BRIEF.md").write_text(
        "# Old\nStatus: inactive\n\n## Goal\nOlder work.\n",
        encoding="utf-8",
    )

    new_inactive = tmp_path / "work" / "threads" / "new"
    new_inactive.mkdir(parents=True)
    (new_inactive / "BRIEF.md").write_text(
        "# New\nStatus: inactive\n\n## Goal\nNewer work.\n",
        encoding="utf-8",
    )

    entries = collect_thread_registry_entries(tmp_path, max_entries=2)

    assert [entry.slug for entry in entries] == ["active", "new"]


def test_thread_yaml_overrides_machine_metadata(tmp_path: Path) -> None:
    thread_dir = tmp_path / "work" / "threads" / "hal-architecture"
    thread_dir.mkdir(parents=True)
    (thread_dir / "BRIEF.md").write_text(
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
    assert path == tmp_path / "work" / "threads" / "hal-architecture" / "episodes" / "episode.md"


def test_thread_metadata_path(tmp_path: Path) -> None:
    path = thread_metadata_path(tmp_path, "hal-architecture")
    assert path == tmp_path / "work" / "threads" / "hal-architecture" / "THREAD.yaml"


def test_thread_repository_reads_and_writes_state_and_episode(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)

    state_path = repo.write_state("hal-architecture", "# HaL Architecture\nStatus: active\n")
    episode_path = repo.write_episode("hal-architecture", "episode.md", "# Episode\n")

    assert state_path == tmp_path / "work" / "threads" / "hal-architecture" / "BRIEF.md"
    assert (
        episode_path
        == tmp_path / "work" / "threads" / "hal-architecture" / "episodes" / "episode.md"
    )
    assert repo.read_state("hal-architecture") == "# HaL Architecture\nStatus: active\n"


def test_thread_repository_records_episode_and_advances_state(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)
    repo.write_state(
        "github-actions",
        "# GitHub Actions\nStatus: active\n\n## Purpose\nShip automation workflow.\n",
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
    brief = (
        "# GitHub Actions\nStatus: active\n\n"
        "## Purpose\nShip automation workflow.\n\n"
        "## Key Decisions\n- Use label-based routing.\n"
    )

    result = repo.record_episode(
        thread_slug="github-actions",
        session_id="s_1",
        episode_markdown=episode,
        brief_markdown=brief,
        now=datetime(2026, 3, 6, 9, 0, 0),
    )
    assert result is not None
    assert result.episode_rel_path == "episodes/2026-03-06-github-actions-s_1.md"
    assert result.episode_title == "2026-03-06: Workflow update"
    assert result.episode_path == (
        tmp_path
        / "work"
        / "threads"
        / "github-actions"
        / "episodes"
        / "2026-03-06-github-actions-s_1.md"
    )
    assert "- Use label-based routing." in result.state_content
    assert "## Recent Episodes" in result.state_content
    assert "- Use label-based routing." in repo.read_state("github-actions")


def test_thread_repository_records_episode_updates_state_status(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)
    repo.write_state(
        "github-actions",
        "# GitHub Actions\nStatus: active\n\n## Purpose\nShip automation workflow.\n",
    )
    episode = (
        "# 2026-03-06: Workflow pause\n\n"
        "Threads: [github-actions]\n"
        "Primary: github-actions\n"
        "Session: s_2\n\n"
        "## What Happened\n"
        "- Work paused pending decision.\n\n"
        "## Decisions\n"
        "- Wait for architecture update.\n"
    )
    brief = "# GitHub Actions\nStatus: paused\n\n## Purpose\nShip automation workflow.\n"

    result = repo.record_episode(
        thread_slug="github-actions",
        session_id="s_2",
        episode_markdown=episode,
        brief_markdown=brief,
        now=datetime(2026, 3, 6, 9, 30, 0),
    )
    assert result is not None
    assert "Status: paused" in result.state_content
    assert result.state_content.count("Status:") == 1
    assert "Status: paused" in (repo.read_state("github-actions") or "")


def test_collect_thread_episode_paths_wrapper_uses_repository(tmp_path: Path) -> None:
    episode_dir = tmp_path / "work" / "threads" / "github-actions" / "episodes"
    episode_dir.mkdir(parents=True)
    (episode_dir / "2026-03-06-actions.md").write_text("# Episode\n", encoding="utf-8")

    assert collect_thread_episode_paths(tmp_path) == [episode_dir / "2026-03-06-actions.md"]


def test_thread_repository_collects_episode_refs_and_reads_documents(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)
    episode_dir = tmp_path / "work" / "threads" / "github-actions" / "episodes"
    episode_dir.mkdir(parents=True)
    episode_path = episode_dir / build_episode_file_name(
        now=datetime(2026, 3, 6, 9, 0, 0),
        session_id="s_20260306090000_deadbeef",
        thread_slug="github-actions",
    )
    episode_markdown = "# 2026-03-06: Workflow update\n\nBody.\n"
    episode_path.write_text(episode_markdown, encoding="utf-8")

    refs = repo.collect_episode_refs("github-actions")
    document = repo.read_episode("github-actions", f"episodes/{episode_path.name}")

    assert refs["s_20260306090000_deadbeef"].thread_slug == "github-actions"
    assert refs["s_20260306090000_deadbeef"].episode_rel_path == f"episodes/{episode_path.name}"
    assert refs["s_20260306090000_deadbeef"].episode_title == "2026-03-06: Workflow update"
    assert document is not None
    assert document.episode_rel_path == f"episodes/{episode_path.name}"
    assert document.episode_title == "2026-03-06: Workflow update"
    assert document.markdown == episode_markdown


def test_thread_repository_collects_session_episode_refs_across_threads(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)
    alpha_dir = tmp_path / "work" / "threads" / "alpha" / "episodes"
    beta_dir = tmp_path / "work" / "threads" / "beta" / "episodes"
    alpha_dir.mkdir(parents=True)
    beta_dir.mkdir(parents=True)
    session_id = "s_20260306090000_deadbeef"
    alpha_path = alpha_dir / build_episode_file_name(
        now=datetime(2026, 3, 6, 9, 0, 0),
        session_id=session_id,
        thread_slug="alpha",
    )
    beta_path = beta_dir / build_episode_file_name(
        now=datetime(2026, 3, 6, 9, 5, 0),
        session_id=session_id,
        thread_slug="beta",
    )
    alpha_path.write_text("# Alpha episode\n", encoding="utf-8")
    beta_path.write_text("# Beta episode\n", encoding="utf-8")

    refs = repo.collect_session_episode_refs({session_id})

    assert [ref.thread_slug for ref in refs[session_id]] == ["alpha", "beta"]
    assert refs[session_id][0].episode_rel_path == f"episodes/{alpha_path.name}"
    assert refs[session_id][1].episode_rel_path == f"episodes/{beta_path.name}"


def test_thread_repository_rejects_invalid_episode_paths(tmp_path: Path) -> None:
    repo = ThreadRepository(tmp_path)

    for episode_rel_path in ("../BRIEF.md", "episodes/../BRIEF.md", "BRIEF.md"):
        with pytest.raises(ValueError):
            repo.read_episode("github-actions", episode_rel_path)


# ---------------------------------------------------------------------------
# Auto-bootstrap: THREAD.yaml only → BRIEF.md generated
# ---------------------------------------------------------------------------


def test_thread_yaml_only_bootstraps_state_md(tmp_path: Path) -> None:
    """A directory with only THREAD.yaml should auto-generate BRIEF.md on discovery."""
    thread_dir = tmp_path / "work" / "threads" / "new-project"
    thread_dir.mkdir(parents=True)
    (thread_dir / "THREAD.yaml").write_text(
        "name: New Project\n"
        "status: active\n"
        "goal: Build the next big thing.\n"
        "related_threads:\n"
        "  - hal-architecture\n",
        encoding="utf-8",
    )

    entries = collect_thread_registry_entries(tmp_path, max_entries=20)

    assert len(entries) == 1
    assert entries[0].slug == "new-project"
    assert entries[0].name == "New Project"
    assert entries[0].status == "active"
    assert entries[0].description == "Build the next big thing."
    assert entries[0].related_threads == ("hal-architecture",)

    # BRIEF.md was auto-generated
    state = (thread_dir / "BRIEF.md").read_text(encoding="utf-8")
    assert "# New Project" in state
    assert "Status: active" in state
    assert "Build the next big thing." in state
    assert "## Purpose" in state


def test_thread_yaml_only_bootstrap_uses_slug_as_fallback_title(tmp_path: Path) -> None:
    """When THREAD.yaml has no name/title, slug is used."""
    thread_dir = tmp_path / "work" / "threads" / "quick-task"
    thread_dir.mkdir(parents=True)
    (thread_dir / "THREAD.yaml").write_text("status: active\n", encoding="utf-8")

    entries = collect_thread_registry_entries(tmp_path, max_entries=20)

    assert len(entries) == 1
    assert entries[0].slug == "quick-task"
    state = (thread_dir / "BRIEF.md").read_text(encoding="utf-8")
    assert "# quick-task" in state
    assert "Status: active" in state


def test_empty_dir_without_yaml_or_state_is_ignored(tmp_path: Path) -> None:
    """Directories with neither BRIEF.md nor THREAD.yaml are skipped."""
    thread_dir = tmp_path / "work" / "threads" / "empty-dir"
    thread_dir.mkdir(parents=True)

    entries = collect_thread_registry_entries(tmp_path, max_entries=20)
    assert len(entries) == 0


def test_bootstrapped_thread_can_receive_episode(tmp_path: Path) -> None:
    """After bootstrap, record_episode should be able to update the thread brief normally."""
    thread_dir = tmp_path / "work" / "threads" / "bootstrapped"
    thread_dir.mkdir(parents=True)
    (thread_dir / "THREAD.yaml").write_text(
        "name: Bootstrapped Thread\nstatus: active\ngoal: Test bootstrap.\n",
        encoding="utf-8",
    )

    # Trigger bootstrap
    repo = ThreadRepository(tmp_path)
    repo.collect_registry_entries(max_entries=20)

    # Now record an episode with a worker-generated brief
    episode = (
        "# 2026-03-07: First session\n\n"
        "## What Happened\n- Initial work done.\n\n"
        "## Decisions\n- Use bootstrap approach.\n"
    )
    brief = (
        "# Bootstrapped Thread\nStatus: active\n\n"
        "## Purpose\nTest bootstrap.\n\n"
        "## Key Decisions\n- Use bootstrap approach.\n"
    )
    result = repo.record_episode(
        thread_slug="bootstrapped",
        session_id="s_1",
        episode_markdown=episode,
        brief_markdown=brief,
        now=datetime(2026, 3, 7, 10, 0, 0),
    )

    assert result is not None
    assert "- Use bootstrap approach." in result.state_content
    assert "## Recent Episodes" in result.state_content
