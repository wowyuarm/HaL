"""Unified memory manager coordinating all memory subsystems."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from hal.context.token_budget import estimate_text_tokens, trim_text_to_token_budget
from hal.workspace.memory import MemoryRepository


class _MemorySearchLike(Protocol):
    async def search(self, query: str, top_k: int = 3) -> list[object]: ...


class MemoryManager:
    """
    Central coordinator for all memory subsystems.

    Provides a unified interface for:
    - Reading/writing persistent knowledge (long-term)
    - Assembling memory context for prompt injection
    - Semantic search over past conversations (optional)
    """

    def __init__(
        self,
        workspace: Path,
        memory_search: _MemorySearchLike | None = None,
    ):
        self.long_term = MemoryRepository(workspace)
        self._search = memory_search

    def get_context(self, budget_tokens: int | None = None, token_model: str | None = None) -> str:
        """
        Assemble memory context for prompt injection.

        Args:
            budget_tokens: Approximate token budget for memory section.
            token_model: Model id used for token counting.
        """
        lt = self.long_term.read()
        if not lt:
            return ""

        content = f"## Long-term Memory\n\n{lt}"
        if budget_tokens is None or budget_tokens <= 0:
            return content
        if estimate_text_tokens(content, model=token_model) <= budget_tokens:
            return content

        # Keep a valid markdown tail marker when truncation is required.
        return trim_text_to_token_budget(
            content,
            budget_tokens,
            model=token_model,
            suffix="\n\n[...truncated]",
        )

    async def search_memories(self, query: str, top_k: int = 3) -> list[object]:
        """Semantic search over indexed past conversations.

        Returns empty list if memory search is not configured.
        """
        if self._search:
            return await self._search.search(query, top_k=top_k)
        return []
