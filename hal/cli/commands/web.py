"""``hal web`` command — start the engine with only the web channel."""

from __future__ import annotations

import asyncio

import typer

from .gateway import _configure_logging
from .root import app, console


@app.command()
def web(
    host: str | None = typer.Option(None, "--host", help="WebSocket bind host"),
    port: int | None = typer.Option(None, "--port", "-p", help="WebSocket bind port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Start HaL with the web channel only (engine + WebSocket server)."""
    from hal import __logo__
    from hal.infra.config.loader import load_config
    from hal.runtime.bootstrap.gateway import build_gateway_runtime

    _configure_logging(verbose=verbose)

    config = load_config()

    # Force web-only: disable telegram, enable web.
    config.channels.telegram.enabled = False
    config.channels.web.enabled = True
    if host is not None:
        config.channels.web.host = host
    if port is not None:
        config.channels.web.port = port

    effective_host = config.channels.web.host
    effective_port = config.channels.web.port
    console.print(f"{__logo__} Starting HaL web channel on {effective_host}:{effective_port}...")

    runtime = build_gateway_runtime(config)
    agent = runtime.agent
    channels = runtime.channels
    memory_search = runtime.memory_search

    if channels.enabled_channels:
        console.print(
            f"[green]\u2713[/green] Channels enabled: {', '.join(channels.enabled_channels)}"
        )
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    async def run() -> None:
        nonlocal memory_search
        try:
            if memory_search:
                try:
                    await memory_search.initialize()
                    backfill_count = await memory_search.backfill()
                    status = (
                        f"initialized ({backfill_count} chunks backfilled)"
                        if backfill_count
                        else "initialized"
                    )
                    console.print(f"[green]\u2713[/green] Memory search {status}")
                except Exception as e:
                    console.print(f"[yellow]Memory search init failed: {e}[/yellow]")
                    agent.disable_memory_search()
                    memory_search = None

            await asyncio.gather(agent.run(), channels.start_all())
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())
