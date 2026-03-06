"""Memory subsystem."""

from hal.core.memory.daily_log import DailyLog, LogEntry
from hal.core.memory.event_log import EventEntry, EventLog
from hal.core.memory.long_term import LongTermMemory
from hal.core.memory.manager import MemoryManager

__all__ = [
    "DailyLog",
    "EventEntry",
    "EventLog",
    "LogEntry",
    "LongTermMemory",
    "MemoryManager",
]

# Optional: available when memory search deps are installed
try:
    from hal.core.memory.chunker import Chunk, MarkdownChunker, compute_chunk_id
    from hal.core.memory.exporter import DailyExporter
    from hal.core.memory.search import MemorySearch
    from hal.core.memory.store import SearchResult, VectorStore

    __all__ += [
        "Chunk",
        "compute_chunk_id",
        "DailyExporter",
        "MarkdownChunker",
        "MemorySearch",
        "SearchResult",
        "VectorStore",
    ]
except Exception:
    # Optional memory-search stack should not break base memory imports.
    # Some third-party dependency failures are raised as non-ImportError.
    pass
