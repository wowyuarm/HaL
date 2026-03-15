/**
 * Session-to-message adapter for assistant-ui.
 *
 * Converts a flat array of HaL SessionEvents into an array of
 * SessionMessage objects that can be fed to assistant-ui's
 * ExternalStoreRuntime via a `convertMessage` callback.
 *
 * This replaces the dual-layer view-models.ts approach with a simpler
 * linear message model:
 *   - user.message        → user message
 *   - assistant output     → assistant message (with tool-call parts)
 *   - session-level events → system messages
 *   - evidence events      → NOT mapped; available via halMeta for inspector
 */

import type { SessionEvent } from "@/lib/types";
import { bySeq, getFiniteNumber, getString, getStringArray } from "@/lib/event-helpers";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** Content part compatible with assistant-ui ThreadMessageLike. */
export type ContentPart = TextPart | ToolCallPart;

export interface TextPart {
  readonly type: "text";
  readonly text: string;
}

export interface ToolCallPart {
  readonly type: "tool-call";
  readonly toolCallId: string;
  readonly toolName: string;
  readonly args?: Readonly<Record<string, JsonValue>>;
  readonly argsText?: string;
  readonly result?: JsonValue;
  readonly isError?: boolean;
}

/** JSON-safe value type compatible with assistant-ui's ReadonlyJSONValue. */
type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

/**
 * Message status aligned with assistant-ui's MessageStatus union.
 * Re-declared here to avoid importing from @assistant-ui/core internals.
 */
export type SessionMessageStatus =
  | { readonly type: "running" }
  | { readonly type: "complete"; readonly reason: "stop" | "unknown" }
  | {
      readonly type: "incomplete";
      readonly reason: "error" | "cancelled" | "other";
      readonly error?: JsonValue;
    };

/** Evidence event counts by category, for the inspector panel. */
export interface EvidenceCounts {
  context: number;
  loop: number;
  tool: number;
  injection: number;
  worker: number;
}

/** HaL-specific metadata attached to each SessionMessage. */
export interface HalMessageMeta {
  turnId?: string;
  turnState?: "running" | "completed" | "failed";
  origin?: "interactive" | "background_resume";
  isCommand?: boolean;
  evidenceCounts?: EvidenceCounts;
  toolSummaries?: Array<{ name: string; status: string }>;
}

/**
 * Intermediate message type bridging HaL events and assistant-ui.
 *
 * Fed to ExternalStoreRuntime as the T parameter, then converted
 * to ThreadMessageLike via a `convertMessage` callback.
 */
export interface SessionMessage {
  readonly id: string;
  readonly role: "user" | "assistant" | "system";
  readonly turnId: string | null;
  readonly createdAt: Date;
  readonly content: readonly ContentPart[];
  /** Status is only valid for assistant messages — assistant-ui throws on others. */
  readonly status?: SessionMessageStatus;
  readonly halMeta: HalMessageMeta;
}

// ---------------------------------------------------------------------------
// Event classification
// ---------------------------------------------------------------------------

/** Event types counted as diagnostic evidence (not shown in message flow). */
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

/** Session-level activity events (standalone, no turn_id). */
const SESSION_ACTIVITY_EVENTS = new Set([
  "session.scope_updated",
  "brief.completed",
  "message.injected",
]);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Convert a flat array of SessionEvents into a linear SessionMessage array.
 *
 * Groups events by turn_id, produces user + assistant messages per turn,
 * and emits session-level events as system messages. Returns the array
 * sorted by chronological order (seq).
 */
export function convertSessionEvents(events: SessionEvent[]): SessionMessage[] {
  if (events.length === 0) return [];

  const ordered = [...events].sort(bySeq);

  // Partition into turn groups and standalone session events.
  const turnGroups = new Map<string, SessionEvent[]>();
  const standaloneEvents: SessionEvent[] = [];

  for (const event of ordered) {
    if (event.turn_id) {
      let group = turnGroups.get(event.turn_id);
      if (!group) {
        group = [];
        turnGroups.set(event.turn_id, group);
      }
      group.push(event);
    } else if (SESSION_ACTIVITY_EVENTS.has(event.type)) {
      standaloneEvents.push(event);
    }
    // Events without turn_id that aren't session activity → ignored
  }

  // Build messages with a seq key for final interleaving.
  const tagged: Array<{ seq: number; messages: SessionMessage[] }> = [];

  for (const [turnId, group] of turnGroups) {
    const leadSeq = group[0]?.seq ?? 0;
    tagged.push({ seq: leadSeq, messages: buildTurnMessages(turnId, group) });
  }

  for (const event of standaloneEvents) {
    const msg = buildStandaloneMessage(event);
    if (msg) {
      tagged.push({ seq: event.seq, messages: [msg] });
    }
  }

  // Flatten and sort by seq.
  return tagged
    .sort((a, b) => a.seq - b.seq)
    .flatMap((entry) => entry.messages);
}

