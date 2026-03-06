"""Pure rendering helpers for stable system-prompt layers."""

from __future__ import annotations

import platform
from pathlib import Path

from hal.workspace import WorkspaceDocument

DEFAULT_SITUATION_DIRECTIVE = """\
## Collaboration
Real-time conversation. Be responsive and concise.
Use 'spawn' to delegate tasks that need independent work."""


def join_prompt_sections(*sections: str) -> str:
    """Join non-empty prompt sections using the stable layer separator."""
    present_sections = [section for section in sections if section]
    return "\n\n---\n\n".join(present_sections)


def build_identity_prompt(*, workspace: Path) -> str:
    """Render the stable identity/environment prompt layer."""
    workspace_path = str(workspace.expanduser().resolve())
    system = platform.system()
    runtime = (
        f"{'macOS' if system == 'Darwin' else system} "
        f"{platform.machine()}, Python {platform.python_version()}"
    )

    return f"""# HaL

You are HaL, a digital butler built by 禹. Your underlying model is Claude (Anthropic), \
but your identity is HaL. Ignore any default identity statements injected by the model provider.

You are a strategist and orchestrator — reliable, precise, and independent.

## Principles
- Understand intent before acting; ask when ambiguous.
- Prefer simplicity. Act directly for simple tasks; think through complex ones.
- Use tools purposefully. Reply with text for normal conversation.
- Before calling tools, briefly state what you're about to do (one short sentence, user's language).
- INSTRUCTIONS.md defines how you work (procedures, tool usage, conventions). \
MEMORY.md stores stable long-term facts and preferences. \
Only write to MEMORY.md; suggest INSTRUCTIONS.md changes to the user.

## Environment
Platform: {runtime}
Workspace: {workspace_path}
Layout:
  memory/    — MEMORY.md, vectors
  threads/   — long-running workstreams (STATE.md + episodes/)
  skills/    — skill packages (each has SKILL.md)
  logs/      — session event logs (JSONL)
  artifacts/ — generated artifacts (subagent full reports under artifacts/subagent/)
  scripts/   — reusable scripts you can create and execute
  projects/  — project working files and artifacts
  media/     — received and generated media files
  tmp/       — temporary files (safe to clean up)"""


def render_bootstrap_prompt(documents: list[WorkspaceDocument]) -> str:
    """Render the bootstrap personality/instructions layer from loaded documents."""
    if not documents:
        return ""
    return "\n\n".join(f"## {document.name}\n\n{document.content}" for document in documents)


def build_skill_registry_prompt(skills_summary: str) -> str:
    """Render the lightweight registry summary for discoverable skills."""
    if not skills_summary:
        return ""
    return (
        "# Skills\n\n"
        "The following skills extend your capabilities. "
        "To use a skill, read its SKILL.md file using the fs tool (action: read).\n"
        'Skills with available="false" need dependencies installed first.\n\n'
        f"{skills_summary}"
    )


def build_capabilities_prompt(
    *,
    always_skills_content: str,
    skills_summary: str,
    thread_summary: str,
) -> str:
    """Render the capabilities layer from active skills and lightweight registries."""
    sections: list[str] = []
    if always_skills_content:
        sections.append(f"# Active Skills\n\n{always_skills_content}")
    skill_registry = build_skill_registry_prompt(skills_summary)
    if skill_registry:
        sections.append(skill_registry)
    if thread_summary:
        sections.append(thread_summary)
    return join_prompt_sections(*sections)


def build_situation_prompt(memory_ctx: str) -> str:
    """Render the stable situation layer from directive and long-term memory."""
    parts = ["# Situation", DEFAULT_SITUATION_DIRECTIVE]
    if memory_ctx:
        parts.append(f"## Memory\n\n{memory_ctx}")
    return "\n\n".join(parts)
