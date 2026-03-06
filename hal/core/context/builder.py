"""Context builder for assembling layered agent prompts.

Implements a 5-layer context system optimized for prompt cache hits:

    Layer 0 — Identity (stable, rarely changes)
    Layer 1 — Personality (per-agent instance)
    Layer 2 — Capabilities (tools, skills)
    Layer 3 — Situation (stable directive + long-term memory)
    Layer 4 — Conversation (current session + message with dynamic context prefix)

Dynamic per-request content (time, channel, chat_id, memory search results) is
injected as an XML-tagged prefix on the last user message rather than in the
system prompt, so the system prompt stays stable and maximizes prefix cache hits.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal.capabilities.skills.loader import SkillsLoader
from hal.core.context.dynamic_context import build_dynamic_context_block
from hal.core.context.message_sequences import assemble_message_sequence, build_system_message
from hal.core.context.prompt_layers import (
    build_capabilities_prompt,
    build_identity_prompt,
    build_situation_prompt,
    join_prompt_sections,
    render_bootstrap_prompt,
)
from hal.core.context.registry import ContextRegistry
from hal.core.context.session_messages import (
    build_session_baseline_message,
    build_user_message_content,
)
from hal.workspace import SystemRepository

if TYPE_CHECKING:
    from hal.core.memory.manager import MemoryManager


class ContextBuilder:
    """
    Assembles layered context for LLM calls.

    Layers 0-2 form a stable prefix (maximizes prompt cache hits).
    Layers 3-4 are dynamic per request.
    """

    # Bootstrap files loaded into Layer 1 (personality/instructions).
    # INSTRUCTIONS.md is the primary instructions source.
    BOOTSTRAP_PRIMARY_FILES = ["SOUL.md", "INSTRUCTIONS.md"]
    # One-release compatibility fallback while workspaces migrate.
    BOOTSTRAP_LEGACY_FILES = ["USER.md", "AGENTS.md", "TOOLS.md"]

    def __init__(
        self,
        workspace: Path,
        memory_manager: "MemoryManager | None" = None,
        max_thread_registry_size: int = 20,
        related_thread_hops: int = 1,
        baseline_max_active_threads: int = 3,
        baseline_active_threads_max_total_tokens: int = 4000,
        baseline_active_thread_max_tokens: int = 1200,
    ):
        self.workspace = workspace
        self._memory_manager = memory_manager
        self.skills = SkillsLoader(workspace)
        self.system = SystemRepository(workspace)
        self._max_thread_registry_size = max(1, max_thread_registry_size)
        self._related_thread_hops = max(1, related_thread_hops)
        self._baseline_max_active_threads = max(1, baseline_max_active_threads)
        self._baseline_active_threads_max_total_tokens = max(
            0, baseline_active_threads_max_total_tokens
        )
        self._baseline_active_thread_max_tokens = max(0, baseline_active_thread_max_tokens)
        self.registry = ContextRegistry.from_workspace(
            workspace=workspace,
            skills_loader=self.skills,
            max_thread_registry_size=self._max_thread_registry_size,
            related_thread_hops=self._related_thread_hops,
        )

    @property
    def baseline_max_active_threads(self) -> int:
        """Return max number of active threads auto-loaded into one session baseline."""
        return self._baseline_max_active_threads

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_system_prompt(
        self,
        memory_budget_tokens: int | None = None,
        token_model: str | None = None,
    ) -> str:
        """Build the system prompt from layered context.

        Layers 0-2 are stable prefix (maximize prompt cache hits).
        Layer 3 (situation) contains only stable-per-session content:
        directive and long-term memory.
        """
        return join_prompt_sections(
            self._build_identity(),
            self._load_bootstrap_files(),
            self._build_capabilities(),
            self._build_situation(
                memory_budget_tokens=memory_budget_tokens,
                token_model=token_model,
            ),
        )

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        memory_search_results: list[Any] | None = None,
        active_threads: list[dict[str, object]] | None = None,
        memory_budget_tokens: int | None = None,
        recall_max_total_tokens: int = 500,
        recall_max_per_item_tokens: int = 125,
        token_model: str | None = None,
        session_baseline: str | None = None,
        prepend_dynamic_context_to_current: bool = True,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call.

        Assembles all 5 layers:
            System message = Layer 0 + 1 + 2 + 3 (stable)
            Conversation   = Layer 4 (history + current message)

        Dynamic per-request context (time, channel, chat_id, memory search
        results) is prepended to the last user message as an XML block, keeping
        the system prompt stable for prompt cache hits.
        """
        return assemble_message_sequence(
            system_message=self._build_system_message(
                memory_budget_tokens=memory_budget_tokens,
                token_model=token_model,
            ),
            history=history,
            session_baseline=(
                build_session_baseline_message(session_baseline) if session_baseline else None
            ),
            user_message=self._build_user_message(
                current_message=current_message,
                media=media,
                channel=channel,
                chat_id=chat_id,
                memory_search_results=memory_search_results,
                active_threads=active_threads,
                recall_max_total_tokens=recall_max_total_tokens,
                recall_max_per_item_tokens=recall_max_per_item_tokens,
                token_model=token_model,
                prepend_dynamic_context_to_current=prepend_dynamic_context_to_current,
            ),
        )

    def build_dynamic_context_block(
        self,
        channel: str | None = None,
        chat_id: str | None = None,
        memory_search_results: list[Any] | None = None,
        active_threads: list[dict[str, object]] | None = None,
        recall_max_total_tokens: int = 500,
        recall_max_per_item_tokens: int = 125,
        token_model: str | None = None,
    ) -> str:
        """Public wrapper for compiling the XML dynamic context block."""
        return self._build_dynamic_context(
            channel=channel,
            chat_id=chat_id,
            memory_search_results=memory_search_results,
            active_threads=active_threads,
            recall_max_total_tokens=recall_max_total_tokens,
            recall_max_per_item_tokens=recall_max_per_item_tokens,
            token_model=token_model,
        )

    def _build_system_message(
        self,
        *,
        memory_budget_tokens: int | None,
        token_model: str | None,
    ) -> dict[str, object]:
        """Build the stable system message for one turn."""
        return build_system_message(
            self.build_system_prompt(
                memory_budget_tokens=memory_budget_tokens,
                token_model=token_model,
            )
        )

    def _build_user_message(
        self,
        *,
        current_message: str,
        media: list[str] | None,
        channel: str | None,
        chat_id: str | None,
        memory_search_results: list[Any] | None,
        active_threads: list[dict[str, object]] | None,
        recall_max_total_tokens: int,
        recall_max_per_item_tokens: int,
        token_model: str | None,
        prepend_dynamic_context_to_current: bool,
    ) -> dict[str, object]:
        """Build the current user turn, optionally prefixed with dynamic context."""
        dynamic_ctx = (
            self.build_dynamic_context_block(
                channel=channel,
                chat_id=chat_id,
                memory_search_results=memory_search_results,
                active_threads=active_threads,
                recall_max_total_tokens=recall_max_total_tokens,
                recall_max_per_item_tokens=recall_max_per_item_tokens,
                token_model=token_model,
            )
            if prepend_dynamic_context_to_current
            else None
        )
        return {
            "role": "user",
            "content": build_user_message_content(current_message, media, dynamic_ctx),
        }

    # ------------------------------------------------------------------
    # Layer builders
    # ------------------------------------------------------------------

    def _build_identity(self) -> str:
        """Layer 0 — Core identity. Truly stable across requests.

        No time, no per-request state. Only who I am, how I think, how I act.
        """
        return build_identity_prompt(workspace=self.workspace)

    def _load_bootstrap_files(self) -> str:
        """Layer 1 — Personality and user profile from workspace markdown files."""
        return render_bootstrap_prompt(
            self.system.load_bootstrap_documents(
                primary_files=self.BOOTSTRAP_PRIMARY_FILES,
                legacy_files=self.BOOTSTRAP_LEGACY_FILES,
            )
        )

    def _build_capabilities(self) -> str:
        """Layer 2 — Skills (tools are already in function calling schema)."""
        always_skills = self.skills.get_always_skills()
        always_content = self.skills.load_skills_for_context(always_skills) if always_skills else ""
        return build_capabilities_prompt(
            always_skills_content=always_content,
            skills_summary=self.registry.render_skill_summary(),
            thread_summary=self.registry.render_thread_summary(),
        )

    def _build_situation(
        self,
        memory_budget_tokens: int | None = None,
        token_model: str | None = None,
    ) -> str:
        """Layer 3 — Situation: directive + long-term memory.

        Stable per session — no time or per-request search results.
        """
        memory_ctx = self._get_memory_context(
            budget_tokens=memory_budget_tokens, token_model=token_model
        )
        return build_situation_prompt(memory_ctx)

    def _get_memory_context(
        self,
        budget_tokens: int | None = None,
        token_model: str | None = None,
    ) -> str:
        """Assemble memory context from MemoryManager."""
        if self._memory_manager:
            return self._memory_manager.get_context(
                budget_tokens=budget_tokens,
                token_model=token_model,
            )
        return ""

    # ------------------------------------------------------------------
    # Dynamic context (injected into user message, not system prompt)
    # ------------------------------------------------------------------

    def _build_dynamic_context(
        self,
        channel: str | None = None,
        chat_id: str | None = None,
        memory_search_results: list[Any] | None = None,
        active_threads: list[dict[str, object]] | None = None,
        recall_max_total_tokens: int = 500,
        recall_max_per_item_tokens: int = 125,
        token_model: str | None = None,
    ) -> str:
        """Build an XML-tagged dynamic context block for the user message.

        This content changes per request (time, channel, search results) and is
        kept out of the system prompt to maximize prompt cache hits.
        """
        return build_dynamic_context_block(
            channel=channel,
            chat_id=chat_id,
            active_threads=active_threads or self.registry.active_thread_entry_snapshot(),
            active_threads_max_total_tokens=self._baseline_active_threads_max_total_tokens,
            active_thread_max_tokens=self._baseline_active_thread_max_tokens,
            memory_search_results=memory_search_results,
            recall_max_total_tokens=recall_max_total_tokens,
            recall_max_per_item_tokens=recall_max_per_item_tokens,
            token_model=token_model,
        )
