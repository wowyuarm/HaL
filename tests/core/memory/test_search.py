"""Tests for MemorySearch — integration of export, chunk, embed, and search."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from hal.core.memory.chunker import MarkdownChunker
from hal.core.memory.exporter import DailyExporter
from hal.core.memory.search import MemorySearch
from hal.core.memory.store import SearchResult


class FakeVectorStore:
    """In-memory vector store for testing (no Milvus dependency)."""

    def __init__(self):
        self._data: dict[str, dict] = {}

    async def initialize(self):
        pass

    async def upsert(self, chunks: list[dict]) -> int:
        for chunk in chunks:
            self._data[chunk["chunk_id"]] = chunk
        return len(chunks)

    async def search(
        self, query_embedding: list[float], *, query_text: str = "", top_k: int = 5
    ) -> list[SearchResult]:
        # Simple: return all stored chunks ranked by first embedding element similarity
        results = []
        for chunk in self._data.values():
            # Fake score based on dot product of first element
            score = sum(a * b for a, b in zip(query_embedding[:3], chunk["embedding"][:3]))
            # Boost score if query_text appears in content (simulates BM25)
            if query_text and query_text.lower() in chunk["content"].lower():
                score += 0.5
            results.append(
                SearchResult(
                    content=chunk["content"],
                    source=chunk["source"],
                    heading=chunk.get("heading", ""),
                    score=score,
                    source_type=chunk.get("source_type", "raw"),
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    async def delete_by_source(self, source: str) -> int:
        to_delete = [k for k, v in self._data.items() if v["source"] == source]
        for k in to_delete:
            del self._data[k]
        return len(to_delete)

    async def get_chunk_ids_by_source(self, source: str) -> set[str]:
        return {k for k, v in self._data.items() if v["source"] == source}

    async def get_indexed_sources(self) -> set[str]:
        return {v["source"] for v in self._data.values()}

    async def close(self):
        pass


def _fake_embedding(texts: list[str]) -> list[list[float]]:
    """Deterministic fake embeddings based on text hash."""
    result = []
    for t in texts:
        h = hash(t) % 10000
        result.append([h / 10000.0] * 8)
    return result


@pytest.fixture
def daily_log(tmp_path):
    from hal.core.memory.daily_log import DailyLog

    return DailyLog(tmp_path / "logs")


@pytest.fixture
def daily_dir(tmp_path):
    d = tmp_path / "daily"
    d.mkdir()
    return d


@pytest.fixture
def memory_search(daily_log, daily_dir):
    exporter = DailyExporter(daily_log, daily_dir)
    chunker = MarkdownChunker(max_size=500, overlap_lines=1)
    store = FakeVectorStore()
    ms = MemorySearch(
        exporter=exporter,
        chunker=chunker,
        store=store,
        embedding_model="fake-model",
        daily_dir=daily_dir,
    )
    return ms


class TestIndexDate:
    async def test_index_empty(self, memory_search):
        with patch.object(memory_search, "_embed_texts", new_callable=AsyncMock) as mock_embed:
            count = await memory_search.index_date(date(2026, 2, 12))
            assert count == 0
            mock_embed.assert_not_called()

    async def test_index_with_data(self, memory_search, daily_log, daily_dir):
        from hal.core.memory.daily_log import LogEntry

        # Write a log entry
        log_file = daily_log.data_dir / "2026-02-12.jsonl"
        entry = LogEntry(
            timestamp="2026-02-12T10:30:00",
            channel="telegram",
            chat_id="123",
            role="user",
            content="Tell me about the weather",
        )
        log_file.write_text(entry.model_dump_json() + "\n")

        with patch.object(
            memory_search,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            count = await memory_search.index_date(date(2026, 2, 12))
            assert count > 0

    async def test_incremental_index(self, memory_search, daily_log, daily_dir):
        """Second call with same data should not re-embed."""
        from hal.core.memory.daily_log import LogEntry

        log_file = daily_log.data_dir / "2026-02-12.jsonl"
        entry = LogEntry(
            timestamp="2026-02-12T10:30:00",
            channel="cli",
            chat_id="direct",
            role="user",
            content="Hello world",
        )
        log_file.write_text(entry.model_dump_json() + "\n")

        with patch.object(
            memory_search,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ) as mock_embed:
            # First indexing: must export first since md doesn't exist yet
            await memory_search.index_date(date(2026, 2, 12))
            first_calls = mock_embed.call_count

            # Re-index — the md file already exists, chunks already in store
            await memory_search.index_date(date(2026, 2, 12))
            # Should not call embed again since chunks are already indexed
            assert mock_embed.call_count == first_calls


class TestSearch:
    async def test_search_returns_results(self, memory_search, daily_log, daily_dir):
        from hal.core.memory.daily_log import LogEntry

        log_file = daily_log.data_dir / "2026-02-12.jsonl"
        entry = LogEntry(
            timestamp="2026-02-12T10:30:00",
            channel="telegram",
            chat_id="123",
            role="user",
            content="The weather in Beijing is sunny",
        )
        log_file.write_text(entry.model_dump_json() + "\n")

        with patch.object(
            memory_search,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            await memory_search.index_date(date(2026, 2, 12))
            results = await memory_search.search("weather", top_k=3)
            assert len(results) > 0
            assert any(
                "weather" in r.content.lower() or "sunny" in r.content.lower() for r in results
            )

    async def test_search_empty_store(self, memory_search):
        with patch.object(
            memory_search,
            "_embed_texts",
            new_callable=AsyncMock,
            return_value=_fake_embedding(["query"]),
        ):
            results = await memory_search.search("anything")
            assert results == []

    async def test_summary_penalty_applied(self, memory_search, daily_log, daily_dir):
        """Summary chunks should have their scores reduced by the penalty factor."""
        from hal.core.memory.daily_log import LogEntry
        from hal.core.memory.search import _SUMMARY_PENALTY

        log_file = daily_log.data_dir / "2026-02-12.jsonl"
        entries = [
            LogEntry(
                timestamp="2026-02-12T10:30:00",
                channel="telegram",
                chat_id="123",
                role="user",
                content="Discuss the deployment strategy for production",
            ),
            LogEntry(
                timestamp="2026-02-12T10:31:00",
                channel="telegram",
                chat_id="123",
                role="user",
                content=(
                    "[System Summary]\n"
                    "Agent deployed the app to production using blue-green strategy."
                ),
                entry_type="summary",
            ),
        ]
        log_file.write_text("\n".join(e.model_dump_json() for e in entries) + "\n")

        with patch.object(
            memory_search,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            await memory_search.index_date(date(2026, 2, 12))

            # Get raw scores from store directly (before penalty)
            raw_results = await memory_search._store.search(
                _fake_embedding(["deployment"])[0], query_text="deployment", top_k=5
            )
            summary_raw_scores = {
                r.content: r.score for r in raw_results if r.source_type == "summary"
            }

            # Get penalized scores via search()
            results = await memory_search.search("deployment", top_k=5)
            summary_penalized = {r.content: r.score for r in results if r.source_type == "summary"}

            # Verify penalty was applied to summary chunks
            for content, penalized_score in summary_penalized.items():
                raw_score = summary_raw_scores[content]
                assert abs(penalized_score - raw_score * _SUMMARY_PENALTY) < 1e-6

    async def test_subagent_penalty_applied(self, memory_search, daily_log, daily_dir):
        """Subagent chunks should be tagged and mildly down-ranked."""
        from hal.core.memory.daily_log import LogEntry
        from hal.core.memory.search import _SUBAGENT_PENALTY

        log_file = daily_log.data_dir / "2026-02-12.jsonl"
        entries = [
            LogEntry(
                timestamp="2026-02-12T10:30:00",
                channel="telegram",
                chat_id="123",
                role="user",
                content="Please audit this repository and summarize findings",
            ),
            LogEntry(
                timestamp="2026-02-12T10:31:00",
                channel="telegram",
                chat_id="123",
                role="user",
                content=(
                    "[Subagent Result: repo-audit]\n"
                    "Found 3 critical issues and 2 warnings.\n"
                    "[Subagent Artifact] /tmp/artifacts/subagent/abc.md"
                ),
                entry_type="injection",
            ),
        ]
        log_file.write_text("\n".join(e.model_dump_json() for e in entries) + "\n")

        with patch.object(
            memory_search,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            await memory_search.index_date(date(2026, 2, 12))

            raw_results = await memory_search._store.search(
                _fake_embedding(["audit"])[0], query_text="audit", top_k=10
            )
            subagent_raw_scores = {
                r.content: r.score for r in raw_results if r.source_type == "subagent"
            }
            assert subagent_raw_scores

            results = await memory_search.search("audit", top_k=10)
            subagent_penalized = {
                r.content: r.score for r in results if r.source_type == "subagent"
            }
            assert subagent_penalized

            for content, penalized_score in subagent_penalized.items():
                raw_score = subagent_raw_scores[content]
                assert abs(penalized_score - raw_score * _SUBAGENT_PENALTY) < 1e-6

    async def test_search_applies_min_score_filter(self, memory_search):
        fake_results = [
            SearchResult(content="high", source="a", heading="", score=0.9, source_type="raw"),
            SearchResult(content="low", source="b", heading="", score=0.1, source_type="raw"),
        ]
        with (
            patch.object(
                memory_search,
                "_embed_texts",
                new_callable=AsyncMock,
                return_value=_fake_embedding(["query"]),
            ),
            patch.object(
                memory_search._store, "search", new_callable=AsyncMock, return_value=fake_results
            ),
        ):
            results = await memory_search.search("query", top_k=5, min_score=0.5)
            assert len(results) == 1
            assert results[0].content == "high"


class TestExportAndIndexYesterday:
    async def test_convenience_method(self, memory_search):
        with patch.object(
            memory_search, "index_date", new_callable=AsyncMock, return_value=5
        ) as mock_idx:
            count = await memory_search.export_and_index_yesterday()
            assert count == 5
            mock_idx.assert_called_once()
