# Thread System

**Status:** Active

Threads are HaL's primary mechanism for continuity across sessions. This
document defines what threads are, how they relate to sessions, and the
contracts that govern brief generation and state preservation.

## Why This Exists

Every session starts cold. Without continuity infrastructure, each new session
must reconstruct context from scratch — re-reading files, re-establishing
decisions, re-discovering what matters. This cost grows with the complexity and
duration of the collaboration.

Threads exist to externalize persistent concerns so that future sessions can
re-enter work without re-heating old context. They are not project containers
or task trackers — they are collaboration lenses that preserve the minimum
state needed for productive re-entry.

## Core Principles

1. **A thread is an externalized persistent concern.** It may be a project, a
   learning journey, a design question, or a recurring coordination topic.
   What makes it a thread is that returning to it across sessions has
   meaningful cost without continuity support.

2. **Threads are lenses, not partitions.** The same session can contribute to
   multiple threads, each extracting different signal from the same events. A
   session about building a web feature might produce a design decision for one
   thread, a coding methodology insight for another, and a direction judgment
   for a third. Overlapping interests do not require new threads — different
   `core_question` values naturally filter for what matters to each.

3. **BRIEF is re-entry state, not summary.** A BRIEF exists so a future
   session can quickly answer: what matters now, what seems true, what is
   unresolved, and where to pick up. It is a living document, not a log.

4. **Episodes are immutable cognitive contributions.** Each episode captures
   what a session contributed to a thread's understanding. Once written,
   episodes never change. They form the thread's historical record and are
   indexed for semantic search.

5. **Human controls direction; system preserves continuity.** The human creates
   sessions, selects threads, triggers briefing, and decides when to drop.
   The system maintains state, compiles context, and generates evidence.

## Thread Identity

Each thread lives at `work/threads/{slug}/` and is defined by a `THREAD.yaml`
file that the collaborator creates. The system reads this file; it does not
modify it.

### Fields

| Field | Required | Semantics |
|-------|----------|-----------|
| `name` | yes | Human-readable title |
| `status` | yes | `active` or `inactive` — inactive threads are excluded from context but preserved for history |
| `goal` | yes | What this thread aims to achieve. Has an endpoint. |
| `scope` | no | Boundaries — what is in scope, what is out |
| `core_question` | no | The persistent tension the thread keeps working through. Unlike `goal`, this may never fully resolve. |
| `brief_hints` | no | Natural language guidance for the brief worker — what to prioritize or avoid in BRIEF updates |
| `related_threads` | no | Declarative links to other thread slugs |
| `pinned` | no | Keep in context even when inactive |

### goal vs core_question

- **goal** describes a destination: "Build a design system for the web client."
- **core_question** describes an ongoing tension: "How to balance design ideals
  with implementation reality without drifting into perpetual research?"

If the thread is straightforward (clear deliverable, obvious scope), `goal`
alone is sufficient. `core_question` adds value for threads that track evolving
understanding, recurring trade-offs, or open-ended exploration.

### brief_hints

`brief_hints` tells the brief worker what to prioritize when updating this
thread's BRIEF. The effective pattern is **"focus on X, preserve Y, avoid Z"**.

Good hints name the kind of signal worth preserving (methodology shifts,
judgment changes, unresolved tensions) and the kind of noise to filter out
(implementation details, tool configurations, progress checklists).

Leave `brief_hints` empty when `goal` and `core_question` already provide
sufficient guidance. Add it when the thread has a pattern of briefs drifting
toward content that does not serve re-entry.

## Session-Thread Relationships

Each thread in a session's context has a role that describes how it got there:

| Role | How it arises | Signal strength |
|------|---------------|-----------------|
| **primary** | Human selects at session creation | Strongest — the session's declared main focus |
| **mounted** | Human adds via scope command | Strong — explicit cross-cutting context |
| **touched** | Detected from file access, memory recall, or context advisor | Medium — may be incidental |
| **related** | Expanded from `related_threads` metadata | Weakest — context only, not directly accessed |

