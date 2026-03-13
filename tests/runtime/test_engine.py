"""Tests for AgentEngine (hal/core/engine.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hal.bus.events import InboundMessage, OutboundMessage, SubagentCompleteEvent
from hal.bus.queue import MessageBus
from hal.context.message_building import add_assistant_message, add_tool_result
from hal.infra.config.schema import ChannelsConfig, TelegramConfig
from hal.infra.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from hal.runtime.engine import (
    AgentEngine,
    LoopMetadata,
    _build_subagent_injection,
    _split_subagent_tool_result,
)
from hal.runtime.session import slim_messages_for_replay

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def mock_provider():
    """A mock LLMProvider whose chat() returns a simple text response."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"

    response = LLMResponse(content="Hello from the agent", tool_calls=[], finish_reason="stop")
    provider.chat = AsyncMock(return_value=response)
    return provider


@pytest.fixture
def bus():
    return MessageBus()


@pytest.fixture
def engine(bus, mock_provider, workspace):
    """Build an AgentEngine with all heavy dependencies mocked."""
    with (
        patch("hal.runtime.engine.ContextBuilder") as mock_ctx,
        patch("hal.runtime.engine.MemoryManager") as mock_mem,
        patch("hal.runtime.engine.SubagentManager"),
    ):
        # ContextBuilder.build_messages returns minimal message list
        builder_instance = mock_ctx.return_value
        builder_instance.build_messages.return_value = [
            {"role": "system", "content": "You are a test agent."},
        ]
        builder_instance.build_system_prompt.return_value = "You are a test agent."
        builder_instance.build_dynamic_context_block.return_value = "<context>ctx</context>"
        builder_instance.build_session_baseline_message.side_effect = lambda baseline: {
            "role": "user",
            "content": f"[Session Baseline Context]\n{baseline}",
        }
        builder_instance.registry = MagicMock()
        builder_instance.registry.thread_snapshot.return_value = []
        builder_instance.registry.skill_snapshot.return_value = []

        # MemoryManager stub
        mem_instance = mock_mem.return_value

        eng = AgentEngine(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            memory_manager=mem_instance,
        )
        # Ensure subagents.await_pending() is awaitable and returns no results
        eng.subagents.await_pending = AsyncMock(return_value=[])
        yield eng


def _set_telegram_progress_policy(
    engine: AgentEngine, *, send_progress: bool, send_tool_hints: bool
) -> None:
    engine._channels_config = ChannelsConfig(
        telegram=TelegramConfig(
            enabled=True,
            send_progress=send_progress,
            send_tool_hints=send_tool_hints,
        )
    )


_LOOP_TEST_MESSAGES = [{"role": "system", "content": "x"}]
_TELEGRAM_TEST_CHANNEL = "telegram"
_TELEGRAM_TEST_CHAT_ID = "c1"


def _create_session(
    engine: AgentEngine,
    *,
    channel: str = _TELEGRAM_TEST_CHANNEL,
    chat_id: str = _TELEGRAM_TEST_CHAT_ID,
) -> str:
    """Create a session and return its session_id."""
    return engine.create_session(channel=channel, chat_id=chat_id).session_id


def _capture_outbound_messages(engine: AgentEngine) -> list[OutboundMessage]:
    """Patch bus.publish_outbound to collect messages for assertions."""
    outbound_messages: list[OutboundMessage] = []

    async def capture_outbound(msg: OutboundMessage) -> None:
        outbound_messages.append(msg)

    engine.bus.publish_outbound = AsyncMock(side_effect=capture_outbound)  # type: ignore[method-assign]
    return outbound_messages


async def _run_telegram_loop_with_outbound_capture(
    engine: AgentEngine,
    mock_provider: MagicMock,
    *,
    responses: list[LLMResponse],
    max_iterations: int = 5,
) -> list[OutboundMessage]:
    """Execute one telegram loop and return all outbound messages."""
    engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]
    outbound_messages = _capture_outbound_messages(engine)
    session_id = _create_session(
        engine, channel=_TELEGRAM_TEST_CHANNEL, chat_id=_TELEGRAM_TEST_CHAT_ID
    )
    mock_provider.chat.side_effect = responses
    await engine._execute_loop(
        messages=list(_LOOP_TEST_MESSAGES),
        max_iterations=max_iterations,
        session_id=session_id,
    )
    return outbound_messages


def _progress_messages(
    outbound_messages: list[OutboundMessage], *, kind: str | None = None
) -> list[OutboundMessage]:
    """Filter captured outbound messages to progress notifications."""
    progress = [msg for msg in outbound_messages if msg.metadata.get("progress")]
    if kind is None:
        return progress
    return [msg for msg in progress if msg.metadata.get("progress_kind") == kind]


# ------------------------------------------------------------------
# Init & alias
# ------------------------------------------------------------------


class TestAgentEngineInit:
    def test_attributes_created(self, engine, bus, mock_provider, workspace):
        assert engine.bus is bus
        assert engine.provider is mock_provider
        assert engine.workspace == workspace
        assert engine.model == "test-model"
        assert engine.max_iterations == 20
        assert engine._running is False


# ------------------------------------------------------------------
# Tool registration
# ------------------------------------------------------------------


class TestRegisterDefaultTools:
    def test_expected_tools_registered(self, engine):
        expected = {"fs", "exec", "web_search", "web_fetch", "message", "spawn"}
        registered = set(engine.tools.tool_names)
        assert expected.issubset(registered), f"Missing tools: {expected - registered}"


# ------------------------------------------------------------------
# _update_tool_contexts
# ------------------------------------------------------------------


class TestUpdateToolContexts:
    def test_sets_context_on_message_and_spawn(self, engine):
        engine._update_tool_contexts("telegram", "chat123")

        msg_tool = engine.tools.get("message")
        assert msg_tool._default_channel == "telegram"
        assert msg_tool._default_chat_id == "chat123"

        spawn_tool = engine.tools.get("spawn")
        assert spawn_tool._origin_channel == "telegram"
        assert spawn_tool._origin_chat_id == "chat123"


# ------------------------------------------------------------------
# process_direct routing
# ------------------------------------------------------------------


