"""Context builder for assembling layered agent prompts.

Implements a 5-layer context system optimized for prompt cache hits:

    Layer 0 — Identity (stable, rarely changes)
    Layer 1 — Personality (per-agent instance)
    Layer 2 — Capabilities (tools, skills)
    Layer 3 — Situation (stable per session: mode directive, long-term memory)
    Layer 4 — Conversation (current session + message with dynamic context prefix)

Dynamic per-request content (time, channel, chat_id, memory search results) is
injected as an XML-tagged prefix on the last user message rather than in the
system prompt, so the system prompt stays stable and maximizes prefix cache hits.
"""

from __future__ import annotations

import base64
import mimetypes
import platform
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal.capabilities.skills.loader import SkillsLoader

if TYPE_CHECKING:
    from hal.core.memory.manager import MemoryManager


class ExecutionMode(str, Enum):
    """Agent execution mode — determines context assembly strategy."""

    COLLAB = "collab"  # Real-time collaborative (user message → response)
    ASYNC = "async"  # Background tasks
    OPERATOR = "operator"  # Scheduled monitoring / cron


# ------------------------------------------------------------------
# Mode-specific behavioral directives
# ------------------------------------------------------------------

_MODE_DIRECTIVES: dict[ExecutionMode, str] = {
    ExecutionMode.COLLAB: """\
## Mode: Collaborative
Real-time conversation. Be responsive and concise. \
Use 'spawn' to delegate tasks that need independent work.""",
    ExecutionMode.ASYNC: """\
## Mode: Focused Task
You are executing a specific task. Stay focused — complete the assigned task only. \
Be thorough in execution and concise in your final report.""",
    ExecutionMode.OPERATOR: """\
## Mode: Operator
Running autonomously via scheduled trigger. \
Only report when there is something actionable. High signal-to-noise.""",
}


class ContextBuilder:
    """
    Assembles layered context for LLM calls.

    Layers 0-2 form a stable prefix (maximizes prompt cache hits).
    Layers 3-4 are dynamic per request.
    """

    # Bootstrap files loaded into Layer 1 (personality/instructions).
    # TOOLS.md provides usage guidance (not definitions — those come from function calling).
    BOOTSTRAP_FILES = ["SOUL.md", "USER.md", "AGENTS.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(
        self,
        workspace: Path,
        memory_manager: "MemoryManager | None" = None,
    ):
        self.workspace = workspace
        self._memory_manager = memory_manager
        self.skills = SkillsLoader(workspace)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        mode: ExecutionMode = ExecutionMode.COLLAB,
    ) -> str:
        """Build the system prompt from layered context.

        Layers 0-2 are stable prefix (maximize prompt cache hits).
        Layer 3 (situation) contains only stable-per-session content:
        mode directive and long-term memory.
        """
        parts: list[str] = []

        # Layer 0 — Identity (stable across all requests)
        parts.append(self._build_identity())

        # Layer 1 — Personality (per-agent: SOUL.md, USER.md, AGENTS.md)
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Layer 2 — Capabilities (skills; tools are in function calling schema)
        capabilities = self._build_capabilities()
        if capabilities:
            parts.append(capabilities)

        # Layer 3 — Situation (stable per session: mode, long-term memory)
        situation = self._build_situation(mode)
        if situation:
            parts.append(situation)

        return "\n\n---\n\n".join(parts)

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        mode: ExecutionMode = ExecutionMode.COLLAB,
        memory_search_results: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call.

        Assembles all 5 layers:
            System message = Layer 0 + 1 + 2 + 3 (stable)
            Conversation   = Layer 4 (history + current message)

        Dynamic per-request context (time, channel, chat_id, memory search
        results) is prepended to the last user message as an XML block, keeping
        the system prompt stable for prompt cache hits.
        """
        messages: list[dict[str, Any]] = []

        # Layers 0-3: stable system prompt (no per-request dynamic content)
        system_prompt = self.build_system_prompt(skill_names, mode)
        messages.append({"role": "system", "content": system_prompt})

        # Layer 4: conversation history
        messages.extend(history)

        # Layer 4: current message with dynamic context prefix
        dynamic_ctx = self._build_dynamic_context(
            channel=channel,
            chat_id=chat_id,
            memory_search_results=memory_search_results,
        )
        user_content = self._build_user_content(current_message, media, dynamic_ctx)
        messages.append({"role": "user", "content": user_content})

        return messages

    # ------------------------------------------------------------------
    # Layer builders
    # ------------------------------------------------------------------

    def _build_identity(self) -> str:
        """Layer 0 — Core identity. Truly stable across requests.

        No time, no per-request state. Only who I am, how I think, how I act.
        """
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = (
            f"{'macOS' if system == 'Darwin' else system} "
            f"{platform.machine()}, Python {platform.python_version()}"
        )

        return f"""# HaL

