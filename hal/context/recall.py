"""Recall helpers used by session-turn compilation."""

from __future__ import annotations

from typing import Any

from loguru import logger


def collect_recalled_thread_slugs(search_results: list[object]) -> set[str]:
    """Collect recalled thread slugs from memory-search results."""
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


async def prefetch_memory_results(
    *,
    memory_search: Any,
    current_message: str,
    top_k: int,
    min_score: float,
) -> list[object]:
    """Best-effort memory-search prefetch for turn-context injects."""
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
