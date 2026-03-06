# Context System v2: Stateful Collaboration Substrate

> Design document for HaL's context architecture evolution.
> Status: **Design converged** — ready for phased implementation planning.

## Core Thesis

HaL's context source shifts from **conversation history** to **current work state**.

The system moves from "remembering what was said" to "knowing where things stand."

---

## 1. Semantic Objects

Five first-class concepts, each with a distinct role:

| Object | Role | Lifecycle |
|--------|------|-----------|
| **Session** | Write unit. A continuous interaction window (first message → idle timeout). | Ephemeral — exists in memory, events persisted to log. |
| **Thread** | Load unit. A long-running human workstream. | Persistent — manual create, auto state transitions, manual archive. |
| **Episode** | Retrieval unit. Immutable compaction of a session's contribution to a thread. | Persistent — append-only, never edited after creation. |
| **Memory** | Sediment layer. Long-term stable facts, preferences, knowledge. | Persistent — rarely changes, no project progress. |
| **Event Log** | Evidence layer. Append-only raw event stream. | Permanent — can rebuild all upper layers. |

**One-liner**: Write by session/event. Read by thread. Retrieve by episode. Settle into memory.

---

## 2. Context Architecture

### 2.1 Layered Context Model

```
+-- Stable Prefix (cached, immutable within session) --------+
|                                                             |
|  Layer 0: Identity (hardcoded + SOUL.md)                    |
|  Layer 1: Instructions (INSTRUCTIONS.md)                    |
|  Layer 2: Capabilities                                      |
|           - Skill registry (name + description)             |
|           - Thread registry (name + status + one-liner)     |
|  Layer 3: Memory (MEMORY.md — stable facts only)            |
|                                                             |
+-------------------------------------------------------------+

+-- Messages (grows within session, compactable) -------------+
|                                                             |
|  [First user message]                                       |
|    <context>                                                |
|      <time>...</time>                                       |
|      <channel>...</channel>                                 |
|      <active_threads>                                       |
|        (STATE.md content for active threads)                |
|      </active_threads>                                      |
|      <relevant_memories>                                    |
|        (episode recall fragments)                           |
|      </relevant_memories>                                   |
|    </context>                                               |
|    (user's actual message)                                  |
|                                                             |
|  [Frozen checkpoint 1]  <-- compacted old turns, cached     |
|  [Frozen checkpoint 2]  <-- compacted old turns, cached     |
|  [Recent raw turns]     <-- full fidelity, evolving         |
|  [Current message]      <-- new                             |
|                                                             |
+-------------------------------------------------------------+
```

### 2.2 Key Design Decisions

**Thread registry in stable prefix:**
- All threads: name + status + one-line description (lightweight)
- Cap at 20 entries (configurable via `config.yaml`)
- Over cap: prioritize active > recently active > user-pinned
- STATE.md content is NEVER in system prompt — always in dynamic context or message inject

**Session history: session-scoped, not time-scoped:**
- `history_days` replaced by `session_id` scoping
- Within session: full fidelity (no truncation, tool calls visible)
- Between sessions: continuity from STATE.md + episodes, not raw history
- Engine maintains session messages in memory, not re-read from JSONL each turn

