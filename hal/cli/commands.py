"""CLI commands for HaL."""

import asyncio
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from hal import __logo__, __version__
from hal.cli.channel_commands import channels_app
from hal.cli.cron_commands import cron_app
from hal.cli.factory import (
    make_memory_search,
    make_provider,
    make_subagent_provider,
    make_summary_provider,
)

app = typer.Typer(
    name="hal",
    help=f"{__logo__} HaL - Digital Butler",
    no_args_is_help=True,
)
app.add_typer(channels_app, name="channels")
app.add_typer(cron_app, name="cron")

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} hal v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """HaL - Digital Butler."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize HaL configuration and workspace."""
    from hal.infra.config.loader import get_config_path, save_config
    from hal.infra.config.schema import Config
    from hal.utils.helpers import get_workspace_path

    config_path = get_config_path()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()

    # Create default config
    config = Config()
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")

    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")

    # Create default bootstrap files
    _create_workspace_templates(workspace)

    console.print(f"\n{__logo__} HaL is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.hal/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print('  2. Chat: [cyan]hal agent -m "Hello!"[/cyan]')


def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

Add operational instructions for your HaL agent here.
See workspace/TOOLS.md for tool usage examples.
""",
        "SOUL.md": """# Soul

I am HaL, your digital butler.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }

    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")

    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")

    # Create utility directories
    for dirname in ("tmp", "scripts"):
        d = workspace / dirname
        if not d.exists():
            d.mkdir(exist_ok=True)
            console.print(f"  [dim]Created {dirname}/[/dim]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the HaL gateway."""
    from hal.bus.queue import MessageBus
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.capabilities.scheduling.heartbeat import HeartbeatService
    from hal.capabilities.scheduling.types import CronJob
    from hal.channels.manager import ChannelManager
    from hal.core.engine import AgentLoop
    from hal.infra.config.loader import get_data_dir, load_config

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting HaL gateway on port {port}...")

    config = load_config()
    bus = MessageBus()
    provider = make_provider(config)

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    memory_search = make_memory_search(config) if config.memory_search.enabled else None
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        web_search_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        summary_model=config.agents.defaults.summary_model,
        summary_provider=make_summary_provider(config),
        subagent_model=config.agents.defaults.subagent_model,
        subagent_provider=make_subagent_provider(config),
        memory_search=memory_search,
        auto_inject_top_k=config.memory_search.auto_inject_top_k,
        history_config=config.agents.defaults.history,
    )

    # Set cron callback (needs agent)
    async def on_cron_job(job: CronJob) -> str | None:
        """Publish a cron job to the MessageBus for processing."""
        from hal.bus.events import InboundMessage

        metadata: dict[str, Any] = {
            "cron_job_id": job.id,
            "cron_job_name": job.name,
            "deliver": job.payload.deliver and bool(job.payload.to),
        }
        if metadata["deliver"]:
            metadata["deliver_channel"] = job.payload.channel or "cli"
            metadata["deliver_chat_id"] = job.payload.to

        await bus.publish_inbound(
            InboundMessage(
                channel="cron",
                sender_id="cron",
                chat_id=job.id,
                content=job.payload.message,
                origin="cron",
                metadata=metadata,
            )
        )
        return None

    cron.on_job = on_cron_job

    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str | None:
        """Publish heartbeat to the MessageBus for processing."""
        from hal.bus.events import InboundMessage

        await bus.publish_inbound(
            InboundMessage(
                channel="heartbeat",
                sender_id="heartbeat",
                chat_id="system",
                content=prompt,
                origin="heartbeat",
            )
        )
        return None

    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True,
    )

    # Create channel manager
    channels = ChannelManager(config, bus, memory_manager=agent.memory)

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print("[green]✓[/green] Heartbeat: every 30m")

    async def run():
        try:
            # Initialize memory search if enabled
            if memory_search:
                try:
                    await memory_search.initialize()
                    backfill_count = await memory_search.backfill()
                    status = (
                        f"initialized ({backfill_count} chunks backfilled)"
                        if backfill_count
                        else "initialized"
                    )
                    console.print(f"[green]✓[/green] Memory search {status}")
                except Exception as e:
                    console.print(f"[yellow]Memory search init failed: {e}[/yellow]")

            await cron.start()
            await heartbeat.start()

            tasks = [
                agent.run(),
                channels.start_all(),
            ]

            # Schedule daily export at midnight
            if memory_search:

                async def daily_export():
                    import datetime as _dt

                    while True:
                        now = _dt.datetime.now()
                        next_midnight = now.replace(
                            hour=0, minute=0, second=0, microsecond=0
                        ) + _dt.timedelta(days=1)
                        wait_s = (next_midnight - now).total_seconds()
                        await asyncio.sleep(wait_s)
                        try:
                            count = await memory_search.export_and_index_yesterday()
                            if count:
                                from loguru import logger

                                logger.info(f"Daily export: indexed {count} chunks")
                        except Exception as e:
                            from loguru import logger

                            logger.warning(f"Daily export failed: {e}")

                tasks.append(daily_export())

            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            heartbeat.stop()
            cron.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from hal.bus.queue import MessageBus
    from hal.core.engine import AgentLoop
    from hal.infra.config.loader import load_config

    config = load_config()

    bus = MessageBus()
    provider = make_provider(config)

    ms = make_memory_search(config) if config.memory_search.enabled else None

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        web_search_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        summary_model=config.agents.defaults.summary_model,
        summary_provider=make_summary_provider(config),
        subagent_model=config.agents.defaults.subagent_model,
        subagent_provider=make_subagent_provider(config),
        memory_search=ms,
        auto_inject_top_k=config.memory_search.auto_inject_top_k,
        history_config=config.agents.defaults.history,
    )

    async def _init_memory_search():
        if ms:
            try:
                await ms.initialize()
                await ms.backfill()
            except Exception as e:
                console.print(f"[yellow]Memory search init failed: {e}[/yellow]")

    if message:
        # Single message mode
        async def run_once():
            await _init_memory_search()
            response = await agent_loop.process_direct(message, session_id)
            console.print(f"\n{__logo__} {response}")

        asyncio.run(run_once())
    else:
        # Interactive mode
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)\n")

        async def run_interactive():
            await _init_memory_search()
            while True:
                try:
                    user_input = console.input("[bold blue]You:[/bold blue] ")
                    if not user_input.strip():
                        continue

                    response = await agent_loop.process_direct(user_input, session_id)
                    console.print(f"\n{__logo__} {response}\n")
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break

        asyncio.run(run_interactive())


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show HaL status."""
    from hal.infra.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} HaL Status\n")

    console.print(
        f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )

    if config_path.exists():
        from hal.infra.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")

        # Check API keys from registry
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            if spec.is_local:
                # Local deployments show api_base instead of api_key
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:
                has_key = bool(p.api_key)
                console.print(
                    f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}"
                )


if __name__ == "__main__":
    app()
