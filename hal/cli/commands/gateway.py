"""Gateway command group."""

from __future__ import annotations

import asyncio

import typer

from .root import app, console


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the HaL gateway."""
    from hal import __logo__
    from hal.core.bootstrap.gateway import build_gateway_runtime
    from hal.infra.config.loader import load_config

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    console.print(f"{__logo__} Starting HaL gateway on port {port}...")

    config = load_config()
    runtime = build_gateway_runtime(config)
    agent = runtime.agent
    channels = runtime.channels
    memory_search = runtime.memory_search

    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    async def run() -> None:
        nonlocal memory_search
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
                    agent.disable_memory_search()
                    memory_search = None

            await asyncio.gather(agent.run(), channels.start_all())
        except KeyboardInterrupt:
            console.print("\nShutting down...")
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())
