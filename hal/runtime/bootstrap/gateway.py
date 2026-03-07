"""Gateway runtime wiring extracted from CLI command handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hal.bus.queue import MessageBus
from hal.channels.manager import ChannelManager
from hal.cli.factory import (
    make_memory_search,
    make_provider,
    make_worker_provider,
)
from hal.runtime.engine import AgentEngine

if TYPE_CHECKING:
    from hal.infra.config.schema import Config


@dataclass(slots=True)
class GatewayRuntime:
    """Runtime components used by the gateway main loop."""

    agent: AgentEngine
    channels: ChannelManager
    memory_search: Any | None


def build_gateway_runtime(config: "Config") -> GatewayRuntime:
    """Build agent, channels, and optional memory search for gateway execution."""
    bus = MessageBus()
    provider = make_provider(config)
    memory_search = make_memory_search(config) if config.memory_search.enabled else None
    worker_provider = make_worker_provider(config) or provider

    agent = AgentEngine(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        web_search_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        worker_model=config.agents.defaults.worker_model,
        worker_provider=worker_provider,
        memory_search=memory_search,
        auto_inject_top_k=config.memory_search.auto_inject_top_k,
        recall_min_score=config.memory_search.recall_min_score,
        history_config=config.agents.defaults.history,
        engine_config=config.engine,
        web_search_config=config.tools.web.search,
        web_fetch_config=config.tools.web.fetch,
        channels_config=config.channels,
    )

    channels = ChannelManager(
        config,
        bus,
        memory_manager=agent.memory,
        context_inspector=agent.inspect_context,
        outbound_poll_timeout_s=config.channels.outbound_poll_timeout_s,
    )

    return GatewayRuntime(agent=agent, channels=channels, memory_search=memory_search)
