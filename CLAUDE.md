# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install (development)
pip install -e ".[dev]"

# Run
hal onboard              # First-time setup (creates ~/.hal/)
hal agent -m "message"   # Single message mode
hal agent                # Interactive REPL
hal gateway              # Start all enabled chat channels

# Test
pytest tests/                # Run all tests
pytest tests/test_tool_validation.py  # Single test file

# Lint & Format
ruff check hal/          # Lint
ruff format hal/         # Format
```

## Architecture Overview

HaL is a reliable, precise, and independent digital butler framework (~3.4K lines of core agent code). Messages flow through an async message bus that decouples chat platforms from the agent core:

```
Channels (Telegram/Discord/etc) → MessageBus (async queue) → AgentEngine → LLMProvider
                                                                   ↕
                                                              ToolRegistry
```

### Agent Engine (`hal/core/engine.py`)

The central engine (renamed from `AgentLoop`; alias kept for compatibility). Supports 3 execution modes:
- **COLLAB** — Real-time user conversation (low latency, interactive)
- **ASYNC** — Background long-running tasks (shared memory with origin)
- **OPERATOR** — Scheduled monitoring via cron/heartbeat (high signal-to-noise)

For each inbound message it:
1. Builds a system prompt via `ContextBuilder` (5-layer context system)
2. Calls the LLM with conversation history + tool definitions
3. Executes any tool calls, appends results, and loops (max 20 iterations)
4. Sends the final response back through the bus

### Context Builder (`hal/core/context/builder.py`)

Assembles the system prompt through a 5-layer architecture. Layers 0–2 form a stable prefix (maximizes prompt cache hits); Layers 3–4 are dynamic per request.

| Layer | Name         | Content                                          |
|-------|--------------|--------------------------------------------------|
| 0     | Identity     | Stable agent identity (rarely changes)           |
| 1     | Personality  | Per-agent instance (SOUL.md, USER.md, etc.)      |
| 2     | Capabilities | Tools + skills definitions                       |
| 3     | Memory       | Dynamic memory (episodic + long-term, per request)|
| 4     | Conversation | Current session history + inbound message        |

### Memory System (`hal/core/memory/`)

Three-tier memory architecture, coordinated by `MemoryManager`:
- **EpisodicMemory** (`episodic.py`) — Short-term event traces stored as JSONL
- **LongTermMemory** (`long_term.py`) — Persistent knowledge stored in MEMORY.md
- **WorkingMemory** (`working.py`) — Current session state (transient)

### Tool System (`hal/capabilities/tools/`)

- All tools extend the abstract `Tool` class (`base.py`), defining `name`, `description`, `parameters` (JSON Schema), and `execute()`
- `ToolRegistry` manages registration and dispatch with built-in parameter validation
- Tools are registered in `AgentEngine._register_default_tools()`
- **FsTool** (`fs.py`) — Unified filesystem tool that replaces the former 4 individual tools (`read_file`, `write_file`, `edit_file`, `list_dir`) with a single multi-action tool
- When `restrict_to_workspace=true`, file/shell tools are sandboxed to the workspace directory

### Provider Registry (`hal/infra/providers/registry.py`)

Single source of truth for LLM provider metadata. A tuple of `ProviderSpec` dataclasses — no if-elif chains. Adding a provider:
1. Add a `ProviderSpec` to `PROVIDERS`
2. Add a field to `ProvidersConfig` in `infra/config/schema.py`
3. Everything else (env vars, prefixing, status display) derives automatically

All providers use `LiteLLMProvider` (`infra/providers/litellm_provider.py`) as the unified implementation.

### Channels (`hal/channels/`)

Chat platform integrations (Telegram, Discord, WhatsApp, Feishu). Each channel pushes `InboundMessage` to the bus and subscribes to `OutboundMessage` dispatches. They are independent of agent internals.

### Configuration (`hal/infra/config/schema.py`)

Pydantic models. Config lives at `~/.hal/config.json`. Key paths:
- `agents.defaults` — model, workspace, max_tokens, temperature, max_tool_iterations
- `providers.<name>` — apiKey, apiBase per provider
- `tools.web.search` — api_key (Tavily), max_results
- `tools.exec` — timeout
- `tools.restrict_to_workspace` — boolean sandbox flag

### Other Key Components

- **Subagent Manager** (`core/subagent.py`) — `spawn` tool creates background agents with isolated context
- **Skills Loader** (`capabilities/skills/`) — Loads and manages callable skills from workspace
- **Scheduling** (`capabilities/scheduling/`) — Cron service and heartbeat monitor
- **Heartbeat** (`capabilities/scheduling/heartbeat.py`) — Checks `HEARTBEAT.md` every 30 min for pending tasks
- **Session Manager** (`session/manager.py`) — Per-channel conversation history, persisted as JSON
- **Message Bus** (`bus/`) — Async queue-based routing between channels and engine

## Code Conventions

- **Python >=3.11**, async-first design throughout
- **Ruff** for linting: rules `E, F, I, N, W` (E501 ignored), line length 100
- **pytest-asyncio** with `asyncio_mode = "auto"`
- Workspace bootstrap files (AGENTS.md, SOUL.md, etc.) are loaded into the system prompt at runtime — they are not code but agent personality/instruction configuration

## Directory Structure

```
hal/
├── core/               # Core engine, context, memory
│   ├── engine.py       # AgentEngine — central execution engine (3 modes)
│   ├── subagent.py     # SubagentManager — spawning with isolated context
│   ├── context/        # Context building
│   │   └── builder.py  # ContextBuilder — 5-layer system prompt assembly
│   └── memory/         # Three-tier memory system
│       ├── manager.py  # MemoryManager — coordinates all memory tiers
│       ├── episodic.py # EpisodicMemory — JSONL event traces
│       ├── long_term.py # LongTermMemory — persistent MEMORY.md
│       └── working.py  # WorkingMemory — transient session state
├── capabilities/       # Tools, skills, and scheduling
│   ├── tools/          # Tool implementations
│   │   ├── base.py     # Abstract Tool class
│   │   ├── registry.py # ToolRegistry — dispatch & validation
│   │   ├── fs.py       # FsTool — unified file operations (read/write/edit/list)
│   │   ├── exec.py     # ExecTool — shell execution
│   │   ├── web.py      # WebSearchTool, WebFetchTool
│   │   ├── spawn.py    # SpawnTool — subagent creation
│   │   ├── schedule.py # CronTool — task scheduling
│   │   └── message.py  # MessageTool — cross-channel messaging
│   ├── skills/         # Callable skills from workspace
│   └── scheduling/     # Scheduled tasks and heartbeat
│       ├── cron_service.py # Cron service via croniter
│       └── heartbeat.py    # Heartbeat monitor for HEARTBEAT.md
├── channels/           # Chat integrations
│   ├── base.py         # Abstract Channel class
│   ├── telegram.py     # Telegram integration
│   ├── discord.py      # Discord integration
│   └── [other channels]
├── bus/                # Async message routing
│   ├── events.py       # InboundMessage, OutboundMessage
│   └── queue.py        # MessageBus — async queue & dispatch
├── infra/              # Providers, config, logging
│   ├── providers/      # LLM provider integrations
│   │   ├── registry.py # ProviderSpec — declarative metadata
│   │   ├── litellm_provider.py # Unified LLM client
│   │   └── [provider files]
│   └── config/         # Configuration management
│       └── schema.py   # Pydantic config models
├── session/            # Conversation sessions
│   └── manager.py      # SessionManager — per-channel history
├── cli/                # CLI commands
│   └── commands.py     # CLI entry points (onboard, agent, gateway)
└── utils/              # Helpers
    └── [utility modules]
```
