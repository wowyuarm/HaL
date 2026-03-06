from __future__ import annotations

from pathlib import Path

from hal.workspace.metrics import MetricsRepository


def test_metrics_repository_uses_legacy_logs_path_by_default(tmp_path: Path) -> None:
    repository = MetricsRepository(tmp_path)

    assert repository.context_metrics_path() == tmp_path / "logs" / "context_metrics.jsonl"


def test_metrics_repository_prefers_v3_runtime_metrics_dir(tmp_path: Path) -> None:
    (tmp_path / "runtime" / "metrics").mkdir(parents=True)
    repository = MetricsRepository(tmp_path)

    assert repository.context_metrics_path() == tmp_path / "runtime" / "metrics" / "context_metrics.jsonl"
