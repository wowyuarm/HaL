"""Factory for building tool registries with configurable capability sets."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hal.capabilities.tools.exec import ExecTool
from hal.capabilities.tools.fs import FsTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.capabilities.tools.web import WebFetchTool, WebSearchTool
from hal.core.ports import SubagentPort

if TYPE_CHECKING:
    from hal.bus.queue import MessageBus
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.core.memory.search import MemorySearch
    from hal.infra.config.schema import ExecToolConfig


def create_tools(
    *,
    workspace: Path,
    exec_config: "ExecToolConfig | None" = None,
    restrict_to_workspace: bool = False,
    web_search_api_key: str | None = None,
    bus: "MessageBus | None" = None,
    subagent_manager: SubagentPort | None = None,
    cron_service: "CronService | None" = None,
    memory_search: "MemorySearch | None" = None,
) -> ToolRegistry:
    """Build a ToolRegistry with the requested capabilities.

    Core tools (fs, exec, web_search, web_fetch) are always registered.
    Optional tools (message, spawn, cron, recall) are registered only when
    their dependencies are provided.

    Args:
        workspace: Agent workspace directory.
        exec_config: Shell execution settings.
        restrict_to_workspace: Sandbox file/exec to workspace.
        web_search_api_key: Tavily API key for web search.
        bus: Message bus (enables message tool).
        subagent_manager: Subagent manager (enables spawn tool).
        cron_service: Cron service (enables cron tool).
        memory_search: Memory search (enables recall tool).
    """
    from hal.infra.config.schema import ExecToolConfig

    exec_config = exec_config or ExecToolConfig()
    allowed_dir = workspace if restrict_to_workspace else None

    tools = ToolRegistry()

    # Core tools (always available)
    tools.register(FsTool(allowed_dir=allowed_dir))
    tools.register(
        ExecTool(
            working_dir=str(workspace),
            timeout=exec_config.timeout,
            restrict_to_workspace=restrict_to_workspace,
        )
    )
    tools.register(WebSearchTool(api_key=web_search_api_key))
    tools.register(WebFetchTool())

    # Optional tools (require external dependencies)
    if bus:
        from hal.capabilities.tools.message import MessageTool

        tools.register(MessageTool(send_callback=bus.publish_outbound))

    if subagent_manager:
        from hal.capabilities.tools.spawn import SpawnTool

        send_cb = bus.publish_outbound if bus else None
        tools.register(SpawnTool(manager=subagent_manager, send_callback=send_cb))

    if cron_service:
        from hal.capabilities.tools.schedule import CronTool

        tools.register(CronTool(cron_service))

    if memory_search:
        from hal.capabilities.tools.recall import RecallTool

        tools.register(RecallTool(memory_search))

    return tools
