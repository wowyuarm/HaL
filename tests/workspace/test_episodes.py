from __future__ import annotations

from pathlib import Path

from hal.workspace.episodes import (
    EpisodeRepository,
    collect_thread_episode_paths,
    episode_path_for_thread,
)


def test_episode_repository_resolves_and_writes_paths(tmp_path: Path) -> None:
    repo = EpisodeRepository(tmp_path)

    episode_path = repo.write_episode("hal-architecture", "episode.md", "# Episode\n")

    assert episode_path == (
        tmp_path / "work" / "threads" / "hal-architecture" / "episodes" / "episode.md"
    )
    assert episode_path.read_text(encoding="utf-8") == "# Episode\n"
    assert repo.episode_path("hal-architecture", "episode.md") == episode_path


def test_episode_repository_collects_markdown_across_threads(tmp_path: Path) -> None:
    first = tmp_path / "work" / "threads" / "github-actions" / "episodes"
    second = tmp_path / "work" / "threads" / "hal-architecture" / "episodes"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "2026-03-06-actions.md").write_text("# Episode\n", encoding="utf-8")
    (second / "2026-03-07-arch.md").write_text("# Episode\n", encoding="utf-8")
    (second / "notes.txt").write_text("ignore", encoding="utf-8")

    assert collect_thread_episode_paths(tmp_path) == [
        first / "2026-03-06-actions.md",
        second / "2026-03-07-arch.md",
    ]
    assert episode_path_for_thread(tmp_path, "hal-architecture", "episode.md") == (
        tmp_path / "work" / "threads" / "hal-architecture" / "episodes" / "episode.md"
    )
