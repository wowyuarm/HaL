"""Baseline planning helpers for session working-set compilation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from hal.context.registry import expand_related_slugs
from hal.context.thread_mentions import detect_thread_mentions


@dataclass(frozen=True, slots=True)
class BaselinePlan:
    """Resolved baseline inputs for one compiled session turn."""

    session_baseline: str
    search_results: list[object]
    recalled_thread_slugs: set[str]
    baseline_thread_slugs: set[str]
    baseline_created: bool


async def compile_baseline_plan(
    *,
    context_builder: Any,
    current_message: str,
    channel: str | None,
    chat_id: str | None,
    token_model: str | None,
    recall_max_total_tokens: int,
    recall_max_per_item_tokens: int,
    mounted_threads: set[str] | None,
    memory_search: Any,
    auto_inject_top_k: int,
    recall_min_score: float,
    thread_snapshot: list[dict[str, object]],
    active_thread_entries: list[dict[str, object]],
    related_lookup: Callable[[str], tuple[str, ...]] | None = None,
    related_hops: int = 1,
    max_active_threads: int = 0,
) -> BaselinePlan:
    """Resolve baseline content, recall prefetch, and baseline thread membership.

    Always compiles fresh: memory recall and thread expansion run every turn.
    When ``mounted_threads`` is provided, thread selection is constrained to
    those explicitly mounted by the user.
    """
    baseline_active_threads = normalize_active_thread_entries(
        active_thread_entries=active_thread_entries,
        thread_snapshot=thread_snapshot,
    )

    search_results = await prefetch_memory_results(
        memory_search=memory_search,
        current_message=current_message,
        top_k=auto_inject_top_k,
        min_score=recall_min_score,
    )
    recalled_thread_slugs = collect_recalled_thread_slugs(search_results)
    mentioned_thread_slugs = detect_thread_mentions(current_message, thread_snapshot)
    preferred_thread_slugs = expand_related_thread_slugs(
        seed_slugs=recalled_thread_slugs | mentioned_thread_slugs,
        related_lookup=related_lookup,
        max_hops=related_hops,
    )

    # When mounted_threads is specified, constrain thread selection to that set.
    if mounted_threads is not None:
        mounted_set = {slug for slug in mounted_threads if slug}
        baseline_active_threads = [
            entry
            for entry in baseline_active_threads
            if str(entry.get("slug", "")).strip() in mounted_set
        ]

    baseline_active_threads = select_active_thread_entries(
        active_thread_entries=baseline_active_threads,
        preferred_slugs=preferred_thread_slugs,
        max_entries=max_active_threads,
    )
    logger.debug(
        "baseline: mounted={} recall={} mentioned={} active={}",
        mounted_threads or set(),
        recalled_thread_slugs,
        mentioned_thread_slugs,
        [str(e.get("slug", "")) for e in baseline_active_threads],
    )
    session_baseline = context_builder.build_dynamic_context_block(
        channel=channel,
        chat_id=chat_id,
        active_threads=baseline_active_threads,
        memory_search_results=search_results or None,
        recall_max_total_tokens=recall_max_total_tokens,
        recall_max_per_item_tokens=recall_max_per_item_tokens,
        token_model=token_model,
    )

    return BaselinePlan(
        session_baseline=session_baseline,
        search_results=search_results,
        recalled_thread_slugs=recalled_thread_slugs,
        baseline_thread_slugs=collect_active_thread_slugs(baseline_active_threads),
        baseline_created=True,
    )


def collect_recalled_thread_slugs(search_results: list[object]) -> set[str]:
    """Collect recalled thread slugs from recall search results."""
    return {
        str(getattr(result, "thread", "")).strip()
        for result in search_results
        if str(getattr(result, "thread", "")).strip()
    }


def collect_active_thread_slugs(thread_snapshot: list[dict[str, object]]) -> set[str]:
    """Collect active thread slugs from a thread registry snapshot."""
    return {
        str(item["slug"])
        for item in thread_snapshot
        if str(item.get("status", "")).strip() == "active"
    }


def expand_related_thread_slugs(
    *,
    seed_slugs: set[str],
    related_lookup: Callable[[str], tuple[str, ...]] | None,
    max_hops: int = 1,
) -> set[str]:
    """Expand one set of thread slugs with bounded related-thread hops."""
    if not seed_slugs:
        return set()
    if related_lookup is None:
        return set(seed_slugs)
    return expand_related_slugs(
        seed_slugs=seed_slugs,
        related_lookup=related_lookup,
        hops=max_hops,
    )


def select_active_thread_entries(
    *,
    active_thread_entries: list[dict[str, object]],
    preferred_slugs: set[str],
    max_entries: int,
) -> list[dict[str, object]]:
    """Select active thread entries for baseline injection."""
    if not active_thread_entries:
        return []
    ranked_entries = sorted(active_thread_entries, key=_active_thread_rank)
    if not preferred_slugs:
        return _apply_entry_limit(ranked_entries, max_entries=max_entries)

    preferred_set = {slug for slug in preferred_slugs if slug}
    selected = [
        entry for entry in ranked_entries if str(entry.get("slug", "")).strip() in preferred_set
    ]
    if selected:
        return _apply_entry_limit(selected, max_entries=max_entries)
    return _apply_entry_limit(ranked_entries, max_entries=max_entries)


def _apply_entry_limit(
    entries: list[dict[str, object]],
    *,
    max_entries: int,
) -> list[dict[str, object]]:
    """Apply max-entry cap when configured."""
    if max_entries <= 0:
        return entries
    return entries[:max_entries]


def _active_thread_rank(entry: dict[str, object]) -> tuple[int, float, str]:
    """Rank active threads by priority and recency (descending)."""
    priority = _coerce_priority(entry.get("priority"))
    mtime = _coerce_mtime(entry.get("mtime"))
    slug = str(entry.get("slug", "")).strip()
    return (-priority, -mtime, slug)


def _coerce_priority(value: object) -> int:
    """Best-effort integer coercion for priority values."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except Exception:
        return 0


