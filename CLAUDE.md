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

# Frontend (web/)
cd web && npm install              # Install frontend deps
cd web && npm run dev              # Vite dev server (port 3000, proxies to backend :8765)
cd web && npm run build            # TypeScript check + Vite production build
cd web && npm test                 # Run all frontend tests
cd web && npm run test:unit        # Run frontend Vitest unit/component tests
cd web && npm run test:regressions # Run bundled frontend regression tests
cd web && npx tsc -b               # TypeScript type-check only
cd web && npx prettier --write .   # Format frontend code
```

## Architecture Overview

HaL is a stateful collaboration system — see `DESIGN.md` for invariants and
collaboration architecture, `docs/specs/message-injects.md` for prompt/replay
inject semantics, `docs/specs/tool-system.md` for tool design principles, and
`docs/specs/design-system.md` plus its linked layer docs for frontend design.

Session-first, async, event-driven: the engine uses `session_id` as its sole
identity key. IM channels are adapters; the native web server bridges directly.

```
Telegram (adapter) ──→ MessageBus ──→ AgentEngine ──→ LLMProvider
                                          ↑             ToolRegistry
Native web (SessionBridge) ──────────────┘             SessionEventPublisher
```

### Key Domain Concepts

| Concept         | Role                                                         |
| --------------- | ------------------------------------------------------------ |
| **Thread**      | Long-lived collaboration container for an ongoing concern    |
| **Session**     | Focused work run, producing durable evidence via events      |
| **Episode**     | Immutable compaction of a session's contribution to a thread |
| **Brief**       | Compiled synthesis of a thread's current state (`BRIEF.md`)  |
| **ContextUnit** | Shared loading protocol for skills and threads               |

### System Layers

| Layer        | Package             | Responsibility                                                             |
| ------------ | ------------------- | -------------------------------------------------------------------------- |
| Domain       | `hal/domain/`       | Semantic types: ContextUnit, SessionManifest, SessionEvent, EventPublisher |
| Context      | `hal/context/`      | Context compilation: builder, compiler, registry, message injects          |
| Runtime      | `hal/runtime/`      | Orchestration: engine, loop, subagent, session lifecycle                   |
| Memory       | `hal/memory/`       | MemoryManager, search, vector store                                        |
| Workspace    | `hal/workspace/`    | Persistence: layout, repos (threads, episodes, sessions, thread refs)      |
| Capabilities | `hal/capabilities/` | Tools and skills                                                           |
| Bus          | `hal/bus/`          | MessageBus, typed events                                                   |
| Web          | `hal/web/`          | Native web server: SessionBridge, REST + WebSocket                         |
| Channels     | `hal/channels/`     | Telegram adapter                                                           |
| CLI          | `hal/cli/`          | CLI commands, factory                                                      |
| Infra        | `hal/infra/`        | Config, LLM providers                                                      |

## Code Conventions

- Python >= 3.11, async-first.
- Ruff rules: `E,F,I,N,W` with `E501` ignored; line length 100.
- Tests use `pytest` + `pytest-asyncio` (`asyncio_mode = auto`).
- Add module-level constants for non-trivial thresholds/limits; avoid magic numbers in flow logic.
- Register new tools/providers through existing registries/factories (`hal/runtime/tool_factory.py`, provider registry).
- Commit messages follow `type(scope): summary`; for frontend work, prefer `web-session`, `web-thread`, `web-ui`, `web-layout`, or `web-runtime` over plain `web` when the change is mainly in one area.

## Frontend Engineering

- For frontend work, read `docs/specs/design-system.md` first, then follow the linked layer docs in `docs/specs/design/` for detailed rules. Use the `hal-design` skill (`/hal-design`).
- Reuse shared patterns before adding one-off classes: `web/src/components/ui/hal-patterns.ts` (layout widths, bounded paper-object variants), `web/src/components/ui/hal-markdown.tsx` (markdown rendering).
- Do not split markdown behavior across multiple styling systems — `HalMarkdown` + `web/src/styles/globals.css` is the primary path.
- Keep working-log and thread-detail body width aligned through shared constants; do not scatter raw width literals like `max-w-[49rem]`.
- Change shared variants or tokens first, not scattered per-component padding values, when adjusting density.
- Vite proxies `/threads` and `/sessions` to backend at `HAL_WEB_BACKEND_ORIGIN` (default `http://localhost:8765`).
- Frontend tests live in `web/tests/`, not `web/scripts/`.
- `web/tests/unit/` is for Vitest + Testing Library coverage of components and helpers.
- `web/tests/regressions/` is for bundled node-side regression tests covering stateful flows like store sync, process summaries, and session-event adaptation.
- Prefer the lightest useful frontend test:
  unit/component first, regression bundle second, browser-level checks only for critical end-to-end paths.

## Configuration & Security

- Runtime config lives in `~/.hal/system/config.yaml`; secrets/tokens in `~/.hal/system/auth.yaml`. Never commit secrets.
- New config keys go in `hal/infra/config/schema.py` with clear inline comments.
- Avoid magic numbers in flow logic — define `UPPER_SNAKE_CASE` module-level constants.
- If modifying filesystem or command-execution tools, validate with `tools.restrict_to_workspace` enabled.
