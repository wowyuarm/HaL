"""Gateway runtime wiring extracted from CLI command handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hal.bus.queue import MessageBus
from hal.channels.manager import ChannelManager
from hal.cli.factory import (
    make_provider,
    make_recall_index,
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
    recall_index: Any | None


def build_gateway_runtime(config: "Config") -> GatewayRuntime:
    """Build agent, channels, and optional episode recall index for gateway execution."""
    bus = MessageBus()
    provider = make_provider(config)
    recall_index = make_recall_index(config) if config.recall.enabled else None
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
        recall_index=recall_index,
        auto_inject_top_k=config.recall.auto_inject_top_k,
        recall_min_score=config.recall.recall_min_score,
        history_config=config.agents.defaults.history,
        engine_config=config.engine,
        web_search_config=config.tools.web.search,
        web_fetch_config=config.tools.web.fetch,
        channels_config=config.channels,
    )

    channels = ChannelManager(
        config,
        bus,
        context_inspector=agent.inspect_context,
        outbound_poll_timeout_s=config.channels.outbound_poll_timeout_s,
    )

    return GatewayRuntime(agent=agent, channels=channels, recall_index=recall_index)
