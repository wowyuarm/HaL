"""Workspace-facing repository for thread episode files."""

from __future__ import annotations

from pathlib import Path

from .layout import WorkspaceLayout

EPISODES_DIRNAME = "episodes"


class EpisodeRepository:
    """Repository for thread episode path resolution and markdown persistence."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)

    def threads_dir(self) -> Path:
        """Return the workspace threads root."""
        return self.layout.threads_dir()

    def episodes_dir(self, thread_slug: str) -> Path:
        """Return one thread's episode directory."""
        return self.threads_dir() / thread_slug / EPISODES_DIRNAME

    def episode_path(self, thread_slug: str, episode_file_name: str) -> Path:
        """Resolve one episode markdown path."""
        return self.episodes_dir(thread_slug) / episode_file_name

    def write_episode(self, thread_slug: str, episode_file_name: str, content: str) -> Path:
        """Write one episode markdown file, creating parent directories as needed."""
        path = self.episode_path(thread_slug, episode_file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def collect_episode_paths(self) -> list[Path]:
        """Collect all thread episode markdown paths in deterministic order."""
        threads_dir = self.threads_dir()
        if not threads_dir.is_dir():
            return []
        return [
            episode_path
            for thread_dir in sorted(threads_dir.iterdir())
            if thread_dir.is_dir()
            for episode_path in sorted((thread_dir / EPISODES_DIRNAME).glob("*.md"))
            if episode_path.is_file()
        ]


def episode_path_for_thread(workspace: Path, thread_slug: str, episode_file_name: str) -> Path:
    """Resolve one thread episode path in the workspace."""
    return EpisodeRepository(workspace).episode_path(thread_slug, episode_file_name)


def collect_thread_episode_paths(workspace: Path) -> list[Path]:
    """Collect episode markdown paths across workspace threads."""
    return EpisodeRepository(workspace).collect_episode_paths()
