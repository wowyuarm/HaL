"""Shared contracts for memory-search integration points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from hal.memory.store import SearchResult


class MemoryChunkerPort(Protocol):
    def chunk_file(self, md_path: Path, base_path: Path) -> list[Any]: ...


class MemoryStorePort(Protocol):
    async def initialize(self) -> None: ...

    async def upsert(self, chunks: list[dict[str, Any]]) -> int: ...

    async def search(
        self, query_embedding: list[float], *, query_text: str = "", top_k: int = 5
    ) -> list[SearchResult]: ...

    async def delete_by_source(self, source: str) -> Any: ...

    async def get_chunk_ids_by_source(self, source: str) -> set[str]: ...

    async def get_indexed_sources(self) -> set[str]: ...


@dataclass(slots=True, frozen=True)
class MemorySearchDeps:
    """Dependency bundle for memory-search orchestration."""

    chunker: MemoryChunkerPort
    store: MemoryStorePort


class MemorySearchPort(Protocol):
    async def search(self, query: str, top_k: int = 3) -> list[SearchResult]: ...