You are HaL, a digital butler — reliable, precise, and independent.

## Principles
- Understand intent before acting; ask when ambiguous.
- Prefer simplicity. Act directly for simple tasks; think through complex ones.
- Use tools purposefully. Reply with text for normal conversation.
- Use 'message' only for cross-channel delivery (e.g., cron → Telegram).
- Record lasting knowledge to memory/MEMORY.md.

## Environment
Platform: {runtime}
Workspace: {workspace_path}
Memory: {workspace_path}/memory/MEMORY.md
Skills: {workspace_path}/skills/*/SKILL.md"""

    def _load_bootstrap_files(self) -> str:
        """Layer 1 — Personality and user profile from workspace markdown files."""
        parts: list[str] = []
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        return "\n\n".join(parts) if parts else ""

    def _build_capabilities(self) -> str:
        """Layer 2 — Skills (tools are already in function calling schema)."""
        parts: list[str] = []

        # Always-loaded skills
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # Available skills summary
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(
                "# Skills\n\n"
                "The following skills extend your capabilities. "
                "To use a skill, read its SKILL.md file using the fs tool (action: read).\n"
                'Skills with available="false" need dependencies installed first.\n\n'
                f"{skills_summary}"
            )

        return "\n\n---\n\n".join(parts) if parts else ""

    def _build_situation(
        self,
        mode: ExecutionMode,
    ) -> str:
        """Layer 3 — Situation: mode directive + long-term memory.

        Stable per session — no time or per-request search results.
        """
        parts: list[str] = []

        parts.append("# Situation")

        # Mode-specific behavioral directive
        directive = _MODE_DIRECTIVES.get(mode)
        if directive:
            parts.append(directive)

        # Long-term memory (stable per session — loaded from MEMORY.md)
        memory_ctx = self._get_memory_context()
        if memory_ctx:
            parts.append(f"## Memory\n\n{memory_ctx}")

        return "\n\n".join(parts)

    def _get_memory_context(self) -> str:
        """Assemble memory context from MemoryManager."""
        if self._memory_manager:
            return self._memory_manager.get_context()
        return ""

    # ------------------------------------------------------------------
    # Dynamic context (injected into user message, not system prompt)
    # ------------------------------------------------------------------

    def _build_dynamic_context(
        self,
        channel: str | None = None,
        chat_id: str | None = None,
        memory_search_results: list[Any] | None = None,
    ) -> str:
        """Build an XML-tagged dynamic context block for the user message.

        This content changes per request (time, channel, search results) and is
        kept out of the system prompt to maximize prompt cache hits.
        """
        from datetime import datetime

        parts: list[str] = []

        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        parts.append(f"<time>{now}</time>")

        if channel:
            parts.append(f"<channel>{channel}</channel>")
        if chat_id:
            parts.append(f"<chat_id>{chat_id}</chat_id>")

        if memory_search_results:
            recall_lines: list[str] = []
            for r in memory_search_results:
                header = f"- **{r.source}"
                if r.heading:
                    header += f" — {r.heading}"
                header += f"** (relevance: {r.score:.2f})"
                recall_lines.append(header)
                recall_lines.append(f"  {r.content[:500]}")
            if recall_lines:
                parts.append(
                    "<relevant_memories>\n" + "\n".join(recall_lines) + "\n</relevant_memories>"
                )

        return "<context>\n" + "\n".join(parts) + "\n</context>"

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def _build_user_content(
        self,
        text: str,
        media: list[str] | None,
        dynamic_context: str | None = None,
    ) -> str | list[dict[str, Any]]:
        """Build user message content with optional dynamic context and images.

        When *dynamic_context* is provided it is prepended to the text body,
        separated by a blank line.
        """
        if dynamic_context:
            text = f"{dynamic_context}\n\n{text}"

        if not media:
            return text

        images: list[dict[str, Any]] = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            }
        )
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        messages.append(msg)
        return messages
