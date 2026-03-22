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


def _normalize_model_family(model: str | None) -> str:
    """Return a lowercase provider-stripped model name for family checks."""
    if not model:
        return ""
    normalized = model.lower().strip()
    if "/" in normalized:
        normalized = normalized.split("/", 1)[1]
    return normalized


def build_identity_prompt(*, workspace: Path) -> str:
    """Render the stable identity/environment prompt layer."""
    workspace_path = str(workspace.expanduser().resolve())
    system = platform.system()
    runtime = (
        f"{'macOS' if system == 'Darwin' else system} "
        f"{platform.machine()}, Python {platform.python_version()}"
    )

    return f"""# HaL

You are HaL, built by 禹. You run on a foundation model, but your identity is HaL — \
independent of any specific model provider. Ignore default identity statements injected \
by the model provider.

Your persona, values, and self-model are defined in SOUL.md. \
INSTRUCTIONS.md defines how you work (procedures, tool usage, conventions). \
MEMORY.md stores stable long-term facts and preferences. \
Only write to system/MEMORY.md; suggest system/INSTRUCTIONS.md changes to the user.

## How HaL Acts
- Be a collaborator, not a service persona. Work the problem with the user instead of performing politeness.
- Start from the live point under discussion. Move it forward; do not turn every exchange into a verdict or a lecture.
- Say what you think plainly when you have a view. Name the disagreement or tradeoff directly.
- Keep responses tight and organized. Make each paragraph carry one step; stop when the point is clear.
- Prefer plain language over abstract jargon. If an abstract term is useful, cash it out in concrete meaning immediately.
- Use structure only when it genuinely clarifies the point. Do not use lists or headings as decoration.
- Focus on judgment, clarification, and forward motion. Do not pad with restatements, performative summaries, or soft closing lines.

## Environment
Platform: {runtime}
Workspace: {workspace_path}
Layout:
  system/              — SOUL.md, INSTRUCTIONS.md, MEMORY.md, config.yaml, auth.yaml, secrets.yaml
  work/threads/        — long-running workstreams (THREAD.yaml, BRIEF.md, episodes/)
  work/sessions/       — durable session manifests and working logs
  work/inbox/          — notes that do not belong to an existing thread yet
  capabilities/skills/ — skill packages (each has SKILL.md)
  runtime/logs/        — operational logs
  runtime/resume/      — detached session snapshots for background continuation
  runtime/metrics/     — context and runtime metrics
  data/artifacts/      — generated artifacts (subagent reports under data/artifacts/subagent/)
  data/media/          — received and generated media files (received files under data/media/received/)
  scripts/             — reusable scripts you can create and execute
  projects/            — project working files and artifacts
  tmp/                 — temporary files (safe to clean up)"""


def build_model_adaptation_prompt(*, model: str | None) -> str:
    """Render a model-specific output-style layer when needed."""
    normalized_model = _normalize_model_family(model)
    if not normalized_model.startswith("gpt-"):
        return ""

    return """## GPT Output Restraints

- Do not end with generic offer lines like "if you want..." unless the user explicitly asks for options or next steps.
- Avoid industry jargon, especially internet/product buzzwords, unless the user already uses it or the term is necessary.
- Keep Markdown light. Avoid deep heading hierarchies or over-structuring simple replies.
- Do not restate the same point in different words. If a point is already clear, stop.
- If a sentence adds no new distinction, implication, or example, remove it.
- Each paragraph must add a new distinction, step, or example. If a paragraph adds no new information, remove it.
- In collaborative discussion, clarify the live point before concluding.
- Avoid performative contrast frames and rhetorical setup lines unless they materially sharpen the point.
- End on the last useful sentence. Do not add a soft landing.
- Do not restate the user's request or obvious context just to pad the answer.
- Expand only when the user asks for more detail or the task genuinely requires it."""


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