class TestProcessDirect:
    async def test_regular_session_routes_to_process(self, engine):
        """Direct sessions should be handled by process()."""
        with patch.object(engine, "process", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = OutboundMessage(
                channel="cli", chat_id="direct", content="process result"
            )

            result = await engine.process_direct(
                content="hello",
                session_key="cli:direct",
            )

            mock_process.assert_awaited_once()
            # process_direct extracts .content from the OutboundMessage
            assert result == "process result"


# ------------------------------------------------------------------
# stop()
# ------------------------------------------------------------------


class TestStop:
    def test_stop_sets_running_false(self, engine):
        engine._running = True
        engine.stop()
        assert engine._running is False


# ------------------------------------------------------------------
# Core behavior
# ------------------------------------------------------------------


class TestDispatch:
    async def test_dispatch_routes_to_process(self, engine):
        msg = InboundMessage(channel="telegram", sender_id="u", chat_id="c", content="hi")
        engine.process = AsyncMock(return_value=None)  # type: ignore[method-assign]

        await engine._dispatch(msg)
        engine.process.assert_awaited_once_with(msg)

    async def test_defaults_final_content_when_execute_loop_returns_none(self, engine):
        engine._execute_loop = AsyncMock(return_value=(None, LoopMetadata(tools_used=["fs"]), []))  # type: ignore[method-assign]

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
        out = await engine.process(msg)

        assert out is not None
        assert out.channel == "telegram"
        assert out.chat_id == "c1"
        assert out.content == "(No response generated.)"

    async def test_error_response_is_not_written_to_history(self, engine):
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            return_value=("Error calling LLM: APIConnectionError", LoopMetadata(), [])
        )

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
        out = await engine.process(msg)

        assert out is not None
        assert out.content.startswith("Error calling LLM:")

    def test_session_reuses_existing_state_for_same_inbound_route(self, engine):
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
        first = engine._ensure_session_for_inbound(msg)
        second = engine._ensure_session_for_inbound(msg)

        assert second.session_id == first.session_id
        assert engine._session_routes[msg.session_key] == first.session_id

    def test_stop_keeps_active_sessions_without_ending_them(self, engine):
        state = engine.create_session(channel="telegram", chat_id="c1")

        engine.stop()

        # Sessions remain in memory as active; no ended_at set
        assert state.session_id in engine._sessions
        assert state.manifest.status == "active"
        assert state.manifest.ended_at is None

    def test_restores_active_sessions_from_workspace(self, bus, mock_provider, workspace):
        session_dir = workspace / "work" / "sessions" / "s_existing"
        session_dir.mkdir(parents=True)
        (session_dir / "manifest.json").write_text(
            """\
{
  "session_id": "s_existing",
  "status": "active",
  "created_at": "2026-03-10T10:00:00",
  "primary_thread": "alpha",
  "mounted_threads": ["alpha"],
  "touched_threads": ["alpha"],
  "turn_count": 0,
  "last_event_seq": 0
}""",
            encoding="utf-8",
        )

        with (
            patch("hal.runtime.engine.ContextBuilder") as mock_ctx,
            patch("hal.runtime.engine.MemoryManager") as mock_mem,
            patch("hal.runtime.engine.SubagentManager"),
        ):
            builder_instance = mock_ctx.return_value
            builder_instance.build_messages.return_value = [
                {"role": "system", "content": "You are a test agent."},
            ]
            builder_instance.build_system_prompt.return_value = "You are a test agent."
            builder_instance.build_dynamic_context_block.return_value = "<context>ctx</context>"
            builder_instance.build_session_baseline_message.side_effect = lambda baseline: {
                "role": "user",
                "content": f"[Session Baseline Context]\n{baseline}",
            }
            builder_instance.registry = MagicMock()
            builder_instance.registry.thread_snapshot.return_value = []
            builder_instance.registry.skill_snapshot.return_value = []

            restored = AgentEngine(
                bus=bus,
                provider=mock_provider,
                workspace=workspace,
                memory_manager=mock_mem.return_value,
            )

        # Session should be eagerly restored by __init__ (via _restore_active_sessions)
        assert "s_existing" in restored._sessions
        state = restored._sessions["s_existing"]
        assert state.session_id == "s_existing"
        assert state.primary_thread == "alpha"
        assert state.mounted_threads == {"alpha"}
        assert state.touched_threads == {"alpha"}

    async def test_process_uses_in_memory_session_history(self, engine):
        engine.context.build_messages.side_effect = (  # type: ignore[method-assign]
            lambda *, history, current_message, **kwargs: [
                {"role": "system", "content": "sys"},
                *history,
                {"role": "user", "content": current_message},
            ]
        )
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                ("reply-1", LoopMetadata(), []),
                ("reply-2", LoopMetadata(), []),
            ]
        )

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
        await engine.process(msg)
        await engine.process(msg)

        second_turn_messages = engine._execute_loop.await_args_list[1].args[0]
        assert any(
            m.get("role") == "assistant" and m.get("content") == "reply-1"
            for m in second_turn_messages
        )
        engine.memory.get_conversation_history.assert_not_called()

    async def test_session_baseline_recompiled_each_turn(self, engine):
        engine.context.build_messages.side_effect = (  # type: ignore[method-assign]
            lambda *, history, current_message, session_baseline=None, **kwargs: [
                {"role": "system", "content": "sys"},
                *(
                    [{"role": "user", "content": f"[Session Baseline Context]\n{session_baseline}"}]
                    if session_baseline
                    else []
                ),
                *history,
                {"role": "user", "content": current_message},
            ]
        )
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                ("reply-1", LoopMetadata(), []),
                ("reply-2", LoopMetadata(), []),
            ]
        )

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
        await engine.process(msg)
        await engine.process(msg)

        assert engine.context.build_dynamic_context_block.call_count == 2
        second_turn_messages = engine._execute_loop.await_args_list[1].args[0]
        baseline_messages = [
            m
            for m in second_turn_messages
            if str(m.get("content", "")).startswith("[Session Baseline Context]")
        ]
        assert len(baseline_messages) == 1

    async def test_brief_command_starts_background_worker(self, engine):
        """Sending /brief records events, creates a brief_task, and returns ack."""
        state = engine.create_session(channel="telegram", chat_id="c1")
        engine._run_session_brief = AsyncMock()  # type: ignore[method-assign]

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/brief")
        out = await engine.process(msg)

        assert out is not None
        assert out.metadata.get("kind") == "session_brief_start"
        assert "Starting session brief" in out.content
        assert state.brief_task is not None

    async def test_brief_command_with_prompt(self, engine):
        """Sending /brief with extra text passes the prompt to the worker."""
        engine.create_session(channel="telegram", chat_id="c1")
        engine._run_session_brief = AsyncMock()  # type: ignore[method-assign]

        msg = InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="c1",
            content="/brief focus on architecture decisions",
        )
        out = await engine.process(msg)

        assert out is not None
        assert out.metadata.get("kind") == "session_brief_start"


