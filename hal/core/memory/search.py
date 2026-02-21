"""Memory search orchestrator — coordinates export, chunking, embedding, and retrieval.

Provides a high-level interface for the memory search pipeline:
JSONL → Markdown → Chunks → Embeddings → Milvus → Semantic Search
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import litellm
from loguru import logger

from hal.core.memory.chunker import MarkdownChunker, compute_chunk_id
from hal.core.memory.exporter import DailyExporter
from hal.core.memory.store import SearchResult, VectorStore

# Score multiplier applied to summary chunks during retrieval.
# Demotes summaries so raw conversation chunks are preferred (raw-first strategy).
_SUMMARY_PENALTY = 0.75
# Score multiplier for subagent injection chunks (derived data, not raw dialog).
# Lower than summary — subagent output is further from user intent and typically
# denser, so it needs stronger demotion to avoid crowding out raw conversation.
_SUBAGENT_PENALTY = 0.70


class MemorySearch:
    """Orchestrates the full memory search pipeline."""

    def __init__(
        self,
        exporter: DailyExporter,
        chunker: MarkdownChunker,
        store: VectorStore,
        embedding_model: str,
        daily_dir: Path,
        api_key: str | None = None,
        api_base: str | None = None,
        embedding_dim: int | None = None,
    ):
        self._exporter = exporter
        self._chunker = chunker
        self._store = store
        self._embedding_model = embedding_model
        self._daily_dir = daily_dir
        self._api_key = api_key
        self._api_base = api_base
        self._embedding_dim = embedding_dim

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

    async def search(
        self, query: str, top_k: int = 5, min_score: float = 0.0
    ) -> list[SearchResult]:
        """Hybrid search (semantic + keyword) across indexed memories.

        Applies source-type penalties so raw conversation chunks are preferred
        when scores are close (raw-first strategy).
        """
        query_embedding = await self._embed_texts([query])
        if not query_embedding:
            return []

        # Fetch extra candidates to compensate for penalty reranking
        fetch_k = min(top_k * 2, top_k + 5)
        results = await self._store.search(query_embedding[0], query_text=query, top_k=fetch_k)

        # Apply source-type penalties and re-rank
        for r in results:
            if r.source_type == "summary":
                r.score *= _SUMMARY_PENALTY
            elif r.source_type == "subagent":
                r.score *= _SUBAGENT_PENALTY
        results.sort(key=lambda r: r.score, reverse=True)
        if min_score > 0:
            results = [r for r in results if r.score >= min_score]
        return results[:top_k]

    async def export_and_index_yesterday(self) -> int:
        """Convenience: export yesterday's log and index it."""
        from datetime import timedelta

        yesterday = date.today() - timedelta(days=1)
        return await self.index_date(yesterday)

    async def backfill(self) -> int:
        """Export and index all un-exported JSONL log files.

        Called on startup to cover days when the server was not running at midnight.
        Compares exported markdown files against indexed sources to find gaps.
        """
        log_dir = self._exporter._log.data_dir
        if not log_dir.exists():
            return 0

        # Collect dates that have JSONL but are not yet indexed.
        # We check by looking at the markdown output dir + the vector store:
        # a date needs indexing if its markdown file does not exist yet, OR
        # if it exists but has no chunks in the store.
        indexed_sources = await self._store.get_indexed_sources()

        total = 0
        for jsonl_path in sorted(log_dir.glob("*.jsonl")):
            try:
                log_date = date.fromisoformat(jsonl_path.stem)
            except ValueError:
                continue
            # Skip today (still accumulating entries)
            if log_date >= date.today():
                continue

            source_name = f"{log_date.isoformat()}.md"
            if source_name in indexed_sources:
                continue

            count = await self.index_date(log_date)
            total += count

        if total:
            logger.info(f"Backfill completed: indexed {total} chunks")
        return total

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _chunk_id(self, chunk) -> str:
        """Compute model-aware chunk ID."""
        return compute_chunk_id(chunk, self._embedding_model)

    async def _index_file(self, md_path: Path) -> int:
        """Index a single markdown file with incremental upsert."""
        chunks = self._chunker.chunk_file(md_path, base_path=self._daily_dir)
        if not chunks:
            return 0

        source = str(md_path.relative_to(self._daily_dir))
        new_ids = {self._chunk_id(c) for c in chunks}
        existing_ids = await self._store.get_chunk_ids_by_source(source)

        # Determine what's new / changed / stale
        to_add = [c for c in chunks if self._chunk_id(c) not in existing_ids]
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
                "chunk_id": self._chunk_id(chunk),
                "embedding": emb,
                "content": chunk.content,
                "source": chunk.source,
                "heading": chunk.heading,
                "heading_level": chunk.heading_level,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "source_type": chunk.source_type,
            }
            for chunk, emb in zip(to_add, embeddings)
        ]

        count = await self._store.upsert(data)
        logger.info(f"Indexed {count} chunks from {md_path.name}")
        return count

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings via direct HTTP call or LiteLLM fallback."""
        try:
            if self._api_base and self._api_key:
                return await self._embed_texts_direct(texts)
            return await self._embed_texts_litellm(texts)
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return []

    async def _embed_texts_direct(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI-compatible embedding endpoint directly.

        Bypasses LiteLLM's parameter validation which incorrectly blocks
        the 'dimensions' param for custom OpenAI-compatible providers.
        """
        import httpx

        # Strip litellm routing prefix (e.g. "openai/") to get raw model name
        model = self._embedding_model
        if "/" in model:
            parts = model.split("/", 1)
            # Only strip known litellm prefixes, not model namespace slashes
            if parts[0] in ("openai", "azure", "bedrock"):
                model = parts[1]

        body: dict = {"model": model, "input": texts}
        if self._embedding_dim:
            body["dimensions"] = self._embedding_dim

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._api_base.rstrip('/')}/embeddings",
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def _embed_texts_litellm(self, texts: list[str]) -> list[list[float]]:
        """Fallback: call embedding via LiteLLM (for standard providers)."""
        kwargs: dict = {
            "model": self._embedding_model,
            "input": texts,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._embedding_dim:
            kwargs["dimensions"] = self._embedding_dim

        response = await litellm.aembedding(**kwargs)
        return [item["embedding"] for item in response.data]
