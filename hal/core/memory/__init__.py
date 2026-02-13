"""Memory subsystem."""

from hal.core.memory.daily_log import DailyLog, LogEntry
from hal.core.memory.long_term import LongTermMemory
from hal.core.memory.manager import MemoryManager

__all__ = [
    "DailyLog",
    "LogEntry",
    "LongTermMemory",
    "MemoryManager",
]

# Optional: available when memory search deps are installed
try:
    from hal.core.memory.chunker import Chunk, MarkdownChunker
    from hal.core.memory.exporter import DailyExporter
    from hal.core.memory.search import MemorySearch
    from hal.core.memory.store import SearchResult, VectorStore

    __all__ += [
        "Chunk",
        "DailyExporter",
        "MarkdownChunker",
        "MemorySearch",
        "SearchResult",
        "VectorStore",
    ]
except ImportError:
    pass