class TestSessionCompaction:
    async def test_compacts_history_when_token_budget_exceeded(self, engine):
        session_id = _create_session(engine)
        engine._engine_config.session.compaction_enabled = True
        engine._engine_config.session.compaction_token_budget = 80
        engine._engine_config.session.compaction_recent_user_turns = 1
        engine._engine_config.session.compaction_checkpoint_tokens = 200

        history = [
            {"role": "user", "content": "old request " * 20},
            {"role": "assistant", "content": "old answer " * 20},
            {"role": "user", "content": "older request " * 20},
            {"role": "assistant", "content": "older answer " * 20},
            {"role": "user", "content": "latest request"},
            {"role": "assistant", "content": "latest answer"},
        ]

        compacted = await engine._maybe_compact_session_history(
            session_id=session_id,
            history=history,
            token_model="test-model",
        )
        # Allow event publisher tasks to flush
        await asyncio.sleep(0)

        assert len(compacted) < len(history)
        assert compacted[0]["role"] == "assistant"
        assert "[Session Checkpoint]" in str(compacted[0]["content"])
        assert any(m.get("content") == "latest request" for m in compacted)

    async def test_skips_compaction_when_under_budget(self, engine):
        session_id = _create_session(engine)
        engine._engine_config.session.compaction_enabled = True
        engine._engine_config.session.compaction_token_budget = 10000

        history = [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": "ok"},
        ]

        compacted = await engine._maybe_compact_session_history(
            session_id=session_id,
            history=history,
            token_model="test-model",
        )

        assert compacted == history

    async def test_compaction_counts_tool_call_payloads_in_budget(self, engine):
        session_id = _create_session(engine)
        engine._engine_config.session.compaction_enabled = True
        engine._engine_config.session.compaction_token_budget = 120
        engine._engine_config.session.compaction_recent_user_turns = 1
        engine._engine_config.session.compaction_checkpoint_tokens = 200

        history = [
            {"role": "user", "content": "look it up"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {"name": "fs", "arguments": '{"path":"' + ("x" * 800) + '"}'},
                    }
                ],
                "reasoning_content": "Need to inspect context before proceeding.",
            },
            {"role": "tool", "name": "fs", "content": "ok"},
            {"role": "user", "content": "latest request"},
            {"role": "assistant", "content": "latest answer"},
        ]

        compacted = await engine._maybe_compact_session_history(
            session_id=session_id,
            history=history,
            token_model="test-model",
        )

        assert compacted[0]["role"] == "assistant"
        assert "[Session Checkpoint]" in str(compacted[0]["content"])

    async def test_compacts_history_when_request_bytes_threshold_exceeded(self, engine):
        session_id = _create_session(engine)
        engine._engine_config.session.compaction_enabled = True
        engine._engine_config.session.compaction_token_budget = 10000
        engine._engine_config.session.compaction_request_bytes_threshold = 900
        engine._engine_config.session.compaction_recent_user_turns = 1
        engine._engine_config.session.history_image_replay = "full"
        engine._engine_config.session.tool_result_replay_max_bytes = 0

        history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + ("a" * 2000)},
                    },
                    {"type": "text", "text": "first image"},
                ],
            },
            {"role": "assistant", "content": "describe it"},
            {"role": "user", "content": "latest request"},
            {"role": "assistant", "content": "latest answer"},
        ]

        compacted = await engine._maybe_compact_session_history(
            session_id=session_id,
            history=history,
            token_model="test-model",
        )

        assert compacted[0]["role"] == "assistant"
        assert "[Session Checkpoint]" in str(compacted[0]["content"])

    async def test_request_preflight_slims_old_image_history_before_execute_loop(self, engine):
        engine.context.build_messages.side_effect = (  # type: ignore[method-assign]
            lambda *, history, current_message, **kwargs: [
                {"role": "system", "content": "sys"},
                *history,
                {"role": "user", "content": current_message},
            ]
        )
        engine._engine_config.session.compaction_request_bytes_threshold = 1200
        engine._engine_config.session.history_image_replay = "summary"
        engine._engine_config.session.tool_result_replay_max_bytes = 12_000
        engine._execute_loop = AsyncMock(return_value=("done", LoopMetadata(), []))  # type: ignore[method-assign]

        state = engine.create_session(channel="telegram", chat_id="c1")
        state.replay_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + ("b" * 2500)},
                    },
                    {"type": "text", "text": "old screenshot"},
                ],
            },
            {"role": "assistant", "content": "saw it"},
        ]

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="continue")
        await engine.process(msg)

        sent_messages = engine._execute_loop.await_args.args[0]
        replayed_history_user = sent_messages[1]
        assert replayed_history_user["role"] == "user"
        assert isinstance(replayed_history_user["content"], str)
        assert "prior image omitted" in replayed_history_user["content"]


class TestRequestReplaySlimming:
    def test_slim_messages_for_replay_truncates_long_tool_results(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "name": "fs", "content": "x" * 5000},
            {"role": "user", "content": "latest"},
        ]

        slimmed, changed = slim_messages_for_replay(
            messages,
            image_replay_mode="summary",
            tool_result_max_bytes=500,
        )

        assert changed is True
        assert isinstance(slimmed[1]["content"], str)
        assert len(slimmed[1]["content"].encode("utf-8")) <= 500 + 64
        assert slimmed[2]["content"] == "latest"


class TestThreadTouching:
    def test_detect_thread_mentions_matches_slug_and_title(self, engine):
        engine.context_registry.thread_snapshot.return_value = [  # type: ignore[method-assign]
            {
                "slug": "github-actions",
                "name": "GitHub Actions",
                "status": "active",
                "description": "workflow work",
                "state_path": "threads/github-actions/BRIEF.md",
            }
        ]

        assert engine._detect_thread_mentions("Actions that one, continue it") == {"github-actions"}

    async def test_active_baseline_threads_marked_touched_after_substantive_work(self, engine):
        engine.context_registry.thread_snapshot.return_value = [  # type: ignore[method-assign]
            {
                "slug": "github-actions",
                "name": "GitHub Actions",
                "status": "active",
                "description": "workflow work",
                "state_path": "threads/github-actions/BRIEF.md",
            }
        ]
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            return_value=("done", LoopMetadata(tools_used=["fs"]), [])
        )

        msg = InboundMessage(
            channel="telegram", sender_id="u1", chat_id="c1", content="please continue"
        )
        await engine.process(msg)

        state = engine._sessions[engine._session_routes[msg.session_key]]
        assert "github-actions" in state.touched_threads


