# Message Injects

**Status:** Active

Message injects are prompt inputs that are not typed directly by the human and
are not natural assistant replies, but still enter the model working set and
therefore must be replayable in later turns unless session compaction rewrites
history.

This document defines the contract for those injected messages, how they are
stored, and how they interact with thread scope, replay history, and the
working log.

## Why This Exists

HaL needs more than plain user and assistant messages to collaborate well.
Examples include:

- a primary thread `BRIEF.md` snapshot when a session starts
- additional thread snapshots when scope expands
- per-turn context such as time, scope, and recalled memories
- runtime reminders or injected follow-up messages while a tool loop is active

The key rule is simple:

> If HaL sends something to the model, that exact content becomes part of the
> session evidence and must remain replayable in later turns.

Without that rule, later turns would replay a different prefix than the model
actually saw, which harms prompt-cache stability and makes the session less
inspectable.

## Core Rules

1. Message injects are appended, never retroactively rewritten.
2. If an inject entered the model prompt, it is persisted into replay history.
3. The only intentional rewrite of older history is session compaction.
4. Thread `BRIEF.md` content is captured as a session-local snapshot at the
   moment it enters the session. It is not silently refreshed from live thread
   state on later turns.
5. Working-log events record every durable inject that entered the prompt.

## Inject Kinds

### Session State

- `primary_thread_snapshot`
  - Emitted when a session starts with a primary thread.
  - Body contains the primary thread `BRIEF.md` snapshot that entered the
    session.
- `scope_add_snapshot`
  - Emitted when mounted scope expands.
  - Body contains the added thread `BRIEF.md` snapshot captured at that moment.
- `scope_remove`
  - Emitted when mounted scope shrinks.
  - Body records which threads left the active scope and what the remaining
    scope is.

### Turn Context

- `turn_context`
  - Emitted once per normal user turn.
  - Records the per-turn time, current mounted scope, and recalled memories that
    entered that turn's prompt.

### Runtime

- `system_reminder`
  - Automatic runtime reminder injected during an active loop.
- `user_follow_up`
  - A user message injected while the loop is still running.
- `subagent_runtime`
  - A detached or inline subagent result injected back into the main loop.
- `context_hint`
  - A runtime-generated suggestion that is injected into the prompt.

## Prompt Assembly

The replayable prompt sequence is:

1. stable system prompt
2. replay history
3. current-turn message injects
4. current user input

Session-state injects are appended to replay history at the moment they occur.
Turn-context injects are appended right before the current user input and then
persist into replay history when the turn completes.

This means a later turn replays the same injected content the earlier turn
actually saw.

## Working Log Contract

Every durable inject is recorded as:

- event type: `message.injected`
- actor:
  - `engine` for thread snapshots, turn context, reminders, and context hints
  - `user` for injected follow-up messages
  - `worker` for subagent runtime injections
- payload fields:
  - `kind`
  - `source`
  - `content`
- refs:
  - thread and scope refs when relevant

The working log stays append-only. It is the durable evidence trail for UI,
brief workers, and inspection.

## Replay History

Replay history is the sequence of messages that the engine reuses for later
turns.

Injected messages that entered the model prompt are stored in replay history as
synthetic `user` messages. This keeps later turns faithful to the original
prompt shape and preserves prompt-cache opportunities.

Compaction is the only exception. When compaction runs, older replay history may
be replaced by a checkpoint summary. That is an explicit design tradeoff, not an
accidental rewrite.

## Thread Scope and BRIEF Snapshots

Primary and mounted threads are not re-expanded from live `BRIEF.md` files on
every turn.

Instead:

- session start captures the primary thread snapshot
- scope expansion captures added thread snapshots
- scope removal records that the thread is no longer active

This ensures that another session updating the same thread later does not
silently mutate the prompt history of an already-running session.

## Effect on Other Systems

- Runtime prompt construction uses append-only injects instead of a synthetic
  per-turn baseline inserted near the front of the message list.
- Web UI can render injects uniformly from `message.injected` plus `payload.kind`.
- Brief workers read the same durable inject evidence from `working-log.jsonl`.
- Session compaction remains enabled and continues to be the only intentional
  rewrite boundary for old replay history.