**Immutability within session:**
- Stable prefix (system prompt) does not change mid-session
- Baseline dynamic context (first message's XML block) does not change
- Working set grows by append: new STATE.md reads, skill loads, tool results
- Edits to MEMORY.md / INSTRUCTIONS.md take effect next session

**Tool result handling in working set:**
- Recent raw tail: full tool results preserved
- When turns freeze into checkpoint: tool results compacted to essential content
  (call args, key findings, errors, artifact paths — not raw output)
- Raw results always in events.jsonl for audit/rebuild

### 2.3 In-Session Compaction

When approaching token budget (~150k tokens), older turns are compacted:

```
Before compaction:
  [turn 1] user -> assistant (3 tool calls, large results)
  [turn 2] user -> assistant (2 tool calls)
  [turn 3] user -> assistant (1 tool call)
  [turn 4] user -> (current)

After compaction:
  [frozen checkpoint: compacted summary of turns 1-2]
  [turn 3] full fidelity
  [turn 4] current
```

Properties:
- Triggered by token budget (primary), not tool call count
- Worker model produces checkpoint: decisions, key results, open items
- Checkpoint is a new message appended, old turns removed from working set
- Old turns remain in events.jsonl (append-only, never modified)
- Frozen checkpoints are cache-friendly (stable once created)

### 2.4 Post-Session Episode Compaction

Triggered by idle timeout + confirmation. Distinct from in-session compaction:

| | In-Session Compaction | Episode Compaction |
|---|---|---|
| **Goal** | Manage runtime working set | Persistent thread sediment |
| **Trigger** | Token budget approaching limit | Idle timeout + user confirm |
| **Output** | Frozen checkpoint in messages | Episode .md + STATE.md patch |
| **Persistence** | Memory only (lost after session) | Filesystem (permanent) |
| **Scope** | All turns regardless of thread | Per-thread extraction |

---

## 3. Runtime Mechanisms

### 3.1 Context Advisor (Foreground)

Runs during active conversation, non-blocking:

```
First substantive tool call in session
  |
  +-- Tool execution (async)
  |
  +-- Context Advisor (worker model, parallel)
       Input:  user message + HaL reasoning + tool call + skill list + thread list
       Output: hint or silence
  |
  v
before_llm_call: inject hint via MessageInjectEvent
```

Properties:
- Only triggers on substantive tool calls (not text replies, not message sends)
- Silence-biased: no output when low confidence
- Same skill/thread only suggested once per session
- Hint format: "If you already have sufficient context, ignore this."

### 3.2 Session Debriefer (Background)

Runs during idle gaps:

```
5 min no messages
  |
  v
HaL sends Telegram confirmation:
  "Session touched [thread-a, thread-b].
   Will update states in 2 min. Reply to continue."
  |
  +-- Alice replies     -> cancel debrief, reset idle timer
  +-- Alice confirms    -> start immediately
  +-- 2 min no response -> start automatically
  |
  v
Session Debriefer (worker model):
  Input:  session events + touched thread STATE.md list
  Output: {
    thread_updates: [{ thread, episode_compaction, state_patch, status_change }],
    thread_suggestions: [{ name, reason }],  // not auto-created
    unassociated: "..."  // inbox
  }
  |
  v
Write to filesystem:
  - Episode .md -> threads/{name}/episodes/
  - STATE.md patch (incremental, not overwrite)
  - Index episodes into VectorStore
```

Confirmation message properties:
- Skipped if session touched no threads (casual chat)
- Not recorded in conversation history (meta/system marker)
- Debrief runs in background, does not block new conversation if Alice returns

### 3.3 Debriefer Permission Boundaries

**Automatic (low risk):**
- Write events to log
- Write episodes (append-only, immutable)
- Patch STATE.md rolling sections (Current State, Open Items)
- Transition thread status (active <-> inactive)
- Suggest thread creation/merge/archive

**Requires confirmation (high risk):**
- Create new threads
- Merge or archive threads
- Edit MEMORY.md long-term facts
- Edit INSTRUCTIONS.md behavioral rules
- Modify thread core goal or key decisions

---

## 4. Storage & Indexing

### 4.1 Hard Principle

**Lower layers are more raw; upper layers are rebuildable from below.**

```
              +----------+
  Load freq   | STATE.md |  Hot — loaded per session (active threads)
              +----+-----+
                   | indexes
              +----v---------+
              | episodes/*.md|  Warm — HaL reads on demand
              +----+---------+
                   | indexes (session_id / time range)
              +----v--------------+
              | logs/events.jsonl |  Cold — audit, rebuild
              +-------------------+
```

### 4.2 Directory Structure

```
~/.hal/
  # -- Identity & Knowledge (system prompt, stable) --
  SOUL.md                           # Who I am
  INSTRUCTIONS.md                   # How I work (merged AGENTS.md + TOOLS.md)

  # -- Long-term Memory (system prompt Layer 3) --
  memory/
    MEMORY.md                       # Stable facts, preferences (no project state)
    vectors/
      hal_memory.db                 # Vector index (Milvus Lite, indexes episodes)

  # -- Work State (on-demand loading) --
  threads/
    {thread-slug}/
      STATE.md                      # Hot: current compacted state
      episodes/                     # Warm: immutable compaction records
        YYYY-MM-DD-{slug}.md

  inbox/                            # Unrouted fragments

  # -- Raw Records (cold, append-only) --
  logs/
    events.jsonl                    # Unified event stream
    sessions/
      {session_id}/
        subagent/
          {record_id}.jsonl         # Subagent execution log
          {record_id}_report.md     # Subagent report (if any)

  # -- Capabilities (on-demand) --
  skills/
    {skill-name}/
      SKILL.md

  # -- Other --
  artifacts/                        # Generated outputs
  media/                            # Media files
  scripts/                          # Reusable scripts
  projects/                         # Project working files
  tmp/                              # Temporary files
```

### 4.3 Event Log Schema

Single append-only JSONL file. Not split by day.

```jsonl
{"ts":"...","session":"s_abc","type":"session_start","channel":"telegram","chat_id":"123"}
{"ts":"...","session":"s_abc","type":"user_message","content":"...","media":[]}
{"ts":"...","session":"s_abc","type":"assistant","content":"...","reasoning_summary":"..."}
{"ts":"...","session":"s_abc","type":"tool_call","tool":"fs","args":{...},"result_size":420}
{"ts":"...","session":"s_abc","type":"context_hint","source":"advisor","content":"..."}
{"ts":"...","session":"s_abc","type":"subagent_spawn","record_id":"r_xyz","label":"..."}
{"ts":"...","session":"s_abc","type":"subagent_complete","record_id":"r_xyz","status":"success","artifact":"..."}
{"ts":"...","session":"s_abc","type":"session_end","reason":"idle_timeout"}
```

Main log records subagent spawn/complete events only. Full subagent execution
lives in `logs/sessions/{session_id}/subagent/{record_id}.jsonl`.

### 4.4 Episode Format

```markdown
# YYYY-MM-DD: {title}

Threads: [{primary-thread}, {related-thread}]
Primary: {primary-thread}
Session: {session_id}

## What Happened
- ...

## Decisions
- ...

## Artifacts
- path/to/artifact

## Open
- [ ] ...

## Source Events
- {session_id}: HH:MM:SS - HH:MM:SS
```

Each episode has one canonical home (`threads/{primary}/episodes/`).
Other threads reference via relative path in their STATE.md.

### 4.5 STATE.md Format

```markdown
# {Thread Title}
Status: active
Created: YYYY-MM-DD

## Goal
One-line purpose of this thread.

## Current State
(Rolling section — updated by debriefer, re-compacted when too long)

## Key Decisions
(Append-only — never compacted away)

## Open Items
- [ ] ...

## Recent Episodes
- [YYYY-MM-DD: title](episodes/YYYY-MM-DD-slug.md)
- [YYYY-MM-DD: title](../other-thread/episodes/YYYY-MM-DD-slug.md)
```

`Key Decisions` is append-only and never removed by re-compaction.
`Current State` is the rolling section that gets re-compacted when STATE.md grows too long.

### 4.6 Indexing Pipeline

Replaces current DailyExporter pipeline:

```
Session Debriefer writes episodes
  |
  v
MarkdownChunker (reused as-is)
  chunks episodes into segments
  |
  v
Embedding (reused as-is)
  |
  v
VectorStore (reused as-is, Milvus Lite)
  - source: episode path (not daily markdown path)
  - metadata: thread name, source_type
  |
  v
MemorySearch.search() returns episode chunks
  injected as <relevant_memories> in dynamic context
```

DailyExporter is deprecated. Chunker and VectorStore require minimal changes
(source path format, metadata fields).

---

## 5. Migration from Current System

### 5.1 What Changes

| Component | Current | New | Migration |
|-----------|---------|-----|-----------|
| **Context files** | SOUL + USER + AGENTS + TOOLS | SOUL + INSTRUCTIONS + MEMORY | Merge files, update ContextBuilder |
| **History loading** | DailyLog JSONL by day window | In-memory session state | Rewrite history management |
| **DailyLog** | Per-day JSONL files | Unified events.jsonl with session_id | Schema change |
| **DailyExporter** | JSONL -> daily markdown | Deprecated (episodes replace) | Remove |
| **Summary** | Per-loop summary after 5+ tool calls | In-session compaction + episode compaction | Replace mechanism |
| **MemorySearch** | Index daily markdown | Index episodes | Change source path |
| **ContextBuilder** | 5-layer with dynamic context | Same structure, new content sources | Moderate refactor |
| **Memory (MEMORY.md)** | Facts + project state | Facts only (project state -> threads) | Content migration |

### 5.2 Phased Implementation

Each phase is independently verifiable. System is usable after any phase.

```
Phase 0: File Reorganization (#41)
  - AGENTS.md + TOOLS.md -> INSTRUCTIONS.md
  - USER.md -> merge into MEMORY.md
  - Update ContextBuilder.BOOTSTRAP_FILES
  - Update identity prompt references

Phase 1: Session Concept + Event Log
  - Introduce session_id generation (first message -> idle timeout)
  - Unified events.jsonl (new schema with session_id, event types)
  - Engine maintains session messages in memory
  - History loading: session-scoped instead of day-scoped
  - Remove history_days config, add session_idle_timeout_s

Phase 2: Thread Directory + STATE Loading
  - Thread directory structure under ~/.hal/threads/
  - Thread registry in system prompt (name + status + description)
  - Active thread STATE.md loaded into first message dynamic context
  - HaL can read STATE.md on demand (like SKILL.md)
  - Manual thread creation/management
  - Config: max_thread_registry_size (default 20)

Phase 3: Session Debriefer
  - Idle timeout detection + Telegram confirmation message
  - Worker model: session events -> episodes + STATE patches
  - Episode writing to thread directories
  - STATE.md incremental patching
  - Thread suggestions (not auto-created)

Phase 4: Context Advisor
  - Hook into on_tool_calls_start (first substantive tool call)
  - Worker model: observe + hint (non-blocking, parallel)
  - MessageInjectEvent for hint delivery
  - Silence preference, frequency limiting

Phase 5: Episode Indexing
  - MarkdownChunker indexes episodes instead of daily markdown
  - VectorStore metadata: thread association
  - MemorySearch.search() returns episode chunks
  - DailyExporter deprecated
  - Old daily markdown files retained as archive

Phase 6: In-Session Compaction
  - Token budget monitoring per session
  - Worker model: compact older turns into frozen checkpoint
  - Checkpoint as new message, old turns removed from working set
  - Raw events unchanged in events.jsonl
```

---

## 6. Control & Evolution

### 6.1 Thread Lifecycle

Early stage: only two system-level states.

| State | Context Loading | Description |
|-------|-----------------|-------------|
| **active** | Auto-load STATE.md in dynamic context | Currently being worked on |
| **inactive** | Load only if explicitly referenced | Paused, done, or archived |

Finer semantic labels (ideation, planning, paused, done, archived) serve
human display, not system dispatch. Can be added later without changing
engine behavior.

### 6.2 Thread Creation Policy

- **Manual**: User explicitly creates via command or instruction
- **Suggested**: Debriefer proposes, HaL relays to user for confirmation
- **Never automatic**: Thread creation is a high-risk decision

### 6.3 Guiding Principle

> High autonomy, low overreach.
>
> The system can organize and update progress,
> but must not silently redefine the user's work world.