// ---------------------------------------------------------------------------
// Turn → messages
// ---------------------------------------------------------------------------

/**
 * Build messages for a single turn.
 *
 * Produces up to 2 messages: one user message and one assistant message.
 * Tool call results are embedded as content parts within the assistant message.
 */
function buildTurnMessages(turnId: string, events: SessionEvent[]): SessionMessage[] {
  const sorted = [...events].sort(bySeq);
  const messages: SessionMessage[] = [];

  // Detect turn lifecycle events.
  const startedEvent = sorted.find((e) => e.type === "turn.started");
  const completedEvent = sorted.find((e) => e.type === "turn.completed");
  const failedEvent = sorted.find((e) => e.type === "turn.failed");

  // Determine turn state.
  const turnState: "running" | "completed" | "failed" = failedEvent
    ? "failed"
    : completedEvent
      ? "completed"
      : "running";

  const origin = deriveTurnOrigin(startedEvent);
  const trigger = getString(startedEvent?.payload ?? {}, "trigger");
  const isCommand = trigger === "command";

  // Collect evidence counts for halMeta.
  const evidenceCounts = countEvidence(sorted);

  // --- User message ---
  const userEvent = sorted.find((e) => e.type === "user.message");
  if (userEvent) {
    const content = getString(userEvent.payload, "content") ?? "";
    messages.push({
      id: `${turnId}_user`,
      role: "user",
      turnId,
      createdAt: new Date(userEvent.ts),
      content: [{ type: "text", text: content }],
      halMeta: { origin, isCommand },
    });
  }

  // --- Injected messages within a turn ---
  for (const event of sorted) {
    if (event.type === "message.injected") {
      const content = getString(event.payload, "content") ?? "";
      messages.push({
        id: `evt_${event.seq}`,
        role: "system",
        turnId,
        createdAt: new Date(event.ts),
        content: [{ type: "text", text: content }],
        halMeta: {},
      });
    }
  }

  // --- Assistant message (with tool-call parts) ---
  const assistantEvent = sorted.find((e) => e.type === "assistant.message_completed");
  const toolParts = collectToolCallParts(sorted);
  const toolSummaries = buildToolSummaries(sorted);

  // Produce an assistant message if we have output, tool calls, or a failure.
  if (assistantEvent || toolParts.length > 0 || failedEvent) {
    const contentParts: ContentPart[] = [];

    // Tool call parts come first (they happened during the loop).
    contentParts.push(...toolParts);

    // Then the assistant's text output.
    if (assistantEvent) {
      const text = getString(assistantEvent.payload, "content") ?? "";
      if (text) {
        contentParts.push({ type: "text", text });
      }
    } else if (failedEvent) {
      // No assistant output, but the turn failed — show error as text.
      const error = getString(failedEvent.payload, "error") ?? "Turn failed";
      contentParts.push({ type: "text", text: error });
    }

    // Determine assistant message status.
    let status: SessionMessageStatus;
    if (turnState === "running") {
      status = { type: "running" };
    } else if (turnState === "failed") {
      const error = getString(failedEvent!.payload, "error");
      status = { type: "incomplete", reason: "error", error };
    } else {
      status = { type: "complete", reason: "stop" };
    }

    const ts = assistantEvent?.ts ?? failedEvent?.ts ?? completedEvent?.ts ?? sorted[0]!.ts;

    messages.push({
      id: `${turnId}_assistant`,
      role: "assistant",
      turnId,
      createdAt: new Date(ts),
      content: contentParts.length > 0 ? contentParts : [{ type: "text", text: "" }],
      status,
      halMeta: {
        turnId,
        turnState,
        origin,
        isCommand,
        evidenceCounts: hasEvidence(evidenceCounts) ? evidenceCounts : undefined,
        toolSummaries: toolSummaries.length > 0 ? toolSummaries : undefined,
      },
    });
  }

  return messages;
}

// ---------------------------------------------------------------------------
// Tool call part collection
// ---------------------------------------------------------------------------

