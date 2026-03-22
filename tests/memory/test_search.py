"""Tests for EpisodeRecallIndex — chunk, embed, and search pipeline."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hal.memory.chunker import MarkdownChunker
from hal.memory.contracts import MemorySearchDeps
from hal.memory.search import (
    EpisodeRecallIndex,
    _extract_channel_from_heading,
)
from hal.memory.store import SearchResult


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
        results = []
        for chunk in self._data.values():
            score = sum(a * b for a, b in zip(query_embedding[:3], chunk["embedding"][:3]))
            if query_text and query_text.lower() in chunk["content"].lower():
                score += 0.5
            results.append(
                SearchResult(
                    content=chunk["content"],
                    source=chunk["source"],
                    heading=chunk.get("heading", ""),
                    score=score,
                    source_type=chunk.get("source_type", "raw"),
                    thread=chunk.get("thread", ""),
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


def _make_search(tmp_path: Path, **kwargs) -> EpisodeRecallIndex:
    """Create an EpisodeRecallIndex with FakeVectorStore for testing."""
    chunker = MarkdownChunker(max_size=500, overlap_lines=1)
    store = FakeVectorStore()
    return EpisodeRecallIndex(
        deps=MemorySearchDeps(chunker=chunker, store=store),
        embedding_model="fake-model",
        source_root=tmp_path,
        **kwargs,
    )


def test_episode_recall_index_instantiates(tmp_path: Path) -> None:
    search = _make_search(tmp_path)

    assert isinstance(search, EpisodeRecallIndex)


@pytest.fixture
def recall_index(tmp_path):
    return _make_search(tmp_path)


@pytest.fixture
def episode_search(tmp_path):
    threads_dir = tmp_path / "work" / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    return _make_search(tmp_path, episodes_root=threads_dir)


class TestIndexFile:
    async def test_index_empty_nonexistent(self, recall_index, tmp_path):
        count = await recall_index.index_episode(tmp_path / "does-not-exist.md")
        assert count == 0

    async def test_index_markdown_file(self, recall_index, tmp_path):
        md_path = tmp_path / "episode.md"
        md_path.write_text(
            "# 2026-03-07: Test episode\n\n## Discussion\n\nThe weather in Beijing is sunny\n",
            encoding="utf-8",
        )

        with patch.object(
            recall_index,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            count = await recall_index._index_file(md_path)
            assert count > 0

    async def test_incremental_index(self, recall_index, tmp_path):
        """Second call with same data should not re-embed."""
        md_path = tmp_path / "episode.md"
        md_path.write_text("# A\n\nHello world\n", encoding="utf-8")

        with patch.object(
            recall_index,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ) as mock_embed:
            await recall_index._index_file(md_path)
            first_calls = mock_embed.call_count

            await recall_index._index_file(md_path)
            assert mock_embed.call_count == first_calls

    async def test_index_file_clears_stale_source_when_all_chunks_excluded(
        self, recall_index, tmp_path
    ):
        source = "episode.md"
        md_path = tmp_path / source
        md_path.write_text(
            "# 2026-02-12\n\n## cron / job-1\n\n**[10:30] User**: should be excluded\n",
            encoding="utf-8",
        )
        recall_index._exclude_channels = {"cron"}

        await recall_index._store.upsert(
            [
                {
                    "chunk_id": "stale-1",
                    "embedding": [0.1] * 8,
                    "content": "old cron content",
                    "source": source,
                    "heading": "cron / job-1",
                    "source_type": "raw",
                }
            ]
        )

        count = await recall_index._index_file(md_path)
        remaining = await recall_index._store.get_chunk_ids_by_source(source)

        assert count == 0
        assert remaining == set()


class TestSearch:
    async def test_search_returns_results(self, recall_index, tmp_path):
        md_path = tmp_path / "episode.md"
        md_path.write_text(
            "# 2026-03-07\n\n## telegram / 123\n\nThe weather in Beijing is sunny\n",
            encoding="utf-8",
        )

        with patch.object(
            recall_index,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            await recall_index._index_file(md_path)
            results = await recall_index.search("weather", top_k=3)
            assert len(results) > 0
            assert any(
                "weather" in r.content.lower() or "sunny" in r.content.lower() for r in results
            )

    async def test_search_empty_store(self, recall_index):
        with patch.object(
            recall_index,
            "_embed_texts",
            new_callable=AsyncMock,
            return_value=_fake_embedding(["query"]),
        ):
            results = await recall_index.search("anything")
            assert results == []

    async def test_search_excludes_channels(self, recall_index):
        recall_index._exclude_channels = {"cron"}
        fake_results = [
            SearchResult(
                content="cron update",
                source="episode.md",
                heading="cron / job-1",
                score=0.95,
                source_type="raw",
            ),
            SearchResult(
                content="user update",
                source="episode.md",
                heading="telegram / 123",
                score=0.9,
                source_type="raw",
            ),
        ]
        with (
            patch.object(
                recall_index,
                "_embed_texts",
                new_callable=AsyncMock,
                return_value=_fake_embedding(["query"]),
            ),
            patch.object(
                recall_index._store, "search", new_callable=AsyncMock, return_value=fake_results
            ),
        ):
            results = await recall_index.search("update", top_k=5)

        assert len(results) == 1
        assert results[0].heading == "telegram / 123"

    async def test_search_keeps_store_ranking_even_for_legacy_source_types(self, recall_index):
        summary = SearchResult(
            content="summary content",
            source="a.md",
            heading="Summary",
            score=1.0,
            source_type="summary",
        )
        subagent = SearchResult(
            content="subagent content",
            source="b.md",
            heading="Subagent Result",
            score=0.95,
            source_type="subagent",
        )
        with (
            patch.object(
                recall_index,
                "_embed_texts",
                new_callable=AsyncMock,
                return_value=_fake_embedding(["query"]),
            ),
            patch.object(
                recall_index._store,
                "search",
                new_callable=AsyncMock,
                return_value=[summary, subagent],
            ),
        ):
            out = await recall_index.search("query", top_k=2)

        assert [item.source_type for item in out] == ["summary", "subagent"]

    async def test_search_expands_keyword_query_terms(self, recall_index):
        with (
            patch.object(
                recall_index,
                "_embed_texts",
                new_callable=AsyncMock,
                return_value=_fake_embedding(["query"]),
            ),
            patch.object(
                recall_index._store, "search", new_callable=AsyncMock, return_value=[]
            ) as mock_store_search,
        ):
            await recall_index.search("opencontext与dev_workflow", top_k=3)
            kwargs = mock_store_search.await_args.kwargs
            query_text = kwargs["query_text"]
            assert "dev_workflow" in query_text
            assert "dev-workflow" in query_text
            assert kwargs["top_k"] > 3

    async def test_search_applies_min_score_filter(self, recall_index):
        fake_results = [
            SearchResult(content="high", source="a", heading="", score=0.9, source_type="raw"),
            SearchResult(content="low", source="b", heading="", score=0.1, source_type="raw"),
        ]
        with (
            patch.object(
                recall_index,
                "_embed_texts",
                new_callable=AsyncMock,
                return_value=_fake_embedding(["query"]),
            ),
            patch.object(
                recall_index._store, "search", new_callable=AsyncMock, return_value=fake_results
            ),
        ):
            results = await recall_index.search("query", top_k=5, min_score=0.5)
            assert len(results) == 1
            assert results[0].content == "high"


class TestEmbeddingResilience:
    async def test_embed_texts_retries_on_transient_error(self, recall_index):
        with (
            patch.object(
                recall_index,
                "_embed_texts_litellm",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("temporary"), _fake_embedding(["query"])],
            ) as mock_embed,
            patch("hal.memory.search.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            out = await recall_index._embed_texts(["query"])
            assert len(out) == 1
            assert mock_embed.await_count == 2
            mock_sleep.assert_awaited_once()

    async def test_index_file_falls_back_to_per_chunk_embedding(self, recall_index, tmp_path):
        md_path = tmp_path / "episode.md"
        md_path.write_text("# A\n\nalpha\n\n## B\n\nbeta", encoding="utf-8")

        async def flaky_embed(texts: list[str]) -> list[list[float]]:
            if len(texts) > 1:
                return []
            if "beta" in texts[0]:
                return []
            return _fake_embedding(texts)

        with patch.object(recall_index, "_embed_texts", new=flaky_embed):
            count = await recall_index._index_file(md_path)

        assert count == 1

    async def test_needs_reindex_detects_chunk_id_mismatch(self, recall_index, tmp_path):
        md_path = tmp_path / "episode.md"
        md_path.write_text("# A\n\nalpha", encoding="utf-8")

        with patch.object(
            recall_index,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            await recall_index._index_file(md_path)

        source_name = "episode.md"
        needs_reindex = await recall_index._needs_reindex(
            source_name, indexed_sources={source_name}
        )
        assert needs_reindex is False

        md_path.write_text("# A\n\nalpha changed", encoding="utf-8")
        needs_reindex = await recall_index._needs_reindex(
            source_name, indexed_sources={source_name}
        )
        assert needs_reindex is True


class TestEpisodeIndexing:
    async def test_index_episode_populates_thread_metadata(self, episode_search, tmp_path):
        episode_path = (
            tmp_path / "work" / "threads" / "github-actions" / "episodes" / "2026-03-06-test.md"
        )
        episode_path.parent.mkdir(parents=True, exist_ok=True)
        episode_path.write_text(
            "# 2026-03-06: Workflow draft\n\n## What Happened\n- Drafted workflow yaml\n",
            encoding="utf-8",
        )

        with patch.object(
            episode_search,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            count = await episode_search.index_episode(episode_path)

        assert count > 0
        assert episode_search._store._data
        sample = next(iter(episode_search._store._data.values()))
        assert sample["thread"] == "github-actions"
        assert sample["source"].startswith("work/threads/github-actions/episodes/")

    async def test_backfill_indexes_episode_sources(self, episode_search, tmp_path):
        episode_path = (
            tmp_path / "work" / "threads" / "hal-architecture" / "episodes" / "2026-03-07-arch.md"
        )
        episode_path.parent.mkdir(parents=True, exist_ok=True)
        episode_path.write_text(
            "# 2026-03-07: Architecture iteration\n\n## Decisions\n- Keep thread registry capped\n",
            encoding="utf-8",
        )

        with patch.object(
            episode_search,
            "_embed_texts",
            new_callable=AsyncMock,
            side_effect=lambda texts: _fake_embedding(texts),
        ):
            count = await episode_search.backfill()

        assert count > 0
        indexed_sources = await episode_search._store.get_indexed_sources()
        assert "work/threads/hal-architecture/episodes/2026-03-07-arch.md" in indexed_sources


def test_extract_channel_from_heading() -> None:
    assert _extract_channel_from_heading("cron / job-1") == "cron"
    assert _extract_channel_from_heading("telegram / 123") == "telegram"
    assert _extract_channel_from_heading("section-without-channel") is None
