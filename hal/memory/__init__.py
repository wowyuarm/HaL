"""System memory and recall-index helpers."""

from hal.workspace.memory import SystemMemoryRepository

__all__ = [
    "SystemMemoryRepository",
]

# Optional: available when recall deps are installed
try:
    from hal.memory.chunker import Chunk, MarkdownChunker, compute_chunk_id
    from hal.memory.search import EpisodeRecallIndex
    from hal.memory.store import SearchResult, VectorStore

    __all__ += [
        "Chunk",
        "compute_chunk_id",
        "EpisodeRecallIndex",
        "MarkdownChunker",
        "SearchResult",
        "VectorStore",
    ]
except Exception:
    # Optional recall stack should not break base memory imports.
    pass
