"""Thread mention matching for session touch detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

_THREAD_MATCH_TOKEN_RE = re.compile(r"[_\W]+", flags=re.UNICODE)
_THREAD_MATCH_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "work",
    "thread",
    "threads",
    "project",
    "projects",
    "task",
    "tasks",
}


@dataclass(frozen=True, slots=True)
class ThreadMatchEntry:
    """Normalized thread matching candidates derived from registry snapshots."""

    slug: str
    phrases: tuple[str, ...]
    tokens: frozenset[str]


def detect_thread_mentions(text: str, registry: Sequence[Mapping[str, object]]) -> set[str]:
    """Best-effort thread mention detection from user-visible text."""
    if not text.strip():
        return set()

    normalized_text = _normalize_thread_match_text(text)
    if not normalized_text:
        return set()

    text_tokens = set(normalized_text.split())
    entries = _build_thread_match_entries(registry)
    token_to_slugs = _build_token_index(entries)
    return {
        entry.slug
        for entry in entries
        if _matches_thread_entry(
            entry,
            normalized_text=normalized_text,
            text_tokens=text_tokens,
            token_to_slugs=token_to_slugs,
        )
    }


def _build_thread_match_entries(registry: Sequence[Mapping[str, object]]) -> list[ThreadMatchEntry]:
    entries: list[ThreadMatchEntry] = []
    for item in registry:
        slug = str(item.get("slug", "")).strip()
        if not slug:
            continue
        phrases = tuple(_iter_normalized_thread_candidates(item, slug=slug))
        tokens = frozenset(
            token for phrase in phrases for token in _extract_thread_match_tokens(phrase)
        )
        entries.append(ThreadMatchEntry(slug=slug, phrases=phrases, tokens=tokens))
    return entries


def _iter_normalized_thread_candidates(
    entry: Mapping[str, object],
    *,
    slug: str,
) -> list[str]:
    candidates = {
        slug,
        str(entry.get("name", "")).strip(),
        slug.replace("-", " ").replace("_", " ").strip(),
    }
    normalized: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        candidate_norm = _normalize_thread_match_text(candidate)
        if not _is_meaningful_thread_candidate(candidate_norm):
            continue
        normalized.append(candidate_norm)
    return normalized


def _build_token_index(entries: Sequence[ThreadMatchEntry]) -> dict[str, set[str]]:
    token_to_slugs: dict[str, set[str]] = {}
    for entry in entries:
        for token in entry.tokens:
            token_to_slugs.setdefault(token, set()).add(entry.slug)
    return token_to_slugs


def _matches_thread_entry(
    entry: ThreadMatchEntry,
    *,
    normalized_text: str,
    text_tokens: set[str],
    token_to_slugs: Mapping[str, set[str]],
) -> bool:
    return _matches_phrases(entry, normalized_text) or _matches_unique_tokens(
        entry,
        text_tokens=text_tokens,
        token_to_slugs=token_to_slugs,
    )


def _matches_phrases(entry: ThreadMatchEntry, normalized_text: str) -> bool:
    return any(phrase in normalized_text for phrase in entry.phrases)


def _matches_unique_tokens(
    entry: ThreadMatchEntry,
    *,
    text_tokens: set[str],
    token_to_slugs: Mapping[str, set[str]],
) -> bool:
    for token in entry.tokens:
        if token not in text_tokens:
            continue
        if token_to_slugs.get(token) == {entry.slug}:
            return True
    return False


def _normalize_thread_match_text(text: str) -> str:
    lowered = text.lower()
    collapsed = _THREAD_MATCH_TOKEN_RE.sub(" ", lowered)
    return " ".join(collapsed.split())


def _is_meaningful_thread_candidate(candidate: str) -> bool:
    if not candidate:
        return False
    if any(ord(ch) > 127 for ch in candidate):
        return len(candidate) >= 2
    return len(candidate) >= 4


def _extract_thread_match_tokens(candidate: str) -> set[str]:
    tokens: set[str] = set()
    for token in candidate.split():
        if token in _THREAD_MATCH_STOPWORDS:
            continue
        if not _is_meaningful_thread_candidate(token):
            continue
        tokens.add(token)
    return tokens
