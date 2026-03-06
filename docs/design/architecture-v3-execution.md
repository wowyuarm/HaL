# Architecture v3 Execution Plan

> Status: active execution tracker for staged implementation.
> North-star reference: `docs/design/architecture-v3.md`.

## Purpose

This document is the execution anchor for long-running Architecture v3 work.
It exists to prevent drift across long sessions and compaction boundaries.

## Milestones

1. Phase 0: Anchor docs and execution rules
2. Phase 1: Workspace persistence boundaries
3. Phase 2: Context compiler and working-set boundaries
4. Phase 3: Runtime orchestration slimming
5. Phase 4: Package reorg readiness (no flag day)

## Current State

- Completed:
  - Session baseline freezing and dynamic-context de-duplication
  - Background resume persistence fixes
  - Thread touch semantics expansion
  - Thread machine metadata (`THREAD.yaml`) support
  - Initial workspace repositories (`events`, `memory`, `artifacts`, `threads`)
  - v3-aware layout resolution and runtime subdirectory detection
- In progress:
  - Deepening workspace repositories and reducing engine-owned file IO
  - Tightening context-layer boundaries (`compiler`/`registry`/`builder`)
- Not started:
  - Full top-level package reorganization (`hal/domain`, `hal/runtime`, `hal/context`, ...)
  - Workspace runtime migration execution for real `~/.hal` environments

## Non-Goals For Current Run

- No flag-day package rename or mass module move
- No direct migration of real production `~/.hal` during refactor batches
- No expansion of thread lifecycle product semantics beyond current behavior

## Compact Recovery Protocol

When work resumes after compaction:

1. Read `docs/design/architecture-v3.md`
2. Read this file (`docs/design/architecture-v3-execution.md`)
3. Read latest 20 commits (`git log --oneline -20`)
4. Continue only from the `In progress` item in this document
5. After each commit batch:
   - Re-read steps 1 and 2
   - Append a short progress entry to `Progress Log`

## Validation Gate

For each small batch:

- `PYTHONPATH=. pytest <targeted tests> -q`
- `uvx pyscn@latest analyze --json --no-open hal/`

For milestone boundary:

- `pytest tests/`
- `ruff check hal tests`
- `uvx pyscn@latest analyze --json --no-open .`

## Working Assumptions

- Code-first, migration-later: refactor capabilities first, migrate runtime workspace later
- Boundary-first reorganization: stabilize interfaces before moving package roots
- `architecture-v3.md` is the semantic north star
- `context-system-v2.md` remains the behavior baseline for correctness

## Progress Log

