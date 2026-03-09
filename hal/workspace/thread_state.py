"""Workspace helpers for thread episode filenames and BRIEF.md maintenance."""

from __future__ import annotations

from datetime import datetime

_STATE_RECENT_EPISODES_SECTION = "## Recent Episodes"


def build_episode_file_name(*, now: datetime, session_id: str, thread_slug: str) -> str:
    """Build deterministic episode file name."""
    return f"{now.strftime('%Y-%m-%d')}-{thread_slug}-{session_id}.md"


def extract_episode_title(episode_markdown: str) -> str:
    """Extract the episode title from the first markdown heading."""
    for line in episode_markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.lstrip("#").strip()
    return "Session update"


def ensure_recent_episodes_section(state_content: str, episode_rel_path: str, title: str) -> str:
    """Append episode link under Recent Episodes (create section if missing)."""
    line = f"- [{title}]({episode_rel_path})"
    if _STATE_RECENT_EPISODES_SECTION not in state_content:
        base = state_content.rstrip()
        return f"{base}\n\n{_STATE_RECENT_EPISODES_SECTION}\n{line}\n"

    parts = state_content.split(_STATE_RECENT_EPISODES_SECTION, maxsplit=1)
    prefix, suffix = parts[0], parts[1]
    if line in suffix:
        return state_content
    suffix = suffix.rstrip() + f"\n{line}\n"
    return f"{prefix}{_STATE_RECENT_EPISODES_SECTION}{suffix}"
