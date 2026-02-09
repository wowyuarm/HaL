"""Tests for AgentEngine (hal/core/engine.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hal.bus.queue import MessageBus
from hal.core.engine import AgentEngine, AgentLoop
from hal.infra.providers.base import LLMProvider, LLMResponse

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
def mock_session_manager(workspace):
    """A mock SessionManager that returns a fresh in-memory session."""
    from hal.session.manager import Session, SessionManager

    mgr = MagicMock(spec=SessionManager)
    session = Session(key="cli:direct")
    mgr.get_or_create.return_value = session
    mgr.save = MagicMock()
    return mgr


@pytest.fixture
def engine(bus, mock_provider, workspace, mock_session_manager):
    """Build an AgentEngine with all heavy dependencies mocked."""
    with (
        patch("hal.core.engine.ContextCompiler") as mock_ctx,
        patch("hal.core.engine.MemoryManager") as mock_mem,
        patch("hal.core.engine.SubagentManager"),
    ):
        # ContextCompiler.build_messages returns minimal message list
        compiler_instance = mock_ctx.return_value
        compiler_instance.build_messages.return_value = [
            {"role": "system", "content": "You are a test agent."},
        ]
        compiler_instance.add_assistant_message.side_effect = lambda msgs, content, tc: msgs
        compiler_instance.add_tool_result.side_effect = lambda msgs, tid, name, result: msgs

        # MemoryManager stub
        mem_instance = mock_mem.return_value
        mem_instance.record_interaction = MagicMock()

        eng = AgentEngine(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            session_manager=mock_session_manager,
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

    def test_agent_loop_alias(self):
        assert AgentLoop is AgentEngine


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
            from hal.bus.events import OutboundMessage

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