- 2026-03-06:
  - Execution anchor document created
  - Next step locked: Phase 1 starts with episode persistence boundary extraction
  - Phase 1 batch 1 completed:
    - Added `EpisodeRepository` in `hal/workspace/episodes.py`
    - Routed episode path/write/collection through workspace episode boundary
    - Updated memory search episode backfill to depend on `EpisodeRepository`
    - Added workspace episode repository tests and retained thread-level compatibility wrappers
  - Phase 1 batch 2 completed:
    - Added `MetricsRepository` in `hal/workspace/metrics.py`
    - Removed direct `WorkspaceLayout` metrics-path dependency from `AgentEngine`
    - Added workspace metrics repository tests and kept collector behavior unchanged
    - `pyscn` command remained non-responsive and timed out in this environment; pytest/ruff gates passed
  - Phase 2 batch 1 started:
    - Added `ContextRegistry.from_workspace()` as the registry composition boundary
    - Removed `ContextBuilder` direct `ThreadRepository` dependency
    - Updated context registry tests to validate workspace-backed composition path
  - Phase 1 batch 3 completed:
    - Added `SessionRepository` in `hal/workspace/sessions.py`
    - Persisted background-resume session snapshots through workspace repository
    - Added repository fallback loading path when in-memory background snapshot cache is empty
    - Added workspace session repository tests and background resume fallback coverage
  - Phase 2 batch 2 completed:
    - Moved active-thread filtering semantics from `ContextBuilder` to `ContextRegistry`
    - Added `active_thread_entry_snapshot()` for dynamic-context assembly
    - Added registry test coverage for active-only filtering behavior
  - Phase 1 batch 4 completed:
    - Added session snapshot cleanup path for idle timeout, debrief start, and engine stop
    - Added `SessionRepository.delete_snapshot()` and wired background-resume cache cleanup
    - Added tests covering repository deletion and background-resume cleanup behavior
  - Phase 1 batch 5 completed:
    - Added `LogRepository` for workspace log directory/date-path resolution
    - Removed `MemoryManager` direct `WorkspaceLayout` dependency for daily log wiring
    - Added workspace log repository tests for legacy and v3 path preference
  - Phase 3 batch 1 completed:
    - Delegated session-id/session-state/session-touch orchestration to `session_runtime`
    - Reduced `AgentEngine` session lifecycle method bodies to thin runtime wrappers
    - Preserved idle-timeout/session-rotation behavior with full `test_engine` coverage
  - Phase 1 batch 6 completed:
    - Added `SkillRepository` for workspace skill directory and SKILL.md path resolution
    - Removed `SkillsLoader` direct `WorkspaceLayout` dependency
    - Added workspace skill repository tests and verified skills/context loader behavior
  - Phase 2 batch 3 completed:
    - Added `build_capabilities_prompt()` in `prompt_layers` for capability-layer rendering
    - Reduced `ContextBuilder` capability assembly logic to a thin layer call
    - Added context prompt-layer unit tests for capability rendering behavior
  - Phase 1 batch 7 completed:
    - Removed `cli/factory.py` direct `WorkspaceLayout` dependency for memory-search roots
    - Switched memory-search path wiring to `ThreadRepository` + `LogRepository` boundaries
    - Added CLI factory coverage for v3-root preference (`work/threads`, `runtime/logs`)
  - Phase 3 batch 2 completed:
    - Extracted session debrief runtime orchestration into `debrief_runtime.py`
    - Reduced `AgentEngine` debrief methods to thin delegation wrappers
    - Preserved existing debrief behavior with full engine+debrief test coverage
  - Phase 2 batch 4 completed:
    - Reused `build_thread_unit_manifests()` inside `ContextRegistry.thread_manifests()`
    - Removed duplicate thread-manifest projection logic from registry layer
    - Updated context unit tests to use repository-driven thread manifest discovery
  - Correctness follow-up batch completed:
    - Extended debrief episode schema to include `## Status`
    - Added hot-layer status merge in `apply_episode_state_patch()` to advance `STATE.md` status
    - Added workspace tests validating debrief-driven status transitions in thread state files
  - Phase 3 batch 3 completed:
    - Extracted session-checkpoint generation runtime into `checkpoint_runtime.py`
    - Removed prompt/template + provider orchestration details from `AgentEngine`
    - Kept compaction behavior stable via existing `test_engine` compaction coverage
  - Phase 3 batch 4 completed:
    - Extracted session snapshot message assembly into `snapshot_runtime.py`
    - Removed `AgentEngine` direct dependency on context message-sequence builders
    - Preserved snapshot/background behavior with engine and compaction test suites
  - Phase 3 batch 5 completed:
    - Extracted tool-loop execution orchestration into `loop_runtime.py`
    - Reduced `AgentEngine._execute_loop()` to runtime delegation with compatibility call-through
    - Preserved loop instrumentation behavior via `test_engine` and progress-flow coverage
  - Phase 3 batch 6 completed:
    - Extracted summary trigger/model resolution orchestration into `summary_runtime.py`
    - Reduced `AgentEngine` summary helpers to thin runtime delegation
    - Preserved summary trigger behavior with engine regression coverage
  - Phase 3 batch 8 completed:
    - Added debrief thread-order policy using registry priorities (high-priority threads first)
    - Expanded debrief thread scope with one-hop related threads before episode generation
    - Added runtime regression coverage for related-thread expansion and ordered debrief processing
  - Governance docs update:
    - Added `architecture-v3-status.md` as a durable implementation snapshot
    - Captured implemented boundaries, remaining gaps, and queue-based next steps
    - Recorded latest milestone validation outcomes for compact-safe recovery
  - Phase 3 batch 7 completed:
    - Extracted runtime `SessionState` into dedicated `session_state.py`
    - Removed in-class session-state dataclass from `AgentEngine`
    - Preserved engine/session behavior with full engine + session-compaction coverage
  - Phase 2 batch 5 completed:
    - Introduced first-pass `ContextUnit` protocol with `SkillContextUnit`/`ThreadContextUnit`
    - Refactored manifest builders to project from explicit unit objects
    - Added unit-level context tests while preserving existing registry/render behavior
  - Phase 2 batch 6 completed:
    - Extended `ContextUnit` protocol with `describe/load/priority/related` semantics
    - Upgraded skill/thread units with explicit load and ranking behavior
    - Switched `ContextRegistry` snapshots to unit-driven projections and added regression coverage
  - Queue B batch 1 completed:
    - Added workspace v3 migration planner/executor in `hal/workspace/migration.py`
    - Added dry-run, conflict-safe, and idempotent migration behavior for legacy roots
    - Added workspace migration tests covering plan, apply, dry-run, and conflict scenarios
  - Queue B batch 2 completed:
    - Added `hal workspace-migrate` CLI command (dry-run default, `--apply` for execution)
    - Wired workspace migration command registration into CLI command package
    - Added CLI regression coverage for dry-run non-destructive behavior and apply-mode moves
  - Queue B batch 3 completed:
    - Added JSON migration report export (`export_workspace_migration_report`) with
      action snapshots and rollback hints
    - Extended `hal workspace-migrate` with `--report` output and action-kind summary lines
    - Added workspace/CLI regression coverage for report export and rollback-hint presence
  - Queue B batch 4 completed:
    - Added rollback shell-script export (`export_workspace_migration_rollback_script`)
      from migration rollback hints
    - Extended `hal workspace-migrate` with `--rollback-script` output
    - Added workspace/CLI regression coverage for rollback script generation
  - Phase 2 batch 7 completed:
    - Adopted `ContextUnit.priority()` in registry-wide unit ordering
    - Added registry-level related-unit lookup based on `ContextUnit.related()`
    - Added regression tests for priority ordering and related-thread key projection
  - Phase 2 batch 8 completed:
    - Wired baseline active-thread selection through `ContextUnit` policy signals
      (`priority` ordering + `related` one-hop expansion from recalled/mentioned threads)
    - Routed active-thread snapshots through unified context-unit ordering instead of
      direct thread-only listing
    - Expanded advisor touch propagation to include related threads for debrief coverage
    - Added regression coverage for related-thread baseline selection and updated registry snapshots
  - Phase 2 batch 9 completed:
    - Extended context-advisor input payload with unified `context_unit_registry`
      (skill/thread manifests plus priority/related policy signals)
    - Wired advisor runtime hook to pass normalized context-unit snapshots
    - Added advisor regression coverage for payload shape and rendering
  - Queue C batch 1 completed:
    - Added runtime facade modules (`hal.core.runtime.session` / `hal.core.runtime.debrief`)
      as stable import surfaces for future package reorganization
    - Switched `AgentEngine` runtime orchestration imports to use runtime facades
      instead of direct engine-runtime module coupling
    - Added regression validation via engine/debrief/advisor test suites
  - Queue C batch 2 completed:
    - Added runtime facade modules for execution/checkpoint/snapshot/summary flow
      (`hal.core.runtime.execution`, `checkpoint`, `snapshot`, `summary_flow`)
    - Switched `AgentEngine` orchestration imports to runtime facades and preserved
      compatibility signatures across loop/snapshot/summary call paths
    - Added regression validation via:
      `PYTHONPATH=. pytest tests/core/test_engine.py tests/core/engine/test_debrief.py tests/core/engine/test_context_advisor.py -q`
      (82 passed)
  - Queue C batch 3 completed:
    - Moved debrief runtime implementation into `hal.core.runtime.debrief_flow`
      and kept `hal.core.engine.debrief_runtime` as compatibility wrappers
    - Updated runtime facade wiring so `hal.core.runtime.debrief` resolves
      through runtime-owned implementation instead of engine-owned implementation
    - Updated debrief-related tests to import/patch runtime surfaces and
      validated with focused engine/debrief/advisor regression suite (82 passed)
  - Queue C batch 4 completed:
    - Moved session runtime implementation into `hal.core.runtime.session_flow`
      and kept `hal.core.engine.session_runtime` as compatibility wrappers
    - Updated runtime facade wiring so `hal.core.runtime.session` resolves
      through runtime-owned implementation instead of engine-owned implementation
    - Validated with focused engine/debrief/advisor regression suite (82 passed)
  - Queue C batch 5 completed:
    - Moved loop execution runtime implementation into
      `hal.core.runtime.execution_flow` and kept
      `hal.core.engine.loop_runtime` as compatibility wrappers
    - Updated runtime facade wiring so `hal.core.runtime.execution` resolves
      through runtime-owned implementation instead of engine-owned implementation
    - Validated with focused engine/debrief/advisor regression suite (82 passed)
  - Queue C batch 6 completed:
    - Moved summary runtime implementation into
      `hal.core.runtime.summary_flow_impl` and kept
      `hal.core.engine.summary_runtime` as compatibility wrappers
    - Updated runtime facade wiring so `hal.core.runtime.summary_flow` resolves
      through runtime-owned implementation instead of engine-owned implementation
    - Validated with focused engine/debrief/advisor regression suite (82 passed)
  - Queue C batch 7 completed:
    - Moved session snapshot assembly implementation into
      `hal.core.runtime.snapshot_flow` and kept
      `hal.core.engine.snapshot_runtime` as compatibility wrappers
    - Updated runtime facade wiring so `hal.core.runtime.snapshot` resolves
      through runtime-owned implementation instead of engine-owned implementation
    - Validated with focused engine/debrief/advisor regression suite (82 passed)
  - Queue C batch 8 completed:
    - Moved session checkpoint generation implementation into
      `hal.core.runtime.checkpoint_flow` and kept
      `hal.core.engine.checkpoint_runtime` as compatibility wrappers
    - Updated runtime facade wiring so `hal.core.runtime.checkpoint` resolves
      through runtime-owned implementation instead of engine-owned implementation
    - Validated with focused engine/debrief/advisor regression suite (82 passed)
  - Queue C batch 9 completed:
    - Added forward-compatible top-level package facades:
      `hal.runtime` and `hal.context`
    - Re-exported runtime/context core symbols through these package surfaces
      to support no-flag-day import migration toward Architecture v3 topology
    - Added regression tests for top-level package surface exports:
      `tests/runtime/test_package.py` and `tests/context/test_context_package.py`
    - Hardened facade import path against runtime-engine cycles by introducing
      lazy loop-flow binding in `hal.core.runtime.execution` and removing
      duplicated runtime helper copies that regressed clone score
  - Queue C batch 10 completed:
    - Switched `AgentEngine` runtime orchestration imports to consume
      `hal.runtime` top-level package surface directly
    - Verified top-level runtime facade can safely carry main execution paths
      without re-introducing import cycles
    - Validated with focused engine/debrief/advisor + package-surface tests
      (`84 passed`)
  - Queue C batch 11 completed:
    - Switched `AgentEngine` context-layer imports to consume
      `hal.context` top-level package surface for builder/compiler/metrics/message helpers
    - Expanded `hal.context` package exports to include operational context helpers
      needed by engine main-path wiring
    - Extended package-surface regression coverage and validated with focused
      engine/debrief/advisor + package tests (`84 passed`)
  - Queue A batch 1 completed:
    - Added configurable relation-hop depth for thread expansion
      (`agents.defaults.history.related_thread_hops`, default `1`, range `1..3`)
    - Wired relation-hop policy through `ContextBuilder`/`ContextRegistry` and
      baseline/debrief related-thread expansion paths while preserving default behavior
    - Added regression coverage for multi-hop registry expansion and updated
      compiler/config defaults coverage (`107 passed` focused suite)
  - Queue C batch 12 completed:
    - Removed unused engine-side runtime compatibility wrapper modules
      (`*_runtime.py`) after main-path imports switched to top-level
      `hal.runtime` / `hal.context`
    - Consolidated related-thread hop traversal via shared helper
      `hal.core.context.related.expand_related_slugs` to reduce duplication
      across context planning and registry expansion
    - Revalidated full suite and quality gates:
      `PYTHONPATH=. pytest tests/ -q` (`535 passed`),
      `ruff check hal tests`,
      `timeout 120 uvx pyscn@latest analyze --json --no-open hal/`
      (Health Score `75`, report: `.pyscn/reports/analyze_20260306_230314.json`)
  - Milestone validation rerun after Queue C package-surface stabilization:
    - `PYTHONPATH=. pytest tests/ -q` passed (`534 passed`)
    - `ruff check hal tests` passed
    - `timeout 120 uvx pyscn@latest analyze --json --no-open hal/` passed
      (Health Score `76`, report: `.pyscn/reports/analyze_20260306_224332.json`)
  - Milestone validation rerun after Queue C runtime-flow migration:
    - `PYTHONPATH=. pytest tests/ -q` passed (`532 passed`)
    - `ruff check hal tests` passed
    - `timeout 120 uvx pyscn@latest analyze --json --no-open hal/` passed
      (Health Score `76`, report: `.pyscn/reports/analyze_20260306_223540.json`)
  - Milestone validation run completed:
    - `pytest tests/ -q` passed (`530 passed`)
    - `ruff check hal tests` passed
    - `uvx pyscn@latest analyze --json --no-open hal/` completed (Health Score `75`, report: `.pyscn/reports/analyze_20260306_221702.json`)
    - Full-repo `pyscn` scan (`--no-open .`) exceeded 120s timeout in this environment
  - Queue A batch 2 completed:
    - Added baseline loading cap policy for active thread states
      (`agents.defaults.history.baseline_max_active_threads`, default `3`)
    - Baseline active-thread selection now applies priority-ranked ordering and
      explicit max-entry limits before dynamic-context rendering
    - Added regression coverage for capped baseline thread selection and updated
      config default coverage
  - Validation rerun after Queue A batch 2:
    - `PYTHONPATH=. pytest tests/ -q` passed (`536 passed`)
    - `ruff check hal tests` passed
    - `timeout 120 uvx pyscn@latest analyze --json --no-open hal/` passed
      (Health Score `77`, report: `.pyscn/reports/analyze_20260306_231033.json`)
  - Queue B batch 5 completed:
    - Added transactional rollback behavior for workspace apply failures
      (`migrate_workspace_v3(..., rollback_on_error=True)`)
    - Added rollback outcome reporting (`rolled_back`) to migration report payload
    - Updated CLI apply behavior to return non-zero exit code when migration apply fails
      and print explicit rollback status
    - Added regression coverage for rollback-on-failure behavior in workspace + CLI tests
  - Validation rerun after Queue B batch 5:
    - `PYTHONPATH=. pytest tests/ -q` passed (`538 passed`)
    - `ruff check hal tests` passed
    - `timeout 120 uvx pyscn@latest analyze --json --no-open hal/` passed
      (Health Score `77`, report: `.pyscn/reports/analyze_20260306_231636.json`)
  - Queue C batch 13 completed:
    - Introduced top-level `hal.domain` package with `ContextUnit` semantic models
      (`ContextUnitManifest`, `SkillContextUnit`, `ThreadContextUnit`)
    - Rewired `hal.core.context.units` to consume domain-owned semantic models while
      preserving compatibility exports
    - Added domain package regression coverage (`tests/domain/test_domain_package.py`)
  - Validation rerun after Queue C batch 13:
    - `PYTHONPATH=. pytest tests/ -q` passed (`539 passed`)
    - `ruff check hal tests` passed
    - `timeout 120 uvx pyscn@latest analyze --json --no-open hal/` passed
      (Health Score `77`, report: `.pyscn/reports/analyze_20260306_232041.json`)
  - Queue A batch 3 completed:
    - Added token-aware active-thread state budgeting during baseline dynamic-context build
      (`baseline_active_threads_max_total_tokens`, `baseline_active_thread_max_tokens`)
    - Wired history config budget fields through engine -> context builder -> dynamic context rendering
    - Added regression coverage for active-thread state budget enforcement
  - Validation rerun after Queue A batch 3:
    - `PYTHONPATH=. pytest tests/ -q` passed (`540 passed`)
    - `ruff check hal tests` passed
    - `timeout 120 uvx pyscn@latest analyze --json --no-open hal/` passed
      (Health Score `75`, report: `.pyscn/reports/analyze_20260306_232425.json`)
