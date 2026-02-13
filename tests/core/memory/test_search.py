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

    async def search(self, query_embedding: list[float], top_k: int = 5) -> list[SearchResult]:
        # Simple: return all stored chunks ranked by first embedding element similarity
        results = []
        for chunk in self._data.values():
            # Fake score based on dot product of first element
            score = sum(a * b for a, b in zip(query_embedding[:3], chunk["embedding"][:3]))
            results.append(
                SearchResult(
                    content=chunk["content"],
                    source=chunk["source"],
                    heading=chunk.get("heading", ""),
                    score=score,
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


class TestExportAndIndexYesterday:
    async def test_convenience_method(self, memory_search):
        with patch.object(
            memory_search, "index_date", new_callable=AsyncMock, return_value=5
        ) as mock_idx:
            count = await memory_search.export_and_index_yesterday()
            assert count == 5
            mock_idx.assert_called_once()
