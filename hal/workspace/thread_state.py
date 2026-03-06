"""Workspace helpers for thread episode filenames and STATE.md hot-layer patching."""

from __future__ import annotations

import re
from datetime import datetime

_EPISODE_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
_STATE_STATUS_LINE_RE = re.compile(r"^Status:\s*(.+)$", re.IGNORECASE)
_STATE_CURRENT_SECTION = "## Current State"
_STATE_DECISIONS_SECTION = "## Key Decisions"
_STATE_OPEN_ITEMS_SECTION = "## Open Items"
_STATE_RECENT_EPISODES_SECTION = "## Recent Episodes"
_PLACEHOLDER_ITEM_TEXTS = {"none", "n/a", "na", "no decisions", "no open items", "no updates"}
_NO_STATUS_CHANGE_VALUES = {"none", "n/a", "na", "no change", "unchanged", "keep", "current"}
_MAX_CURRENT_STATE_ITEMS = 4


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


def apply_episode_state_patch(
    state_content: str,
    *,
    episode_markdown: str,
    episode_rel_path: str,
    episode_title: str | None = None,
) -> str:
    """Merge episode decisions/open items/current-state summary into STATE.md."""
    title = episode_title or extract_episode_title(episode_markdown)
    sections = _parse_episode_sections(episode_markdown)
    status_value = _extract_episode_status(sections.get("Status", []))

    current_state_items = _extract_markdown_list_items(sections.get("What Happened", []))
    if not current_state_items:
        current_state_items = ["- Session debrief update recorded."]
    patched = state_content
    if status_value:
        patched = ensure_state_status_line(patched, status=status_value)
    patched = ensure_current_state_block(
        patched,
        title=title,
        items=current_state_items[:_MAX_CURRENT_STATE_ITEMS],
    )
    patched = ensure_list_section_items(
        patched,
        section_header=_STATE_DECISIONS_SECTION,
        items=_extract_markdown_list_items(sections.get("Decisions", [])),
    )
    patched = ensure_list_section_items(
        patched,
        section_header=_STATE_OPEN_ITEMS_SECTION,
        items=_extract_markdown_list_items(sections.get("Open", [])),
    )
    return ensure_recent_episodes_section(patched, episode_rel_path, title)


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


def ensure_current_state_note(state_content: str, note: str) -> str:
    """Append a note under Current State (create section when missing)."""
    if _STATE_CURRENT_SECTION not in state_content:
        base = state_content.rstrip()
        return f"{base}\n\n{_STATE_CURRENT_SECTION}\n- {note}\n"

    parts = state_content.split(_STATE_CURRENT_SECTION, maxsplit=1)
    prefix, suffix = parts[0], parts[1]
    entry = f"- {note}"
    if entry in suffix:
        return state_content
    suffix = suffix.rstrip() + f"\n{entry}\n"
    return f"{prefix}{_STATE_CURRENT_SECTION}{suffix}"


def ensure_state_status_line(state_content: str, *, status: str) -> str:
    """Ensure STATE.md contains one normalized Status metadata line."""
    normalized = " ".join(status.strip().lower().split())
    if not normalized:
        return state_content
    next_line = f"Status: {normalized}"
    lines = state_content.rstrip("\n").splitlines()
    for index, line in enumerate(lines):
        if not _STATE_STATUS_LINE_RE.match(line.strip()):
            continue
        if line.strip() == next_line:
            return state_content
        lines[index] = next_line
        return "\n".join(lines).rstrip() + "\n"

    if not lines:
        return f"{next_line}\n"

    if lines[0].startswith("# "):
        insertion_index = 1
        lines.insert(insertion_index, next_line)
        if len(lines) > insertion_index + 1 and lines[insertion_index + 1].strip():
            lines.insert(insertion_index + 1, "")
    else:
        lines.insert(0, next_line)
        if len(lines) > 1 and lines[1].strip():
            lines.insert(1, "")
    return "\n".join(lines).rstrip() + "\n"


def ensure_current_state_block(state_content: str, *, title: str, items: list[str]) -> str:
    """Append one episode-derived block under Current State once."""
    block_header = f"### {title}"
    found, body = _extract_section_body(state_content, _STATE_CURRENT_SECTION)
    if block_header in body:
        return state_content

    existing = body.strip()
    block_body = "\n".join([block_header, *items]).strip()
    new_body = block_body if not existing else f"{existing}\n\n{block_body}"
    if not found and not state_content.strip():
        return f"{_STATE_CURRENT_SECTION}\n\n{new_body}\n"
    return _replace_section_body(state_content, _STATE_CURRENT_SECTION, new_body)


def ensure_list_section_items(state_content: str, *, section_header: str, items: list[str]) -> str:
    """Append unique list items under a state section."""
    if not items:
        return state_content

    found, body = _extract_section_body(state_content, section_header)
    existing_lines, existing_keys = _collect_section_list_state(body)
    updated_lines = _append_unique_list_items(existing_lines, existing_keys, items)
    new_body = "\n".join(updated_lines).strip()
    if not found and not state_content.strip():
        return f"{section_header}\n{new_body}\n" if new_body else f"{section_header}\n"
    return _replace_section_body(state_content, section_header, new_body)


