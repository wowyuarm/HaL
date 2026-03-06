# Architecture v3 Status Snapshot

> Last updated: 2026-03-06
> Anchor docs: `architecture-v3.md`, `architecture-v3-execution.md`, `context-system-v2.md`

## Implemented So Far

1. Correctness baseline (v2 behavior guarantees)
   - Session baseline context is frozen once and not re-injected each turn.
   - Background resume writes back into active session history/event flow.
   - Touched-thread semantics include baseline/recall/mentions/tool usage paths.
   - Debrief episodes now advance `STATE.md` hot layer, including status updates.

2. Workspace boundary extraction
   - Repository boundaries exist for: events, memory/system files, artifacts, threads/episodes, sessions, skills, logs, metrics.
   - CLI memory-search wiring now resolves roots via repositories (not direct layout lookups).
   - v3 path preference (`system/`, `work/`, `runtime/`, `capabilities/`, `data/`) is recognized where supported.

3. Runtime orchestration slimming
   - Session lifecycle/touch/rotation implementation moved to `hal.core.runtime.session_flow`
     (engine module kept as compatibility wrapper).
   - Debrief generation/persistence implementation moved to `hal.core.runtime.debrief_flow`
     (engine module kept as compatibility wrapper).
   - Session checkpoint generation moved to `hal.core.runtime.checkpoint_flow`
     (engine module kept as compatibility wrapper).
   - Session snapshot assembly moved to `hal.core.runtime.snapshot_flow`
     (engine module kept as compatibility wrapper).
   - Loop orchestration moved to `hal.core.runtime.execution_flow`
     (engine module kept as compatibility wrapper).
   - Summary trigger/model resolution moved to `hal.core.runtime.summary_flow_impl`
     (engine module kept as compatibility wrapper).
   - Engine imports now resolve through stable runtime facades in `hal.core.runtime`.
   - Legacy engine-side runtime compatibility wrappers were removed after
     top-level package surfaces became the main-path import source.

4. Context-layer tightening
   - `ContextRegistry.from_workspace()` introduced as composition boundary.
   - Active-thread filtering centralized in registry.
   - Thread manifest projection path unified via `build_thread_unit_manifests()`.
   - First-pass `ContextUnit` protocol now includes `describe/load/priority/related`.
   - Capability rendering extracted into `prompt_layers`.
   - Related-thread expansion now supports configurable hop depth
     (`history.related_thread_hops`, default one-hop).
   - Related-thread graph traversal is now centralized in
     `hal.core.context.related.expand_related_slugs`.
   - Baseline active-thread loading now has an explicit policy cap
     (`history.baseline_max_active_threads`, default `3`) with
     priority-ranked selection.
   - Active-thread state injection is now token-budget aware via
     `history.baseline_active_threads_max_total_tokens` and
     `history.baseline_active_thread_max_tokens`.

5. Workspace migration utility (first pass)
   - Added `hal/workspace/migration.py` with v3 migration planning and execution helpers.
   - Supports dry-run, idempotent apply, and conflict-safe move behavior.
   - Covers legacy roots to v3 namespaces (`system/work/runtime/capabilities/data`).
   - Added CLI entrypoint: `hal workspace-migrate` (dry-run by default, `--apply` to execute).
   - Added report export and rollback hints (`--report`, JSON snapshots, reverse-move hints).
   - Added transactional apply rollback: failed migration attempts now auto-restore
     already moved paths (`rollback_on_error=True` default).
   - CLI now exits non-zero when apply fails and surfaces rollback result explicitly.

6. Package reorg readiness surfaces
   - Added top-level forward-compatible package facades: `hal.runtime`, `hal.context`.
   - Added regression coverage for facade import/export stability.
   - Runtime facade import path made cycle-safe via lazy loop-flow binding in
     `hal.core.runtime.execution`.
   - `AgentEngine` runtime orchestration imports now consume `hal.runtime`
     package surface directly, proving main-path viability for staged topology migration.
   - `AgentEngine` context orchestration imports now consume `hal.context`
     package surface directly for builder/compiler/metrics/message helpers.
   - Added initial `hal.domain` package with `ContextUnit` semantic models, and
     rewired `hal.core.context.units` to consume domain-owned unit definitions.

## Validation Snapshot

- `PYTHONPATH=. pytest tests/ -q`: passing (`540 passed` on latest run)
- `ruff check hal tests`: passing
- `timeout 120 uvx pyscn@latest analyze --json --no-open hal/`: passing, score `75/100` (report: `.pyscn/reports/analyze_20260306_232425.json`)
- Full-repo `pyscn` (`--no-open .`) still exceeds 120s timeout in this environment.

## Remaining Gaps To Reach Architecture v3 End-State

1. Package topology migration (early start)
   - Top-level surfaces now include `hal/domain`, `hal/runtime`, `hal/context`, `hal/workspace`.
   - Remaining work is deeper semantic extraction and import-path migration away from `hal.core.*`.

2. Workspace runtime migration tooling (partial)
   - Planner/executor/report export/rollback script exists in workspace layer with CLI surface.
   - Remaining work is one-shot preflight + post-apply verification strategy for
     production-grade confidence (current rollback is best-effort on move failures).

3. ContextUnit interface hardening (partial)
   - `manifest/describe/load/priority/related` semantics are implemented.
   - Runtime policy is now consumed by baseline/advisor/debrief ordering paths.
   - Remaining work is smarter cross-unit budget arbitration (threads vs skills vs recall)
     instead of per-source fixed budgets.

4. Debriefer semantics depth (partial)
   - Episode creation + hot-layer patching are in place.
   - Thread creation/merge/archive suggestion workflow and explicit permission gates need full productization.

## Recommended Next Queues

1. Queue A: `ContextUnit` policy adoption
   - Wire `priority/related` into actual loading policies and advisor/debrief inputs.
   - Keep skill/thread semantics distinct while sharing selection mechanics.

2. Queue B: workspace migration utility
   - Add a safe, idempotent migration command for local `~/.hal` layout transformation.
   - Produce migration report + rollback hints.

3. Queue C: package reorg readiness pass
   - Move one slice at a time behind stable imports (no flag day).
   - Start with low-risk modules already extracted in runtime helpers.

## Guardrails For Future Batches

- Keep each commit single-purpose and test-backed.
- Re-read `architecture-v3.md` + `architecture-v3-execution.md` after each batch.
- Update execution log on every completed batch.
- Prefer boundary extraction + behavior-preserving refactor before semantic expansion.
