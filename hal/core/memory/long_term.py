"""Compatibility wrapper for workspace-backed MEMORY.md access."""

from hal.workspace.memory import MemoryRepository

LongTermMemory = MemoryRepository

__all__ = ["LongTermMemory", "MemoryRepository"]
