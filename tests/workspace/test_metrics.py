from __future__ import annotations

from pathlib import Path

from hal.workspace.metrics import MetricsRepository


def test_metrics_repository_resolves_v3_path(tmp_path: Path) -> None:
    repository = MetricsRepository(tmp_path)

    assert repository.context_metrics_path() == (
        tmp_path / "runtime" / "metrics" / "context_metrics.jsonl"
    )
