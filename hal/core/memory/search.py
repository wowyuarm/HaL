"""Memory search orchestrator — coordinates indexing, embedding, and retrieval.

Primary pipeline (context system v2):
episodes/*.md -> chunks -> embeddings -> Milvus -> semantic search

Legacy daily-export indexing is retained for backward compatibility.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from pathlib import Path

import litellm
from loguru import logger

from hal.core.memory.chunker import compute_chunk_id
from hal.core.memory.contracts import MemorySearchDeps
from hal.core.memory.store import SearchResult
from hal.workspace import EpisodeRepository

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
_FETCH_K_MULTIPLIER = 5
_FETCH_K_BUFFER = 12
_FETCH_K_CAP = 40
_SUBAGENT_LITERAL_HIT_THRESHOLD = 2


class MemorySearch:
    """Orchestrates the full memory search pipeline."""

    def __init__(
        self,
        exporter: object | None = None,
        chunker: object | None = None,
        store: object | None = None,
        *,
        deps: MemorySearchDeps | None = None,
        embedding_model: str,
        source_root: Path | None = None,
        episodes_root: Path | None = None,
        daily_dir: Path | None = None,
        log_dir: Path | None = None,
        exclude_channels: list[str] | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        embedding_dim: int | None = None,
        embed_retry_attempts: int = _EMBED_RETRY_ATTEMPTS,
        embed_retry_base_delay_s: float = _EMBED_RETRY_BASE_DELAY_S,
        embed_timeout_s: float = 60.0,
    ):
        resolved = self._resolve_deps(
            deps=deps,
            exporter=exporter,
            chunker=chunker,
            store=store,
        )
        self._exporter = resolved.exporter
        self._chunker = resolved.chunker
        self._store = resolved.store
        self._embedding_model = embedding_model
        self._episodes_root = episodes_root
        self._daily_dir = daily_dir
        self._source_root = self._resolve_source_root(
            source_root=source_root,
            episodes_root=episodes_root,
            daily_dir=daily_dir,
        )
        self._log_dir = log_dir
        self._exclude_channels = {
            c.strip().lower() for c in (exclude_channels or []) if c and c.strip()
        }
        self._api_key = api_key
        self._api_base = api_base
        self._embedding_dim = embedding_dim
        self._embed_retry_attempts = embed_retry_attempts
        self._embed_retry_base_delay_s = embed_retry_base_delay_s
        self._embed_timeout_s = embed_timeout_s

    @staticmethod
    def _resolve_deps(
        *,
        deps: MemorySearchDeps | None,
        exporter: object | None,
        chunker: object | None,
        store: object | None,
    ) -> MemorySearchDeps:
        if deps is not None:
            return deps
        if chunker is None or store is None:
            raise ValueError(
                "MemorySearch requires either deps=MemorySearchDeps(...) or "
                "legacy chunker/store arguments."
            )
        return MemorySearchDeps(exporter=exporter, chunker=chunker, store=store)

    @staticmethod
    def _resolve_source_root(
        *,
        source_root: Path | None,
        episodes_root: Path | None,
        daily_dir: Path | None,
    ) -> Path:
        if source_root is not None:
            return source_root
        if episodes_root is not None:
            return episodes_root.parent
        if daily_dir is not None:
            return daily_dir
        raise ValueError("MemorySearch requires source_root, episodes_root, or daily_dir.")

    async def initialize(self) -> None:
        """Initialize the vector store."""
        await self._store.initialize()
        logger.info("MemorySearch initialized")

    async def index_date(self, target_date: date) -> int:
        """Legacy: export and index a single date. Returns chunks indexed."""
        if self._exporter is None or self._daily_dir is None:
            logger.warning("index_date skipped: legacy exporter/daily_dir not configured")
            return 0
        self._exporter.export_date(target_date)

        md_path = self._daily_dir / f"{target_date.isoformat()}.md"
        if not md_path.exists():
            return 0

        return await self._index_file(md_path)

    async def index_range(self, start: date, end: date) -> int:
        """Legacy: export and index a date range. Returns total chunks indexed."""
        if self._exporter is None or self._daily_dir is None:
            logger.warning("index_range skipped: legacy exporter/daily_dir not configured")
            return 0
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
        results = await self._search_candidates(
            query_embedding=query_embedding[0], keyword_query=keyword_query, top_k=top_k
        )
        results = self._filter_excluded_channels(results)
        results = self._rank_with_source_penalties(results, query_terms=query_terms)
        return self._slice_results(results, top_k=top_k, min_score=min_score)

    async def export_and_index_yesterday(self) -> int:
        """Legacy convenience: export yesterday's log and index it."""
        from datetime import timedelta

        yesterday = date.today() - timedelta(days=1)
        return await self.index_date(yesterday)

    async def index_episode(self, episode_path: Path) -> int:
        """Index one episode markdown file."""
        if not episode_path.exists():
            return 0
        return await self._index_file(episode_path)

    async def index_paths(self, paths: list[Path]) -> int:
        """Index a list of markdown paths (best-effort)."""
        total = 0
        for path in paths:
            if not path.exists():
                continue
            total += await self._index_file(path)
        return total

    async def backfill(self) -> int:
        """Backfill missing indexes from primary source (episodes by default)."""
        if self._episodes_root is not None:
            return await self._backfill_episodes()
        return await self._backfill_daily()

    async def _backfill_episodes(self) -> int:
        """Index all episode markdown files that are missing or out-of-date."""
        if not self._episodes_root.exists():
            return 0

        indexed_sources = await self._store.get_indexed_sources()
        total = 0
        episode_repository = EpisodeRepository(self._source_root)
        for md_path in episode_repository.collect_episode_paths():
            source_name = self._source_for_path(md_path)
            if not await self._needs_reindex(source_name, indexed_sources=indexed_sources):
                continue
            total += await self._index_file(md_path)

        if total:
            logger.info(f"Episode backfill completed: indexed {total} chunks")
        return total

    async def _backfill_daily(self) -> int:
        """Legacy: export and index un-exported daily JSONL log files."""
        if self._exporter is None or self._daily_dir is None:
            return 0
        log_dir = self._resolve_log_dir()
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

    def _resolve_log_dir(self) -> Path:
        """Resolve JSONL log directory for backfill date discovery."""
        if self._log_dir is not None:
            return self._log_dir

        # Backward compatibility for integrations that still pass DailyExporter only.
        exporter_log = getattr(self._exporter, "_log", None)
        exporter_data_dir = getattr(exporter_log, "data_dir", None)
        if isinstance(exporter_data_dir, Path):
            return exporter_data_dir

        logger.warning(
            "MemorySearch.log_dir not configured and exporter has no _log.data_dir; "
            "falling back to source_root for backfill scan"
        )
        return self._source_root

    def _source_for_path(self, md_path: Path) -> str:
        """Build deterministic source id from markdown path."""
        try:
            return str(md_path.relative_to(self._source_root))
        except ValueError:
            return md_path.name

    def _candidate_fetch_k(self, top_k: int) -> int:
        return min(max(top_k * _FETCH_K_MULTIPLIER, top_k + _FETCH_K_BUFFER), _FETCH_K_CAP)

    async def _search_candidates(
        self, *, query_embedding: list[float], keyword_query: str, top_k: int
    ) -> list[SearchResult]:
        return await self._store.search(
            query_embedding,
            query_text=keyword_query,
            top_k=self._candidate_fetch_k(top_k),
        )

    def _filter_excluded_channels(self, results: list[SearchResult]) -> list[SearchResult]:
        if not self._exclude_channels:
            return results
        return [
            result
            for result in results
            if _extract_channel_from_heading(result.heading) not in self._exclude_channels
        ]

    def _rank_with_source_penalties(
        self, results: list[SearchResult], *, query_terms: list[str]
    ) -> list[SearchResult]:
        # For subagent chunks, keep full score when multiple query terms match
        # literally — this avoids suppressing clearly relevant snippets.
        for result in results:
            hit_count = _count_literal_hits(f"{result.heading}\n{result.content}", query_terms)
            if result.source_type == "summary":
                result.score *= _SUMMARY_PENALTY
            elif result.source_type == "subagent" and hit_count < _SUBAGENT_LITERAL_HIT_THRESHOLD:
                result.score *= _SUBAGENT_PENALTY
        return sorted(results, key=lambda result: result.score, reverse=True)

    @staticmethod
    def _slice_results(
        results: list[SearchResult], *, top_k: int, min_score: float
    ) -> list[SearchResult]:
        if min_score > 0:
            results = [result for result in results if result.score >= min_score]
        return results[:top_k]

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
                "thread": _extract_thread_from_source(chunk.source),
            }
            for chunk, embedding in pairs
        ]

    async def _index_file(self, md_path: Path) -> int:
        """Index a single markdown file with incremental upsert."""
        chunks = self._chunker.chunk_file(md_path, base_path=self._source_root)
        chunks = self._filter_indexable_chunks(chunks)
        source = self._source_for_path(md_path)
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
        md_path = self._source_root / source_name
        if source_name not in indexed_sources:
            return True
        if not md_path.exists():
            return True

        expected = {
            self._chunk_id(c)
            for c in self._chunker.chunk_file(md_path, base_path=self._source_root)
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


def _extract_thread_from_source(source: str) -> str:
    """Infer thread slug from source path when source is an episode markdown."""
    parts = [part for part in source.split("/") if part]
    if not parts:
        return ""

    if "threads" in parts:
        idx = parts.index("threads")
        if idx + 1 < len(parts):
            return parts[idx + 1]

    if len(parts) >= 3 and parts[1] == "episodes":
        return parts[0]

    return ""