class TestBackgroundResume:
    async def test_finalize_resumed_turn_updates_session_history_and_publishes_outbound(
        self, engine
    ):
        session_id = _create_session(engine)
        engine.bus.publish_outbound = AsyncMock()  # type: ignore[method-assign]

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "[Session Baseline Context]\n<context>ctx</context>"},
            {"role": "user", "content": "work on it"},
            {"role": "assistant", "content": "done"},
        ]

        await engine._background_resume._finalize_resumed_turn(
            session_id=session_id,
            messages=messages,
            final_content="background reply",
            meta=LoopMetadata(),
        )

        history = engine._get_session_history(session_id)
        assert all(
            "[Session Baseline Context]" not in str(item.get("content", "")) for item in history
        )
        assert history[-1]["content"] == "background reply"
        engine.bus.publish_outbound.assert_awaited_once()

    def test_load_resume_snapshot_falls_back_to_session_repository(self, engine):
        session_id = _create_session(engine)
        engine._background_resume.store_session_snapshot(
            session_id=session_id,
            channel="telegram",
            chat_id="c1",
            messages=[{"role": "system", "content": "sys"}],
            final_content="assistant reply",
        )
        engine._background_resume._session_snapshots.clear()
        engine._background_resume._session_routes.clear()

        loaded = engine._background_resume._load_resume_snapshot(session_id)

        assert loaded is not None
        assert loaded[-1]["content"] == "assistant reply"
        assert engine._background_resume._session_routes[session_id] == ("telegram", "c1")

    def test_clear_session_snapshot_removes_cache_and_repository_copy(self, engine):
        session_id = _create_session(engine, channel="telegram", chat_id="c2")
        engine._background_resume.store_session_snapshot(
            session_id=session_id,
            channel="telegram",
            chat_id="c2",
            messages=[{"role": "user", "content": "hello"}],
            final_content=None,
        )

        assert engine._background_resume._load_resume_snapshot(session_id) is not None
        engine._background_resume.clear_session_snapshot(session_id)
        assert engine._background_resume._load_resume_snapshot(session_id) is None


class TestExecuteLoop:
    async def test_tool_calls_are_executed_and_tools_used_is_deduped(self, engine, mock_provider):
        engine.tools.execute = AsyncMock(return_value="tool ok")  # type: ignore[method-assign]

        tool_calls = [
            ToolCallRequest(id="t1", name="web_search", arguments={"query": "a"}),
            ToolCallRequest(id="t2", name="web_search", arguments={"query": "b"}),
            ToolCallRequest(id="t3", name="fs", arguments={"action": "list", "path": "."}),
        ]

        mock_provider.chat.side_effect = [
            LLMResponse(content="calling tools", tool_calls=tool_calls),
            LLMResponse(content="final", tool_calls=[]),
        ]

        with (
            patch(
                "hal.runtime.engine.add_assistant_message", wraps=add_assistant_message
            ) as add_assistant,
            patch("hal.runtime.engine.add_tool_result", wraps=add_tool_result) as add_tool,
        ):
            final, meta, injected = await engine._execute_loop(
                messages=[{"role": "system", "content": "x"}],
                max_iterations=3,
            )

            assert add_assistant.call_count == 1
            assert add_tool.call_count == 3

        assert final == "final"
        assert meta.tools_used == ["web_search", "fs"]
        assert meta.iterations == 2
        assert injected == []
        assert engine.tools.execute.await_count == 3

    async def test_nudge_on_empty_response_after_tool_calls(self, engine, mock_provider):
        """When LLM returns empty content after tool work, the loop injects a nudge and retries."""
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "read", "path": "x"}),
        ]

        # Turn 1: tool call, Turn 2: empty (triggers nudge), Turn 3: real reply
        mock_provider.chat.side_effect = [
            LLMResponse(content=None, tool_calls=tool_calls),
            LLMResponse(content=None, tool_calls=[]),
            LLMResponse(content="here is the file", tool_calls=[]),
        ]

        final, meta, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
        )

        assert final == "here is the file"
        assert meta.iterations == 3
        assert mock_provider.chat.await_count == 3
        # Verify nudge message was appended
        third_call_msgs = mock_provider.chat.await_args_list[2].kwargs["messages"]
        nudge_msgs = [
            m
            for m in third_call_msgs
            if m.get("role") == "user" and "[System]" in m.get("content", "")
        ]
        assert len(nudge_msgs) == 1

    async def test_nudge_only_fires_once(self, engine, mock_provider):
        """Nudge is a one-shot retry — if the second attempt is also empty, loop exits."""
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "read", "path": "x"}),
        ]

        # Turn 1: tool call, Turn 2: empty (nudge), Turn 3: still empty (exits)
        mock_provider.chat.side_effect = [
            LLMResponse(content=None, tool_calls=tool_calls),
            LLMResponse(content=None, tool_calls=[]),
            LLMResponse(content=None, tool_calls=[]),
        ]

        final, meta, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
        )

        assert final is None
        assert meta.iterations == 3

    async def test_empty_response_without_tools_retries_once(self, engine, mock_provider):
        """Empty response before tool calls should get one lightweight retry."""
        mock_provider.chat.side_effect = [
            LLMResponse(content=None, tool_calls=[]),
            LLMResponse(content=None, tool_calls=[]),
        ]

        final, meta, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
        )

        assert final is None
        assert meta.iterations == 2
        assert mock_provider.chat.await_count == 2

    async def test_context_advisor_injects_hint_on_next_round(self, engine, mock_provider):
        session_id = _create_session(engine)
        engine.context_registry.skill_snapshot.return_value = [
            {
                "kind": "skill",
                "key": "git-ops",
                "name": "git-ops",
                "description": "git ops",
                "available": True,
            }
        ]
        engine.context_registry.thread_snapshot.return_value = [
            {
                "slug": "github-actions",
                "name": "GitHub Actions",
                "status": "active",
                "description": "workflow",
                "state_path": "threads/github-actions/BRIEF.md",
            }
        ]

        worker_provider = MagicMock()
        worker_provider.chat = AsyncMock(
            return_value=LLMResponse(
                content='{"skills":["git-ops"],"threads":["github-actions"],"reason":"match"}',
                tool_calls=[],
                finish_reason="stop",
            )
        )
        engine.subagents.provider = worker_provider
        engine.subagents.model = "worker-model"
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        mock_provider.chat.side_effect = [
            LLMResponse(
                content="calling tools",
                tool_calls=[ToolCallRequest(id="t1", name="fs", arguments={"action": "read"})],
            ),
            LLMResponse(content="final answer", tool_calls=[]),
        ]

        final, meta, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}, {"role": "user", "content": "do task"}],
            max_iterations=5,
            session_id=session_id,
        )

        assert final == "final answer"
        assert meta.iterations == 2
        second_call_messages = mock_provider.chat.await_args_list[1].kwargs["messages"]
        assert any(
            m.get("role") == "user" and "[Context Hint]" in m.get("content", "")
            for m in second_call_messages
        )
        assert worker_provider.chat.await_count == 1

    async def test_context_advisor_runs_per_loop(self, engine, mock_provider):
        session_id = _create_session(engine)
        engine.context_registry.skill_snapshot.return_value = [
            {
                "kind": "skill",
                "key": "git-ops",
                "name": "git-ops",
                "description": "git ops",
                "available": True,
            }
        ]
        engine.context_registry.thread_snapshot.return_value = []

        worker_provider = MagicMock()
        worker_provider.chat = AsyncMock(
            return_value=LLMResponse(
                content='{"skills":["git-ops"],"threads":[],"reason":"match"}',
                tool_calls=[],
                finish_reason="stop",
            )
        )
        engine.subagents.provider = worker_provider
        engine.subagents.model = "worker-model"
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        mock_provider.chat.side_effect = [
            LLMResponse(
                content="call",
                tool_calls=[ToolCallRequest(id="a1", name="fs", arguments={"action": "read"})],
            ),
            LLMResponse(content="done", tool_calls=[]),
            LLMResponse(
                content="call2",
                tool_calls=[ToolCallRequest(id="a2", name="fs", arguments={"action": "read"})],
            ),
            LLMResponse(content="done2", tool_calls=[]),
        ]

        await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}, {"role": "user", "content": "first"}],
            max_iterations=5,
            session_id=session_id,
        )
        await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}, {"role": "user", "content": "second"}],
            max_iterations=5,
            session_id=session_id,
        )

        # Context advisor now runs once per loop invocation, not once per session
        assert worker_provider.chat.await_count == 2

    async def test_retryable_llm_error_retries_and_recovers(self, engine, mock_provider):
        mock_provider.chat.side_effect = [
            LLMResponse(
                content=None,
                tool_calls=[],
                finish_reason="error",
                error_message="litellm.APIConnectionError: network unstable",
                retryable=True,
            ),
            LLMResponse(content="recovered", tool_calls=[]),
        ]

        with patch("hal.runtime.loop.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            final, meta, _ = await engine._execute_loop(
                messages=[{"role": "system", "content": "x"}],
                max_iterations=5,
            )

        assert final == "recovered"
        assert meta.iterations == 1
        assert mock_provider.chat.await_count == 2
        mock_sleep.assert_awaited_once()

    async def test_retryable_llm_error_returns_error_after_retry_exhaustion(
        self, engine, mock_provider
    ):
        mock_provider.chat.side_effect = [
            LLMResponse(
                content=None,
                tool_calls=[],
                finish_reason="error",
                error_message="litellm.APIConnectionError: timeout",
                retryable=True,
            ),
            LLMResponse(
                content=None,
                tool_calls=[],
                finish_reason="error",
                error_message="litellm.APIConnectionError: timeout",
                retryable=True,
            ),
            LLMResponse(
                content=None,
                tool_calls=[],
                finish_reason="error",
                error_message="litellm.APIConnectionError: timeout",
                retryable=True,
            ),
        ]

        with patch("hal.runtime.loop.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            final, meta, _ = await engine._execute_loop(
                messages=[{"role": "system", "content": "x"}],
                max_iterations=5,
            )

        assert final is not None
        assert final.startswith("Error calling LLM:")
        assert "retried 2 times" in final
        assert meta.iterations == 1
        assert mock_provider.chat.await_count == 3
        assert mock_sleep.await_count == 2

    async def test_non_retryable_llm_error_does_not_retry(self, engine, mock_provider):
        mock_provider.chat.side_effect = [
            LLMResponse(
                content=None,
                tool_calls=[],
                finish_reason="error",
                error_message="invalid request",
                retryable=False,
            ),
            LLMResponse(content="should not be used", tool_calls=[]),
        ]

        with patch("hal.runtime.loop.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            final, meta, _ = await engine._execute_loop(
                messages=[{"role": "system", "content": "x"}],
                max_iterations=5,
            )

        assert final == "Error calling LLM: invalid request"
        assert meta.iterations == 1
        assert mock_provider.chat.await_count == 1
        mock_sleep.assert_not_awaited()


