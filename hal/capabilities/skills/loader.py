"""Skills loader for agent capabilities."""

import os
import re
import shutil
from pathlib import Path


class SkillsLoader:
    """
    Loader for agent skills.

    Skills live in <workspace>/skills/<name>/SKILL.md.
    Each skill directory can also contain scripts, references, etc.
    """

    def __init__(self, workspace: Path):
        self.skills_dir = workspace / "skills"

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """List all skills. Returns list of dicts with name, path."""
        skills = []
        if not self.skills_dir.exists():
            return skills

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skills.append({"name": skill_dir.name, "path": str(skill_file)})

        if filter_unavailable:
            return [
                s
                for s in skills
                if self._check_requirements(self.get_skill_metadata(s["name"]) or {})
            ]
        return skills

    def load_skill(self, name: str) -> str | None:
        """Load a skill's SKILL.md content by name."""
        skill_file = self.skills_dir / name / "SKILL.md"
        if skill_file.exists():
            return skill_file.read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """Load and format specific skills for agent context."""
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """Build XML summary of all skills for system prompt."""
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            meta = self.get_skill_metadata(s["name"]) or {}
            available = self._check_requirements(meta)
            desc = esc(meta.get("description", s["name"]))

            lines.append(f'  <skill available="{str(available).lower()}">')
            lines.append(f"    <name>{esc(s['name'])}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{s['path']}</location>")
            lines.append("  </skill>")

        lines.append("</skills>")
        return "\n".join(lines)

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            if meta.get("always", "").lower() in ("true", "1", "yes"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """Parse YAML frontmatter from a skill's SKILL.md."""
        content = self.load_skill(name)
        if not content or not content.startswith("---"):
            return None

        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return None

        metadata = {}
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")
        return metadata

    # -- private --

    def _strip_frontmatter(self, content: str) -> str:
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end() :].strip()
        return content

    def _check_requirements(self, meta: dict) -> bool:
        for b in self._parse_list(meta.get("requires_bins", "")):
            if not shutil.which(b):
                return False
        for env in self._parse_list(meta.get("requires_env", "")):
            if not os.environ.get(env):
                return False
        return True

    @staticmethod
    def _parse_list(value: str) -> list[str]:
        if not value:
            return []
        stripped = value.strip().strip("[]")
        if not stripped:
            return []
        return [item.strip().strip("\"'") for item in stripped.split(",") if item.strip()]
