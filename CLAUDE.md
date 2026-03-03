# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install (development)
pip install -e ".[dev]"

# Run
hal gateway                    # Start engine + enabled channels
hal anyrouter bridge           # Start local AnyRouter Node bridge (optional)

# Test
pytest tests/                  # Run all tests
pytest tests/core/test_engine.py

# Lint & Format
ruff check hal/
ruff format hal/
```

## Architecture Overview

HaL is an async, bus-driven personal butler. Channels send inbound messages to a shared `MessageBus`; the engine consumes, runs the LLM/tool loop, and publishes outbound messages.

```
Channel (Telegram) -> MessageBus -> AgentEngine -> LLMProvider
                                   -> ToolRegistry
```

### Agent Engine (`hal/core/engine/`)

`AgentEngine` now lives in a package (not a single `engine.py` file):
- `__init__.py`: engine wiring and public methods.
- `processing.py`: main `process_message()` path.
- `hooks.py`: per-loop hook adapter (`_EngineLoopHooks`).
- `subscribers.py`: event subscribers for tool/memory/subagent injections.
- `background_resume.py`: background subagent completion continuation runtime.
- `inspect.py`: context inspection payload builder.
- `progress.py`: tool progress text formatting.
- `subagent_injection.py`: parse/build subagent metadata injections.

Important runtime model:
- Single processing path (`PROCESSING_MODE = "default"`).
- No legacy mode switching stack in engine.
- Per-message failures are isolated and converted into user-facing fallback output.

### Runtime Loop (`hal/core/runtime/loop.py`)

`run_tool_loop()` is the shared hook-based loop for both main engine and subagents.
- Tracks `LoopMetadata` (iterations, usage, side effects, tool counts, skipped calls).
- Supports caller hooks (`before_llm_call`, `on_tool_calls_start`, `on_tool_result`, etc.).
- Executes tool calls in parallel and records side-effect metadata from tool interfaces.

### Subagent System (`hal/core/subagent/`)

Subagent code is package-split:
- `manager.py`: `SubagentManager` sync/background execution and event emission.
- `hooks.py`: loop hooks with repeated-error recovery nudges.
- `results.py`: status classification, artifact extraction, JSONL execution logs.
- `prompt.py`: focused subagent system prompt and skills injection.

Background completions are delivered via `SubagentCompleteEvent` and resumed by engine-side background runtime. The internal completed-results cache is bounded to avoid unbounded growth.

### Message Bus (`hal/bus/`)

Typed events are first-class:
- `InboundMessage`, `OutboundMessage`
- `ToolCallEvent`, `ReminderEvent`, `MessageInjectEvent`, `SubagentCompleteEvent`, `SystemStartupEvent`

`MessageBus` supports:
- inbound/outbound async queues for channel-engine routing
- typed event subscribe/unsubscribe/emit fanout for extension points

### Channels (`hal/channels/`)

Telegram integration is package-split (`hal/channels/telegram/`):
- `channel.py`: composed `TelegramChannel`
- `lifecycle.py`: start/stop, startup notification, startup events
- `messaging.py`: send/inbound media handling/typing indicator
- `commands.py`: `/start`, `/reset`, `/context`, `/help`
- `context.py`, `context_report.py`, `formatting.py`, `constants.py`

`ChannelManager` owns enabled channel startup/shutdown and outbound dispatching.

### CLI (`hal/cli/`)

CLI commands are package-split:
- `commands/root.py`: root Typer app and shared helpers
- `commands/gateway.py`: gateway command
- `commands/anyrouter.py`: AnyRouter bridge command
- `commands/__init__.py`: command module registration

Bootstrap wiring for runtime assembly is in `hal/core/bootstrap/gateway.py`.

### Configuration (`hal/infra/config/`)

Pydantic-based strict config (`extra="forbid"`):
- `~/.hal/config.yaml`: non-secret settings
- `~/.hal/auth.yaml`: secrets (API keys/tokens)

Notable points:
- legacy/unknown keys are rejected
- runtime knobs are centralized in schema (`EngineConfig`, tool configs, etc.)
- no scheduling/cron runtime section in current architecture

### Memory (`hal/core/memory/`)

`MemoryManager` coordinates:
- daily log (`daily_log.py`)
- long-term memory (`long_term.py`)
- optional semantic memory search stack (`search.py`, `store.py`, `chunker.py`, `exporter.py`)

`hal/core/memory/__init__.py` keeps memory-search imports optional so base memory usage works without memory extras installed.

## Code Conventions

- Python >= 3.11, async-first.
- Ruff rules: `E,F,I,N,W` with `E501` ignored; line length 100.
- Tests use `pytest` + `pytest-asyncio` (`asyncio_mode = auto`).
- Add module-level constants for non-trivial thresholds/limits; avoid magic numbers in flow logic.
- Register new tools/providers through existing registries/factories (`runtime/tool_factory.py`, provider registry).

## Current Directory Structure

```text
hal/
├── bus/
│   ├── events.py
│   └── queue.py
├── capabilities/
│   ├── skills/
│   └── tools/
├── channels/
│   ├── base.py
│   ├── manager.py
│   └── telegram/
├── cli/
│   ├── commands/
│   └── factory.py
├── core/
│   ├── bootstrap/
│   ├── context/
│   ├── engine/
│   ├── memory/
│   ├── runtime/
│   ├── subagent/
│   └── ports.py
├── infra/
│   ├── config/
│   └── providers/
└── bridge/
    └── anyrouter_bridge.mjs
```
