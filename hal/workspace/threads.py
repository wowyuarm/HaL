"""Workspace-facing thread repository and filesystem helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .episodes import EpisodeRepository
from .layout import WorkspaceLayout
from .thread_metadata import (
    THREAD_METADATA_FILENAME,
    ResolvedThreadMetadata,
    load_thread_metadata,
    resolve_thread_metadata,
)
from .thread_state import (
    build_episode_file_name,
    ensure_recent_episodes_section,
    extract_episode_title,
)

THREADS_DIRNAME = "threads"
THREAD_STATE_FILENAME = "BRIEF.md"
_THREAD_STATUS_ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class ThreadRegistryEntry:
    """Normalized thread metadata discovered from the workspace."""

    slug: str
    name: str
    status: str
    description: str
    pinned: bool
    state_path: str
    metadata_path: str | None
    mtime: float
    state_content: str
    related_threads: tuple[str, ...] = ()
    updated_at: str | None = None
    scope: str = ""


@dataclass(frozen=True, slots=True)
class ThreadEpisodeWriteResult:
    """Result of writing one episode and advancing the thread hot state."""

    episode_path: Path
    episode_rel_path: str
    episode_title: str
    state_content: str


class ThreadRepository:
    """Repository for thread state, metadata, episodes, and registry discovery."""

    def __init__(self, workspace: Path):
        self.layout = WorkspaceLayout(workspace)
        self.episodes = EpisodeRepository(workspace)

    def threads_dir(self) -> Path:
        """Return the root threads directory inside the workspace."""
        return self.layout.threads_dir()

    def state_path(self, thread_slug: str) -> Path:
        """Resolve one thread's BRIEF.md path."""
        return self.threads_dir() / thread_slug / THREAD_STATE_FILENAME

    def metadata_path(self, thread_slug: str) -> Path:
        """Resolve one thread's THREAD.yaml path."""
        return self.threads_dir() / thread_slug / THREAD_METADATA_FILENAME

    def episode_path(self, thread_slug: str, episode_file_name: str) -> Path:
        """Resolve one thread episode path."""
        return self.episodes.episode_path(thread_slug, episode_file_name)

    def read_state(self, thread_slug: str) -> str | None:
        """Read one thread BRIEF.md file, returning None when unavailable."""
        path = self.state_path(thread_slug)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None

    def write_state(self, thread_slug: str, content: str) -> Path:
        """Write one thread BRIEF.md file, creating parent directories as needed."""
        path = self.state_path(thread_slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_episode(self, thread_slug: str, episode_file_name: str, content: str) -> Path:
        """Write one thread episode file, creating parent directories as needed."""
        return self.episodes.write_episode(thread_slug, episode_file_name, content)

    def record_debrief_episode(
        self,
        *,
        thread_slug: str,
        session_id: str,
        episode_markdown: str,
        brief_markdown: str | None = None,
        now: datetime,
        state_content: str | None = None,
    ) -> ThreadEpisodeWriteResult | None:
        """Write one debrief episode and update BRIEF.md."""
        base_state = state_content if state_content is not None else self.read_state(thread_slug)
        if base_state is None:
            return None

        episode_file_name = build_episode_file_name(
            now=now,
            session_id=session_id,
            thread_slug=thread_slug,
        )
        episode_path = self.write_episode(thread_slug, episode_file_name, episode_markdown)
        episode_title = extract_episode_title(episode_markdown)
        episode_rel_path = f"episodes/{episode_file_name}"

        # Use worker-generated brief when available, otherwise keep current brief.
        next_state = brief_markdown if brief_markdown is not None else base_state
        # Always append the new episode link.
        next_state = ensure_recent_episodes_section(next_state, episode_rel_path, episode_title)
        self.write_state(thread_slug, next_state)
        return ThreadEpisodeWriteResult(
            episode_path=episode_path,
            episode_rel_path=episode_rel_path,
            episode_title=episode_title,
            state_content=next_state,
        )

    def collect_registry_entries(self, *, max_entries: int) -> list[ThreadRegistryEntry]:
        """Collect and rank thread registry entries from the workspace."""
        threads_dir = self.threads_dir()
        if not threads_dir.is_dir():
            return []

        entries = [
            entry
            for thread_dir in self._iter_thread_dirs(threads_dir)
            if (entry := self._load_registry_entry(thread_dir)) is not None
        ]
        ranked_entries = self._rank_registry_entries(entries)
        return ranked_entries[: max(1, max_entries)]

    def collect_episode_paths(self) -> list[Path]:
        """Collect episode markdown paths from all thread directories."""
        return self.episodes.collect_episode_paths()

    def _iter_thread_dirs(self, threads_dir: Path) -> list[Path]:
        """List candidate thread directories that may contain thread state."""
        return [thread_dir for thread_dir in sorted(threads_dir.iterdir()) if thread_dir.is_dir()]

    def _load_registry_entry(self, thread_dir: Path) -> ThreadRegistryEntry | None:
        """Load one normalized registry entry from a thread directory."""
        state_path = thread_dir / THREAD_STATE_FILENAME
        if not state_path.is_file():
            # Auto-bootstrap: if THREAD.yaml exists, generate initial BRIEF.md.
            if not (thread_dir / THREAD_METADATA_FILENAME).is_file():
                return None
            self._bootstrap_state_from_metadata(thread_dir)
        try:
            state_content = state_path.read_text(encoding="utf-8")
        except Exception:
            return None
        metadata = load_thread_metadata(thread_dir / THREAD_METADATA_FILENAME)
        return self._build_registry_entry(
            thread_dir=thread_dir,
            state_path=state_path,
            state_content=state_content,
            metadata=metadata,
        )

    def _build_registry_entry(
        self,
        *,
        thread_dir: Path,
        state_path: Path,
        state_content: str,
        metadata: dict,
    ) -> ThreadRegistryEntry:
        """Merge markdown state and optional THREAD.yaml into one registry entry."""
        resolved = resolve_thread_metadata(
            slug=thread_dir.name,
            state_content=state_content,
            metadata=metadata,
        )
        return self._build_registry_entry_from_metadata(
            thread_dir=thread_dir,
            state_path=state_path,
            state_content=state_content,
            resolved=resolved,
        )

    def _build_registry_entry_from_metadata(
        self,
        *,
        thread_dir: Path,
        state_path: Path,
        state_content: str,
        resolved: ResolvedThreadMetadata,
    ) -> ThreadRegistryEntry:
        """Build one registry entry from resolved thread metadata."""
        return ThreadRegistryEntry(
            slug=thread_dir.name,
            name=resolved.title,
            status=resolved.status,
            description=resolved.description,
            pinned=resolved.pinned,
            state_path=self._relative_thread_path(thread_dir.name, THREAD_STATE_FILENAME),
            metadata_path=self._relative_metadata_path(
                thread_dir.name,
                has_machine_metadata=resolved.has_machine_metadata,
            ),
            mtime=state_path.stat().st_mtime,
            state_content=state_content,
            related_threads=resolved.related_threads,
            updated_at=resolved.updated_at,
            scope=resolved.scope,
        )

    @staticmethod
    def _relative_thread_path(thread_slug: str, file_name: str) -> str:
        """Build a workspace-relative path for one file inside a thread directory."""
        return f"{THREADS_DIRNAME}/{thread_slug}/{file_name}"

    def _relative_metadata_path(
        self, thread_slug: str, *, has_machine_metadata: bool
    ) -> str | None:
        """Build metadata path only when machine-readable metadata exists."""
        if not has_machine_metadata:
            return None
        return self._relative_thread_path(thread_slug, THREAD_METADATA_FILENAME)

    def _bootstrap_state_from_metadata(self, thread_dir: Path) -> None:
        """Generate initial BRIEF.md from THREAD.yaml when only metadata exists."""
        metadata = load_thread_metadata(thread_dir / THREAD_METADATA_FILENAME)
        title = metadata.get("name") or metadata.get("title") or thread_dir.name
        status = metadata.get("status", "active")
        goal = metadata.get("goal") or metadata.get("description") or "No description provided."
        scope = metadata.get("scope", "")
        parts = [f"# {title}", f"Status: {status}", "", "## Purpose", goal]
        if scope:
            parts.extend(["", "## Scope", scope])
        parts.append("")
        content = "\n".join(parts) + "\n"
        state_path = thread_dir / THREAD_STATE_FILENAME
        state_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _rank_registry_entries(entries: list[ThreadRegistryEntry]) -> list[ThreadRegistryEntry]:
        """Rank entries: active first, then recent inactive, then pinned inactive."""
        active = [entry for entry in entries if entry.status == _THREAD_STATUS_ACTIVE]
        inactive_non_pinned = [
            entry for entry in entries if entry.status != _THREAD_STATUS_ACTIVE and not entry.pinned
        ]
        inactive_pinned = [
            entry for entry in entries if entry.status != _THREAD_STATUS_ACTIVE and entry.pinned
        ]
        inactive_non_pinned.sort(key=lambda item: item.mtime, reverse=True)
        inactive_pinned.sort(key=lambda item: item.mtime, reverse=True)
        return active + inactive_non_pinned + inactive_pinned


def thread_state_path(workspace: Path, thread_slug: str) -> Path:
    """Resolve one thread's BRIEF.md path in the workspace."""
    return ThreadRepository(workspace).state_path(thread_slug)


def thread_metadata_path(workspace: Path, thread_slug: str) -> Path:
    """Resolve one thread's THREAD.yaml path in the workspace."""
    return ThreadRepository(workspace).metadata_path(thread_slug)


def episode_path_for_thread(workspace: Path, thread_slug: str, episode_file_name: str) -> Path:
    """Resolve one thread episode path in the workspace."""
    return ThreadRepository(workspace).episode_path(thread_slug, episode_file_name)


def collect_thread_registry_entries(
    workspace: Path,
    *,
    max_entries: int,
) -> list[ThreadRegistryEntry]:
    """Collect and rank thread registry entries from workspace work/threads/."""
    return ThreadRepository(workspace).collect_registry_entries(max_entries=max_entries)


def collect_thread_episode_paths(workspace: Path) -> list[Path]:
    """Collect episode markdown paths across workspace threads."""
    return ThreadRepository(workspace).collect_episode_paths()