def _coerce_mtime(value: object) -> float:
    """Best-effort float coercion for mtime values."""
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return 0.0


def normalize_active_thread_entries(
    *,
    active_thread_entries: object,
    thread_snapshot: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Normalize active-thread entries, falling back to thread snapshots when needed."""
    if isinstance(active_thread_entries, list):
        normalized = [
            item
            for item in active_thread_entries
            if isinstance(item, dict) and str(item.get("slug", "")).strip()
        ]
        if normalized:
            return normalized

    def _to_active_entry(item: dict[str, object]) -> dict[str, object] | None:
        if str(item.get("status", "")).strip() != "active":
            return None
        slug = str(item.get("slug", "")).strip()
        if not slug:
            return None
        return {
            "slug": slug,
            "name": str(item.get("name", "")).strip(),
            "status": "active",
            "description": str(item.get("description", "")).strip(),
            "state_path": str(item.get("state_path", "")).strip(),
            "state_content": str(item.get("state_content", "")).strip(),
            "priority": item.get("priority", 0),
            "related_threads": item.get("related_threads", ()),
        }

    return [
        entry
        for entry in (_to_active_entry(item) for item in thread_snapshot if isinstance(item, dict))
        if entry is not None
    ]


async def prefetch_memory_results(
    *,
    memory_search: Any,
    current_message: str,
    top_k: int,
    min_score: float,
) -> list[object]:
    """Best-effort memory-search prefetch for baseline compilation."""
    if not memory_search:
        return []
    try:
        return await memory_search.search(
            current_message,
            top_k=top_k,
            min_score=min_score,
        )
    except Exception as e:
        logger.warning(f"Memory search prefetch failed: {e}")
        return []