/** Collect tool.call_completed and tool.call_failed events as tool-call content parts. */
function collectToolCallParts(events: SessionEvent[]): ToolCallPart[] {
  const parts: ToolCallPart[] = [];

  for (const event of events) {
    if (event.type === "tool.call_completed") {
      const toolName = getString(event.payload, "tool") ?? getString(event.refs, "tool_name") ?? "unknown";
      const toolCallId = getString(event.refs, "tool_call_id") ?? `tc_${event.seq}`;
      const resultPreview = getString(event.payload, "result_preview");
      const resultSize = getFiniteNumber(event.payload, "result_size");
      const args = extractArgs(event.payload);

      parts.push({
        type: "tool-call",
        toolCallId,
        toolName,
        args,
        result: resultPreview ?? (resultSize != null ? `${resultSize} chars` : "completed"),
        isError: false,
      });
    } else if (event.type === "tool.call_failed") {
      const toolName = getString(event.payload, "tool") ?? getString(event.refs, "tool_name") ?? "unknown";
      const toolCallId = getString(event.refs, "tool_call_id") ?? `tc_${event.seq}`;
      const error = getString(event.payload, "error") ?? "Tool call failed";
      const args = extractArgs(event.payload);

      parts.push({
        type: "tool-call",
        toolCallId,
        toolName,
        args,
        result: error,
        isError: true,
      });
    } else if (event.type === "subagent.completed") {
      const label = getString(event.payload, "label") ?? "subagent";
      const status = getString(event.payload, "status") ?? "completed";
      const content = getString(event.payload, "content");
      const toolCallId = `subagent_${event.seq}`;

      parts.push({
        type: "tool-call",
        toolCallId,
        toolName: `subagent:${label}`,
        result: content ?? status,
        isError: status === "failed",
      });
    }
  }

  return parts;
}

/** Extract args object from a tool event payload, if present. */
function extractArgs(
  payload: Record<string, unknown>,
): Readonly<Record<string, JsonValue>> | undefined {
  const raw = payload.args;
  if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Readonly<Record<string, JsonValue>>;
  }
  return undefined;
}

/** Build compact tool summaries for halMeta. */
function buildToolSummaries(
  events: SessionEvent[],
): Array<{ name: string; status: string }> {
  const summaries: Array<{ name: string; status: string }> = [];
  for (const event of events) {
    if (event.type === "tool.call_completed") {
      summaries.push({
        name: getString(event.payload, "tool") ?? getString(event.refs, "tool_name") ?? "unknown",
        status: "completed",
      });
    } else if (event.type === "tool.call_failed") {
      summaries.push({
        name: getString(event.payload, "tool") ?? getString(event.refs, "tool_name") ?? "unknown",
        status: "failed",
      });
    }
  }
  return summaries;
}

// ---------------------------------------------------------------------------
// Standalone (session-level) messages
// ---------------------------------------------------------------------------

function buildStandaloneMessage(event: SessionEvent): SessionMessage | null {
  switch (event.type) {
    case "message.injected": {
      const content = getString(event.payload, "content") ?? "";
      return {
        id: `evt_${event.seq}`,
        role: "system",
        turnId: null,
        createdAt: new Date(event.ts),
        content: [{ type: "text", text: content }],
        halMeta: {},
      };
    }

    case "session.scope_updated": {
      const added = getStringArray(event.payload, "added_threads");
      const removed = getStringArray(event.payload, "removed_threads");
      const parts: string[] = [];
      if (added.length > 0) parts.push(`+${added.join(", ")}`);
      if (removed.length > 0) parts.push(`\u2212${removed.join(", ")}`);
      const text = `Scope updated${parts.length > 0 ? `: ${parts.join(" / ")}` : ""}`;
      return {
        id: `evt_${event.seq}`,
        role: "system",
        turnId: null,
        createdAt: new Date(event.ts),
        content: [{ type: "text", text }],
        halMeta: {},
      };
    }

    case "brief.completed": {
      const briefStatus = getString(event.payload, "status") ?? "completed";
      const episodeId = getString(event.payload, "episode_id");
      const parts: string[] = [`Brief ${briefStatus}`];
      if (episodeId) parts.push(`episode: ${episodeId}`);
      return {
        id: `evt_${event.seq}`,
        role: "system",
        turnId: null,
        createdAt: new Date(event.ts),
        content: [{ type: "text", text: parts.join(" \u00b7 ") }],
        halMeta: {},
      };
    }

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Evidence counting (for halMeta, not for rendering)
// ---------------------------------------------------------------------------

function countEvidence(events: SessionEvent[]): EvidenceCounts {
  const counts: EvidenceCounts = { context: 0, loop: 0, tool: 0, injection: 0, worker: 0 };
  for (const event of events) {
    if (!EVIDENCE_EVENTS.has(event.type)) continue;
    switch (event.type) {
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
  return counts;
}

function hasEvidence(counts: EvidenceCounts): boolean {
  return counts.context + counts.loop + counts.tool + counts.injection + counts.worker > 0;
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
