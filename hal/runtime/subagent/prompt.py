"""Prompt construction helpers for subagent execution."""

from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path

_SUBAGENT_DIRECTIVE = """\
## Focused Task
You are executing a specific task. Stay focused — complete the assigned task only.
Be thorough in execution and concise in your final report."""


def build_system_prompt(workspace: Path, skills_section: str | None) -> str:
    """Build a focused, task-agnostic system prompt for the subagent."""
    workspace_path = str(workspace.expanduser().resolve())

    system = platform.system()
    runtime = (
        f"{'macOS' if system == 'Darwin' else system} "
        f"{platform.machine()}, Python {platform.python_version()}"
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")

    parts: list[str] = []

    parts.append(f"""# Subagent

You are a focused task executor working on behalf of the main agent.
Your result will be reported back — you do not interact with the user directly.

{_SUBAGENT_DIRECTIVE}""")

    parts.append("""\
## Rules
- Complete only the assigned task. Do not take on side tasks.
- Be thorough in execution, concise in your final report.
- If the task is ambiguous, make reasonable assumptions and state them.
- For file operations, use the dedicated read/write/edit tools as primary tools.
- Do not use bash (cat/sed/python read_text) as the primary way to read file contents.
- If bash output shows \"truncated\", switch to read(path=..., offset=..., limit=...) chunked reads.
- If the same tool error repeats twice, change strategy immediately (different tool or corrected params).
- If the task requires writing deliverables, write early (not only at the final step).
- Before claiming a file is written, verify with bash(command=\"ls ...\") and read(path=...).
- Never claim \"done\" or \"written\" unless verification succeeded.

## Final Output Contract
Your final response must include these sections:
1. Status: completed | partial | failed
2. Completed: what you finished
3. Incomplete: what remains unfinished
4. Deliverables Verified: file paths + exists=true/false
5. Side Effects: files modified, commands run, web actions
6. Key Findings: important outputs/data""")

    parts.append("""\
## Tool Orchestration

Tool descriptions carry full usage guidance. These rules govern cross-tool behavior:

- Read before edit: always `read` → `edit`, never blind edits.
- File I/O goes through `read`/`write`/`edit`, not bash (cat/sed/awk).
- If bash output says "truncated", switch to `read(path=..., offset=..., limit=...)`.
- If the same tool error repeats twice, change strategy immediately.
- Write deliverables early (not only at the final step); verify with `read` after writing.
""")

    if skills_section:
        parts.append(skills_section)

    parts.append(f"""\
## Environment
Platform: {runtime}
Workspace: {workspace_path}
Current time: {now}""")

    return "\n\n".join(parts)


def build_skills_section(workspace: Path) -> str | None:
    """Build the skills section for the subagent system prompt."""
    from hal.capabilities.skills.loader import SkillsLoader

    loader = SkillsLoader(workspace)
    parts: list[str] = []

    deepwiki_content = loader.load_skill("deepwiki")
    if deepwiki_content:
        deepwiki_script = resolve_skill_script(workspace, "deepwiki", "scripts/deepwiki.sh")
        if deepwiki_script:
            content = loader._strip_frontmatter(deepwiki_content)
            content = content.replace("scripts/deepwiki.sh", str(deepwiki_script))
            parts.append(f"### Skill: DeepWiki\n\n{content}")

    if not parts:
        return None

    return "## Skills\n\n" + "\n\n---\n\n".join(parts)


def resolve_skill_script(workspace: Path, skill_name: str, relative_path: str) -> Path | None:
    """Resolve absolute path to a skill script from workspace skills."""
    from hal.workspace import WorkspaceLayout

    layout = WorkspaceLayout(workspace)
    workspace_path = layout.skills_dir() / skill_name / relative_path
    if workspace_path.exists():
        return workspace_path
    return None
