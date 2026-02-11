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

DEFAULT_WORKSPACE = Path.home() / ".hal" / "workspace"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "context_dump.md"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _load_session_history(session_key: str) -> list[dict]:
    """Load conversation history from a session file."""
    from hal.session.manager import SessionManager

    # SessionManager reads from ~/.hal/sessions/
    sm = SessionManager(workspace=DEFAULT_WORKSPACE)
    session = sm.get_or_create(session_key)
    return session.get_history()


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
) -> str:
    """Build and return the full context dump as markdown."""
    sections: list[str] = []

    # --- Header ---
    sections.append(f"# Context Dump\n")
    sections.append(f"- **Workspace**: `{workspace}`")
    sections.append(f"- **Mode**: `{mode.value}`")
    if session_key:
        sections.append(f"- **Session**: `{session_key}`")
    if channel:
        sections.append(f"- **Channel**: `{channel}`")
    if chat_id:
        sections.append(f"- **Chat ID**: `{chat_id}`")
    sections.append("")

    # --- Build context ---
    memory = MemoryManager(workspace)
    builder = ContextBuilder(workspace, memory_manager=memory)

    # Load session history if provided
    history: list[dict] = []
    if session_key:
        history = _load_session_history(session_key)

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
            sections.append("```json\n" + json.dumps(content, indent=2, ensure_ascii=False) + "\n```\n")

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
        len(m.get("content", "")) if isinstance(m.get("content"), str) else 0
        for m in messages
    )
    sections.append(f"- System prompt: **{len(system_content)}** chars (~{len(system_content) // 4} tokens)")
    sections.append(f"- Total message content: **{total_chars}** chars (~{total_chars // 4} tokens)")
    sections.append(f"- Conversation history messages: **{len(history)}**")

    # Layer breakdown (heuristic: split by --- dividers in system prompt)
    if isinstance(system_content, str):
        layers = system_content.split("\n\n---\n\n")
        sections.append(f"- System prompt layers: **{len(layers)}**")
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
        "--workspace", "-w",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help=f"Workspace path (default: {DEFAULT_WORKSPACE})",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["collab", "async", "operator"],
        default="collab",
        help="Execution mode (default: collab)",
    )
    parser.add_argument(
        "--session", "-s",
        type=str,
        default=None,
        help="Session key to load history from (e.g. 'cli:direct', 'telegram:12345')",
    )
    parser.add_argument(
        "--tools", "-t",
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
        "--output", "-o",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help=f"Output file path, or '-' for stdout (default: {DEFAULT_OUTPUT})",
    )

    args = parser.parse_args()

    mode = ExecutionMode(args.mode)

    result = dump_context(
        workspace=args.workspace,
        mode=mode,
        session_key=args.session,
        show_tools=args.tools,
        simulated_message=args.message,
        channel=args.channel,
        chat_id=args.chat_id,
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
