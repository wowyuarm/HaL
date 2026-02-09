"""Unified memory manager coordinating all memory subsystems."""

from __future__ import annotations

import time
from pathlib import Path

from hal.core.memory.episodic import Episode, EpisodicMemory, InteractionTurn


class MemoryManager:
    """
    Central coordinator for all memory subsystems.

    Provides a unified interface for:
    - Recording interactions (episodic)
    - Reading/writing persistent knowledge (long-term)
    - Assembling memory context for prompt injection
    """

    def __init__(self, workspace: Path, data_dir: Path | None = None):
        from hal.core.memory.long_term import LongTermMemory

        memory_dir = workspace / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        self.long_term = LongTermMemory(memory_dir / "MEMORY.md")

        # Episodic memory stored in data_dir (outside workspace)
        ep_dir = (data_dir or workspace) / "episodes"
        self.episodic = EpisodicMemory(ep_dir)

    def record_interaction(
        self,
        channel: str,
        user_request: str | None = None,
        agent_response: str | None = None,
        tools_used: list[str] | None = None,
        turns: list[InteractionTurn] | None = None,
        duration_seconds: float = 0.0,
    ) -> Episode:
        """Record a completed interaction as an episode."""
        # Auto-generate headline from user request
        headline = ""
        if user_request:
            headline = user_request[:80]
            if len(user_request) > 80:
                headline += "..."
        else:
            headline = "Background task"

        return self.episodic.record(
            channel=channel,
            headline=headline,
            user_request=user_request,
            agent_response=agent_response,
            tools_used=tools_used or [],
            turns=turns,
            duration_seconds=duration_seconds,
        )

    def get_context(self, budget: int | None = None) -> str:
        """
        Assemble memory context for prompt injection.

        Args:
            budget: Approximate token limit for memory section (not yet enforced).
        """
        sections = []

        # Long-term memory
        lt = self.long_term.read()
        if lt:
            sections.append(f"## Long-term Memory\n\n{lt}")

        # Recent episodes
        recent = self.episodic.get_recent(limit=15)
        if recent:
            sections.append(self._format_episodes(recent))

        return "\n\n".join(sections)

    def _format_episodes(self, episodes: list[Episode]) -> str:
        """Format episodes with two-tier detail level."""
        lines = ["## Recent Interactions\n"]

        # Split: last 5 = detailed, older = traces
        detailed = episodes[-5:]
        older = episodes[:-5] if len(episodes) > 5 else []

        if older:
            lines.append("### Earlier\n")
            for ep in older:
                trace = self.episodic.to_trace(ep)
                ts = time.strftime("%m-%d %H:%M", time.localtime(trace.timestamp))
                tools = f" [{', '.join(trace.tools_used)}]" if trace.tools_used else ""
                lines.append(f"- `{ts}` {trace.headline}{tools}")
            lines.append("")

        if detailed:
            lines.append("### Recent\n")
            for ep in detailed:
                ts = time.strftime("%m-%d %H:%M", time.localtime(ep.timestamp))
                tools = f" [{', '.join(ep.tools_used)}]" if ep.tools_used else ""
                lines.append(f"**{ts}** {ep.headline}{tools}")
                if ep.summary and ep.summary != ep.headline:
                    lines.append(f"  {ep.summary}")
                lines.append("")

        return "\n".join(lines)
