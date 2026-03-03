"""Memory search orchestrator — coordinates export, chunking, embedding, and retrieval.

Provides a high-level interface for the memory search pipeline:
JSONL → Markdown → Chunks → Embeddings → Milvus → Semantic Search
"""

from __future__ import annotations

import asyncio
import re
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
_EMBED_RETRY_ATTEMPTS = 3
_EMBED_RETRY_BASE_DELAY_S = 0.5
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")


class MemorySearch:
    """Orchestrates the full memory search pipeline."""

    def __init__(
        self,
        exporter: DailyExporter,
        chunker: MarkdownChunker,
        store: VectorStore,
        embedding_model: str,
        daily_dir: Path,
        exclude_channels: list[str] | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        embedding_dim: int | None = None,
        embed_retry_attempts: int = _EMBED_RETRY_ATTEMPTS,
        embed_retry_base_delay_s: float = _EMBED_RETRY_BASE_DELAY_S,
        embed_timeout_s: float = 60.0,
    ):
        self._exporter = exporter
        self._chunker = chunker
        self._store = store
        self._embedding_model = embedding_model
        self._daily_dir = daily_dir
        self._exclude_channels = {
            c.strip().lower() for c in (exclude_channels or []) if c and c.strip()
        }
        self._api_key = api_key
        self._api_base = api_base
        self._embedding_dim = embedding_dim
        self._embed_retry_attempts = embed_retry_attempts
        self._embed_retry_base_delay_s = embed_retry_base_delay_s
        self._embed_timeout_s = embed_timeout_s

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

        # Expand keyword query text for BM25 (e.g. dev_workflow/dev-workflow variants)
        # and fetch a wider candidate pool for reranking.
        query_terms = _build_keyword_terms(query)
        keyword_query = _build_keyword_query(query, query_terms)
        fetch_k = min(max(top_k * 5, top_k + 12), 40)
        results = await self._store.search(
            query_embedding[0],
            query_text=keyword_query,
            top_k=fetch_k,
        )

        if self._exclude_channels:
            results = [
                r
                for r in results
                if _extract_channel_from_heading(r.heading) not in self._exclude_channels
            ]

        # Apply source-type penalties and re-rank.
        # For subagent chunks, keep full score when multiple query terms match
        # literally — this avoids suppressing clearly relevant snippets.
        for r in results:
            hit_count = _count_literal_hits(f"{r.heading}\n{r.content}", query_terms)
            if r.source_type == "summary":
                r.score *= _SUMMARY_PENALTY
            elif r.source_type == "subagent" and hit_count < 2:
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
        Compares exported markdown files against indexed chunk IDs to find gaps.
        """
        log_dir = self._exporter._log.data_dir
        if not log_dir.exists():
            return 0

        # Collect dates that have JSONL but are not yet fully indexed.
        # A date needs indexing when:
        # 1) its source markdown isn't present in the vector store, OR
        # 2) its indexed chunk IDs differ from the chunk IDs computed from markdown.
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
            if not await self._needs_reindex(source_name, indexed_sources=indexed_sources):
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

    def _filter_indexable_chunks(self, chunks: list) -> list:
        """Apply channel exclusion filter to chunk list."""
        if not self._exclude_channels:
            return chunks
        return [
            chunk
            for chunk in chunks
            if _extract_channel_from_heading(chunk.heading) not in self._exclude_channels
        ]

    async def _clear_source_if_present(self, source: str) -> None:
        """Delete a source from index when it has no indexable chunks."""
        existing_ids = await self._store.get_chunk_ids_by_source(source)
        if existing_ids:
            await self._store.delete_by_source(source)

    async def _compute_chunks_to_add(self, source: str, chunks: list) -> list:
        """Return chunks that require (re)embedding and upsert for a source."""
        new_ids = {self._chunk_id(chunk) for chunk in chunks}
        existing_ids = await self._store.get_chunk_ids_by_source(source)

        to_add = [chunk for chunk in chunks if self._chunk_id(chunk) not in existing_ids]
        stale_ids = existing_ids - new_ids
        if stale_ids:
            await self._store.delete_by_source(source)
            return chunks
        return to_add

    async def _embed_chunks_with_fallback(self, md_path: Path, chunks: list) -> list[tuple]:
        """Embed chunks in batch, then retry per-chunk when batch output mismatches."""
        texts = [chunk.content for chunk in chunks]
        embeddings = await self._embed_texts(texts)
        if embeddings and len(embeddings) == len(chunks):
            return list(zip(chunks, embeddings))

        logger.warning(
            f"Embedding mismatch for {md_path} "
            f"(expected {len(chunks)}, got {len(embeddings) if embeddings else 0}); "
            "falling back to per-chunk retries"
        )
        return await self._embed_chunks_individually(md_path, chunks)

    async def _embed_chunks_individually(self, md_path: Path, chunks: list) -> list[tuple]:
        """Embed each chunk separately to salvage partial indexing on failures."""
        pairs: list[tuple] = []
        for chunk in chunks:
            one = await self._embed_texts([chunk.content])
            if len(one) == 1:
                pairs.append((chunk, one[0]))
                continue
            logger.warning(
                f"Skipping chunk after retries: {chunk.source}:{chunk.start_line}-{chunk.end_line}"
            )

        if not pairs:
            return []
        if len(pairs) < len(chunks):
            logger.warning(
                f"Partial indexing for {md_path.name}: "
                f"{len(pairs)}/{len(chunks)} chunks embedded successfully"
            )
        return pairs

    def _build_upsert_payload(self, pairs: list[tuple]) -> list[dict]:
        """Build vector-store payload for chunk/embedding pairs."""
        return [
            {
                "chunk_id": self._chunk_id(chunk),
                "embedding": embedding,
                "content": chunk.content,
                "source": chunk.source,
                "heading": chunk.heading,
                "heading_level": chunk.heading_level,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "source_type": chunk.source_type,
            }
            for chunk, embedding in pairs
        ]

    async def _index_file(self, md_path: Path) -> int:
        """Index a single markdown file with incremental upsert."""
        chunks = self._chunker.chunk_file(md_path, base_path=self._daily_dir)
        chunks = self._filter_indexable_chunks(chunks)
        source = str(md_path.relative_to(self._daily_dir))
        if not chunks:
            # Source now fully excluded (or empty): clear any previously indexed chunks
            # so backfill/index checks do not keep flagging this file for reindex.
            await self._clear_source_if_present(source)
            return 0

        to_add = await self._compute_chunks_to_add(source, chunks)
        if not to_add:
            return 0

        pairs = await self._embed_chunks_with_fallback(md_path, to_add)
        if not pairs:
            return 0

        data = self._build_upsert_payload(pairs)
        count = await self._store.upsert(data)
        logger.info(f"Indexed {count} chunks from {md_path.name}")
        return count

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings with retry via direct HTTP call or LiteLLM fallback."""
        if not texts:
            return []

        for attempt in range(1, self._embed_retry_attempts + 1):
            try:
                if self._api_base and self._api_key:
                    return await self._embed_texts_direct(texts)
                return await self._embed_texts_litellm(texts)
            except Exception as e:
                if attempt >= self._embed_retry_attempts:
                    logger.error(
                        f"Embedding failed after {self._embed_retry_attempts} attempts: {e}"
                    )
                    return []

                delay = self._embed_retry_base_delay_s * (2 ** (attempt - 1))
                logger.warning(
                    f"Embedding attempt {attempt}/{self._embed_retry_attempts} failed: {e}; "
                    f"retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)

        return []

    async def _needs_reindex(self, source_name: str, *, indexed_sources: set[str]) -> bool:
        """Whether a source needs (re)indexing based on current chunk IDs."""
        md_path = self._daily_dir / source_name
        if source_name not in indexed_sources:
            return True
        if not md_path.exists():
            return True

        expected = {
            self._chunk_id(c)
            for c in self._chunker.chunk_file(md_path, base_path=self._daily_dir)
            if _extract_channel_from_heading(c.heading) not in self._exclude_channels
        }
        existing = await self._store.get_chunk_ids_by_source(source_name)
        return expected != existing

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

        async with httpx.AsyncClient(timeout=self._embed_timeout_s) as client:
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
            "timeout": self._embed_timeout_s,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._embedding_dim:
            kwargs["dimensions"] = self._embedding_dim

        response = await litellm.aembedding(**kwargs)
        return [item["embedding"] for item in response.data]


def _extract_channel_from_heading(heading: str) -> str | None:
    """Extract channel from exporter heading format: '<channel> / <chat_id>'."""
    if not heading or "/" not in heading:
        return None
    channel = heading.split("/", 1)[0].strip().lower()
    return channel or None


def _build_keyword_terms(query: str) -> list[str]:
    """Extract strong ASCII terms and separator variants for literal matching/BM25."""
    q = query.lower()
    terms: list[str] = []
    seen: set[str] = set()

    for tok in _ASCII_TOKEN_RE.findall(q):
        candidates: set[str] = {tok}
        if "_" in tok:
            candidates.add(tok.replace("_", "-"))
            candidates.add(tok.replace("_", " "))
        if "-" in tok:
            candidates.add(tok.replace("-", "_"))
            candidates.add(tok.replace("-", " "))

        parts = [p for p in re.split(r"[_-]+", tok) if len(p) >= 4]
        candidates.update(parts)

        for c in candidates:
            c_norm = re.sub(r"\s+", " ", c).strip()
            if len(c_norm) < 4 or c_norm in seen:
                continue
            seen.add(c_norm)
            terms.append(c_norm)

    return terms


def _build_keyword_query(query: str, terms: list[str]) -> str:
    """Build BM25 query text from original query + normalized term variants."""
    parts: list[str] = [query.strip()]
    parts.extend(terms)
    combined = " ".join(p for p in parts if p)
    return combined[:512]


def _count_literal_hits(text: str, terms: list[str]) -> int:
    """Count literal term hits with separator-normalized matching."""
    if not terms:
        return 0
    raw = text.lower()
    normalized = re.sub(r"[_-]+", " ", raw)
    normalized = re.sub(r"\s+", " ", normalized)
    hits = 0
    for t in terms:
        if t in raw or t in normalized:
            hits += 1
    return hits
