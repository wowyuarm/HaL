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
- For file read/write/edit/list tasks, use fs(action=...) as the primary tool.
- Do not use exec(cat/sed/python read_text) as the primary way to read file contents.
- If exec output shows \"truncated\", switch to fs(action=\"read\", offset=..., limit=...) chunked reads.
- If the same tool error repeats twice, change strategy immediately (different tool or corrected params).
- If the task requires writing deliverables, write early (not only at the final step).
- Before claiming a file is written, verify with fs(action=\"list\") and fs(action=\"read\").
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
## Tools

Use only the tools listed below in this subagent run. Do not assume other tools exist.

### fs — File Operations
Unified file tool with four actions:
```
fs(action="read", path="file.txt")
fs(action="read", path="file.txt", offset=2001, limit=2000)
fs(action="write", path="file.txt", content="...")
fs(action="edit", path="file.txt", old_text="...", new_text="...")
fs(action="list", path=".")
```
- `read` supports paginated reads via `offset`/`limit`.
- `edit` requires exact `old_text`; if not unique or missing, refine and retry.

### exec — Shell Execution
Execute shell commands with safety guards.
```
exec(command="ls -la", working_dir="/path")
exec(command="pytest tests/subagents -q", timeout=120)
```
- Output is truncated at 10K chars.
- Use `fs(action="read")` for source-file reading; do not rely on `cat/sed` for primary file reads.

### web_search — Web Search
```
web_search(query="latest news", count=5)
```
- `count` range is 1-10.

### web_fetch — Fetch Web Page
Fetch and extract page content.
```
web_fetch(url="https://example.com", extractMode="markdown")
web_fetch(url="https://example.com", extractMode="text", maxChars=20000)
```
- Returns a JSON string (with fields like `url`, `finalUrl`, `status`, `extractor`, `text`), not plain text only.
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
    workspace_path = workspace / "skills" / skill_name / relative_path
    if workspace_path.exists():
        return workspace_path
    return None
