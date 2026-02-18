"""Tests for AgentEngine (hal/core/engine.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hal.bus.events import InboundMessage, OutboundMessage
from hal.bus.queue import MessageBus
from hal.core.engine import AgentEngine, LoopMetadata
from hal.infra.providers.base import LLMProvider, LLMResponse, ToolCallRequest

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
        patch("hal.core.engine.ContextBuilder") as mock_ctx,
        patch("hal.core.engine.MemoryManager") as mock_mem,
        patch("hal.core.engine.SubagentManager"),
    ):
        # ContextBuilder.build_messages returns minimal message list
        builder_instance = mock_ctx.return_value
        builder_instance.build_messages.return_value = [
            {"role": "system", "content": "You are a test agent."},
        ]
        builder_instance.add_assistant_message.side_effect = lambda msgs, content, tc, **kw: msgs
        builder_instance.add_tool_result.side_effect = lambda msgs, tid, name, result: msgs

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


@pytest.fixture
def engine_with_cron(bus, mock_provider, workspace):
    """AgentEngine with a cron_service provided (registers CronTool)."""
    cron = MagicMock()
    with (
        patch("hal.core.engine.ContextBuilder") as mock_ctx,
        patch("hal.core.engine.MemoryManager") as mock_mem,
        patch("hal.core.engine.SubagentManager"),
    ):
        builder_instance = mock_ctx.return_value
        builder_instance.build_messages.return_value = [
            {"role": "system", "content": "You are a test agent."},
        ]
        builder_instance.add_assistant_message.side_effect = lambda msgs, content, tc, **kw: msgs
        builder_instance.add_tool_result.side_effect = lambda msgs, tid, name, result: msgs

        mem_instance = mock_mem.return_value

        eng = AgentEngine(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            cron_service=cron,
            memory_manager=mem_instance,
        )
        yield eng


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

    def test_cron_tool_registered_when_cron_service_provided(self, engine_with_cron):
        assert "cron" in set(engine_with_cron.tools.tool_names)


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

    def test_sets_context_on_cron_when_present(self, engine_with_cron):
        engine_with_cron._update_tool_contexts("discord", "c9")
        cron_tool = engine_with_cron.tools.get("cron")
        assert cron_tool._channel == "discord"
        assert cron_tool._chat_id == "c9"


# ------------------------------------------------------------------
# process_direct routing
# ------------------------------------------------------------------


class TestProcessDirect:
    async def test_cron_session_routes_to_operator(self, engine):
        """Sessions starting with 'cron:' should be handled by process_operator."""
        with patch.object(engine, "process_operator", new_callable=AsyncMock) as mock_op:
            mock_op.return_value = "operator result"

            result = await engine.process_direct(
                content="check status",
                session_key="cron:daily-check",
                channel="cli",
                chat_id="direct",
            )

            mock_op.assert_awaited_once()
            assert result == "operator result"

    async def test_heartbeat_session_routes_to_operator(self, engine):
        with patch.object(engine, "process_operator", new_callable=AsyncMock) as mock_op:
            mock_op.return_value = "heartbeat result"

            result = await engine.process_direct(
                content="heartbeat",
                session_key="heartbeat",
            )

            mock_op.assert_awaited_once()
            assert result == "heartbeat result"

    async def test_regular_session_routes_to_collab(self, engine):
        """Non-cron sessions should be handled by process_collab."""
        with patch.object(engine, "process_collab", new_callable=AsyncMock) as mock_collab:
            mock_collab.return_value = OutboundMessage(
                channel="cli", chat_id="direct", content="collab result"
            )

            result = await engine.process_direct(
                content="hello",
                session_key="cli:direct",
            )

            mock_collab.assert_awaited_once()
            # process_direct extracts .content from the OutboundMessage
            assert result == "collab result"


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
    async def test_dispatch_routes_to_process_collab(self, engine):
        msg = InboundMessage(channel="telegram", sender_id="u", chat_id="c", content="hi")
        engine.process_collab = AsyncMock(return_value=None)  # type: ignore[method-assign]

        await engine._dispatch(msg)
        engine.process_collab.assert_awaited_once_with(msg)

    async def test_dispatch_cron_routes_to_operator(self, engine):
        """Cron-origin messages should route to process_operator, not process_collab."""
        msg = InboundMessage(
            channel="cron",
            sender_id="cron",
            chat_id="abc123",
            content="check updates",
            origin="cron",
            metadata={"cron_job_id": "abc123", "deliver": False},
        )
        engine.process_operator = AsyncMock(return_value="done")  # type: ignore[method-assign]

        result = await engine._dispatch(msg)

        engine.process_operator.assert_awaited_once_with(
            prompt="check updates",
            channel="cron",
            chat_id="abc123",
            session_key="cron:abc123",
            origin="cron",
        )
        assert result is None  # deliver=False → no outbound

    async def test_dispatch_cron_with_deliver(self, engine):
        """Cron with deliver=True should return OutboundMessage to target channel."""
        msg = InboundMessage(
            channel="cron",
            sender_id="cron",
            chat_id="abc123",
            content="check updates",
            origin="cron",
            metadata={
                "cron_job_id": "abc123",
                "deliver": True,
                "deliver_channel": "telegram",
                "deliver_chat_id": "999",
            },
        )
        engine.process_operator = AsyncMock(return_value="Update found!")  # type: ignore[method-assign]

        result = await engine._dispatch(msg)

        assert result is not None
        assert result.channel == "telegram"
        assert result.chat_id == "999"
        assert result.content == "Update found!"

    async def test_dispatch_heartbeat_routes_to_operator(self, engine):
        """Heartbeat-origin messages should route to process_operator, return None."""
        msg = InboundMessage(
            channel="heartbeat",
            sender_id="heartbeat",
            chat_id="system",
            content="check tasks",
            origin="heartbeat",
        )
        engine.process_operator = AsyncMock(return_value="HEARTBEAT_OK")  # type: ignore[method-assign]

        result = await engine._dispatch(msg)

        engine.process_operator.assert_awaited_once_with(
            prompt="check tasks",
            channel="heartbeat",
            chat_id="system",
            session_key="heartbeat:system",
            origin="heartbeat",
        )
        assert result is None

    async def test_defaults_final_content_when_execute_loop_returns_none(self, engine):
        engine._execute_loop = AsyncMock(return_value=(None, LoopMetadata(tools_used=["fs"]), []))  # type: ignore[method-assign]

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
        out = await engine.process_collab(msg)

        assert out is not None
        assert out.channel == "telegram"
        assert out.chat_id == "c1"
        assert "no response" in out.content.lower()


class TestProcessOperator:
    async def test_operator_uses_max_10_iterations_and_default_message(self, engine):
        engine._execute_loop = AsyncMock(
            return_value=(None, LoopMetadata(tools_used=["web_search"]), [])
        )  # type: ignore[method-assign]

        result = await engine.process_operator(
            prompt="check",
            channel="cli",
            chat_id="direct",
        )

        assert result == "Monitoring complete. Nothing to report."
        # second arg to _execute_loop is max_iter
        assert engine._execute_loop.await_args.args[1] == 10


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

        final, meta, injected = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=3,
        )

        assert final == "final"
        assert meta.tools_used == ["web_search", "fs"]
        assert meta.iterations == 2
        assert injected == []
        assert engine.tools.execute.await_count == 3
        engine.context.add_assistant_message.assert_called_once()
        assert engine.context.add_tool_result.call_count == 3


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

        final, meta, injected = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=5,
            session_key="telegram:c1",
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

        final, _, injected = await engine._execute_loop(
            messages=[{"role": "system", "content": "x"}],
            max_iterations=1,
            session_key="telegram:c1",
        )

        assert injected == []
        assert bus.inbound.qsize() == 1
        requeued = bus.inbound.get_nowait()
        assert requeued.content == "unrelated"

    def test_drain_empty_queue_returns_empty(self, engine):
        result = engine._drain_pending_for_session("telegram:c1")
        assert result == []


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


class TestLoopMetadata:
    def test_needs_summary_true_when_many_iterations(self):
        meta = LoopMetadata(iterations=5)
        assert meta.needs_summary is True

    def test_needs_summary_true_when_has_side_effects(self):
        meta = LoopMetadata(iterations=1, has_side_effects=True)
        assert meta.needs_summary is True

    def test_needs_summary_false_when_few_iterations_no_side_effects(self):
        meta = LoopMetadata(iterations=2, has_side_effects=False)
        assert meta.needs_summary is False

    def test_needs_summary_boundary_four_iterations(self):
        meta = LoopMetadata(iterations=4)
        assert meta.needs_summary is False


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


class TestSummaryTrigger:
    """Test that summary is triggered/skipped correctly in process_collab."""

    async def test_summary_not_triggered_when_needs_summary_false(self, engine):
        """No summary task created when loop doesn't qualify."""
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            return_value=("response", LoopMetadata(iterations=2, has_side_effects=False), [])
        )

        msg = InboundMessage(channel="cli", sender_id="u", chat_id="d", content="hi")
        await engine.process_collab(msg)

        assert msg.session_key not in engine._pending_summaries

    async def test_summary_triggered_with_default_model(self, engine):
        """Summary task created using main model when summary_model is 'default'."""
        engine._summary_model = "default"
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            return_value=("response", LoopMetadata(iterations=6, has_side_effects=True), [])
        )
        engine._generate_summary = AsyncMock()  # type: ignore[method-assign]

        msg = InboundMessage(channel="cli", sender_id="u", chat_id="d", content="hi")
        await engine.process_collab(msg)

        assert msg.session_key in engine._pending_summaries

    async def test_summary_triggered_when_conditions_met(self, engine):
        """Summary task created when needs_summary=True and summary_model set."""
        engine._summary_model = "cheap-model"
        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            return_value=("response", LoopMetadata(iterations=6, has_side_effects=True), [])
        )
        engine._generate_summary = AsyncMock()  # type: ignore[method-assign]

        msg = InboundMessage(channel="cli", sender_id="u", chat_id="d", content="hi")
        await engine.process_collab(msg)

        assert msg.session_key in engine._pending_summaries

    async def test_summary_barrier_waits_for_pending_task(self, engine):
        """process_collab waits for a pending summary before proceeding."""
        engine._summary_model = "cheap-model"
        completed = False

        async def fake_summary(*args):
            nonlocal completed
            await asyncio.sleep(0.01)
            completed = True

        # Simulate a pending summary from a previous call
        task = asyncio.create_task(fake_summary())
        session_key = "cli:d"
        engine._pending_summaries[session_key] = task

        engine._execute_loop = AsyncMock(  # type: ignore[method-assign]
            return_value=("response", LoopMetadata(iterations=1), [])
        )

        msg = InboundMessage(channel="cli", sender_id="u", chat_id="d", content="follow up")
        await engine.process_collab(msg)

        assert completed is True
        assert session_key not in engine._pending_summaries


class TestGenerateSummary:
    async def test_summary_uses_summary_entry_type(self, engine, mock_provider):
        """_generate_summary should record with entry_type='summary'."""
        mock_provider.chat = AsyncMock(
            return_value=LLMResponse(content="Summary text", tool_calls=[])
        )

        meta = LoopMetadata(
            iterations=6,
            tools_used=["fs"],
            files_modified=["/tmp/a.txt"],
            has_side_effects=True,
            loop_messages=[],
        )

        await engine._generate_summary(meta, "final response", "telegram", "c1")

        engine.memory.record_conversation.assert_called_with(
            channel="telegram",
            chat_id="c1",
            role="user",
            content="[System Summary]\nSummary text",
            entry_type="summary",
        )
