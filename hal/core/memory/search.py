"""Memory search orchestrator — coordinates export, chunking, embedding, and retrieval.

Provides a high-level interface for the memory search pipeline:
JSONL → Markdown → Chunks → Embeddings → Milvus → Semantic Search
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import litellm
from loguru import logger

from hal.core.memory.chunker import MarkdownChunker
from hal.core.memory.exporter import DailyExporter
from hal.core.memory.store import SearchResult, VectorStore


class MemorySearch:
    """Orchestrates the full memory search pipeline."""

    def __init__(
        self,
        exporter: DailyExporter,
        chunker: MarkdownChunker,
        store: VectorStore,
        embedding_model: str,
        daily_dir: Path,
    ):
        self._exporter = exporter
        self._chunker = chunker
        self._store = store
        self._embedding_model = embedding_model
        self._daily_dir = daily_dir

    async def initialize(self) -> None:
        """Initialize the vector store."""
        await self._store.initialize()
        logger.info("MemorySearch initialized")

    async def index_date(self, target_date: date) -> int:
        """Export and index a single date. Returns number of chunks indexed."""
        self._exporter.export_date(target_date)

        md_path = self._daily_dir / f"{target_date.isoformat()}.md"
        if not md_path.exists():
            return 0

        return await self._index_file(md_path)

    async def index_range(self, start: date, end: date) -> int:
        """Export and index a date range. Returns total chunks indexed."""
        self._exporter.export_range(start, end)

        total = 0
        for md_path in sorted(self._daily_dir.glob("*.md")):
            # Filter to requested range
            try:
                file_date = date.fromisoformat(md_path.stem)
            except ValueError:
                continue
            if file_date < start or file_date > end:
                continue
            total += await self._index_file(md_path)

        return total

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Semantic search across indexed memories."""
        query_embedding = await self._embed_texts([query])
        if not query_embedding:
            return []
        return await self._store.search(query_embedding[0], top_k=top_k)

    async def export_and_index_yesterday(self) -> int:
        """Convenience: export yesterday's log and index it."""
        from datetime import timedelta

        yesterday = date.today() - timedelta(days=1)
        return await self.index_date(yesterday)

    async def backfill(self) -> int:
        """Export and index all un-exported JSONL log files.

        Called on startup to cover days when the server was not running at midnight.
        """

        indexed_sources = await self._store.get_indexed_sources()
        log_dir = self._exporter._log.data_dir

        total = 0
        for jsonl_path in sorted(log_dir.glob("*.jsonl")):
            try:
                log_date = date.fromisoformat(jsonl_path.stem)
            except ValueError:
                continue
            # Skip today (still accumulating entries)
            if log_date >= date.today():
                continue
            md_name = f"{log_date.isoformat()}.md"
            if md_name in indexed_sources:
                continue
            count = await self.index_date(log_date)
            total += count

        if total:
            logger.info(f"Backfill completed: indexed {total} chunks")
        return total

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _index_file(self, md_path: Path) -> int:
        """Index a single markdown file with incremental upsert."""
        chunks = self._chunker.chunk_file(md_path, base_path=self._daily_dir)
        if not chunks:
            return 0

        source = str(md_path.relative_to(self._daily_dir))
        new_ids = {c.chunk_id for c in chunks}
        existing_ids = await self._store.get_chunk_ids_by_source(source)

        # Determine what's new / changed / stale
        to_add = [c for c in chunks if c.chunk_id not in existing_ids]
        stale_ids = existing_ids - new_ids

        # Remove stale chunks
        if stale_ids:
            await self._store.delete_by_source(source)
            # Re-add everything since we deleted by source
            to_add = chunks

        if not to_add:
            return 0

        # Embed new chunks
        texts = [c.content for c in to_add]
        embeddings = await self._embed_texts(texts)
        if not embeddings or len(embeddings) != len(to_add):
            logger.warning(f"Embedding mismatch for {md_path}")
            return 0

        # Build upsert data
        data = [
            {
                "chunk_id": chunk.chunk_id,
                "embedding": emb,
                "content": chunk.content,
                "source": chunk.source,
                "heading": chunk.heading,
                "heading_level": chunk.heading_level,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
            }
            for chunk, emb in zip(to_add, embeddings)
        ]

        count = await self._store.upsert(data)
        logger.info(f"Indexed {count} chunks from {md_path.name}")
        return count

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts via LiteLLM."""
        try:
            response = await litellm.aembedding(
                model=self._embedding_model,
                input=texts,
            )
            return [item["embedding"] for item in response.data]
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return []
