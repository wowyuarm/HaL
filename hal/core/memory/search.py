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
        pairs: list[tuple] = []
        if embeddings and len(embeddings) == len(to_add):
            pairs = list(zip(to_add, embeddings))
        else:
            logger.warning(
                f"Embedding mismatch for {md_path} "
                f"(expected {len(to_add)}, got {len(embeddings) if embeddings else 0}); "
                "falling back to per-chunk retries"
            )
            for chunk in to_add:
                one = await self._embed_texts([chunk.content])
                if len(one) == 1:
                    pairs.append((chunk, one[0]))
                else:
                    logger.warning(
                        f"Skipping chunk after retries: {chunk.source}:{chunk.start_line}-{chunk.end_line}"
                    )
            if not pairs:
                return 0
            if len(pairs) < len(to_add):
                logger.warning(
                    f"Partial indexing for {md_path.name}: "
                    f"{len(pairs)}/{len(to_add)} chunks embedded successfully"
                )

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
            for chunk, emb in pairs
        ]

        count = await self._store.upsert(data)
        logger.info(f"Indexed {count} chunks from {md_path.name}")
        return count

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings with retry via direct HTTP call or LiteLLM fallback."""
        if not texts:
            return []

        for attempt in range(1, _EMBED_RETRY_ATTEMPTS + 1):
            try:
                if self._api_base and self._api_key:
                    return await self._embed_texts_direct(texts)
                return await self._embed_texts_litellm(texts)
            except Exception as e:
                if attempt >= _EMBED_RETRY_ATTEMPTS:
                    logger.error(f"Embedding failed after {_EMBED_RETRY_ATTEMPTS} attempts: {e}")
                    return []

                delay = _EMBED_RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
                logger.warning(
                    f"Embedding attempt {attempt}/{_EMBED_RETRY_ATTEMPTS} failed: {e}; "
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

        expected = {self._chunk_id(c) for c in self._chunker.chunk_file(md_path, base_path=self._daily_dir)}
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
