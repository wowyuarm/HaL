"""Tests for context metrics collection and loop usage capture."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.capabilities.tools.registry import ToolRegistry
from hal.core.context.metrics import ContextMetrics, MetricsCollector
from hal.core.runtime.loop import run_tool_loop
from hal.infra.providers.base import LLMProvider, LLMResponse


def test_metrics_collector_record_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "context_metrics.jsonl"
    collector = MetricsCollector(path)
    row = ContextMetrics.create(
        channel="cli",
        chat_id="direct",
        mode="collab",
        system_prompt_chars=123,
        total_input_chars=456,
    )

    collector.record(row)

    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["channel"] == "cli"
    assert data["chat_id"] == "direct"
    assert data["system_prompt_chars"] == 123
    assert data["total_input_chars"] == 456
    assert data["first_prompt_tokens"] is None  # not set in this row


def test_metrics_collector_summary_returns_stats(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "context_metrics.jsonl"
    collector = MetricsCollector(path)

    for value in (10, 20, 40, 80):
        collector.record(
            ContextMetrics.create(
                channel="cli",
                chat_id="direct",
                mode="collab",
                total_input_chars=value,
                loop_iterations=value // 10,
            )
        )

    summary = collector.get_summary(last_n=4)
    assert summary["count"] == 4
    assert summary["fields"]["total_input_chars"]["min"] == 10
    assert summary["fields"]["total_input_chars"]["max"] == 80
    assert summary["fields"]["total_input_chars"]["median"] == 30
    assert summary["fields"]["loop_iterations"]["p90"] == pytest.approx(6.8)


def test_metrics_collector_get_latest_with_filters(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "context_metrics.jsonl"
    collector = MetricsCollector(path)

    collector.record(
        ContextMetrics.create(channel="cli", chat_id="a", mode="collab", total_input_chars=10)
    )
    collector.record(
        ContextMetrics.create(channel="telegram", chat_id="1", mode="collab", total_input_chars=20)
    )
    collector.record(
        ContextMetrics.create(channel="telegram", chat_id="2", mode="operator", total_input_chars=30)
    )

    latest_tg = collector.get_latest(channel="telegram")
    assert latest_tg is not None
    assert latest_tg["chat_id"] == "2"

    latest_tg_collab = collector.get_latest(channel="telegram", mode="collab")
    assert latest_tg_collab is not None
    assert latest_tg_collab["chat_id"] == "1"

    none_match = collector.get_latest(channel="discord")
    assert none_match is None


def test_metrics_collector_get_latest_require_usage(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "context_metrics.jsonl"
    collector = MetricsCollector(path)

    collector.record(
        ContextMetrics.create(channel="telegram", chat_id="1", mode="collab", total_input_chars=10)
    )
    collector.record(
        ContextMetrics.create(
            channel="telegram",
            chat_id="1",
            mode="collab",
            total_input_chars=20,
            first_prompt_tokens=101,
            first_completion_tokens=22,
            first_total_tokens=123,
        )
    )
    collector.record(
        ContextMetrics.create(channel="telegram", chat_id="1", mode="collab", total_input_chars=30)
    )

    latest = collector.get_latest(channel="telegram", chat_id="1", mode="collab")
    assert latest is not None
    assert latest["total_input_chars"] == 30
    assert latest["first_prompt_tokens"] is None

    latest_with_usage = collector.get_latest(
        channel="telegram",
        chat_id="1",
        mode="collab",
        require_usage=True,
    )
    assert latest_with_usage is not None
    assert latest_with_usage["total_input_chars"] == 20
    assert latest_with_usage["first_prompt_tokens"] == 101


@pytest.mark.asyncio
async def test_run_tool_loop_records_first_response_usage() -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="done",
            tool_calls=[],
            usage={"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133},
            finish_reason="stop",
        )
    )

    final_content, meta = await run_tool_loop(
        provider=provider,
        model="test-model",
        tools=ToolRegistry(),
        messages=[{"role": "system", "content": "test"}],
        max_iterations=2,
    )

    assert final_content == "done"
    assert meta.first_response_usage == {
        "prompt_tokens": 111,
        "completion_tokens": 22,
        "total_tokens": 133,
    }
    assert meta.total_usage == {
        "prompt_tokens": 111,
        "completion_tokens": 22,
        "total_tokens": 133,
    }
