from __future__ import annotations

import pytest

from hal.capabilities.tools.recall import RecallTool
from hal.core.memory.store import SearchResult


class DummyMemorySearch:
    async def search(self, _query: str, top_k: int = 5):
        return [
            SearchResult(
                content="matched memory",
                source="2026-02-20.md",
                heading="telegram / 123",
                score=0.021,
                source_type="raw",
            )
        ][:top_k]


@pytest.mark.asyncio
async def test_recall_tool_uses_rrf_score_label() -> None:
    tool = RecallTool(DummyMemorySearch())
    out = await tool.execute(query="memory", top_k=1)
    assert "rrf_score: 0.021" in out
    assert "(score:" not in out