### Invariants

- Primary is always in mounted (auto-added at creation, cannot be removed).
- Mounted threads are auto-touched when any tool is used during the session.
- Mounted threads are also touched during context compilation (scope discovery).
- These guarantees ensure that primary and mounted threads are reliably present
  in the brief worker's candidate list.

### Related threads

`related_threads` is a declarative, non-directional link. Its effect is
bounded:

- **Brief worker**: touched threads are expanded by one hop through related
  links, adding related threads to the candidate list.
- **Context advisor**: suggested threads are expanded through related links
  before being marked as touched.

Related threads do not affect context compilation, thread mounting, or session
creation. They are a soft signal, not a hard dependency.

## Storage Layers

| Temperature | Medium | Semantics |
|-------------|--------|-----------|
| Identity | `THREAD.yaml` | Thread definition and guidance. Created by the collaborator, read by the system. |
| Hot | `BRIEF.md` | Living re-entry state. Updated by the brief worker after each briefed session. |
| Warm | `episodes/*.md` | Immutable session contribution records. Vector-indexed for semantic search. |
| Cold | `sessions/{session_id}/working-log.jsonl` | Raw session event stream. Input to the brief worker. Append-only audit trail. |

`BRIEF.md` is the only mutable layer. Episodes and events are append-only.
`THREAD.yaml` is human-controlled — the system reads but never writes it.

## Brief Worker Contract

The brief worker is a tool-equipped mini-agent triggered by the `/brief`
command. It reads session evidence and thread metadata, then decides what is
worth preserving.

### Input

- **Session events**: rendered from `working-log.jsonl`, token-capped per event
  and in total.
- **Thread candidates**: ordered list of threads with metadata. Each thread
  carries its `role` (primary, mounted, touched, related), `goal`, `scope`,
  `core_question`, and `brief_hints`.
- **Optional user guidance**: free-text direction from the `/brief` command.

### Decision

The worker evaluates each candidate thread:

1. Did the session materially change this thread's state?
2. Is the change worth preserving for future re-entry?
3. What signal does the thread's `core_question` highlight?
4. What does `brief_hints` say to prioritize or avoid?

If nothing is worth preserving, the worker produces no files.

### Output

For each thread worth updating:

- **Episode**: immutable record written to `threads/{slug}/episodes/`. Captures
  what emerged, decisions made, open questions. Concise.
- **Updated BRIEF.md**: evolves to reflect current state. Removes stale
  content, preserves useful structure. Not a log — a living state document.

For insights that do not belong to any existing thread:

- **Inbox note**: written to `work/inbox/` with a date-prefixed filename.

### Role-based attention

- **primary / mounted**: these threads reflect explicit user intent. The worker
  should carefully evaluate whether the session changed their state.
- **touched**: may be incidental. Use event content to judge whether the
  thread's state actually changed.
- **related**: context only. Update only when the session clearly moved their
  state and the connection is strong.

## BRIEF Semantics

A BRIEF is a living state document. It exists so a future session can quickly
answer:

- What matters now?
- What seems true now?
- What is still unresolved?
- Where should we pick up?

### What belongs in a BRIEF

- Stable decisions, including decisions not to do something
- Changed judgments or perspective shifts
- Unresolved tensions
- Important open questions
- The current focus and next useful re-entry point
- Meaningful links to other threads

### What does not belong

- Chronological recap or tool-by-tool replay
- Generic status wording
- Trivial activity without consequence
- Details already captured in episodes or code

### Structure

There is no mandatory template. The BRIEF should use whatever structure fits
the thread naturally. Good BRIEFs often include sections for current focus,
stable judgments, unresolved tensions, and a re-entry pointer — but only when
those sections serve the thread.

The brief worker should remove stale or superseded content and preserve useful
structure. The goal is not to rewrite the BRIEF each time, but to keep it
current.
