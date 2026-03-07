from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from hal.runtime.debrief import resolve_debrief_thread_order
from hal.runtime.engine.debrief import (
    build_debrief_confirmation_message,
    extract_touched_threads,
    is_debrief_confirm_message,
)
from hal.workspace import (
    apply_episode_state_patch,
    build_episode_file_name,
    ensure_current_state_note,
    ensure_recent_episodes_section,
)


def test_extract_touched_threads_from_nested_fs_args() -> None:
    args = {
        "action": "read",
        "path": "/tmp/workspace/threads/github-actions/STATE.md",
        "extra": [
            {"candidate": "threads/hal-architecture/STATE.md"},
            "ignore/me",
        ],
    }
    touched = extract_touched_threads(args)
    assert touched == {"github-actions", "hal-architecture"}


def test_is_debrief_confirm_message() -> None:
    assert is_debrief_confirm_message("confirm")
    assert is_debrief_confirm_message("/debrief now")
    assert not is_debrief_confirm_message("let us continue")


def test_build_debrief_confirmation_message_contains_threads() -> None:
    msg = build_debrief_confirmation_message(threads=["a", "b"], confirm_timeout_s=120)
    assert "a, b" in msg
    assert "2 minute(s)" in msg


def test_build_episode_file_name() -> None:
    name = build_episode_file_name(
        now=datetime(2026, 3, 6, 9, 0, 0),
        session_id="s_1",
        thread_slug="github-actions",
    )
    assert name == "2026-03-06-github-actions-s_1.md"


def test_ensure_recent_episodes_section_appends_once() -> None:
    base = "# Thread\nStatus: active\n"
    updated = ensure_recent_episodes_section(base, "episodes/x.md", "Title")
    assert "## Recent Episodes" in updated
    assert "- [Title](episodes/x.md)" in updated
    updated_again = ensure_recent_episodes_section(updated, "episodes/x.md", "Title")
    assert updated_again.count("- [Title](episodes/x.md)") == 1


def test_ensure_current_state_note_appends_once() -> None:
    base = "# Thread\nStatus: active\n"
    updated = ensure_current_state_note(base, "note-1")
    assert "## Current State" in updated
    assert "- note-1" in updated
    updated_again = ensure_current_state_note(updated, "note-1")
    assert updated_again.count("- note-1") == 1


def test_apply_episode_state_patch_merges_hot_sections() -> None:
    state = "# Thread\nStatus: active\n\n## Current State\n- old status\n"
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

    updated = apply_episode_state_patch(
        state,
        episode_markdown=episode,
        episode_rel_path="episodes/2026-03-06-github-actions-s_1.md",
    )

    assert "### 2026-03-06: Workflow update" in updated
    assert "- Updated workflow draft." in updated
    assert "## Key Decisions" in updated
    assert "- Use label-based routing." in updated
    assert "## Open Items" in updated
    assert "- [ ] Verify in CI." in updated
    assert "## Recent Episodes" in updated


def test_resolve_debrief_thread_order_expands_related_and_prefers_priority() -> None:
    registry = SimpleNamespace(
        expand_related_thread_slugs=lambda slugs: set(slugs) | {"hal-architecture"},
        thread_snapshot=lambda: [
            {"slug": "github-actions", "priority": 200},
            {"slug": "hal-architecture", "priority": 320},
            {"slug": "blog", "priority": 100},
        ],
    )

    ordered = resolve_debrief_thread_order(
        context_registry=registry,
        touched_threads={"github-actions"},
    )

    assert ordered == ["hal-architecture", "github-actions"]
