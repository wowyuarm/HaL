"""``hal web`` command — start the native session-first web runtime."""

from __future__ import annotations

import asyncio
import webbrowser

from loguru import logger

import typer

from .gateway import _configure_logging
from .root import app, console

_BROWSER_LOCAL_HOSTS = {"0.0.0.0", "::"}


def _browser_url(host: str, port: int) -> str:
    """Translate bind host/port into a browser-friendly local URL."""
    browser_host = "127.0.0.1" if host in _BROWSER_LOCAL_HOSTS else host
    return f"http://{browser_host}:{port}/"


def _try_open_browser(host: str, port: int) -> None:
    """Best-effort browser launch after the web server is listening."""
    url = _browser_url(host, port)
    try:
        opened = webbrowser.open_new_tab(url)
    except Exception as exc:  # pragma: no cover - platform-specific browser failures
        logger.warning("failed to open browser for {}: {}", url, exc)
        console.print(f"[yellow]Could not open browser automatically.[/yellow] Visit {url}")
        return

    if not opened:
        console.print(f"[yellow]Browser did not open automatically.[/yellow] Visit {url}")


@app.command()
def web(
    host: str | None = typer.Option(None, "--host", help="Web server bind host"),
    port: int | None = typer.Option(None, "--port", "-p", help="Web server bind port"),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Open the HaL web UI in a local browser after startup",
    ),
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
        config.web.host = host
    if port is not None:
        config.web.port = port

    effective_host = config.web.host
    effective_port = config.web.port
    console.print(
        f"{__logo__} Starting HaL native web runtime on {effective_host}:{effective_port}..."
    )

    runtime = build_gateway_runtime(config)
    agent = runtime.agent
    memory_search = runtime.memory_search
    server = WebServer(config.web, SessionBridge(agent))

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
            if open_browser:
                await asyncio.to_thread(_try_open_browser, effective_host, effective_port)
            await agent.run()
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            agent.stop()
            await server.stop()

    asyncio.run(run())
