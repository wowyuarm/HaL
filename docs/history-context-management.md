# History Context Management — Design Document

> Status: **Token-based budgeting implemented** for history/memory/recall truncation.

## Problem

When conversation history is sent to the LLM as raw alternating `user`/`assistant` messages, the model treats them as **behavioral examples** (few-shot in-context learning). This causes:

- **Style contamination**: the model copies formatting, tone, and structure from its own earlier outputs
- **Pattern lock-in**: verbose/structured responses early in a session bias all subsequent responses toward the same pattern
- **Tool usage mimicry**: the model may repeat tool-calling patterns from earlier turns even when inappropriate

## Research: OpenClaw's Approach

OpenClaw (189k+ stars, the largest open-source personal AI agent) handles this through three layers:

1. **Session Pruning** — trims old tool results from in-memory context before each LLM call (does not rewrite disk). Protects the last N assistant messages; older `toolResult` entries get soft-trimmed (head+tail with `...`) or hard-cleared (replaced with placeholder).

2. **Auto-Compaction** — when context approaches the model's window limit, older turns are summarized into a single compact `compaction` entry. Only recent messages survive in full. The summary is persisted to the session JSONL.

3. **Memory Flush** — before compaction, a silent agentic turn writes durable state to `memory/YYYY-MM-DD.md`, preventing critical context loss during summarization.

Key insight: OpenClaw's compaction **indirectly** reduces style contamination because the summary is factual (what happened) rather than stylistic (how it was phrased). However, OpenClaw has no explicit mechanism targeting in-context learning contamination.

## HaL's Approach: Two Phases

### Phase 1: Assistant Message Truncation (Implemented)

Simple heuristic applied in `DailyLog.get_recent_conversation()`:

- The most recent `recent_full_turns` assistant messages are kept **verbatim**
- Older assistant messages are **truncated** to `assistant_truncate_tokens` tokens
- User messages are **always kept in full** (they carry intent, not style)
- Tool messages are already filtered by `include_tools=False`
- Optional hard cap keeps only the newest history under `max_history_tokens`

Configuration via `config.yaml`:

```yaml
agents:
  defaults:
    history:
      max_messages: 50
      recent_full_turns: 3
      assistant_truncate_tokens: 50
      max_history_tokens: 0
      memory_budget_tokens: 0
      recall_max_total_tokens: 500
      recall_max_per_item_tokens: 125
      history_days: 1
```

This addresses the core issue: old assistant outputs lose their formatting/style information through truncation, while preserving enough factual content for conversation coherence.

### Phase 2: Structured Context Injection (Future)

A more sophisticated approach that separates old history from recent turns at the message structure level.

#### Architecture

```
┌─────────────────────────────────────────────┐
│  System Prompt (Layer 0-2, cache-stable)    │
│  ├── Identity, Personality, Capabilities    │
│  └── Situation (time, mode, memory)         │
├─────────────────────────────────────────────┤
│  [user] Conversation Context block          │  ← Condensed old history
│  (structured log, NOT alternating roles)    │
├─────────────────────────────────────────────┤
│  Recent turns (native user/assistant/tool)  │  ← Last N turns verbatim
├─────────────────────────────────────────────┤
│  [user] Current message                     │
└─────────────────────────────────────────────┘
```

#### Why `user` role (not `system`) for the context block

Placing condensed history inside the system prompt would break the cache-stable prefix design (Layers 0-2). Since history changes every turn, it would invalidate the prompt cache entirely.

A single `user` message with clear framing ("for reference only, do not imitate style") preserves cache hits for the system prompt while presenting old history as **reference information** rather than **behavioral examples**.

#### Condensed Log Format

Old messages would be reformatted into a structured, factual log:

```markdown
[Conversation context — for reference only, do not imitate style]

- 14:20 | User asked about weather in Beijing
  → Agent queried web_search, reported 22°C sunny
- 14:25 | User asked to draft an email to Zhang Wei
  → Agent wrote draft to workspace/drafts/email.md
- 14:30 | User asked to modify the email tone
  → Agent edited the file, made it more formal
```

This format:
- Strips style/formatting from assistant outputs
- Merges tool calls into factual outcomes
- Keeps user intent visible
- Prevents the model from treating it as few-shot examples

#### Tiered Decay Strategy

```
Time ────────────────────────────────────────→ Now
│                                               │
│  Zone A: Compacted    Zone B: Condensed  Zone C: Verbatim  │
│  (LLM summary)       (log format)       (native roles)    │
│  → user role block    → user role block  → native roles    │
```

**Zone C (Verbatim)** — most recent N turns, full native role alternation including tool calls/results. Token budget: ~8,000.

**Zone B (Condensed)** — older turns within the day, reformatted to structured log. Generated by heuristic template (zero LLM cost). Token budget: ~10,000.

**Zone A (Compacted)** — when Zone B accumulates too much, an LLM call summarizes it into 2-3 sentences. Or simply discard (rely on semantic search for older context). Token budget: ~2,000.

#### Condensing: Who and When

| Method | Pros | Cons |
|--------|------|------|
| **Query-time LLM** | High quality | Extra API call per turn (latency + cost) |
| **Write-time LLM** | Amortized cost | Already have `_generate_summary` for heavy loops |
| **Heuristic template** | Zero cost, zero latency | May lose nuance |

Recommendation: start with **heuristic template** for Zone B (sufficient for style-stripping), use **LLM summary** only for Zone A compaction.

#### Configuration (Proposed)

```yaml
agents:
  defaults:
    history:
      max_messages: 50
      recent_full_turns: 3
      assistant_truncate_tokens: 50
      condensed_context:
        enabled: false
        verbatim_budget_tokens: 8000
        condensed_budget_tokens: 10000
        compacted_budget_tokens: 2000
```

#### Open Questions

1. **Tokenizer fallback behavior** — when model-aware token counting is unavailable, fallback rough counting (`chars/4`) can still introduce budget drift.

2. **Cross-day history** — `DailyLog` only reads today's file. Conversations spanning midnight would lose earlier context. May need to extend to read yesterday's file for ongoing sessions.

3. **Auto-compaction trigger** — should it be token-count-based (like OpenClaw) or turn-count-based? Token-based is more accurate but requires estimation.

4. **Memory flush before compaction** — OpenClaw's pattern of running a silent LLM turn to persist important context before compaction is worth considering, but adds complexity and cost.

## References

- [OpenClaw](https://github.com/openclaw/openclaw) — Agent System, Session Management, Auto-Compaction
- Claude Code — uses automatic context compression as context limits approach
- HaL `ContextBuilder` — `hal/core/context/builder.py` (5-layer architecture)
- HaL `DailyLog` — `hal/core/memory/daily_log.py` (JSONL storage)
