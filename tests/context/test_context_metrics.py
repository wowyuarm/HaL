"""Tests for context metrics collection and loop usage capture."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hal.capabilities.tools.registry import ToolRegistry
from hal.context.metrics import ContextMetrics, MetricsCollector
from hal.infra.providers.base import LLMProvider, LLMResponse
from hal.runtime.loop import _normalize_usage, run_tool_loop


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
    assert data["estimated_input_tokens"] == 0
    assert data["prompt_tokens"] is None
    assert data["completion_tokens"] is None
    assert data["total_tokens"] is None
    assert data["usage_available"] is False
    assert data["usage_source"] == "none"


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
        ContextMetrics.create(channel="telegram", chat_id="2", mode="default", total_input_chars=30)
    )

    latest_tg = collector.get_latest(channel="telegram")
    assert latest_tg is not None
    assert latest_tg["chat_id"] == "2"

    latest_tg_collab = collector.get_latest(channel="telegram", mode="collab")
    assert latest_tg_collab is not None
    assert latest_tg_collab["chat_id"] == "1"

    latest_tg_default = collector.get_latest(channel="telegram", mode="default")
    assert latest_tg_default is not None
    assert latest_tg_default["chat_id"] == "2"

    none_match = collector.get_latest(channel="discord")
    assert none_match is None


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


@pytest.mark.asyncio
async def test_run_tool_loop_records_cache_usage_counters() -> None:
    provider = MagicMock(spec=LLMProvider)
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="done",
            tool_calls=[],
            usage={
                "prompt_tokens": 200,
                "completion_tokens": 20,
                "total_tokens": 220,
                "cache_creation_input_tokens": 160,
                "cache_read_input_tokens": 0,
                "prompt_cache_miss_tokens": 40,
            },
            finish_reason="stop",
        )
    )

    final_content, meta = await run_tool_loop(
        provider=provider,
        model="test-model",
        tools=ToolRegistry(),
        messages=[{"role": "system", "content": "test"}],
        max_iterations=1,
    )

    assert final_content == "done"
    assert meta.cache_creation_tokens == 160
    assert meta.cache_read_tokens == 0
    assert meta.cache_miss_tokens == 40
    assert meta.total_usage["cache_creation_input_tokens"] == 160
    assert meta.total_usage["cache_read_input_tokens"] == 0
    assert meta.total_usage["prompt_cache_miss_tokens"] == 40


def test_normalize_usage_reads_prompt_tokens_details_cached_tokens() -> None:
    normalized = _normalize_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 48},
        }
    )

    assert normalized["prompt_tokens"] == 100
    assert normalized["completion_tokens"] == 20
    assert normalized["total_tokens"] == 120
    assert normalized["cache_read_input_tokens"] == 48


def test_normalize_usage_reads_prompt_cache_miss_tokens() -> None:
    normalized = _normalize_usage(
        {
            "prompt_tokens": 140,
            "completion_tokens": 20,
            "total_tokens": 160,
            "prompt_cache_miss_tokens": 60,
        }
    )

    assert normalized["prompt_cache_miss_tokens"] == 60


def test_normalize_usage_reads_anthropic_input_output_tokens() -> None:
    normalized = _normalize_usage(
        {
            "input_tokens": 91,
            "output_tokens": 13,
        }
    )

    assert normalized["prompt_tokens"] == 91
    assert normalized["completion_tokens"] == 13
    assert normalized["total_tokens"] == 104