class TestMidLoopInjection:
    async def test_pending_messages_injected_into_loop(self, engine, bus, mock_provider):
        """Messages arriving mid-execution are injected as user messages."""
        # First call triggers tool use, second call returns final
        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."})
        ]
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        async def chat_side_effect(messages, tools, model):
            # On first call, enqueue a pending message to simulate user sending mid-loop
            if mock_provider.chat.await_count == 1:
                pending = InboundMessage(
                    channel="telegram", sender_id="alice", chat_id="c1", content="also check X"
                )
                await bus.publish_inbound(pending)
                return LLMResponse(content="calling tools", tool_calls=tool_calls)
            return LLMResponse(content="final", tool_calls=[])

        mock_provider.chat = AsyncMock(side_effect=chat_side_effect)

        session_id = _create_session(engine)
        final, meta, injected = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
            session_id=session_id,
        )

        assert final == "final"
        assert len(injected) == 1
        assert injected[0].content == "also check X"
        # Verify the prefix in messages sent to LLM on the second call
        second_call_msgs = mock_provider.chat.await_args_list[1].kwargs["messages"]
        injected_user_msgs = [
            m
            for m in second_call_msgs
            if m.get("role") == "user" and "[User follow-up" in m.get("content", "")
        ]
        assert len(injected_user_msgs) == 1

    async def test_non_matching_session_messages_are_requeued(self, engine, bus, mock_provider):
        """Messages for other sessions stay in the queue."""
        other_msg = InboundMessage(
            channel="discord", sender_id="bob", chat_id="d1", content="unrelated"
        )
        await bus.publish_inbound(other_msg)

        session_id = _create_session(engine)
        final, _, injected = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=1,
            session_id=session_id,
        )

        assert injected == []
        assert bus.inbound.qsize() == 1
        requeued = bus.inbound.get_nowait()
        assert requeued.content == "unrelated"

    def test_drain_empty_queue_returns_empty(self, engine):
        result = engine._drain_pending_for_session("telegram:c1")
        assert result == []

    async def test_interrupt_skips_tool_execution(self, engine, bus, mock_provider):
        """When >= 3 queued messages, tool calls are skipped with placeholder results."""
        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."}),
            ToolCallRequest(id="t2", name="exec", arguments={"command": "ls"}),
        ]
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        call_count = 0

        async def chat_side_effect(messages, tools, model):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Enqueue 3 messages to trigger interrupt
                for i in range(3):
                    await bus.publish_inbound(
                        InboundMessage(
                            channel="telegram",
                            sender_id="alice",
                            chat_id="c1",
                            content=f"stop msg {i}",
                        )
                    )
                return LLMResponse(content="calling tools", tool_calls=tool_calls)
            # Second call: LLM sees skipped results + user messages, returns final
            return LLMResponse(content="adjusted direction", tool_calls=[])

        mock_provider.chat = AsyncMock(side_effect=chat_side_effect)

        session_id = _create_session(engine)
        final, meta, injected = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
            session_id=session_id,
        )

        assert final == "adjusted direction"
        # Tools should NOT have been executed
        engine.tools.execute.assert_not_awaited()
        # 3 user messages should be injected
        assert len(injected) == 3
        # Skipped tool calls tracked in metadata
        assert meta.skipped_tool_calls == 2

    async def test_no_interrupt_below_threshold(self, engine, bus, mock_provider):
        """When < 3 queued messages, tools execute normally."""
        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."})
        ]
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        call_count = 0

        async def chat_side_effect(messages, tools, model):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Only 2 messages — below threshold
                for i in range(2):
                    await bus.publish_inbound(
                        InboundMessage(
                            channel="telegram",
                            sender_id="alice",
                            chat_id="c1",
                            content=f"msg {i}",
                        )
                    )
                return LLMResponse(content="calling tools", tool_calls=tool_calls)
            return LLMResponse(content="final", tool_calls=[])

        mock_provider.chat = AsyncMock(side_effect=chat_side_effect)

        session_id = _create_session(engine)
        final, meta, injected = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
            session_id=session_id,
        )

        assert final == "final"
        # Tools SHOULD have been executed
        engine.tools.execute.assert_awaited_once()
        assert meta.skipped_tool_calls == 0
        # 2 messages still injected (via buffered + before_llm_call)
        assert len(injected) == 2

    async def test_no_progress_on_interrupt(self, engine, bus, mock_provider):
        """No progress notification sent when interrupt triggers."""
        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."})
        ]
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]
        outbound_messages = _capture_outbound_messages(engine)

        call_count = 0

        async def chat_side_effect(messages, tools, model):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                for i in range(3):
                    await bus.publish_inbound(
                        InboundMessage(
                            channel="telegram",
                            sender_id="alice",
                            chat_id="c1",
                            content=f"stop {i}",
                        )
                    )
                return LLMResponse(content="calling tools", tool_calls=tool_calls)
            return LLMResponse(content="done", tool_calls=[])

        mock_provider.chat = AsyncMock(side_effect=chat_side_effect)

        session_id = _create_session(engine)
        await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
            session_id=session_id,
        )

        # No progress messages should have been sent
        progress_msgs = _progress_messages(outbound_messages)
        assert len(progress_msgs) == 0

    async def test_no_progress_for_message_only_tool_calls(self, engine, mock_provider):
        """Message-only tool calls should not emit separate progress notifications."""
        tool_calls = [
            ToolCallRequest(id="t1", name="message", arguments={"content": "hello"}),
        ]
        outbound_messages = await _run_telegram_loop_with_outbound_capture(
            engine,
            mock_provider,
            responses=[
                LLMResponse(content="我来给你发一条消息", tool_calls=tool_calls),
                LLMResponse(content="done", tool_calls=[]),
            ],
        )

        progress_msgs = _progress_messages(outbound_messages)
        assert len(progress_msgs) == 0

    async def test_background_completion_event_injected_without_polling(
        self, engine, bus, mock_provider
    ):
        """Background completion should be injected via events, not await_pending polling."""
        session_id = _create_session(engine)

        async def chat_side_effect(messages, tools, model):
            if mock_provider.chat.await_count == 1:
                await bus.emit(
                    SubagentCompleteEvent(
                        label="bg-task",
                        status="completed",
                        content="background done",
                        background=True,
                        session_id=session_id,
                        messages=[],
                        channel="telegram",
                        chat_id="c1",
                    )
                )
                return LLMResponse(content="intermediate", tool_calls=[])
            return LLMResponse(content="final", tool_calls=[])

        mock_provider.chat = AsyncMock(side_effect=chat_side_effect)

        final, _, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
            session_id=session_id,
        )

        assert final == "final"
        engine.subagents.await_pending.assert_not_awaited()

        second_call_msgs = mock_provider.chat.await_args_list[1].kwargs["messages"]
        assert any(
            "[Background subagent 'bg-task' completed]" in m.get("content", "")
            for m in second_call_msgs
            if m.get("role") == "user"
        )

    async def test_background_completion_event_queued_by_global_subscriber(self, engine, bus):
        original = engine.queue_background_completion
        engine.queue_background_completion = AsyncMock(side_effect=original)  # type: ignore[method-assign]
        session_id = _create_session(engine)

        await bus.emit(
            SubagentCompleteEvent(
                label="bg-task",
                status="completed",
                content="background done",
                background=True,
                session_id=session_id,
                messages=[],
                channel="telegram",
                chat_id="c1",
            )
        )

        engine.queue_background_completion.assert_awaited_once()

    async def test_background_completion_after_loop_end_resumes_same_session(self, engine, bus):
        first_meta = LoopMetadata(iterations=1, has_side_effects=False)
        resumed_meta = LoopMetadata(iterations=1, has_side_effects=False)
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                ("started", first_meta, []),
                ("bg-final", resumed_meta, []),
            ]
        )
        engine.bus.publish_outbound = AsyncMock()  # type: ignore[method-assign]

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="run bg")
        out = await engine.process(msg)
        assert out is not None
        assert out.content == "started"

        session_id = engine._session_routes[msg.session_key]
        await bus.emit(
            SubagentCompleteEvent(
                label="bg-task",
                status="completed",
                content="background done",
                background=True,
                session_id=session_id,
                messages=[],
                channel="telegram",
                chat_id="c1",
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0.05)

        assert engine._execute_loop.await_count >= 2
        engine.bus.publish_outbound.assert_awaited()
        published = engine.bus.publish_outbound.await_args.args[0]
        assert published.channel == "telegram"
        assert published.chat_id == "c1"
        assert published.content == "bg-final"

    async def test_progress_hides_message_tool_when_mixed_with_others(self, engine, mock_provider):
        """Progress text and tool hints are emitted separately when both are enabled."""
        tool_calls = [
            ToolCallRequest(id="t1", name="message", arguments={"content": "hello"}),
            ToolCallRequest(id="t2", name="fs", arguments={"action": "list", "path": "."}),
        ]
        outbound_messages = await _run_telegram_loop_with_outbound_capture(
            engine,
            mock_provider,
            responses=[
                LLMResponse(content="先发消息再查目录", tool_calls=tool_calls),
                LLMResponse(content="done", tool_calls=[]),
            ],
        )

        progress_msgs = _progress_messages(outbound_messages)
        assert len(progress_msgs) == 2
        text_msgs = _progress_messages(progress_msgs, kind="text")
        hint_msgs = _progress_messages(progress_msgs, kind="tool_hints")
        assert len(text_msgs) == 1
        assert len(hint_msgs) == 1
        assert text_msgs[0].content == "先发消息再查目录"
        assert "↳ fs(" in hint_msgs[0].content
        assert "↳ message(" not in hint_msgs[0].content

    async def test_progress_policy_progress_only(self, engine, mock_provider):
        """When hints are disabled, only assistant progress text is sent."""
        _set_telegram_progress_policy(engine, send_progress=True, send_tool_hints=False)
        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."}),
        ]
        outbound_messages = await _run_telegram_loop_with_outbound_capture(
            engine,
            mock_provider,
            responses=[
                LLMResponse(content="先确认当前目录", tool_calls=tool_calls),
                LLMResponse(content="done", tool_calls=[]),
            ],
        )

        progress_msgs = _progress_messages(outbound_messages)
        assert len(progress_msgs) == 1
        assert progress_msgs[0].content == "先确认当前目录"
        assert "↳" not in progress_msgs[0].content

    async def test_progress_policy_tool_hints_only(self, engine, mock_provider):
        """When progress text is disabled, only tool hints are sent."""
        _set_telegram_progress_policy(engine, send_progress=False, send_tool_hints=True)
        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."}),
        ]
        outbound_messages = await _run_telegram_loop_with_outbound_capture(
            engine,
            mock_provider,
            responses=[
                LLMResponse(content="先确认当前目录", tool_calls=tool_calls),
                LLMResponse(content="done", tool_calls=[]),
            ],
        )

        progress_msgs = _progress_messages(outbound_messages)
        assert len(progress_msgs) == 1
        assert "↳ fs(" in progress_msgs[0].content
        assert "先确认当前目录" not in progress_msgs[0].content
        assert progress_msgs[0].metadata.get("append_mode") == "concat"
        assert progress_msgs[0].metadata.get("append_key")

    async def test_progress_policy_disabled_sends_no_interim_message(self, engine, mock_provider):
        """When both flags are false, no progress outbound is published."""
        _set_telegram_progress_policy(engine, send_progress=False, send_tool_hints=False)
        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."}),
        ]
        outbound_messages = await _run_telegram_loop_with_outbound_capture(
            engine,
            mock_provider,
            responses=[
                LLMResponse(content="先确认当前目录", tool_calls=tool_calls),
                LLMResponse(content="done", tool_calls=[]),
            ],
        )

        progress_msgs = _progress_messages(outbound_messages)
        assert len(progress_msgs) == 0

    async def test_tool_hints_reuse_append_key_when_no_progress(self, engine, mock_provider):
        """Consecutive hint-only batches should share one append stream."""
        _set_telegram_progress_policy(engine, send_progress=True, send_tool_hints=True)
        first_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."})
        ]
        second_calls = [ToolCallRequest(id="t2", name="exec", arguments={"command": "ls"})]
        outbound_messages = await _run_telegram_loop_with_outbound_capture(
            engine,
            mock_provider,
            responses=[
                LLMResponse(content=None, tool_calls=first_calls),
                LLMResponse(content=None, tool_calls=second_calls),
                LLMResponse(content="done", tool_calls=[]),
            ],
        )

        hint_msgs = _progress_messages(outbound_messages, kind="tool_hints")
        assert len(hint_msgs) == 2
        first_key = hint_msgs[0].metadata.get("append_key")
        second_key = hint_msgs[1].metadata.get("append_key")
        assert first_key == second_key
        assert hint_msgs[0].metadata.get("append_reset") is False
        assert hint_msgs[1].metadata.get("append_reset") is False

    async def test_progress_text_resets_tool_hint_append_stream(self, engine, mock_provider):
        """When progress text is emitted, next tool-hint batch starts a fresh append stream."""
        _set_telegram_progress_policy(engine, send_progress=True, send_tool_hints=True)
        first_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "list", "path": "."})
        ]
        second_calls = [ToolCallRequest(id="t2", name="exec", arguments={"command": "ls"})]
        third_calls = [ToolCallRequest(id="t3", name="web_search", arguments={"query": "hal"})]
        outbound_messages = await _run_telegram_loop_with_outbound_capture(
            engine,
            mock_provider,
            responses=[
                LLMResponse(content=None, tool_calls=first_calls),
                LLMResponse(content="先看一下命令输出", tool_calls=second_calls),
                LLMResponse(content=None, tool_calls=third_calls),
                LLMResponse(content="done", tool_calls=[]),
            ],
            max_iterations=6,
        )

        text_msgs = _progress_messages(outbound_messages, kind="text")
        hint_msgs = _progress_messages(outbound_messages, kind="tool_hints")
        assert len(text_msgs) == 1
        assert text_msgs[0].content == "先看一下命令输出"
        assert len(hint_msgs) == 3
        assert hint_msgs[0].metadata.get("append_reset") is False
        assert hint_msgs[1].metadata.get("append_reset") is True
        assert hint_msgs[2].metadata.get("append_reset") is False


