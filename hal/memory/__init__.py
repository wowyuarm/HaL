"""Memory subsystem."""

from hal.memory.daily_log import DailyLog, LogEntry
from hal.memory.event_log import EventEntry, EventLog
from hal.memory.long_term import LongTermMemory
from hal.memory.manager import MemoryManager

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
    from hal.memory.chunker import Chunk, MarkdownChunker, compute_chunk_id
    from hal.memory.exporter import DailyExporter
    from hal.memory.search import MemorySearch
    from hal.memory.store import SearchResult, VectorStore

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
