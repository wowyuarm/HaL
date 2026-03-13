"""Memory subsystem."""

from hal.memory.manager import MemoryManager
from hal.workspace.memory import MemoryRepository

__all__ = [
    "MemoryManager",
    "MemoryRepository",
]

# Optional: available when memory search deps are installed
try:
    from hal.memory.chunker import Chunk, MarkdownChunker, compute_chunk_id
    from hal.memory.search import MemorySearch
    from hal.memory.store import SearchResult, VectorStore

    __all__ += [
        "Chunk",
        "compute_chunk_id",
        "MarkdownChunker",
        "MemorySearch",
        "SearchResult",
        "VectorStore",
    ]
except Exception:
    # Optional memory-search stack should not break base memory imports.
    pass
