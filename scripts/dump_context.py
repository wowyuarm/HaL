#!/usr/bin/env python3
"""Dump the full context that ContextBuilder would send to an LLM.

Renders each layer as markdown so you can inspect exactly what the agent sees.
Optionally loads a real workspace (with bootstrap files, skills, memory, episodes)
and a session to show a realistic, populated context.

Usage:
    # Default workspace (~/.hal/workspace)
    python scripts/dump_context.py

    # Custom workspace
    python scripts/dump_context.py --workspace /path/to/workspace

    # Include a session's conversation history
    python scripts/dump_context.py --session cli:direct

    # Include tool definitions (JSON)
    python scripts/dump_context.py --tools

    # Specify execution mode
    python scripts/dump_context.py --mode operator

    # Simulate a multi-turn conversation (shows truncation behavior)
    python scripts/dump_context.py --simulate

    # Write output to file (default: scripts/context_dump.md)
    python scripts/dump_context.py -o scripts/context_dump.md

Output is written to scripts/context_dump.md by default, or printed to stdout with -o -.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from hal.capabilities.tools.exec import ExecTool
from hal.capabilities.tools.fs import FsTool
from hal.capabilities.tools.message import MessageTool
from hal.capabilities.tools.registry import ToolRegistry
from hal.capabilities.tools.spawn import SpawnTool
from hal.capabilities.tools.web import WebFetchTool, WebSearchTool
from hal.core.context.builder import ContextBuilder, ExecutionMode
from hal.core.memory.manager import MemoryManager
from hal.infra.config.schema import HistoryConfig

DEFAULT_WORKSPACE = Path.home() / ".hal" / "workspace"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "context_dump.md"


# ------------------------------------------------------------------
# Simulated conversation data
# ------------------------------------------------------------------

SIMULATED_TURNS: list[dict[str, str]] = [
    {
        "role": "user",
        "content": "Help me understand the project structure of this codebase.",
    },
    {
        "role": "assistant",
        "content": (
            "I've analyzed the project structure. Here's a comprehensive overview:\n\n"
            "## Architecture\n\n"
            "The project follows a layered architecture with clear separation of concerns:\n\n"
            "```\n"
            "hal/\n"
            "├── core/           # Core engine, context, memory\n"
            "├── capabilities/   # Tools, skills, scheduling\n"
            "├── channels/       # Chat integrations (Telegram, Discord)\n"
            "├── bus/            # Async message routing\n"
            "├── infra/          # Providers, config, logging\n"
            "└── cli/            # CLI commands\n"
            "```\n\n"
            "### Key Components\n\n"
            "1. **AgentEngine** (`core/engine.py`) — Central execution engine supporting "
            "3 modes: COLLAB, ASYNC, OPERATOR\n"
            "2. **ContextBuilder** (`core/context/builder.py`) — 5-layer prompt assembly\n"
            "3. **MemoryManager** (`core/memory/manager.py`) — Coordinates daily log, "
            "long-term memory, and episodic traces\n"
            "4. **ToolRegistry** (`capabilities/tools/registry.py`) — Tool dispatch "
            "with parameter validation\n\n"
            "The message flow is:\n"
            "```\n"
            "Channels → MessageBus → AgentEngine → LLMProvider\n"
            "                            ↕\n"
            "                       ToolRegistry\n"
            "```\n\n"
            "Would you like me to dive deeper into any specific component?"
        ),
    },
    {
        "role": "user",
        "content": "What tests exist? Run them and show me the results.",
    },
    {
        "role": "assistant",
        "content": (
            "I ran the test suite. Here are the results:\n\n"
            "```\n"
            "$ pytest tests/ -q\n"
            ".................................................................... [100%]\n"
            "262 passed in 8.25s\n"
            "```\n\n"
            "All **262 tests** pass. The test structure mirrors the source layout:\n\n"
            "| Directory | Tests | Coverage |\n"
            "|-----------|-------|----------|\n"
            "| `tests/core/` | 89 | Engine, context, memory |\n"
            "| `tests/capabilities/` | 112 | Tools, skills, scheduling |\n"
            "| `tests/channels/` | 34 | Telegram, Discord, WhatsApp |\n"
            "| `tests/infra/` | 27 | Config, providers |\n\n"
            "Key test files:\n"
            "- `test_engine.py` — Engine execution modes and tool loop\n"
            "- `test_memory.py` — Daily log, long-term memory, manager\n"
            "- `test_tool_validation.py` — Parameter validation for all tools\n"
            "- `test_context_builder.py` — 5-layer context assembly\n\n"
            "No warnings except some deprecation notices from `lark_oapi`."
        ),
    },
    {
        "role": "user",
        "content": "Can you add a health check endpoint to the gateway?",
    },
    {
        "role": "assistant",
        "content": (
            "I've added a `/health` endpoint to the gateway. Here's what I did:\n\n"
            "**Modified `hal/cli/commands.py`:**\n"
            "```python\n"
            "@app.get('/health')\n"
            "async def health_check():\n"
            "    return {\n"
            "        'status': 'ok',\n"
            "        'version': __version__,\n"
            "        'uptime': time.time() - start_time,\n"
            "        'channels': {name: ch.is_connected for name, ch in channels.items()}\n"
            "    }\n"
            "```\n\n"
            "**Added test `tests/test_gateway_health.py`:**\n"
            "```python\n"
            "async def test_health_endpoint(client):\n"
            "    resp = await client.get('/health')\n"
            "    assert resp.status_code == 200\n"
            "    data = resp.json()\n"
            "    assert data['status'] == 'ok'\n"
            "```\n\n"
            "The endpoint returns:\n"
            "- `status` — always 'ok' if reachable\n"
            "- `version` — current HaL version\n"
            "- `uptime` — seconds since gateway start\n"
            "- `channels` — connection status per channel\n\n"
            "All tests pass including the new one (263 total)."
        ),
    },
    {
        "role": "user",
        "content": "Now help me refactor the config schema to support environment-specific overrides.",
    },
    {
        "role": "assistant",
        "content": (
            "I've implemented environment-specific config overrides. The approach:\n\n"
            "## Design\n\n"
            "Config files are loaded in priority order (later overrides earlier):\n"
            "1. `~/.hal/config.json` — base config\n"
            "2. `~/.hal/config.{env}.json` — environment overlay (e.g., `config.dev.json`)\n"
            "3. `HAL_*` environment variables — runtime overrides\n\n"
            "The `env` is determined by `HAL_ENV` (default: `production`).\n\n"
            "## Changes\n\n"
            "**`hal/infra/config/loader.py`:**\n"
            "```python\n"
            "def load_config(config_path=None, env=None):\n"
            "    env = env or os.getenv('HAL_ENV', 'production')\n"
            "    base = _load_json(config_path or get_config_path())\n"
            "    overlay_path = get_config_path().with_suffix(f'.{env}.json')\n"
            "    if overlay_path.exists():\n"
            "        overlay = _load_json(overlay_path)\n"
            "        base = deep_merge(base, overlay)\n"
            "    return Config.model_validate(convert_keys(base))\n"
            "```\n\n"
            "**`hal/infra/config/schema.py`:**\n"
            "- Added `env: str` field to `Config`\n"
            "- Added `ConfigOverride` model for partial configs\n\n"
            "**Tests:** Added 5 new tests covering merge behavior, missing overlay, "
            "env var precedence.\n\n"
            "```\n"
            "$ pytest tests/infra/test_config.py -q\n"
            "12 passed in 0.4s\n"
            "```"
        ),
    },
    {
        "role": "user",
        "content": "Good work. What's the current memory usage pattern?",
    },
    {
        "role": "assistant",
        "content": (
            "Here's the memory system's current usage pattern:\n\n"
            "## Storage\n\n"
            "- **Daily logs**: `~/.hal/data/logs/YYYY-MM-DD.jsonl` — append-only, one file per day\n"
            "- **Long-term memory**: `~/.hal/workspace/memory/MEMORY.md` — agent-editable markdown\n"
            "- **Config**: `~/.hal/config.json` — Pydantic-validated JSON\n\n"
            "## Typical sizes\n\n"
            "| Component | Size/day | Growth |\n"
            "|-----------|----------|--------|\n"
            "| Daily log (active) | 50-200 KB | Linear with conversation |\n"
            "| MEMORY.md | 2-10 KB | Slow (agent curates) |\n"
            "| Session data | N/A | Deprecated |\n\n"
            "## Context window usage\n\n"
            "Per request, the context consumes roughly:\n"
            "- System prompt (L0-L3): ~3,500 tokens (stable, cached)\n"
            "- Dynamic context prefix: ~100-300 tokens (time, channel, memories)\n"
            "- History (L4): ~2,000-8,000 tokens (last 50 messages)\n"
            "- Current message: variable\n\n"
            "Total: typically **6,000-12,000 tokens** per request, well within "
            "most model context windows. The system prompt is fully cacheable."
        ),
    },
]


def _populate_simulated_history(memory: MemoryManager, channel: str, chat_id: str) -> None:
    """Write simulated conversation entries to the daily log."""
    for turn in SIMULATED_TURNS:
        memory.record_conversation(
            channel=channel,
            chat_id=chat_id,
            role=turn["role"],
            content=turn["content"],
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _load_conversation_history(
    memory: MemoryManager,
    session_key: str,
    history_config: HistoryConfig | None = None,
) -> list[dict]:
    """Load conversation history from the daily log."""
    if ":" in session_key:
        channel, chat_id = session_key.split(":", 1)
    else:
        channel, chat_id = "cli", session_key

    hc = history_config or HistoryConfig()
    return memory.get_conversation_history(
        channel=channel,
        chat_id=chat_id,
        max_messages=hc.max_messages,
        recent_full_turns=hc.recent_full_turns,
        assistant_truncate_chars=hc.assistant_truncate_chars,
    )


def _build_tool_registry() -> ToolRegistry:
    """Build a default tool registry (same as AgentEngine._register_default_tools)."""
    registry = ToolRegistry()
    registry.register(FsTool())
    registry.register(ExecTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(MessageTool(send_callback=None))
    registry.register(SpawnTool(manager=None))
    return registry


def _format_tool_definitions(registry: ToolRegistry) -> str:
    """Format tool definitions as indented JSON."""
    defs = registry.get_definitions()
    return json.dumps(defs, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


def dump_context(
    workspace: Path,
    mode: ExecutionMode,
    session_key: str | None,
    show_tools: bool,
    simulated_message: str,
    channel: str | None,
    chat_id: str | None,
    simulate: bool = False,
    history_config: HistoryConfig | None = None,
) -> str:
    """Build and return the full context dump as markdown."""
    sections: list[str] = []
    hc = history_config or HistoryConfig()

    # --- Header ---
    sections.append("# Context Dump\n")
    sections.append(f"- **Workspace**: `{workspace}`")
    sections.append(f"- **Mode**: `{mode.value}`")
    if session_key:
        sections.append(f"- **Session**: `{session_key}`")
    if channel:
        sections.append(f"- **Channel**: `{channel}`")
    if chat_id:
        sections.append(f"- **Chat ID**: `{chat_id}`")
    sections.append(
        f"- **History config**: max_messages={hc.max_messages}, "
        f"recent_full_turns={hc.recent_full_turns}, "
        f"assistant_truncate_chars={hc.assistant_truncate_chars}"
    )
    if simulate:
        sections.append(f"- **Simulated**: {len(SIMULATED_TURNS)} turns injected")
    sections.append("")

    # --- Build context ---
    memory = MemoryManager(workspace)
    builder = ContextBuilder(workspace, memory_manager=memory)

    # Populate simulated data if requested
    sim_channel = channel or "cli"
    sim_chat_id = chat_id or "simulate"  # Use distinct chat_id to avoid polluting real sessions
    if simulate:
        # Reset first to ensure idempotent output across repeated runs
        memory.clear_conversation_history(sim_channel, sim_chat_id)
        _populate_simulated_history(memory, sim_channel, sim_chat_id)
        if not session_key:
            session_key = f"{sim_channel}:{sim_chat_id}"

    # Load conversation history if provided
    history: list[dict] = []
    if session_key:
        history = _load_conversation_history(memory, session_key, history_config=hc)

    messages = builder.build_messages(
        history=history,
        current_message=simulated_message,
        channel=channel,
        chat_id=chat_id,
        mode=mode,
    )

    # --- Render each message ---
    sections.append("---\n")
    sections.append("## Messages Sent to LLM\n")
    sections.append(f"Total messages: **{len(messages)}**\n")

    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # Truncation hint for large content
        if isinstance(content, str):
            char_count = len(content)
            token_est = char_count // 4  # rough estimate
            label = f"Message {i} — `{role}` (~{token_est} tokens, {char_count} chars)"
        elif isinstance(content, list):
            label = f"Message {i} — `{role}` (multimodal, {len(content)} parts)"
        else:
            label = f"Message {i} — `{role}`"

        sections.append(f"### {label}\n")

        if isinstance(content, str):
            # For system prompt, render the raw content with layer markers
            if role == "system":
                sections.append("<details>\n<summary>System prompt (click to expand)</summary>\n")
                sections.append(f"```\n{content}\n```")
                sections.append("\n</details>\n")

                # Also render it as actual markdown for readability
                sections.append("**Rendered system prompt:**\n")
                sections.append(content)
                sections.append("")
            else:
                sections.append(f"```\n{content}\n```\n")
        elif isinstance(content, list):
            sections.append(
                "```json\n" + json.dumps(content, indent=2, ensure_ascii=False) + "\n```\n"
            )

    # --- Tool definitions ---
    if show_tools:
        sections.append("---\n")
        sections.append("## Tool Definitions (function calling schema)\n")
        registry = _build_tool_registry()
        sections.append(f"Registered tools: **{len(registry)}**\n")
        sections.append(f"```json\n{_format_tool_definitions(registry)}\n```\n")

    # --- Statistics ---
    sections.append("---\n")
    sections.append("## Statistics\n")

    system_content = messages[0].get("content", "") if messages else ""
    total_chars = sum(
        len(m.get("content", "")) if isinstance(m.get("content"), str) else 0 for m in messages
    )
    sections.append(
        f"- System prompt (stable): **{len(system_content)}** chars "
        f"(~{len(system_content) // 4} tokens)"
    )
    sections.append(
        f"- Total message content: **{total_chars}** chars (~{total_chars // 4} tokens)"
    )
    sections.append(f"- Conversation history messages: **{len(history)}**")

    # Show dynamic context size (last user message minus the raw user text)
    if messages:
        last_msg = messages[-1].get("content", "")
        if isinstance(last_msg, str) and "<context>" in last_msg:
            ctx_end = last_msg.find("</context>")
            if ctx_end != -1:
                dynamic_size = ctx_end + len("</context>")
                sections.append(
                    f"- Dynamic context prefix: **{dynamic_size}** chars "
                    f"(~{dynamic_size // 4} tokens) — time, channel, memories"
                )

    # Layer breakdown (heuristic: split by --- dividers in system prompt)
    if isinstance(system_content, str):
        layers = system_content.split("\n\n---\n\n")
        sections.append(f"- System prompt layers: **{len(layers)}** (all stable, cacheable)")
        for j, layer in enumerate(layers):
            first_line = layer.strip().split("\n")[0][:80]
            sections.append(f"  - Layer {j}: {len(layer)} chars — `{first_line}`")

    sections.append("")
    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(
        description="Dump the full agent context as markdown for inspection."
    )
    parser.add_argument(
        "--workspace",
        "-w",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help=f"Workspace path (default: {DEFAULT_WORKSPACE})",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=["collab", "async", "operator"],
        default="collab",
        help="Execution mode (default: collab)",
    )
    parser.add_argument(
        "--session",
        "-s",
        type=str,
        default=None,
        help="Session key to load history from (e.g. 'cli:direct', 'telegram:12345')",
    )
    parser.add_argument(
        "--tools",
        "-t",
        action="store_true",
        help="Include tool definitions in the dump",
    )
    parser.add_argument(
        "--message",
        type=str,
        default="Hello, what can you help me with?",
        help="Simulated user message (default: greeting)",
    )
    parser.add_argument(
        "--channel",
        type=str,
        default=None,
        help="Channel name (e.g. 'telegram', 'cli')",
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=None,
        help="Chat ID",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Inject simulated multi-turn conversation to demonstrate truncation",
    )
    parser.add_argument(
        "--recent-full-turns",
        type=int,
        default=None,
        help="Override recent_full_turns from config (number of recent assistant msgs kept verbatim)",
    )
    parser.add_argument(
        "--truncate-chars",
        type=int,
        default=None,
        help="Override assistant_truncate_chars from config",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help=f"Output file path, or '-' for stdout (default: {DEFAULT_OUTPUT})",
    )

    args = parser.parse_args()

    mode = ExecutionMode(args.mode)

    # Build history config: start from file config, apply CLI overrides
    hc = HistoryConfig()
    try:
        from hal.infra.config.loader import load_config

        file_cfg = load_config()
        hc = file_cfg.agents.defaults.history
    except Exception:
        pass
    if args.recent_full_turns is not None:
        hc = hc.model_copy(update={"recent_full_turns": args.recent_full_turns})
    if args.truncate_chars is not None:
        hc = hc.model_copy(update={"assistant_truncate_chars": args.truncate_chars})

    result = dump_context(
        workspace=args.workspace,
        mode=mode,
        session_key=args.session,
        show_tools=args.tools,
        simulated_message=args.message,
        channel=args.channel,
        chat_id=args.chat_id,
        simulate=args.simulate,
        history_config=hc,
    )

    if args.output == "-":
        print(result)
    else:
        out_path = Path(args.output)
        out_path.write_text(result, encoding="utf-8")
        print(f"Context dump written to {out_path}")
        print(f"  Size: {len(result)} chars")


if __name__ == "__main__":
    main()
