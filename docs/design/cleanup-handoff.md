# Cleanup Handoff: Context System v3 Structural Cleanup

> Written during active cleanup. Resume from here after context compaction.

## What Was Done

### Git History
- 96 Codex commits squashed into 1 meaningful commit (`2c48f98`)
- Backup branch: `backup/pre-cleanup-20260306`
- Current branch: `main`

### Code Cleanup (IN PROGRESS)

**Completed:**
1. Deleted facade packages `hal/runtime/` and `hal/context/` (empty re-export shells)
   - Updated `hal/core/engine/__init__.py` to import from `hal.core.*` directly
   - Updated `hal/core/context/units.py` to import from `hal.domain.context_units` directly
   - Deleted facade test files (`tests/runtime/`, `tests/context/`)

2. Merged runtime facade pairs (6 pairs → 6 files):
   - `session.py` (facade) removed, `session_flow.py` renamed to `session.py`
   - Same for: `debrief`, `execution`, `checkpoint`, `snapshot`
   - `summary_flow.py` (facade) removed, `summary_flow_impl.py` renamed to `summary_flow.py`
   - Fixed test patch path: `debrief_flow` → `debrief` in `test_engine.py:440`

3. Removed legacy compat from workspace:
   - `WorkspaceLayout` now returns v3 paths only (no fallback logic)
   - `SystemRepository.load_bootstrap_documents()` simplified: `files=` param only (no `primary_files`/`legacy_files`)
   - `ContextBuilder.BOOTSTRAP_FILES = ["SOUL.md", "INSTRUCTIONS.md"]` (removed `BOOTSTRAP_LEGACY_FILES`)

**IN PROGRESS:**
4. Fixing workspace tests — 47 tests fail because they create files at legacy paths
   (e.g., writing to `workspace/` root instead of `workspace/system/`, `workspace/work/threads/` etc.)
   These tests need to create v3 directory structure:
   - System docs → `workspace/system/SOUL.md`
   - Threads → `workspace/work/threads/{slug}/`
   - Logs → `workspace/runtime/logs/`
   - Sessions → `workspace/runtime/sessions/`
   - Metrics → `workspace/runtime/metrics/`
   - Skills → `workspace/capabilities/skills/`
   - Artifacts → `workspace/data/artifacts/`

**NOT YET STARTED:**
5. Remove `hal/domain/__init__.py` re-exports (units.py already imports from `hal.domain.context_units` directly)
6. Consider merging small context files in `hal/core/context/` (e.g., `messages.py`, `related.py`)
7. Remove `AgentLoop` backward compat alias from engine
8. Clean up workspace migration code (now unnecessary since we target v3 directly)
9. Update `docs/design/` to reflect final structure
10. Update project CLAUDE.md with new architecture

## Test Status
- Before cleanup: 540 passed
- After facade removal: 538 passed (2 facade tests deleted)
- After layout v3-only: 47 failed (workspace tests need v3 paths), 490 passed
- Target: all pass

## Key Files to Understand

### Import chain (after cleanup):
```
hal/core/engine/__init__.py
  → hal.core.runtime (session, debrief, execution, etc.)
  → hal.core.context (builder, compiler, metrics, messages)
  → hal.domain.context_units (ContextUnit protocol)
  → hal.workspace (ThreadRepository, MetricsRepository, etc.)
```

### Runtime package (after merge):
```
hal/core/runtime/
  __init__.py       — public exports
  loop.py           — shared tool-calling loop (LoopHooks, LoopMetadata)
  session.py        — session lifecycle (was session_flow.py)
  debrief.py        — episode generation (was debrief_flow.py)
  execution.py      — loop orchestration (was execution_flow.py)
  checkpoint.py     — in-session compaction (was checkpoint_flow.py)
  snapshot.py       — background resume snapshots (was snapshot_flow.py)
  summary.py        — summary generation
  summary_flow.py   — summary trigger/resolution (was summary_flow_impl.py)
  tool_factory.py   — tool creation
```

### Workspace v3 directory contract:
```
~/.hal/
  system/           — SOUL.md, INSTRUCTIONS.md, MEMORY.md, config.yaml, auth.yaml
  work/threads/     — thread directories with STATE.md + episodes/
  work/inbox/       — unrouted items
  runtime/logs/     — events.jsonl + daily JSONL
  runtime/sessions/ — session snapshots
  runtime/metrics/  — context_metrics.jsonl
  capabilities/skills/ — skill packages
  data/artifacts/   — outputs, subagent reports
  data/vectors/     — Milvus vector index
  data/media/       — media files
  projects/         — project files
```

## Resume Instructions
1. Fix the 47 failing workspace tests (all need v3 path structure in test fixtures)
2. Run `pytest tests/ -q` to verify all pass
3. Run `ruff check hal/ tests/` to verify lint
4. Commit the cleanup
5. Continue with items 5-10 from "NOT YET STARTED" above
