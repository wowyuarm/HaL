"""Machine-truth parsing for thread registry metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

THREAD_METADATA_FILENAME = "THREAD.yaml"

_THREAD_STATUS_INACTIVE = "inactive"
_THREAD_STATUS_RE = re.compile(r"^Status:\s*(.+)$", re.IGNORECASE)
_THREAD_PINNED_RE = re.compile(r"^Pinned:\s*(.+)$", re.IGNORECASE)
_THREAD_TITLE_RE = re.compile(r"^#\s+(.+)$")
_THREAD_HEADING_GOAL = "## Goal"
_STATE_METADATA_PREFIXES = ("status:", "created:", "pinned:")
_DEFAULT_THREAD_DESCRIPTION = "No description provided."


@dataclass(frozen=True, slots=True)
class ResolvedThreadMetadata:
    """Merged thread metadata from BRIEF.md and optional THREAD.yaml."""

    status: str
    pinned: bool
    title: str
    description: str
    scope: str
    related_threads: tuple[str, ...]
    updated_at: str | None
    has_machine_metadata: bool


def load_thread_metadata(path: Path) -> dict:
    """Load THREAD.yaml into a dict, returning empty data on invalid input."""
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_thread_metadata(
    *, slug: str, state_content: str, metadata: dict
) -> ResolvedThreadMetadata:
    """Resolve registry-facing thread metadata from state content and THREAD.yaml."""
    status, pinned, title, description = _parse_thread_state_metadata(
        slug=slug,
        content=state_content,
    )
    return ResolvedThreadMetadata(
        status=_normalize_status(metadata.get("status"), fallback=status),
        pinned=_coerce_bool(metadata.get("pinned"), fallback=pinned),
        title=_normalize_text(metadata.get("name") or metadata.get("title"), fallback=title),
        description=_normalize_text(
            metadata.get("description") or metadata.get("goal"),
            fallback=description,
        ),
        scope=_normalize_text(metadata.get("scope"), fallback=""),
        related_threads=_normalize_related_threads(metadata.get("related_threads")),
        updated_at=_normalize_optional_text(metadata.get("updated_at")),
        has_machine_metadata=bool(metadata),
    )


def _parse_thread_state_metadata(*, slug: str, content: str) -> tuple[str, bool, str, str]:
    status = _THREAD_STATUS_INACTIVE
    pinned = False
    title = slug
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        title_match = _THREAD_TITLE_RE.match(stripped)
        if title_match:
            title = title_match.group(1).strip()
            continue
        status_match = _THREAD_STATUS_RE.match(stripped)
        if status_match:
            normalized = status_match.group(1).strip().lower()
            if normalized:
                status = normalized
            continue
        pinned_match = _THREAD_PINNED_RE.match(stripped)
        if pinned_match:
            pinned = pinned_match.group(1).strip().lower() in {"true", "yes", "1", "y"}

    return status, pinned, title, _extract_thread_goal(content)


def _normalize_status(value: object, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().lower()
    return normalized or fallback


def _coerce_bool(value: object, *, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "y"}:
            return True
        if normalized in {"false", "no", "0", "n"}:
            return False
    return fallback


def _normalize_text(value: object, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized or fallback


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        normalized = str(value.isoformat()).strip()
        return normalized or None
    normalized = str(value).strip()
    return normalized or None


def _normalize_related_threads(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return tuple(items)
    return ()


def _extract_thread_goal(content: str) -> str:
    lines = content.splitlines()
    goal_line = _extract_goal_section_line(lines)
    if goal_line:
        return goal_line
    return _first_descriptive_line(lines) or _DEFAULT_THREAD_DESCRIPTION


def _extract_goal_section_line(lines: list[str]) -> str | None:
    goal_index = _find_heading_index(lines, _THREAD_HEADING_GOAL)
    if goal_index is None:
        return None
    for stripped in _iter_nonempty_stripped_lines(lines[goal_index + 1 :]):
        if stripped.startswith("#"):
            return None
        return stripped
    return None


def _find_heading_index(lines: list[str], heading: str) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == heading:
            return index
    return None


def _first_descriptive_line(lines: list[str]) -> str | None:
    for stripped in _iter_nonempty_stripped_lines(lines):
        if _is_description_candidate(stripped):
            return stripped
    return None


def _iter_nonempty_stripped_lines(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def _is_description_candidate(stripped: str) -> bool:
    if stripped.startswith("#"):
        return False
    return not stripped.lower().startswith(_STATE_METADATA_PREFIXES)
