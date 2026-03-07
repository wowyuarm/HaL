"""Workspace-facing repositories and filesystem helpers."""

from .artifacts import ArtifactRepository, SubagentExecutionRecord
from .episodes import (
    EPISODES_DIRNAME,
    EpisodeRepository,
    collect_thread_episode_paths,
    episode_path_for_thread,
)
from .layout import (
    SKILL_FILENAME,
    LogRepository,
    MetricsRepository,
    SkillRepository,
    WorkspaceLayout,
)
from .sessions import SessionRepository, SessionSnapshot
from .system_files import SystemRepository, WorkspaceDocument
from .thread_state import (
    apply_episode_state_patch,
    build_episode_file_name,
    ensure_current_state_note,
    ensure_recent_episodes_section,
)
from .threads import (
    THREAD_METADATA_FILENAME,
    THREAD_STATE_FILENAME,
    THREADS_DIRNAME,
    ThreadEpisodeWriteResult,
    ThreadRegistryEntry,
    ThreadRepository,
    collect_thread_registry_entries,
    thread_metadata_path,
    thread_state_path,
)

__all__ = [
    "ArtifactRepository",
    "EpisodeRepository",
    "EPISODES_DIRNAME",
    "SystemRepository",
    "SubagentExecutionRecord",
    "MetricsRepository",
    "LogRepository",
    "SessionRepository",
    "SessionSnapshot",
    "SkillRepository",
    "SKILL_FILENAME",
    "THREAD_METADATA_FILENAME",
    "THREADS_DIRNAME",
    "THREAD_STATE_FILENAME",
    "ThreadEpisodeWriteResult",
    "ThreadRepository",
    "ThreadRegistryEntry",
    "WorkspaceLayout",
    "WorkspaceDocument",
    "collect_thread_episode_paths",
    "apply_episode_state_patch",
    "build_episode_file_name",
    "collect_thread_registry_entries",
    "ensure_current_state_note",
    "ensure_recent_episodes_section",
    "episode_path_for_thread",
    "thread_metadata_path",
    "thread_state_path",
]
