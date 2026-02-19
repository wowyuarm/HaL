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

HaL is a reliable, precise, and independent digital butler framework. Messages flow through an async message bus that decouples chat platforms from the agent core:

```
Channels (Telegram/Discord/etc) → MessageBus (async queue) → AgentEngine → LLMProvider
                                                                   ↕
                                                              ToolRegistry
```

### Agent Engine (`hal/core/engine.py`)

Thin coordination layer supporting 3 execution modes:
- **COLLAB** — Real-time user conversation (low latency, interactive)
- **ASYNC** — Background long-running tasks (shared memory with origin)
- **OPERATOR** — Scheduled monitoring via cron/heartbeat (high signal-to-noise)

For each inbound message it:
1. Builds a system prompt via `ContextBuilder` (5-layer context system)
2. Delegates to the shared `run_tool_loop()` for LLM calls and tool execution
3. Optionally generates a summary via `generate_summary()`
4. Sends the final response back through the bus

### Runtime (`hal/core/runtime/`)

Shared execution components extracted from the engine:
- **ToolCallingLoop** (`loop.py`) — Hook-based tool-calling loop used by both engine and subagent. Tracks `LoopMetadata` (iterations, side effects, tools used). Customized via `LoopHooks` Protocol.
- **ToolFactory** (`tool_factory.py`) — `create_tools()` builds a `ToolRegistry` with capability-based filtering (engine gets full tools; subagents get a restricted set without message/spawn/cron).
- **Summary** (`summary.py`) — Stateless `generate_summary()` function for post-loop summarization.

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

Coordinated by `MemoryManager`:
- **DailyLog** (`daily_log.py`) — Daily JSONL logs of all interactions
- **LongTermMemory** (`long_term.py`) — Persistent knowledge stored in MEMORY.md
- **MemorySearch** (`search.py`) — Semantic search over memory using vector embeddings
- **VectorStore** (`store.py`) — Milvus-backed vector storage
- **MarkdownChunker** (`chunker.py`) — Splits markdown into chunks for indexing
- **DailyExporter** (`exporter.py`) — Exports daily logs to markdown for indexing

### Tool System (`hal/capabilities/tools/`)

- All tools extend the abstract `Tool` class (`base.py`), defining `name`, `description`, `parameters` (JSON Schema), `execute()`, and optionally `get_side_effects()`
- `get_side_effects(params)` returns metadata (e.g. `files_modified`, `commands_run`) for tracking; returns `None` for read-only calls
- `ToolRegistry` manages registration and dispatch with built-in parameter validation
- Tools are registered via `create_tools()` in `runtime/tool_factory.py`
- **FsTool** (`fs.py`) — Unified filesystem tool (read/write/edit/list). Path restriction uses `Path.relative_to()` for security.
- When `restrict_to_workspace=true`, file/shell tools are sandboxed to the workspace directory

### Provider Registry (`hal/infra/providers/registry.py`)

Single source of truth for LLM provider metadata. A tuple of `ProviderSpec` dataclasses — no if-elif chains. Adding a provider:
1. Add a `ProviderSpec` to `PROVIDERS`
2. Add a field to `ProvidersConfig` in `infra/config/schema.py`
3. Everything else (env vars, prefixing, status display) derives automatically

All providers use `LiteLLMProvider` (`infra/providers/litellm_provider.py`) as the unified implementation.

For OpenAI-compatible proxies (e.g. codex-proxy), set `compatMode: "openai"` in the provider config. This bypasses gateway auto-detection, model-name prefixing, and LiteLLM's internal model registry — the model name is sent as-is and `custom_llm_provider` is passed to LiteLLM so it treats the endpoint as a plain OpenAI client.

### Channels (`hal/channels/`)

Chat platform integrations (Telegram, Discord, WhatsApp, Feishu). Each channel pushes `InboundMessage` to the bus and subscribes to `OutboundMessage` dispatches. They are independent of agent internals.

### Configuration (`hal/infra/config/schema.py`)

Pydantic models. Config lives at `~/.hal/config.json`. Key paths:
- `agents.defaults` — model, workspace, max_tokens, temperature, max_tool_iterations
- `providers.<name>` — apiKey, apiBase, compatMode per provider
  - `compatMode` — protocol hint for proxy endpoints (e.g. `"openai"` for any OpenAI-compatible server); bypasses LiteLLM model registry and auto-detection
- `tools.web.search` — api_key (Tavily), max_results
- `tools.exec` — timeout
- `tools.restrict_to_workspace` — boolean sandbox flag

### Other Key Components

- **Subagent Manager** (`core/subagent.py`) — `spawn` tool creates background agents with isolated context, shares `run_tool_loop()` with the engine
- **Skills Loader** (`capabilities/skills/`) — Loads and manages callable skills from workspace
- **Scheduling** (`capabilities/scheduling/`) — Cron service and heartbeat monitor
- **Heartbeat** (`capabilities/scheduling/heartbeat.py`) — Checks `HEARTBEAT.md` every 30 min for pending tasks
- **Message Bus** (`bus/`) — Async queue-based routing between channels and engine

## Code Conventions

- **Python >=3.11**, async-first design throughout
- **Ruff** for linting: rules `E, F, I, N, W` (E501 ignored), line length 100
- **pytest-asyncio** with `asyncio_mode = "auto"`
- Workspace bootstrap files (AGENTS.md, SOUL.md, etc.) are loaded into the system prompt at runtime — they are not code but agent personality/instruction configuration

## Directory Structure

```
hal/
├── core/               # Core engine, context, memory, runtime
│   ├── engine.py       # AgentEngine — coordination layer (3 modes)
│   ├── subagent.py     # SubagentManager — spawning with isolated context
│   ├── context/        # Context building
│   │   └── builder.py  # ContextBuilder — 5-layer system prompt assembly
│   ├── runtime/        # Shared execution components
│   │   ├── loop.py     # ToolCallingLoop — hook-based tool-calling loop
│   │   ├── tool_factory.py # create_tools() — unified tool registration
│   │   └── summary.py  # generate_summary() — stateless summarization
│   └── memory/         # Memory system
│       ├── manager.py  # MemoryManager — coordinates all memory tiers
│       ├── daily_log.py # DailyLog — JSONL interaction logs
│       ├── long_term.py # LongTermMemory — persistent MEMORY.md
│       ├── search.py   # MemorySearch — semantic search
│       ├── store.py    # VectorStore — Milvus-backed storage
│       ├── chunker.py  # MarkdownChunker — chunk splitting
│       └── exporter.py # DailyExporter — log-to-markdown export
├── capabilities/       # Tools, skills, and scheduling
│   ├── tools/          # Tool implementations
│   │   ├── base.py     # Abstract Tool class (with get_side_effects())
│   │   ├── registry.py # ToolRegistry — dispatch & validation
│   │   ├── fs.py       # FsTool — unified file operations
│   │   ├── exec.py     # ExecTool — shell execution
│   │   ├── web.py      # WebSearchTool, WebFetchTool
│   │   ├── spawn.py    # SpawnTool — subagent creation
│   │   ├── recall.py   # RecallTool — semantic memory search
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
├── cli/                # CLI commands
│   ├── commands.py     # CLI entry points (onboard, agent, gateway, status)
│   ├── factory.py      # Provider and memory search construction
│   ├── cron_commands.py # Cron job management commands
│   └── channel_commands.py # Channel management commands
└── utils/              # Helpers
    └── [utility modules]
```
