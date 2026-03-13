from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from hal.runtime.brief import (
    _build_brief_system_prompt,
    _build_brief_tools,
    _build_brief_user_prompt,
    _cap_text,
    _event_preview,
    extract_touched_threads,
    format_session_events_for_prompt,
    resolve_brief_thread_order,
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


def test_extract_touched_threads_from_non_brief_paths() -> None:
    """Thread touch detection matches any file under threads/<slug>/."""
    assert extract_touched_threads({"path": "/home/user/.hal/work/threads/hal-arch/STATE.md"}) == {
        "hal-arch"
    }
    assert extract_touched_threads({"path": "threads/daily-ops/THREAD.yaml"}) == {"daily-ops"}
    assert extract_touched_threads({"path": "threads/blog/episodes/2026-03-06-blog-s1.md"}) == {
        "blog"
    }


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


def test_resolve_brief_thread_order_expands_related_and_prefers_priority() -> None:
    registry = SimpleNamespace(
        expand_related_thread_slugs=lambda slugs: set(slugs) | {"hal-architecture"},
        thread_snapshot=lambda: [
            {"slug": "github-actions", "priority": 200},
            {"slug": "hal-architecture", "priority": 320},
            {"slug": "blog", "priority": 100},
        ],
    )

    ordered = resolve_brief_thread_order(
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
    from hal.domain.events import SessionEvent

    huge_content = "x" * 20000  # ~5000 tokens, well over default max_event_tokens (1500)
    events = [
        SessionEvent(
            seq=1,
            session_id="s1",
            type="user_message",
            actor="user",
            payload={"content": huge_content},
        ),
        SessionEvent(
            seq=2,
            session_id="s1",
            type="assistant",
            actor="engine",
            payload={"content": "short reply"},
        ),
    ]
    rendered = format_session_events_for_prompt(events)
    # The huge event should be truncated, but the short one preserved
    assert "short reply" in rendered
    assert "...[truncated]" in rendered
    # Overall output should be much smaller than the raw input
    assert len(rendered) < len(huge_content)


def test_format_session_events_overall_budget() -> None:
    from hal.domain.events import SessionEvent

    # Create many events that individually fit but collectively exceed a small budget
    events = [
        SessionEvent(
            seq=i,
            session_id="s1",
            type="msg",
            actor="user",
            payload={"content": f"event number {i}"},
        )
        for i in range(500)
    ]
    rendered = format_session_events_for_prompt(events, max_tokens=200)
    # Should be trimmed to roughly 200 tokens (~800 chars)
    assert rendered.endswith("...[truncated]")
    assert len(rendered) < 2000


def test_event_preview_tool_call_with_result_preview() -> None:
    """tool_call events with result_preview render as 'tool -> preview'."""
    payload = {
        "tool": "fs",
        "args": {"action": "read", "path": "/some/file"},
        "result_size": 500,
        "result_preview": "file contents here",
    }
    preview = _event_preview(payload)
    assert "fs" in preview
    assert "\u2192" in preview
    assert "file contents here" in preview


def test_event_preview_tool_call_without_result_preview() -> None:
    """tool_call events without result_preview fall back to tool name only."""
    payload = {
        "tool": "exec",
        "args": {"command": "ls"},
        "result_size": 100,
    }
    assert _event_preview(payload) == "exec"


# ---------------------------------------------------------------------------
# Brief worker unit tests
# ---------------------------------------------------------------------------


def test_parse_brief_command() -> None:
    from hal.runtime.engine.processing import _parse_brief_command

    assert _parse_brief_command("/brief") == (True, "")
    assert _parse_brief_command("/brief focus on arch") == (True, "focus on arch")
    assert _parse_brief_command("/briefing") == (False, "")
    assert _parse_brief_command("hello /brief") == (False, "")
    assert _parse_brief_command("  /brief  ") == (True, "")
    assert _parse_brief_command("  /brief  some prompt  ") == (True, "some prompt")


def test_is_drop_command() -> None:
    from hal.runtime.engine.processing import _is_drop_command

    assert _is_drop_command("/drop") is True
    assert _is_drop_command("  /drop  ") is True
    assert _is_drop_command("/drop extra") is False
    assert _is_drop_command("/dropping") is False
    assert _is_drop_command("hello /drop") is False


def test_build_brief_tools_restricted(tmp_path: Path) -> None:
    tools = _build_brief_tools(tmp_path)
    assert tools.has("fs")
    assert not tools.has("exec")
    assert not tools.has("web_search")
    assert not tools.has("spawn")
    assert len(tools) == 1


def test_build_brief_system_prompt() -> None:
    prompt = _build_brief_system_prompt()
    assert "brief maintainer" in prompt.lower()
    assert "episodes" in prompt.lower()
    assert "BRIEF.md" in prompt
    assert "fs" in prompt


def test_build_brief_user_prompt() -> None:
    prompt = _build_brief_user_prompt(
        rendered_events="- [ts] user_message: hello",
        touched_threads={"github-actions"},
        thread_order=["github-actions", "hal-arch"],
        thread_meta={
            "github-actions": {"name": "GitHub Actions", "scope": "dev"},
            "hal-arch": {"name": "HaL Architecture", "scope": ""},
        },
        user_prompt="focus on CI",
        session_id="s_test",
    )
    assert '<session id="s_test">' in prompt
    assert "<events>" in prompt
    assert "hello" in prompt
    assert '<thread slug="github-actions"' in prompt
    assert 'touched="true"' in prompt
    assert '<thread slug="hal-arch"' in prompt
    assert 'touched="false"' in prompt
    assert "<guidance>focus on CI</guidance>" in prompt


def test_build_brief_user_prompt_no_guidance() -> None:
    prompt = _build_brief_user_prompt(
        rendered_events="- events",
        touched_threads=set(),
        thread_order=[],
        thread_meta={},
        user_prompt="",
        session_id="s_1",
    )
    assert "<guidance>" not in prompt