class TestRunLoop:
    async def test_run_publishes_dispatch_response(self, engine):
        msg = InboundMessage(channel="cli", sender_id="u", chat_id="direct", content="hi")
        engine.bus.consume_inbound = AsyncMock(return_value=msg)  # type: ignore[method-assign]
        engine._dispatch = AsyncMock(
            return_value=OutboundMessage(channel="cli", chat_id="direct", content="ok")
        )  # type: ignore[method-assign]

        async def stop_after_publish(_msg: OutboundMessage) -> None:
            engine.stop()

        engine.bus.publish_outbound = AsyncMock(side_effect=stop_after_publish)  # type: ignore[method-assign]

        await engine.run()

        engine._dispatch.assert_awaited_once()
        engine.bus.publish_outbound.assert_awaited_once()

    async def test_run_sends_apology_when_dispatch_raises(self, engine):
        msg = InboundMessage(channel="telegram", sender_id="u", chat_id="c1", content="hi")
        engine.bus.consume_inbound = AsyncMock(return_value=msg)  # type: ignore[method-assign]
        engine._dispatch = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        async def stop_after_publish(_msg: OutboundMessage) -> None:
            engine.stop()

        engine.bus.publish_outbound = AsyncMock(side_effect=stop_after_publish)  # type: ignore[method-assign]

        await engine.run()

        published = engine.bus.publish_outbound.await_args.args[0]
        assert published.channel == "telegram"
        assert published.chat_id == "c1"
        assert "encountered an error" in published.content.lower()
        assert "boom" in published.content

    async def test_run_timeout_does_not_crash(self, engine, monkeypatch: pytest.MonkeyPatch):
        real_wait_for = asyncio.wait_for

        async def fake_wait_for(awaitable, timeout: float):
            # Avoid leaking an un-awaited coroutine.
            if hasattr(awaitable, "close"):
                awaitable.close()
            engine.stop()
            raise asyncio.TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        try:
            await engine.run()
        finally:
            monkeypatch.setattr(asyncio, "wait_for", real_wait_for)


