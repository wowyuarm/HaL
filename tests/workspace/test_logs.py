from __future__ import annotations

from datetime import date
from pathlib import Path

from hal.workspace.logs import LogRepository


def test_log_repository_uses_legacy_logs_dir_by_default(tmp_path: Path) -> None:
    repository = LogRepository(tmp_path)

    assert repository.logs_dir() == tmp_path / "logs"
    assert repository.daily_log_path(date(2026, 3, 6)) == tmp_path / "logs" / "2026-03-06.jsonl"


def test_log_repository_prefers_v3_runtime_logs_dir(tmp_path: Path) -> None:
    (tmp_path / "runtime" / "logs").mkdir(parents=True)
    repository = LogRepository(tmp_path)

    assert repository.logs_dir() == tmp_path / "runtime" / "logs"
    assert repository.daily_log_path(date(2026, 3, 6)) == (
        tmp_path / "runtime" / "logs" / "2026-03-06.jsonl"
    )
