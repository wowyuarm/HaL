"""Episodic memory — records of meaningful interactions."""

from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel, Field


class InteractionTurn(BaseModel):
    """One turn in an interaction."""

    role: str  # "user" | "assistant" | "tool"
    content: str
    tool_name: str | None = None
    tool_result: str | None = None


class Episode(BaseModel):
    """Record of a single meaningful interaction."""

    id: str  # e.g. "EP-20260209-0001"
    timestamp: float  # Unix timestamp
    channel: str  # "telegram", "cli", "cron"
    duration_seconds: float = 0.0

    headline: str  # One-line summary
    summary: str = ""  # Compressed description
    user_request: str | None = None
    agent_response: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Full turns (only for recent episodes; cleared for old ones)
    turns: list[InteractionTurn] | None = None


class MemoryTrace(BaseModel):
    """Compressed impression of an older episode."""

    episode_id: str
    timestamp: float
    headline: str
    summary: str
    tools_used: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EpisodicMemory:
    """
    Manages episodic memory — interaction records stored as JSONL.

    Recent episodes retain full turns; older ones are compressed to traces.
    """

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._episodes_file = data_dir / "episodes.jsonl"
        self._counter = self._count_episodes()

    def _count_episodes(self) -> int:
        """Count existing episodes for ID generation."""
        if not self._episodes_file.exists():
            return 0
        count = 0
        for line in self._episodes_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                count += 1
        return count

    def _next_id(self) -> str:
        """Generate next episode ID."""
        self._counter += 1
        date_str = time.strftime("%Y%m%d")
        return f"EP-{date_str}-{self._counter:04d}"

    def record(
        self,
        channel: str,
        headline: str,
        user_request: str | None = None,
        agent_response: str | None = None,
        tools_used: list[str] | None = None,
        tags: list[str] | None = None,
        turns: list[InteractionTurn] | None = None,
        duration_seconds: float = 0.0,
        summary: str = "",
    ) -> Episode:
        """Record a new episode."""
        episode = Episode(
            id=self._next_id(),
            timestamp=time.time(),
            channel=channel,
            duration_seconds=duration_seconds,
            headline=headline,
            summary=summary or headline,
            user_request=user_request,
            agent_response=agent_response,
            tools_used=tools_used or [],
            tags=tags or [],
            turns=turns,
        )
        self._append(episode)
        return episode

    def get_recent(self, limit: int = 15) -> list[Episode]:
        """Get the most recent episodes."""
        all_eps = self._load_all()
        return all_eps[-limit:]

    def to_trace(self, episode: Episode) -> MemoryTrace:
        """Compress an episode to a memory trace (drop turns)."""
        return MemoryTrace(
            episode_id=episode.id,
            timestamp=episode.timestamp,
            headline=episode.headline,
            summary=episode.summary,
            tools_used=episode.tools_used,
            tags=episode.tags,
        )

    def _append(self, episode: Episode) -> None:
        """Append an episode to the JSONL file."""
        with self._episodes_file.open("a", encoding="utf-8") as f:
            f.write(episode.model_dump_json() + "\n")

    def _load_all(self) -> list[Episode]:
        """Load all episodes from JSONL."""
        if not self._episodes_file.exists():
            return []
        episodes = []
        for line in self._episodes_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                episodes.append(Episode.model_validate_json(line))
        return episodes
