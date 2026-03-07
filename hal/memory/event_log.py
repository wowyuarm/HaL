"""Compatibility wrapper for workspace-backed session event logging."""

from hal.workspace.events import EventEntry, EventLogRepository

EventLog = EventLogRepository

__all__ = ["EventEntry", "EventLog", "EventLogRepository"]
