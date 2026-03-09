"""Milvus Lite vector store for memory search.

Wraps pymilvus MilvusClient (synchronous) with async wrappers via
asyncio.to_thread() to avoid blocking the event loop.

Uses hybrid search (dense cosine + BM25 keyword) with Reciprocal Rank
Fusion (RRF) to combine semantic and keyword relevance.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pymilvus import MilvusClient


@dataclass
class SearchResult:
    """A single search result from the vector store."""

    content: str
    source: str
    heading: str
    score: float
    source_type: str = "raw"  # "raw" | "summary" | "subagent"
    thread: str = ""


_OUTPUT_FIELDS = ["content", "source", "heading", "source_type", "thread"]


class VectorStore:
    """Async wrapper around Milvus Lite for chunk storage and hybrid retrieval."""

    def __init__(self, uri: str, collection_name: str, embedding_dim: int):
        self._uri = uri
        self._collection_name = collection_name
        self._embedding_dim = embedding_dim
        self._client: MilvusClient | None = None

    async def initialize(self) -> None:
        """Create Milvus client and ensure collection exists."""
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        from pathlib import Path

        from pymilvus import DataType, Function, FunctionType, MilvusClient

        # Ensure parent directory exists
        uri_path = Path(self._uri).expanduser()
        uri_path.parent.mkdir(parents=True, exist_ok=True)

        self._client = MilvusClient(uri=str(uri_path))

        if self._client.has_collection(self._collection_name):
            # Migrate: drop collection when required metadata fields are missing.
            try:
                info = self._client.describe_collection(self._collection_name)
                field_names = {f["name"] for f in info.get("fields", [])}
            except Exception as e:
                logger.warning(f"Failed to describe collection, will recreate: {e}")
                field_names = set()

            if "source_type" not in field_names or "thread" not in field_names:
                logger.info(
                    f"Migrating collection '{self._collection_name}': "
                    "adding required metadata fields (drop + recreate)"
                )
                try:
                    self._client.drop_collection(self._collection_name)
                except Exception as e:
                    logger.warning(f"Failed to drop collection during migration: {e}")
            else:
                return

        schema = self._client.create_schema()
        schema.add_field(
            field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64, is_primary=True
        )
        schema.add_field(
            field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=self._embedding_dim
        )
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=65535,
            enable_analyzer=True,
        )
        schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="heading", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="thread", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="heading_level", datatype=DataType.INT16)
        schema.add_field(field_name="start_line", datatype=DataType.INT32)
        schema.add_field(field_name="end_line", datatype=DataType.INT32)
        schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=32)

        # BM25 auto-generates sparse_vector from content
        schema.add_function(
            Function(
                name="bm25_fn",
                function_type=FunctionType.BM25,
                input_field_names=["content"],
                output_field_names=["sparse_vector"],
            )
        )

        # Dense + sparse indexes
        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="embedding", index_type="FLAT", metric_type="COSINE")
        index_params.add_index(
            field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"
        )

        self._client.create_collection(
            collection_name=self._collection_name,
            schema=schema,
            index_params=index_params,
        )

        logger.info(f"Created Milvus collection '{self._collection_name}' (hybrid search)")

    async def upsert(self, chunks: list[dict]) -> int:
        """Upsert chunk data. sparse_vector is auto-generated from content."""
        if not chunks:
            return 0
        result = await asyncio.to_thread(
            self._client.upsert,
            collection_name=self._collection_name,
            data=chunks,
        )
        return result.get("upsert_count", len(chunks)) if isinstance(result, dict) else len(chunks)

    @property
    def is_ready(self) -> bool:
        """Whether the store has been initialized and is ready for queries."""
        return self._client is not None

    async def search(
        self, query_embedding: list[float], *, query_text: str = "", top_k: int = 5
    ) -> list[SearchResult]:
        """Hybrid search: dense cosine + BM25 keyword with RRF reranking.

        Falls back to dense-only search if BM25 produces invalid values
        (known Milvus Lite issue with small collections).
        Returns empty list if the store has not been initialized yet.
        """
        if not self.is_ready:
            logger.debug("VectorStore not yet initialized, skipping search")
            return []

        try:
            raw = await asyncio.to_thread(
                self._hybrid_search_sync, query_embedding, query_text, top_k
            )
        except Exception as e:
            if "NaN" in str(e) or "Inf" in str(e) or "isfinite" in str(e):
                logger.debug(f"Hybrid search failed ({e}), falling back to dense-only")
                raw = await asyncio.to_thread(self._dense_search_sync, query_embedding, top_k)
            else:
                raise

        results: list[SearchResult] = []
        if raw and raw[0]:
            for hit in raw[0]:
                entity = hit.get("entity", {})
                results.append(
                    SearchResult(
                        content=entity.get("content", ""),
                        source=entity.get("source", ""),
                        heading=entity.get("heading", ""),
                        score=hit.get("distance", 0.0),
                        source_type=entity.get("source_type", "raw"),
                        thread=entity.get("thread", ""),
                    )
                )
        return results

    def _hybrid_search_sync(
        self, query_embedding: list[float], query_text: str, top_k: int
    ) -> list:
        from pymilvus import AnnSearchRequest, RRFRanker

        dense_req = AnnSearchRequest(
            data=[query_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
        )

        bm25_req = AnnSearchRequest(
            data=[query_text] if query_text else [""],
            anns_field="sparse_vector",
            param={"metric_type": "BM25"},
            limit=top_k,
        )

        return self._client.hybrid_search(
            collection_name=self._collection_name,
            reqs=[dense_req, bm25_req],
            ranker=RRFRanker(k=60),
            limit=top_k,
            output_fields=_OUTPUT_FIELDS,
        )

    def _dense_search_sync(self, query_embedding: list[float], top_k: int) -> list:
        """Dense-only cosine search (fallback when BM25 fails)."""
        return self._client.search(
            collection_name=self._collection_name,
            data=[query_embedding],
            anns_field="embedding",
            search_params={"metric_type": "COSINE"},
            limit=top_k,
            output_fields=_OUTPUT_FIELDS,
        )

    async def delete_by_source(self, source: str) -> int:
        """Delete all chunks from a given source file."""
        result = await asyncio.to_thread(
            self._client.delete,
            collection_name=self._collection_name,
            filter=f'source == "{source}"',
        )
        return result if isinstance(result, int) else 0

    async def get_chunk_ids_by_source(self, source: str) -> set[str]:
        """Get all chunk IDs for a given source."""
        raw = await asyncio.to_thread(
            self._client.query,
            collection_name=self._collection_name,
            filter=f'source == "{source}"',
            output_fields=["chunk_id"],
        )
        return {r["chunk_id"] for r in raw} if raw else set()

    async def get_indexed_sources(self) -> set[str]:
        """Get all distinct source values currently indexed."""
        raw = await asyncio.to_thread(
            self._client.query,
            collection_name=self._collection_name,
            filter="chunk_id != ''",
            output_fields=["source"],
        )
        return {r["source"] for r in raw} if raw else set()

    async def close(self) -> None:
        """Close the Milvus client."""
        if self._client:
            await asyncio.to_thread(self._client.close)
            self._client = None  # noqa: PYI026
