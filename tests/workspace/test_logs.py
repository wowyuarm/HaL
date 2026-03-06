from __future__ import annotations

from datetime import date
from pathlib import Path

from hal.workspace.logs import LogRepository


def test_log_repository_resolves_v3_paths(tmp_path: Path) -> None:
    repository = LogRepository(tmp_path)

    assert repository.logs_dir() == tmp_path / "runtime" / "logs"
    assert repository.daily_log_path(date(2026, 3, 6)) == (
        tmp_path / "runtime" / "logs" / "2026-03-06.jsonl"
    )
