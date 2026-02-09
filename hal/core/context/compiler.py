"""Context compiler for assembling layered agent prompts.

Implements a 5-layer context system optimized for prompt cache hits:

    Layer 0 — Identity (stable, rarely changes)
    Layer 1 — Personality (per-agent instance)
    Layer 2 — Capabilities (tools, skills)
    Layer 3 — Memory (dynamic per request)
    Layer 4 — Conversation (current session + message)
"""

from __future__ import annotations

import base64
import mimetypes
import platform
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal.capabilities.skills.loader import SkillsLoader
from hal.core.memory.store import MemoryStore

if TYPE_CHECKING:
    from hal.core.memory.manager import MemoryManager


class ExecutionMode(str, Enum):
    """Agent execution mode — determines context assembly strategy."""

    COLLAB = "collab"  # Real-time collaborative (user message → response)
    ASYNC = "async"  # Background long-running task
    OPERATOR = "operator"  # Scheduled monitoring / cron


class ContextCompiler:
    """
    Assembles layered context for LLM calls.

    Layers 0-2 form a stable prefix (maximizes prompt cache hits).
    Layers 3-4 are dynamic per request.

    Backward compatible: exposes the same API as the old ContextBuilder.
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(
        self,
        workspace: Path,
        memory_manager: "MemoryManager | None" = None,
    ):
        self.workspace = workspace
        # Legacy memory store (for backward compatibility)
        self._legacy_memory = MemoryStore(workspace)
        self._memory_manager = memory_manager
        self.skills = SkillsLoader(workspace)

    # ------------------------------------------------------------------
    # Public API (backward compatible with ContextBuilder)
    # ------------------------------------------------------------------

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        mode: ExecutionMode = ExecutionMode.COLLAB,
    ) -> str:
        """Build the system prompt from layered context.

        Layers 0-2 are assembled here (stable prefix).
        Layer 3 (memory) is appended dynamically.
        """
        parts: list[str] = []

        # Layer 0 — Identity
        parts.append(self._build_identity())

        # Layer 1 — Personality (bootstrap files: SOUL.md, USER.md, etc.)
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Layer 2 — Capabilities (tools + skills)
        capabilities = self._build_capabilities()
        if capabilities:
            parts.append(capabilities)

        # Layer 3 — Memory (dynamic)
        memory_ctx = self._build_memory_context(mode)
        if memory_ctx:
            parts.append(f"# Memory\n\n{memory_ctx}")

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
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call.

        Assembles all 5 layers:
            System message = Layer 0 + 1 + 2 + 3
            Conversation   = Layer 4 (history + current message)
        """
        messages: list[dict[str, Any]] = []

        # Layers 0-3: system prompt
        system_prompt = self.build_system_prompt(skill_names, mode)
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})

        # Layer 4: conversation history
        messages.extend(history)

        # Layer 4: current message
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    # ------------------------------------------------------------------
    # Layer builders
    # ------------------------------------------------------------------

    def _build_identity(self) -> str:
        """Layer 0 — Core identity. Stable across requests."""
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = (
            f"{'macOS' if system == 'Darwin' else system} "
            f"{platform.machine()}, Python {platform.python_version()}"
        )

        return f"""# HaL 🔴

You are HaL, a reliable and precise digital butler. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now}

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""

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
        """Layer 2 — Available tools and skills."""
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
                'Skills with available="false" need dependencies installed first '
                "- you can try installing them with apt/brew.\n\n"
                f"{skills_summary}"
            )

        return "\n\n---\n\n".join(parts) if parts else ""

    def _build_memory_context(self, mode: ExecutionMode) -> str:
        """Layer 3 — Memory injection (dynamic per request)."""
        if self._memory_manager:
            return self._memory_manager.get_context()
        # Fallback to legacy MemoryStore
        return self._legacy_memory.get_memory_context()

    # ------------------------------------------------------------------
    # Message helpers (unchanged API)
    # ------------------------------------------------------------------

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
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
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)
        return messages


# Backward compatibility alias
ContextBuilder = ContextCompiler
