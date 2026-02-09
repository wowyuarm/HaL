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
Channels (Telegram/Discord/etc) → MessageBus (async queue) → AgentLoop → LLMProvider
                                                               ↕
                                                          ToolRegistry
```

### Agent Loop (`hal/agent/loop.py`)

The central engine. For each inbound message it:
1. Builds a system prompt via `ContextBuilder` (assembles workspace files: AGENTS.md, SOUL.md, USER.md, TOOLS.md, IDENTITY.md, plus memory and skills)
2. Calls the LLM with conversation history + tool definitions
3. Executes any tool calls, appends results, and loops (max 20 iterations)
4. Sends the final response back through the bus

### Tool System (`hal/agent/tools/`)

- All tools extend the abstract `Tool` class (`base.py`), defining `name`, `description`, `parameters` (JSON Schema), and `execute()`
- `ToolRegistry` manages registration and dispatch with built-in parameter validation
- Tools are registered in `AgentLoop._register_default_tools()`
- When `restrict_to_workspace=true`, file/shell tools are sandboxed to the workspace directory

### Provider Registry (`hal/providers/registry.py`)

Single source of truth for LLM provider metadata. A tuple of `ProviderSpec` dataclasses — no if-elif chains. Adding a provider:
1. Add a `ProviderSpec` to `PROVIDERS`
2. Add a field to `ProvidersConfig` in `config/schema.py`
3. Everything else (env vars, prefixing, status display) derives automatically

All providers use `LiteLLMProvider` (`providers/litellm_provider.py`) as the unified implementation.

### Channels (`hal/channels/`)

Chat platform integrations (Telegram, Discord, WhatsApp, Feishu). Each channel pushes `InboundMessage` to the bus and subscribes to `OutboundMessage` dispatches. They are independent of agent internals.

### Configuration (`hal/config/schema.py`)

Pydantic models. Config lives at `~/.hal/config.json`. Key paths:
- `agents.defaults` — model, workspace, max_tokens, temperature, max_tool_iterations
- `providers.<name>` — apiKey, apiBase per provider
- `tools.web.search` — api_key (Tavily), max_results
- `tools.exec` — timeout
- `tools.restrict_to_workspace` — boolean sandbox flag

### Other Key Components

- **Subagent** (`agent/subagent.py`) — `spawn` tool creates background agents with isolated context
- **Context Builder** (`agent/context.py`) — Assembles system prompt from workspace markdown files + memory + skills
- **Session Manager** (`session/manager.py`) — Per-channel conversation history, persisted as JSON
- **Cron Service** (`cron/service.py`) — Scheduled tasks via croniter
- **Heartbeat** (`heartbeat/service.py`) — Checks `HEARTBEAT.md` every 30 min for pending tasks

## Code Conventions

- **Python >=3.11**, async-first design throughout
- **Ruff** for linting: rules `E, F, I, N, W` (E501 ignored), line length 100
- **pytest-asyncio** with `asyncio_mode = "auto"`
- Workspace bootstrap files (AGENTS.md, SOUL.md, etc.) are loaded into the system prompt at runtime — they are not code but agent personality/instruction configuration
