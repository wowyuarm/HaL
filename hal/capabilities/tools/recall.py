"""Recall tool — semantic search over past episode notes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from hal.capabilities.tools.base import Tool

if TYPE_CHECKING:
    from hal.memory.search import EpisodeRecallIndex


class RecallTool(Tool):
    """Search past episode notes semantically."""

    def __init__(self, recall_index: EpisodeRecallIndex):
        self._search = recall_index

    @property
    def name(self) -> str:
        return "recall"

    @property
    def description(self) -> str:
        return "Search past episode notes semantically."

    @property
    def prompt(self) -> str:
        return (
            "Search past episode notes by semantic relevance.\n"
            "Use for finding information from earlier sessions — decisions, context, "
            "prior work. The current session is already in your context; "
            "recall covers past sessions only.\n"
            "Check auto-injected memories first; use recall when they are insufficient "
            "or you need targeted results on a specific topic.\n"
            "top_k range: 1-10 (default 5). Returns ranked snippets with rrf_score."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query describing what to find.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (1-10).",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        top_k = kwargs.get("top_k", 5)

        try:
            results = await self._search.search(query, top_k=top_k)
        except Exception as e:
            logger.warning(f"Recall search failed: {e}")
            return "Recall is temporarily unavailable."

        if not results:
            return "No relevant past notes found."

        parts: list[str] = [f"Found {len(results)} relevant past notes:\n"]
        for i, r in enumerate(results, 1):
            header = f"**[{i}] {r.source}"
            if r.heading:
                header += f" — {r.heading}"
            header += f"** (rrf_score: {r.score:.3f}"
            if r.source_type and r.source_type != "raw":
                header += f", {r.source_type}"
            header += ")"
            parts.append(header)
            parts.append(r.content)
            parts.append("")

        return "\n".join(parts)
