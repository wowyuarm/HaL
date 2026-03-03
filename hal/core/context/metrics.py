"""Context metrics collection for observability and optimization."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

USAGE_SOURCE_NONE = "none"
USAGE_SOURCE_PROVIDER = "provider"


@dataclass
class ContextMetrics:
    """Per-request context metrics captured around one loop execution."""

    timestamp: str
    channel: str
    chat_id: str
    mode: str
    system_prompt_chars: int = 0
    history_message_count: int = 0
    history_chars: int = 0
    recall_count: int = 0
    recall_max_score: float = 0.0
    recall_chars: int = 0
    current_message_chars: int = 0
    total_input_chars: int = 0
    estimated_input_tokens: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    usage_available: bool = False
    usage_source: str = USAGE_SOURCE_NONE
    loop_iterations: int = 0
    tools_used: list[str] = field(default_factory=list)
    spawn_count: int = 0
    has_side_effects: bool = False

    @classmethod
    def create(cls, *, channel: str, chat_id: str, mode: str, **kwargs: Any) -> "ContextMetrics":
        """Create a metric row with auto timestamp."""
        return cls(
            timestamp=datetime.now().isoformat(),
            channel=channel,
            chat_id=chat_id,
            mode=mode,
            **kwargs,
        )


class MetricsCollector:
    """Append-only JSONL collector for context metrics."""

    @classmethod
    def _numeric_fields(cls) -> tuple[str, ...]:
        """Derive numeric field names from the dataclass definition."""
        import dataclasses

        return tuple(
            f.name
            for f in dataclasses.fields(ContextMetrics)
            if f.type in ("int", "int | None", "float", "float | None", "bool")
            and f.name not in ("timestamp", "channel", "chat_id", "mode")
        )

    def __init__(self, log_path: Path):
        self._log_path = log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """Path to the metrics JSONL file."""
        return self._log_path

    def record(self, metrics: ContextMetrics) -> None:
        """Append one metrics row to JSONL."""
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(metrics), ensure_ascii=False) + "\n")

    def get_summary(self, last_n: int = 50) -> dict[str, Any]:
        """Return min/max/median/p90 summary for the most recent rows."""
        rows = self._load_recent(last_n)
        result: dict[str, Any] = {"count": len(rows), "fields": {}}
        if not rows:
            return result

        for field_name in self._numeric_fields():
            values = [
                row[field_name] for row in rows if isinstance(row.get(field_name), int | float)
            ]
            if not values:
                continue
            values = sorted(values)
            result["fields"][field_name] = {
                "min": values[0],
                "max": values[-1],
                "median": median(values),
                "p90": _percentile(values, 0.9),
            }
        return result

    def get_latest(
        self,
        *,
        channel: str | None = None,
        chat_id: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the latest row optionally filtered by channel/chat/mode."""
        rows = self._load_recent(0)
        for row in reversed(rows):
            if channel and row.get("channel") != channel:
                continue
            if chat_id and row.get("chat_id") != chat_id:
                continue
            if mode and row.get("mode") != mode:
                continue
            return row
        return None

    def _load_recent(self, last_n: int) -> list[dict[str, Any]]:
        if not self._log_path.exists():
            return []

        rows: list[dict[str, Any]] = []
        with self._log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if last_n <= 0:
            return rows
        return rows[-last_n:]


def _percentile(sorted_values: list[float], p: float) -> float:
    """Return percentile value using nearest-rank with linear interpolation."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    idx = (len(sorted_values) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac
