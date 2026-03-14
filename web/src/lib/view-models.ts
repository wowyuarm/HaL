/**
 * Working-log view model layer.
 *
 * Classifies raw SessionEvent streams into a two-tier display model:
 *  - Activity items: user-visible actions (messages, tool results, failures)
 *  - Evidence items: diagnostic events (context, loop, LLM requests)
 *
 * The builder produces an interleaved sequence of TurnViewModel groups and
 * standalone session-level activity entries, ordered by event sequence number.
 */

import type { SessionEvent } from "@/lib/types";

// ---------------------------------------------------------------------------
// Event classification
// ---------------------------------------------------------------------------

/** Event types that surface as user-visible activity in the working log. */
export const ACTIVITY_EVENTS = new Set([
  "user.message",
  "assistant.message_completed",
  "tool.call_completed",
  "turn.failed",
  "message.injected",
  "subagent.completed",
  "session.scope_updated",
  "brief.completed",
]);

/** Event types retained as diagnostic evidence within a turn. */
export const EVIDENCE_EVENTS = new Set([
  "context.compiled",
  "loop.started",
  "loop.iteration_started",
  "llm.request_started",
  "llm.response_completed",
  "tool.call_started",
  "assistant.message_started",
  "hook.injected",
  "subagent.spawned",
  "brief.started",
]);

export type EventTier = "activity" | "evidence" | "hidden";

/** Classify a raw event type string into its display tier. */
export function classifyEvent(eventType: string): EventTier {
  if (ACTIVITY_EVENTS.has(eventType)) return "activity";
  if (EVIDENCE_EVENTS.has(eventType)) return "evidence";
  return "hidden";
}

// ---------------------------------------------------------------------------
// View model types
// ---------------------------------------------------------------------------

/** A user-visible activity entry within a turn. */
export interface ActivityItem {
  kind:
    | "user_message"
    | "message_injected"
    | "tool_result"
    | "subagent_completed"
    | "assistant_output"
    | "turn_failed";
  ts: string;
  seq: number;
  eventType: string;
  content?: string;
  brief?: string;
  error?: string;
  toolName?: string;
  status?: string;
  meta?: Record<string, unknown>;
}

/** A session-level activity entry (not scoped to a turn). */
export interface SessionActivityItem {
  kind: "scope_updated" | "brief_completed";
  ts: string;
  seq: number;
  eventType: string;
  title: string;
  brief?: string;
  meta?: Record<string, unknown>;
}

/** Aggregated view of one turn's lifecycle and content. */
export interface TurnViewModel {
  turnId: string;
  state: "running" | "completed" | "failed";
  origin: "interactive" | "background_resume";
  startedAt: string;
  completedAt?: string;

  /** Seq-ordered activity items within this turn. */
  activityItems: ActivityItem[];

  /** First user.message in the turn (convenience projection). */
  userMessage?: { content: string; ts: string; seq: number };
  /** Final assistant output (convenience projection). */
  assistantOutput?: {
    content: string;
    ts: string;
    seq: number;
    toolsUsed: string[];
    iterations: number;
  };
  /** Per-tool completion summaries in seq order. */
  toolSummaries: { name: string; status: string; brief: string; ts: string; seq: number }[];
  /** Present only when the turn failed. */
  failure?: { error: string; ts: string; seq: number };

  /** Whether any evidence-tier events exist for this turn. */
  hasEvidence: boolean;
  /** Raw evidence events preserved for drill-down display. */
  evidenceEvents: SessionEvent[];
  /** Evidence counts grouped by category. */
  evidenceCounts: {
    context: number;
    loop: number;
    tool: number;
    injection: number;
    worker: number;
  };
}

/** Discriminated union for the top-level working-log stream. */
export type WorkingLogItem =
  | { kind: "turn"; turn: TurnViewModel }
  | { kind: "session_activity"; item: SessionActivityItem };

// ---------------------------------------------------------------------------
// Builder
// ---------------------------------------------------------------------------

/**
 * Build a working-log view model from a flat array of session events.
 *
 * Events are grouped by turn_id into TurnViewModels. Session-level activity
 * events (those without a turn_id) are emitted as standalone entries. The
 * final array is interleaved by sequence number.
 */
export function buildWorkingLog(events: SessionEvent[]): WorkingLogItem[] {
  const ordered = [...events].sort(bySeq);

  // Partition into turn groups and session-level events
  const turnGroups = new Map<string, SessionEvent[]>();
  const sessionEvents: SessionEvent[] = [];

  for (const event of ordered) {
    if (event.turn_id) {
      let group = turnGroups.get(event.turn_id);
      if (!group) {
        group = [];
        turnGroups.set(event.turn_id, group);
      }
      group.push(event);
    } else {
      sessionEvents.push(event);
    }
  }

  // Build tagged items with a seq key for final interleaving
  const tagged: Array<{ seq: number; item: WorkingLogItem }> = [];

  for (const [turnId, group] of turnGroups) {
    const turn = buildTurnViewModel(turnId, group);
    // Use the first event's seq as the turn's sort key
    const leadSeq = group[0]?.seq ?? 0;
    tagged.push({ seq: leadSeq, item: { kind: "turn", turn } });
  }

  for (const event of sessionEvents) {
    if (classifyEvent(event.type) !== "activity") continue;
    const sessionItem = toSessionActivityItem(event);
    if (sessionItem) {
      tagged.push({ seq: event.seq, item: { kind: "session_activity", item: sessionItem } });
    }
  }

  return tagged.sort((a, b) => a.seq - b.seq).map((entry) => entry.item);
}

// ---------------------------------------------------------------------------
// Turn view model assembly
// ---------------------------------------------------------------------------

function buildTurnViewModel(turnId: string, events: SessionEvent[]): TurnViewModel {
  const sorted = [...events].sort(bySeq);

  const startedEvent = sorted.find((e) => e.type === "turn.started");
  const completedEvent = sorted.find((e) => e.type === "turn.completed");
  const failedEvent = sorted.find((e) => e.type === "turn.failed");

  const activityItems: ActivityItem[] = [];
  const evidenceEvents: SessionEvent[] = [];
  const evidenceCounts = { context: 0, loop: 0, tool: 0, injection: 0, worker: 0 };
  const toolSummaries: TurnViewModel["toolSummaries"] = [];

  let userMessage: TurnViewModel["userMessage"];
  let assistantOutput: TurnViewModel["assistantOutput"];
  let failure: TurnViewModel["failure"];

  for (const event of sorted) {
    const tier = classifyEvent(event.type);

    if (tier === "activity") {
      const item = toActivityItem(event);
      if (!item) continue;
      activityItems.push(item);

      // Convenience projections (first user message, last assistant output)
      if (!userMessage && item.kind === "user_message" && item.content) {
        userMessage = { content: item.content, ts: item.ts, seq: item.seq };
      }
      if (item.kind === "assistant_output" && item.content) {
        const toolsUsed = getStringArray(event.payload, "tools_used");
        const iterations = getFiniteNumber(event.payload, "iterations") ?? 0;
        assistantOutput = {
          content: item.content,
          ts: item.ts,
          seq: item.seq,
          toolsUsed,
          iterations,
        };
      }
      if (item.kind === "turn_failed" && item.error) {
        failure = { error: item.error, ts: item.ts, seq: item.seq };
      }
      if (item.kind === "tool_result" && item.toolName) {
        toolSummaries.push({
          name: item.toolName,
          status: item.status ?? "completed",
          brief: item.brief ?? "completed",
          ts: item.ts,
          seq: item.seq,
        });
      }
      continue;
    }

    if (tier === "evidence") {
      evidenceEvents.push(event);
      incrementEvidenceCount(evidenceCounts, event.type);
    }
  }

  return {
    turnId,
    state: failedEvent ? "failed" : completedEvent ? "completed" : "running",
    origin: deriveTurnOrigin(startedEvent),
    startedAt: startedEvent?.ts ?? sorted[0]?.ts ?? "",
    completedAt: failedEvent?.ts ?? completedEvent?.ts,
    activityItems,
    userMessage,
    assistantOutput,
    toolSummaries,
    failure,
    hasEvidence: evidenceEvents.length > 0,
    evidenceEvents,
    evidenceCounts,
  };
}

// ---------------------------------------------------------------------------
// Activity item extraction
// ---------------------------------------------------------------------------

function toActivityItem(event: SessionEvent): ActivityItem | null {
  switch (event.type) {
    case "user.message":
      return {
        kind: "user_message",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        content: getString(event.payload, "content"),
      };

    case "message.injected":
      return {
        kind: "message_injected",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        content: getString(event.payload, "content"),
      };

    case "tool.call_completed": {
      const toolName = getString(event.payload, "tool") ?? getString(event.refs, "tool_name");
      const preview = getString(event.payload, "result_preview");
      const resultSize = getFiniteNumber(event.payload, "result_size");
      const brief = preview ?? (resultSize != null ? `${resultSize} chars` : "completed");
      return {
        kind: "tool_result",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        content: preview,
        brief,
        toolName,
        status: "completed",
        meta: compactMeta(event.payload, ["result_size", "args"]),
      };
    }

    case "subagent.completed": {
      const label = getString(event.payload, "label");
      const status = getString(event.payload, "status");
      const recordId = getString(event.payload, "record_id");
      const brief = [status, recordId ? `record:${recordId}` : null].filter(Boolean).join(" · ");
      return {
        kind: "subagent_completed",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        brief: brief || undefined,
        status,
        meta: compactMeta(event.payload, ["label", "record_id", "artifact_path"]),
      };
    }

    case "assistant.message_completed": {
      const content = getString(event.payload, "content");
      const iterations = getFiniteNumber(event.payload, "iterations");
      const toolsUsed = getStringArray(event.payload, "tools_used");
      const parts: string[] = [];
      if (iterations != null) parts.push(`${iterations} iteration${iterations === 1 ? "" : "s"}`);
      if (toolsUsed.length > 0) parts.push(`${toolsUsed.length} tool${toolsUsed.length === 1 ? "" : "s"}`);
      return {
        kind: "assistant_output",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        content,
        brief: parts.length > 0 ? parts.join(" \u00b7 ") : undefined,
      };
    }

    case "turn.failed":
      return {
        kind: "turn_failed",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        error: getString(event.payload, "error"),
      };

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Session-level activity items
// ---------------------------------------------------------------------------

function toSessionActivityItem(event: SessionEvent): SessionActivityItem | null {
  switch (event.type) {
    case "session.scope_updated": {
      const added = getStringArray(event.payload, "added_threads");
      const removed = getStringArray(event.payload, "removed_threads");
      const parts: string[] = [];
      if (added.length > 0) parts.push(`+${added.join(", ")}`);
      if (removed.length > 0) parts.push(`\u2212${removed.join(", ")}`);
      return {
        kind: "scope_updated",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        title: "Scope updated",
        brief: parts.length > 0 ? parts.join(" / ") : undefined,
        meta: compactMeta(event.payload, ["added_threads", "removed_threads"]),
      };
    }

    case "brief.completed": {
      const threadsLinked = getStringArray(event.payload, "threads_linked");
      const filesModified = getStringArray(event.payload, "files_modified");
      const parts: string[] = [];
      if (threadsLinked.length > 0) {
        parts.push(`${threadsLinked.length} thread${threadsLinked.length === 1 ? "" : "s"} linked`);
      }
      if (filesModified.length > 0) {
        parts.push(`${filesModified.length} file${filesModified.length === 1 ? "" : "s"} modified`);
      }
      return {
        kind: "brief_completed",
        ts: event.ts,
        seq: event.seq,
        eventType: event.type,
        title: "Brief completed",
        brief: parts.length > 0 ? parts.join(" \u00b7 ") : undefined,
        meta: compactMeta(event.payload, ["threads_linked", "files_modified", "indexed_chunks"]),
      };
    }

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Evidence counting
// ---------------------------------------------------------------------------

function incrementEvidenceCount(
  counts: TurnViewModel["evidenceCounts"],
  eventType: string,
): void {
  switch (eventType) {
    case "context.compiled":
      counts.context++;
      break;
    case "loop.started":
    case "loop.iteration_started":
    case "llm.request_started":
    case "llm.response_completed":
    case "assistant.message_started":
      counts.loop++;
      break;
    case "tool.call_started":
      counts.tool++;
      break;
    case "hook.injected":
      counts.injection++;
      break;
    case "subagent.spawned":
    case "brief.started":
      counts.worker++;
      break;
  }
}

// ---------------------------------------------------------------------------
// Turn origin
// ---------------------------------------------------------------------------

function deriveTurnOrigin(
  startedEvent: SessionEvent | undefined,
): "interactive" | "background_resume" {
  if (!startedEvent) return "interactive";
  return getString(startedEvent.payload, "origin") === "background_resume"
    ? "background_resume"
    : "interactive";
}

// ---------------------------------------------------------------------------
// Safe payload access helpers
// ---------------------------------------------------------------------------

function getString(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function getFiniteNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getStringArray(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

/** Pick only defined keys from a record, returning undefined when empty. */
function compactMeta(
  record: Record<string, unknown>,
  keys: readonly string[],
): Record<string, unknown> | undefined {
  const result: Record<string, unknown> = {};
  let count = 0;
  for (const key of keys) {
    if (record[key] !== undefined) {
      result[key] = record[key];
      count++;
    }
  }
  return count > 0 ? result : undefined;
}

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

function bySeq(a: SessionEvent, b: SessionEvent): number {
  return a.seq - b.seq;
}
