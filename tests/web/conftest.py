from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hal.bus.queue import MessageBus
from hal.infra.providers.base import LLMProvider
from hal.runtime.engine import AgentEngine, LoopMetadata
from hal.web import SessionBridge
from hal.workspace.threads import ThreadRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def mock_provider() -> MagicMock:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.resolve_model.return_value = "test-model"
    return provider


@pytest.fixture
def engine(workspace: Path, mock_provider: MagicMock) -> AgentEngine:
    with (
        patch("hal.runtime.engine.ContextBuilder") as mock_ctx,
        patch("hal.runtime.engine.MemoryManager") as mock_mem,
        patch("hal.runtime.engine.SubagentManager"),
    ):
        builder_instance = mock_ctx.return_value
        builder_instance.registry = MagicMock()
        builder_instance.registry.thread_snapshot.return_value = []
        builder_instance.registry.skill_snapshot.return_value = []

        engine = AgentEngine(
            bus=MessageBus(),
            provider=mock_provider,
            workspace=workspace,
            memory_manager=mock_mem.return_value,
        )
        engine.subagents.await_pending = AsyncMock(return_value=[])
        engine.context_compiler.compile_session_turn = AsyncMock(
            return_value=SimpleNamespace(
                messages=[
                    {"role": "system", "content": "You are HaL."},
                    {"role": "user", "content": "hello"},
                ],
                search_results=[],
                recalled_thread_slugs=set(),
                baseline_thread_slugs={"auth"},
            )
        )
        engine._execute_loop = AsyncMock(
            return_value=(
                "Final answer",
                LoopMetadata(
                    iterations=1, total_usage={"prompt_tokens": 10, "completion_tokens": 5}
                ),
                [],
            )
        )
        engine._store_session_snapshot = MagicMock()
        return engine


@pytest.fixture
def thread_repo(workspace: Path) -> ThreadRepository:
    return ThreadRepository(workspace)


@pytest.fixture
def bridge(engine: AgentEngine) -> SessionBridge:
    return SessionBridge(engine)


def create_thread(repo: ThreadRepository, slug: str, title: str) -> None:
    repo.write_state(
        slug,
        f"# {title}\nStatus: active\n\n## Purpose\nThread for {title}.\n",
    )
