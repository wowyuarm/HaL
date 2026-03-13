from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from hal.runtime.engine.inspect import build_context_inspection


async def test_build_context_inspection_uses_mounted_threads() -> None:
    provider = MagicMock()
    provider.resolve_model.return_value = "test-model"

    tools_registry = MagicMock()
    tools_registry.get_definitions.return_value = []

    history_config = SimpleNamespace(
        memory_budget_tokens=0,
        recall_max_total_tokens=500,
        recall_max_per_item_tokens=125,
    )
    compiled = SimpleNamespace(
        messages=[{"role": "system", "content": "sys"}],
        search_results=[],
        baseline_created=False,
        baseline_thread_slugs={"alpha-thread"},
        recalled_thread_slugs=set(),
    )

    with patch("hal.runtime.engine.inspect.ContextCompiler") as compiler_cls:
        compiler = compiler_cls.return_value
        compiler.compile_session_turn = AsyncMock(return_value=compiled)

        payload = await build_context_inspection(
            provider=provider,
            model="demo-model",
            memory=MagicMock(),
            context_builder=MagicMock(),
            context_registry=MagicMock(),
            tools_registry=tools_registry,
            memory_search=None,
            auto_inject_top_k=3,
            recall_min_score=0.0,
            history_config=history_config,
            channel="telegram",
            chat_id="42",
            session_id="s_telegram_42",
            session_history=[{"role": "assistant", "content": "older"}],
            mounted_threads={"alpha-thread"},
            current_message="inspect",
            mode="default",
        )

    request = compiler.compile_session_turn.await_args.args[0]
    assert request.mounted_threads == {"alpha-thread"}
    assert payload["baseline_created"] is False
    assert payload["baseline_thread_slugs"] == ["alpha-thread"]
    assert payload["recalled_thread_slugs"] == []
    assert payload["history_config"]["memory_budget_tokens"] == 0
    assert payload["history_config"]["recall_max_total_tokens"] == 500
    assert payload["history_config"]["recall_max_per_item_tokens"] == 125
