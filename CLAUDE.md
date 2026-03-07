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
pytest tests/runtime/test_engine.py

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

### System Layers

| Layer | Package | Responsibility |
|-------|---------|----------------|
| Domain | `hal/domain/` | Semantic types: ContextUnit, ports, metadata |
| Context | `hal/context/` | Context compilation: builder, compiler, registry, baseline |
| Runtime | `hal/runtime/` | Orchestration: engine, loop, subagent, session lifecycle |
| Memory | `hal/memory/` | MemoryManager, daily log, search, vector store |
| Workspace | `hal/workspace/` | Persistence: layout, repos (threads, episodes, sessions) |
| Capabilities | `hal/capabilities/` | Tools and skills |
| Bus | `hal/bus/` | MessageBus, typed events |
| Channels | `hal/channels/` | Telegram integration |
| CLI | `hal/cli/` | CLI commands, factory |
| Infra | `hal/infra/` | Config, LLM providers |

### Agent Engine (`hal/runtime/engine/`)

`AgentEngine` lives in a package:
- `__init__.py`: engine wiring and public methods.
- `processing.py`: main `process_message()` path.
- `hooks.py`: per-loop hook adapter (`_EngineLoopHooks`).
- `subscribers.py`: event subscribers for tool/memory/subagent injections.
- `background_resume.py`: background subagent completion continuation.
- `inspect.py`: context inspection payload builder.
- `progress.py`: tool progress text formatting.
- `subagent_injection.py`: parse/build subagent metadata injections.
- `session_state.py`: SessionState dataclass.
- `session_compaction.py`: in-session history splitting.
- `context_advisor.py`: worker model hint generation.
- `debrief.py`: session debrief confirmation and thread extraction.

### Runtime Loop (`hal/runtime/loop.py`)

`run_tool_loop()` is the shared hook-based loop for both main engine and subagents.
- Tracks `LoopMetadata` (iterations, usage, side effects, tool counts, skipped calls).
- Supports caller hooks (`before_llm_call`, `on_tool_calls_start`, `on_tool_result`, etc.).
- Executes tool calls in parallel and records side-effect metadata.

### Subagent System (`hal/runtime/subagent/`)

- `manager.py`: `SubagentManager` sync/background execution and event emission.
- `hooks.py`: loop hooks with repeated-error recovery nudges.
- `results.py`: status classification, artifact extraction, JSONL execution logs.
- `prompt.py`: focused subagent system prompt and skills injection.

### Context System (`hal/context/`)

- `builder.py`: ContextBuilder — assembles system prompt and message sequence.
- `compiler.py`: ContextCompiler — frozen baseline reuse across turns.
- `registry.py`: ContextRegistry — unified skill/thread discovery + related expansion.
- `baseline.py`: baseline planning (recall, thread selection, related expansion).
- `message_building.py`: message construction helpers (assistant, tool, session baseline, sequences).
- `dynamic_context.py`: XML context block rendering.
- `prompt_layers.py`: system-prompt layer rendering (identity, bootstrap, skills, situation).
- `units.py`: ContextUnit wrappers for skills and threads.
- `history.py`: history loading from session or memory.
- `token_budget.py`: token estimation and text trimming.
- `metrics.py`: context metrics collection.
- `thread_mentions.py`: thread mention detection in messages.

### Message Bus (`hal/bus/`)

Typed events: `InboundMessage`, `OutboundMessage`, `ToolCallEvent`, `ReminderEvent`, `MessageInjectEvent`, `SubagentCompleteEvent`, `SystemStartupEvent`.

### Configuration (`hal/infra/config/`)

Pydantic-based strict config (`extra="forbid"`):
- `~/.hal/system/config.yaml`: non-secret settings
- `~/.hal/system/auth.yaml`: secrets (API keys/tokens)

### Memory (`hal/memory/`)

`MemoryManager` coordinates:
- daily log (`daily_log.py`)
- long-term memory (`long_term.py`)
- optional semantic memory search stack (`search.py`, `store.py`, `chunker.py`, `exporter.py`)

Memory-search imports are optional so base memory usage works without extras installed.

## Code Conventions

- Python >= 3.11, async-first.
- Ruff rules: `E,F,I,N,W` with `E501` ignored; line length 100.
- Tests use `pytest` + `pytest-asyncio` (`asyncio_mode = auto`).
- Add module-level constants for non-trivial thresholds/limits; avoid magic numbers in flow logic.
- Register new tools/providers through existing registries/factories (`hal/runtime/tool_factory.py`, provider registry).

## Directory Structure

```text
hal/
├── bus/              # MessageBus, typed events
├── capabilities/
│   ├── skills/       # Skill loader
│   └── tools/        # Tool implementations (fs, exec, web, spawn, etc.)
├── channels/
│   ├── base.py
│   ├── manager.py
│   └── telegram/
├── cli/
│   ├── commands/
│   └── factory.py
├── context/          # Context compilation (read path)
├── domain/           # Semantic types (ContextUnit, ports, metadata)
├── infra/
│   ├── config/
│   └── providers/
├── memory/           # MemoryManager, daily log, search, store
├── runtime/
│   ├── bootstrap/    # Gateway wiring
│   ├── engine/       # AgentEngine and components
│   ├── subagent/     # SubagentManager
│   ├── loop.py       # Shared tool-calling loop
│   ├── session.py    # Session lifecycle
│   ├── debrief.py    # Episode generation
│   └── ...           # execution, checkpoint, snapshot, summary
├── utils/            # Generic helpers
├── workspace/        # Persistence (layout, repos)
└── bridge/
    └── anyrouter_bridge.mjs
```

## Workspace Layout (`~/.hal/`)

```text
~/.hal/
  system/             # SOUL.md, INSTRUCTIONS.md, MEMORY.md, config.yaml, auth.yaml
  work/threads/       # Thread dirs (STATE.md + THREAD.yaml + episodes/)
  work/inbox/         # Unrouted items
  runtime/logs/       # events.jsonl + daily JSONL
  runtime/sessions/   # Session snapshots
  runtime/metrics/    # context_metrics.jsonl
  capabilities/skills/ # Skill packages
  data/vectors/       # Vector index
  data/artifacts/     # Outputs, subagent reports
  data/media/         # Media files
  projects/           # Project files
```