def _parse_episode_sections(episode_markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for line in episode_markdown.splitlines():
        match = _EPISODE_SECTION_RE.match(line.strip())
        if match:
            current_section = match.group(1)
            sections.setdefault(current_section, [])
            continue
        if current_section is not None:
            sections[current_section].append(line.rstrip())

    return sections


def _extract_markdown_list_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    fallback_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- [ ]", "- [x]", "- [X]", "- ", "* ")):
            normalized = _normalize_markdown_list_item(stripped)
            if not _is_placeholder_item(normalized):
                items.append(normalized)
            continue
        fallback_lines.append(stripped)

    if not items and fallback_lines:
        fallback_item = _normalize_markdown_list_item(f"- {fallback_lines[0]}")
        if not _is_placeholder_item(fallback_item):
            items.append(fallback_item)

    return items


def _extract_episode_status(lines: list[str]) -> str | None:
    for line in lines:
        candidate = _normalize_status_candidate(line)
        if candidate is None:
            continue
        if candidate in _NO_STATUS_CHANGE_VALUES:
            return None
        return candidate
    return None


def _normalize_status_candidate(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith(("- [ ]", "- [x]", "- [X]")):
        stripped = stripped[5:].strip()
    elif stripped.startswith(("- ", "* ")):
        stripped = stripped[2:].strip()
    if stripped.lower().startswith("status:"):
        stripped = stripped.split(":", maxsplit=1)[1].strip()
    normalized = " ".join(stripped.strip("`").lower().split())
    return normalized or None


def _normalize_markdown_list_item(item: str) -> str:
    stripped = item.strip()
    if stripped.startswith("* "):
        return f"- {stripped[2:].strip()}"
    return stripped


def _is_placeholder_item(item: str) -> bool:
    normalized = _normalize_list_item_key(item)
    return normalized in _PLACEHOLDER_ITEM_TEXTS


def _looks_like_list_item(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(("- [ ]", "- [x]", "- [X]", "- ", "* "))


def _normalize_list_item_key(item: str) -> str:
    normalized = item.strip().lower()
    if normalized.startswith("- [ ]"):
        normalized = normalized[5:].strip()
    elif normalized.startswith("- [x]"):
        normalized = normalized[5:].strip()
    elif normalized.startswith("* "):
        normalized = normalized[2:].strip()
    elif normalized.startswith("- "):
        normalized = normalized[2:].strip()
    return " ".join(normalized.split())


def _collect_section_list_state(body: str) -> tuple[list[str], set[str]]:
    existing_lines = [line.rstrip() for line in body.splitlines() if line.strip()]
    existing_keys = {
        _normalize_list_item_key(line) for line in existing_lines if _looks_like_list_item(line)
    }
    return existing_lines, existing_keys


def _append_unique_list_items(
    existing_lines: list[str],
    existing_keys: set[str],
    items: list[str],
) -> list[str]:
    updated_lines = list(existing_lines)
    for item in items:
        key = _normalize_list_item_key(item)
        if key in existing_keys:
            continue
        updated_lines.append(item)
        existing_keys.add(key)
    return updated_lines


def _extract_section_body(document: str, section_header: str) -> tuple[bool, str]:
    lines = document.rstrip().splitlines()
    bounds = _find_section_bounds(lines, section_header)
    if bounds is None:
        return False, ""
    start, end = bounds
    return True, "\n".join(lines[start:end]).strip()


def _replace_section_body(document: str, section_header: str, new_body: str) -> str:
    lines = document.rstrip().splitlines()
    bounds = _find_section_bounds(lines, section_header)
    if bounds is None:
        return _append_new_section(document, section_header, new_body)

    start, end = bounds
    header_index = start - 1
    prefix = "\n".join(lines[: header_index + 1]).rstrip()
    suffix = "\n".join(lines[end:]).lstrip("\n")
    parts = [prefix]
    if new_body.strip():
        parts.append(new_body.strip())
    if suffix:
        parts.append(suffix)
    return "\n\n".join(part for part in parts if part).rstrip() + "\n"


def _find_section_bounds(lines: list[str], section_header: str) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        if line.strip() != section_header:
            continue
        return index + 1, _find_next_section_start(lines, start=index + 1)
    return None


def _find_next_section_start(lines: list[str], *, start: int) -> int:
    for cursor in range(start, len(lines)):
        if lines[cursor].startswith("## "):
            return cursor
    return len(lines)


def _append_new_section(document: str, section_header: str, new_body: str) -> str:
    parts = [document.rstrip(), section_header]
    if new_body.strip():
        parts.append(new_body.strip())
    return "\n\n".join(part for part in parts if part).rstrip() + "\n"
