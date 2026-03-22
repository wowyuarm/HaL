"""Factory for building tool registries with configurable capability sets."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hal.capabilities.tools.exec import ExecTool
from hal.capabilities.tools.fs import FsTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.capabilities.tools.web import WebFetchTool, WebSearchTool
from hal.domain.ports import SubagentPort

if TYPE_CHECKING:
    from hal.bus.queue import MessageBus
    from hal.infra.config.schema import ExecToolConfig, WebFetchConfig, WebSearchConfig
    from hal.memory.search import EpisodeRecallIndex


def create_tools(
    *,
    workspace: Path,
    exec_config: "ExecToolConfig | None" = None,
    restrict_to_workspace: bool = False,
    web_search_api_key: str | None = None,
    web_search_config: "WebSearchConfig | None" = None,
    web_fetch_config: "WebFetchConfig | None" = None,
    bus: "MessageBus | None" = None,
    subagent_manager: SubagentPort | None = None,
    recall_index: "EpisodeRecallIndex | None" = None,
) -> ToolRegistry:
    """Build a ToolRegistry with the requested capabilities.

    Core tools (fs, exec, web_search, web_fetch) are always registered.
    Optional tools (message, spawn, recall) are registered only when
    their dependencies are provided.

    Args:
        workspace: Agent workspace directory.
        exec_config: Shell execution settings.
        restrict_to_workspace: Sandbox file/exec to workspace.
        web_search_api_key: Tavily API key for web search.
        web_search_config: Web search tool settings (max_results, timeout).
        web_fetch_config: Web fetch tool settings (max_chars, timeout, redirects).
        bus: Message bus (enables message tool).
        subagent_manager: Subagent manager (enables spawn tool).
        recall_index: Episode recall index (enables recall tool).
    """
    from hal.infra.config.schema import ExecToolConfig, WebFetchConfig, WebSearchConfig

    exec_config = exec_config or ExecToolConfig()
    ws_cfg = web_search_config or WebSearchConfig()
    wf_cfg = web_fetch_config or WebFetchConfig()
    allowed_dir = workspace if restrict_to_workspace else None

    tools = ToolRegistry()

    # Core tools (always available)
    tools.register(FsTool(allowed_dir=allowed_dir, base_dir=workspace))
    tools.register(
        ExecTool(
            working_dir=str(workspace),
            timeout=exec_config.timeout,
            kill_wait_s=exec_config.kill_wait_s,
            restrict_to_workspace=restrict_to_workspace,
        )
    )
    tools.register(
        WebSearchTool(
            api_key=web_search_api_key,
            max_results=ws_cfg.max_results,
            timeout_s=ws_cfg.timeout_s,
        )
    )
    tools.register(
        WebFetchTool(
            max_chars=wf_cfg.default_max_chars,
            timeout_s=wf_cfg.timeout_s,
            max_redirects=wf_cfg.max_redirects,
        )
    )

    # Optional tools (require external dependencies)
    if bus:
        from hal.capabilities.tools.message import MessageTool

        tools.register(MessageTool(send_callback=bus.publish_outbound))

    if subagent_manager:
        from hal.capabilities.tools.spawn import SpawnTool

        send_cb = bus.publish_outbound if bus else None
        tools.register(SpawnTool(manager=subagent_manager, send_callback=send_cb))

    if recall_index:
        from hal.capabilities.tools.recall import RecallTool

        tools.register(RecallTool(recall_index))

    return tools