# ------------------------------------------------------------------
# LoopMetadata
# ------------------------------------------------------------------


class TestExecuteLoopMetadata:
    """Test that _execute_loop tracks files_modified and commands_run."""

    async def test_tracks_fs_write_side_effects(self, engine, mock_provider):
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        tool_calls = [
            ToolCallRequest(
                id="t1",
                name="fs",
                arguments={"action": "write", "path": "/tmp/a.txt", "content": "x"},
            ),
            ToolCallRequest(
                id="t2",
                name="fs",
                arguments={"action": "edit", "path": "/tmp/b.txt", "old": "x", "new": "y"},
            ),
        ]
        mock_provider.chat.side_effect = [
            LLMResponse(content="writing", tool_calls=tool_calls),
            LLMResponse(content="done", tool_calls=[]),
        ]

        _, meta, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=3,
        )

        assert meta.has_side_effects is True
        assert "/tmp/a.txt" in meta.files_modified
        assert "/tmp/b.txt" in meta.files_modified

    async def test_tracks_exec_side_effects(self, engine, mock_provider):
        engine.tools.execute = AsyncMock(return_value="output")  # type: ignore[method-assign]

        tool_calls = [
            ToolCallRequest(id="t1", name="exec", arguments={"command": "ls -la"}),
        ]
        mock_provider.chat.side_effect = [
            LLMResponse(content="running", tool_calls=tool_calls),
            LLMResponse(content="done", tool_calls=[]),
        ]

        _, meta, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=3,
        )

        assert meta.has_side_effects is True
        assert "ls -la" in meta.commands_run

    async def test_no_side_effects_for_read_only_tools(self, engine, mock_provider):
        engine.tools.execute = AsyncMock(return_value="ok")  # type: ignore[method-assign]

        tool_calls = [
            ToolCallRequest(id="t1", name="fs", arguments={"action": "read", "path": "/tmp/a.txt"}),
            ToolCallRequest(id="t2", name="web_search", arguments={"query": "test"}),
        ]
        mock_provider.chat.side_effect = [
            LLMResponse(content="reading", tool_calls=tool_calls),
            LLMResponse(content="done", tool_calls=[]),
        ]

        _, meta, _ = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=3,
        )

        assert meta.has_side_effects is False
        assert meta.files_modified == []
        assert meta.commands_run == []


