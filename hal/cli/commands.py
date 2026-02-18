"""CLI commands for HaL."""

import asyncio
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from hal import __logo__, __version__

app = typer.Typer(
    name="hal",
    help=f"{__logo__} HaL - Digital Butler",
    no_args_is_help=True,
)

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


def _make_provider(config):
    """Create LiteLLMProvider from config. Exits if no API key found."""
    from hal.infra.providers.litellm_provider import LiteLLMProvider

    p = config.get_provider()
    model = config.agents.defaults.model
    if not (p and p.api_key) and not model.startswith("bedrock/"):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.hal/config.json under providers section")
        raise typer.Exit(1)
    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
    )


def _make_summary_provider(config):
    """Create a separate LiteLLMProvider for summary model if needed. Returns None if same provider."""
    return _make_alternate_provider(config, config.agents.defaults.summary_model)


def _make_subagent_provider(config):
    """Create a separate LiteLLMProvider for subagent model if needed. Returns None if same provider."""
    return _make_alternate_provider(config, config.agents.defaults.subagent_model)


def _make_alternate_provider(config, model_name: str):
    """Create a separate LiteLLMProvider for an alternate model. Returns None if 'default' or same provider."""
    from hal.infra.providers.litellm_provider import LiteLLMProvider

    if model_name == "default":
        return None

    sp = config.get_provider(model_name)
    mp = config.get_provider()
    # If alternate model resolves to the same provider, no need for a separate instance
    if sp and mp and sp.api_key == mp.api_key and sp.api_base == mp.api_base:
        return None
    if not sp or not sp.api_key:
        return None

    api_base = sp.api_base
    if not api_base:
        from hal.infra.providers.registry import find_by_model

        spec = find_by_model(model_name)
        if spec and spec.default_api_base:
            api_base = spec.default_api_base

    return LiteLLMProvider(
        api_key=sp.api_key,
        api_base=api_base,
        default_model=model_name,
        extra_headers=sp.extra_headers if sp else None,
    )


def _resolve_embedding_provider(config, ms_cfg) -> dict:
    """Resolve api_key/api_base for embedding from the named provider."""
    result: dict = {}
    name = ms_cfg.embedding_provider
    if not name:
        # Fallback: try to auto-detect provider from embedding model name
        p = config.get_provider(ms_cfg.embedding_model)
        if p and p.api_key:
            result["api_key"] = p.api_key
            base = config.get_api_base(ms_cfg.embedding_model)
            if base:
                result["api_base"] = base
        return result

    p = getattr(config.providers, name, None)
    if p and p.api_key:
        result["api_key"] = p.api_key
        # Use provider's api_base, falling back to registry default
        if p.api_base:
            result["api_base"] = p.api_base
        else:
            from hal.infra.providers.registry import find_by_name

            spec = find_by_name(name)
            if spec and spec.default_api_base:
                result["api_base"] = spec.default_api_base
    return result


def _make_memory_search(config):
    """Create MemorySearch instance from config. Returns None if deps missing."""
    try:
        from hal.core.memory.chunker import MarkdownChunker
        from hal.core.memory.exporter import DailyExporter
        from hal.core.memory.search import MemorySearch
        from hal.core.memory.store import VectorStore
    except ImportError as e:
        console.print(f"[yellow]Memory search unavailable (missing dependency: {e})[/yellow]")
        return None

    ms_cfg = config.memory_search

    from hal.core.memory.daily_log import DailyLog

    # Must match MemoryManager's log_dir: (data_dir or workspace) / "logs".
    # MemoryManager defaults data_dir=None → uses workspace, so logs live
    # under workspace/logs, not get_data_dir()/logs.
    log_dir = config.workspace_path / "logs"
    daily_log = DailyLog(log_dir)
    daily_dir = config.workspace_path / "memory" / "daily"

    exporter = DailyExporter(daily_log, daily_dir)
    chunker = MarkdownChunker(
        max_size=ms_cfg.max_chunk_size,
        overlap_lines=ms_cfg.chunk_overlap_lines,
    )
    store = VectorStore(
        uri=ms_cfg.milvus_uri,
        collection_name=ms_cfg.collection_name,
        embedding_dim=ms_cfg.embedding_dim,
    )

    return MemorySearch(
        exporter=exporter,
        chunker=chunker,
        store=store,
        embedding_model=ms_cfg.embedding_model,
        daily_dir=daily_dir,
        embedding_dim=ms_cfg.embedding_dim,
        **_resolve_embedding_provider(config, ms_cfg),
    )


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
    provider = _make_provider(config)

    # Create cron service first (callback set after agent creation)
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # Create agent with cron service
    memory_search = _make_memory_search(config) if config.memory_search.enabled else None
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
        summary_provider=_make_summary_provider(config),
        subagent_model=config.agents.defaults.subagent_model,
        subagent_provider=_make_subagent_provider(config),
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
    provider = _make_provider(config)

    ms = _make_memory_search(config) if config.memory_search.enabled else None

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        web_search_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        summary_model=config.agents.defaults.summary_model,
        summary_provider=_make_summary_provider(config),
        subagent_model=config.agents.defaults.subagent_model,
        subagent_provider=_make_subagent_provider(config),
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
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from hal.infra.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row("WhatsApp", "✓" if wa.enabled else "✗", wa.bridge_url)

    dc = config.channels.discord
    table.add_row("Discord", "✓" if dc.enabled else "✗", dc.gateway_url)

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row("Telegram", "✓" if tg.enabled else "✗", tg_config)

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess

    # User's bridge location
    user_bridge = Path.home() / ".hal" / "bridge"

    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # hal/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall hal")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess

    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.infra.config.loader import get_data_dir

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    jobs = service.list_jobs(include_disabled=all)

    if not jobs:
        console.print("No scheduled jobs.")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")

    import time

    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"

        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000)
            )
            next_run = next_time

        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"

        table.add_row(job.id, job.name, sched, status, next_run)

    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(
        None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"
    ),
):
    """Add a scheduled job."""
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.capabilities.scheduling.types import CronSchedule
    from hal.infra.config.loader import get_data_dir

    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime

        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )

    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.infra.config.loader import get_data_dir

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.infra.config.loader import get_data_dir

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from hal.capabilities.scheduling.cron_service import CronService
    from hal.infra.config.loader import get_data_dir

    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)

    async def run():
        return await service.run_job(job_id, force=force)

    if asyncio.run(run()):
        console.print("[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


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
