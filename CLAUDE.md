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

HaL is a stateful collaboration system — see `DESIGN.md` for invariants and
collaboration architecture, `docs/specs/message-injects.md` for prompt/replay
inject semantics, and `docs/specs/design-system.md` for frontend design.

Session-first, async, event-driven: the engine uses `session_id` as its sole
identity key. IM channels are adapters; the native web server bridges directly.

```
Telegram (adapter) ──→ MessageBus ──→ AgentEngine ──→ LLMProvider
                                          ↑             ToolRegistry
Native web (SessionBridge) ──────────────┘             SessionEventPublisher
```

### Key Domain Concepts

| Concept | Role |
|---------|------|
| **Thread** | Long-lived collaboration container for an ongoing concern |
| **Session** | Focused work run, producing durable evidence via events |
| **Episode** | Immutable compaction of a session's contribution to a thread |
| **Brief** | Compiled synthesis of a thread's current state (`BRIEF.md`) |
| **ContextUnit** | Shared loading protocol for skills and threads |

### System Layers

| Layer | Package | Responsibility |
|-------|---------|----------------|
| Domain | `hal/domain/` | Semantic types: ContextUnit, SessionManifest, SessionEvent, EventPublisher |
| Context | `hal/context/` | Context compilation: builder, compiler, registry, message injects |
| Runtime | `hal/runtime/` | Orchestration: engine, loop, subagent, session lifecycle |
| Memory | `hal/memory/` | MemoryManager, search, vector store |
| Workspace | `hal/workspace/` | Persistence: layout, repos (threads, episodes, sessions, thread refs) |
| Capabilities | `hal/capabilities/` | Tools and skills |
| Bus | `hal/bus/` | MessageBus, typed events |
| Web | `hal/web/` | Native web server: SessionBridge, REST + WebSocket |
| Channels | `hal/channels/` | Telegram adapter |
| CLI | `hal/cli/` | CLI commands, factory |
| Infra | `hal/infra/` | Config, LLM providers |

## Code Conventions

- Python >= 3.11, async-first.
- Ruff rules: `E,F,I,N,W` with `E501` ignored; line length 100.
- Tests use `pytest` + `pytest-asyncio` (`asyncio_mode = auto`).
- Add module-level constants for non-trivial thresholds/limits; avoid magic numbers in flow logic.
- Register new tools/providers through existing registries/factories (`hal/runtime/tool_factory.py`, provider registry).