class TestSubagentInjectionHelpers:
    def test_split_subagent_tool_result_extracts_metadata(self):
        payload = (
            "Result line\n\n"
            "[Subagent Record ID] abc123\n\n"
            "[Subagent Artifact] /tmp/a.md\n\n"
            "[Subagent Total Tokens] 123\n\n"
            "[Subagent Status] partial\n\n"
            '[Subagent Tools Used] ["fs", "web_search"]\n\n'
            '[Subagent Tool Counts] {"fs": 2}\n\n'
            "[Subagent Has Side Effects] true\n\n"
            '[Subagent Files Modified] ["/tmp/a.md"]\n\n'
            '[Subagent Commands Run] ["ls -la"]'
        )
        parsed = _split_subagent_tool_result(payload)
        assert parsed.content == "Result line"
        assert parsed.artifact_path == "/tmp/a.md"
        assert parsed.total_tokens == 123
        assert parsed.record_id == "abc123"
        assert parsed.status == "partial"
        assert parsed.tools_used == ["fs", "web_search"]
        assert parsed.tool_call_counts == {"fs": 2}
        assert parsed.has_side_effects is True
        assert parsed.files_modified == ["/tmp/a.md"]
        assert parsed.commands_run == ["ls -la"]

    def test_build_subagent_injection_truncates_success(self):
        text = _build_subagent_injection(
            label="task",
            content="X" * 1200,
            status="completed",
            background=False,
            record_id="abc123",
            artifact_path="/tmp/a.md",
            total_tokens=88,
        )
        assert "[Full result saved to subagent artifact file]" in text
        assert "[Subagent Record ID] abc123" in text
        assert "[Subagent Artifact] /tmp/a.md" in text
        assert "[Subagent Total Tokens] 88" in text
        assert "[Subagent Status] completed" in text
        assert "[Subagent Has Side Effects] false" in text

    def test_build_subagent_injection_keeps_error_untruncated(self):
        err = "Error: failed step\ntrace"
        text = _build_subagent_injection(
            label="task",
            content=err,
            status="failed",
            background=True,
            record_id=None,
            artifact_path=None,
            total_tokens=0,
        )
        assert err in text
        assert "[Full result saved to subagent artifact file]" not in text
        assert "[Subagent Status] failed" in text

    def test_build_subagent_injection_no_truncate_when_limit_disabled(self):
        text = _build_subagent_injection(
            label="task",
            content="X" * 1200,
            status="completed",
            background=True,
            record_id=None,
            artifact_path=None,
            total_tokens=0,
            max_tokens=0,
        )
        assert "[Full result saved to subagent artifact file]" not in text
        assert " [...]" not in text

    def test_build_subagent_injection_includes_side_effect_markers(self):
        text = _build_subagent_injection(
            label="task",
            content="done",
            status="completed",
            background=False,
            record_id="rid",
            artifact_path=None,
            total_tokens=12,
            tools_used=["fs"],
            tool_call_counts={"fs": 2},
            has_side_effects=True,
            files_modified=["/tmp/a.md"],
            commands_run=["echo hi"],
            tool_errors=["fs: Error: bad path"],
            missing_artifacts=["/tmp/missing.md"],
        )
        assert '[Subagent Tools Used] ["fs"]' in text
        assert '[Subagent Tool Counts] {"fs": 2}' in text
        assert "[Subagent Has Side Effects] true" in text
        assert '[Subagent Files Modified] ["/tmp/a.md"]' in text
        assert '[Subagent Commands Run] ["echo hi"]' in text
        assert '[Subagent Tool Errors] ["fs: Error: bad path"]' in text
        assert '[Subagent Missing Artifacts] ["/tmp/missing.md"]' in text
