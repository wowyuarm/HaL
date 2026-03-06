"""Related-thread expansion helpers."""

from __future__ import annotations

from collections.abc import Callable


def expand_related_slugs(
    *,
    seed_slugs: set[str],
    related_lookup: Callable[[str], tuple[str, ...]],
    hops: int,
) -> set[str]:
    """Expand seed thread slugs using bounded related-thread hops."""
    if not seed_slugs:
        return set()
    expanded = set(seed_slugs)
    frontier = set(seed_slugs)
    for _ in range(max(1, hops)):
        if not frontier:
            break
        next_frontier: set[str] = set()
        for slug in frontier:
            next_frontier.update(related_lookup(slug))
        next_frontier.difference_update(expanded)
        expanded.update(next_frontier)
        frontier = next_frontier
    return expanded


__all__ = ["expand_related_slugs"]
