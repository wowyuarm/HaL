"""Milvus Lite vector store for memory search.

Wraps pymilvus MilvusClient (synchronous) with async wrappers via
asyncio.to_thread() to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger


@dataclass
class SearchResult:
    """A single search result from the vector store."""

    content: str
    source: str
    heading: str
    score: float


class VectorStore:
    """Async wrapper around Milvus Lite for chunk storage and retrieval."""

    def __init__(self, uri: str, collection_name: str, embedding_dim: int):
        self._uri = uri
        self._collection_name = collection_name
        self._embedding_dim = embedding_dim
        self._client = None

    async def initialize(self) -> None:
        """Create Milvus client and ensure collection exists."""
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        from pathlib import Path

        from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

        # Ensure parent directory exists
        uri_path = Path(self._uri).expanduser()
        uri_path.parent.mkdir(parents=True, exist_ok=True)

        self._client = MilvusClient(uri=str(uri_path))

        if self._client.has_collection(self._collection_name):
            return

        fields = [
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=self._embedding_dim,
            ),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="heading", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="heading_level", dtype=DataType.INT16),
            FieldSchema(name="start_line", dtype=DataType.INT32),
            FieldSchema(name="end_line", dtype=DataType.INT32),
        ]
        schema = CollectionSchema(fields=fields)

        self._client.create_collection(
            collection_name=self._collection_name,
            schema=schema,
        )

        # Create vector index
        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="FLAT",
            metric_type="COSINE",
        )
        self._client.create_index(
            collection_name=self._collection_name,
            index_params=index_params,
        )

        logger.info(f"Created Milvus collection '{self._collection_name}'")

    async def upsert(self, chunks: list[dict]) -> int:
        """Upsert chunk data. Each dict must have chunk_id, embedding, content, etc."""
        if not chunks:
            return 0
        result = await asyncio.to_thread(
            self._client.upsert,
            collection_name=self._collection_name,
            data=chunks,
        )
        return result.get("upsert_count", len(chunks)) if isinstance(result, dict) else len(chunks)

    async def search(self, query_embedding: list[float], top_k: int = 5) -> list[SearchResult]:
        """Search for similar chunks by embedding vector."""
        raw = await asyncio.to_thread(
            self._client.search,
            collection_name=self._collection_name,
            data=[query_embedding],
            limit=top_k,
            output_fields=["content", "source", "heading"],
            anns_field="embedding",
        )

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
                    )
                )
        return results

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
            self._client = None
