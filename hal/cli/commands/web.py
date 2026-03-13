"""``hal web`` command — start the native session-first web runtime."""

from __future__ import annotations

import asyncio

import typer

from .gateway import _configure_logging
from .root import app, console


@app.command()
def web(
    host: str | None = typer.Option(None, "--host", help="Web server bind host"),
    port: int | None = typer.Option(None, "--port", "-p", help="Web server bind port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Start HaL with the native web server and no IM channels."""
    from hal import __logo__
    from hal.infra.config.loader import load_config
    from hal.runtime.bootstrap.gateway import build_gateway_runtime
    from hal.web import SessionBridge, WebServer

    _configure_logging(verbose=verbose)

    config = load_config()
    config.channels.telegram.enabled = False
    if host is not None:
        config.channels.web.host = host
    if port is not None:
        config.channels.web.port = port

    effective_host = config.channels.web.host
    effective_port = config.channels.web.port
    console.print(
        f"{__logo__} Starting HaL native web runtime on {effective_host}:{effective_port}..."
    )

    runtime = build_gateway_runtime(config)
    agent = runtime.agent
    memory_search = runtime.memory_search
    server = WebServer(config.channels.web, SessionBridge(agent))

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
                except Exception as exc:
                    console.print(f"[yellow]Memory search init failed: {exc}[/yellow]")
                    agent.disable_memory_search()
                    memory_search = None

            await server.start()
            await agent.run()
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            agent.stop()
            await server.stop()

    asyncio.run(run())
