from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from hal.runtime.debrief import (
    DebriefOutput,
    _cap_text,
    _parse_debrief_response,
    build_debrief_confirmation_message,
    extract_touched_threads,
    format_session_events_for_prompt,
    is_debrief_action_message,
    is_debrief_confirm_message,
    resolve_debrief_thread_order,
)
from hal.workspace import (
    build_episode_file_name,
    ensure_recent_episodes_section,
)


def test_extract_touched_threads_from_nested_fs_args() -> None:
    args = {
        "action": "read",
        "path": "/tmp/workspace/threads/github-actions/BRIEF.md",
        "extra": [
            {"candidate": "threads/hal-architecture/BRIEF.md"},
            "ignore/me",
        ],
    }
    touched = extract_touched_threads(args)
    assert touched == {"github-actions", "hal-architecture"}


def test_is_debrief_confirm_message() -> None:
    assert is_debrief_confirm_message("confirm")
    assert is_debrief_confirm_message("/debrief now")
    assert not is_debrief_confirm_message("let us continue")


def test_is_debrief_action_message_confirm() -> None:
    assert is_debrief_action_message({"debrief_action": "confirm"}) == "confirm"


def test_is_debrief_action_message_cancel() -> None:
    assert is_debrief_action_message({"debrief_action": "cancel"}) == "cancel"


def test_is_debrief_action_message_missing_key() -> None:
    assert is_debrief_action_message({}) is None


def test_is_debrief_action_message_invalid_value() -> None:
    assert is_debrief_action_message({"debrief_action": "bogus"}) is None


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


def test_cap_text_passes_short_text_through() -> None:
    short = "hello world"
    assert _cap_text(short) == short


def test_cap_text_truncates_large_text() -> None:
    # ~1500 tokens ≈ ~6000 chars; create something well over that
    large = "word " * 3000  # ~15000 chars ≈ ~3750 tokens
    result = _cap_text(large)
    assert len(result) < len(large)
    assert result.endswith("...[truncated]")


def test_format_session_events_respects_per_event_cap() -> None:
    from hal.workspace.events import EventEntry

    huge_content = "x" * 20000  # ~5000 tokens, well over default max_event_tokens (1500)
    events = [
        EventEntry(session="s1", type="user_message", payload={"content": huge_content}),
        EventEntry(session="s1", type="assistant", payload={"content": "short reply"}),
    ]
    rendered = format_session_events_for_prompt(events)
    # The huge event should be truncated, but the short one preserved
    assert "short reply" in rendered
    assert "...[truncated]" in rendered
    # Overall output should be much smaller than the raw input
    assert len(rendered) < len(huge_content)


def test_format_session_events_overall_budget() -> None:
    from hal.workspace.events import EventEntry

    # Create many events that individually fit but collectively exceed a small budget
    events = [
        EventEntry(session="s1", type="msg", payload={"content": f"event number {i}"})
        for i in range(500)
    ]
    rendered = format_session_events_for_prompt(events, max_tokens=200)
    # Should be trimmed to roughly 200 tokens (~800 chars)
    assert rendered.endswith("...[truncated]")
    assert len(rendered) < 2000


def test_parse_debrief_response_splits_episode_and_brief() -> None:
    raw = (
        "---EPISODE---\n"
        "# 2026-03-06: Update\n\n"
        "## What Happened\n- Did work.\n"
        "---BRIEF---\n"
        "# Thread\nStatus: active\n\n## Purpose\nNew brief content.\n"
    )
    result = _parse_debrief_response(raw)
    assert isinstance(result, DebriefOutput)
    assert "# 2026-03-06: Update" in result.episode_markdown
    assert "## What Happened" in result.episode_markdown
    assert result.brief_markdown is not None
    assert "New brief content." in result.brief_markdown


def test_parse_debrief_response_fallback_without_markers() -> None:
    raw = "# 2026-03-06: Update\n\n## What Happened\n- Did work.\n"
    result = _parse_debrief_response(raw)
    assert isinstance(result, DebriefOutput)
    assert result.episode_markdown == raw.strip()
    assert result.brief_markdown is None


def test_parse_debrief_response_empty_brief_returns_none() -> None:
    raw = "---EPISODE---\n# Episode\n---BRIEF---\n"
    result = _parse_debrief_response(raw)
    assert isinstance(result, DebriefOutput)
    assert result.episode_markdown == "# Episode"
    assert result.brief_markdown is None
