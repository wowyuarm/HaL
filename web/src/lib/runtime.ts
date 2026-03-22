import type { SessionEvent, SessionManifest, SessionStatus } from "@/lib/types";

export interface TurnGroup {
  kind: "turn";
  turnId: string;
  startedAt: string;
  events: SessionEvent[];
}

export interface StandaloneEventItem {
  kind: "event";
  event: SessionEvent;
}

export type WorkingLogItem = TurnGroup | StandaloneEventItem;

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

export function buildWorkingLogItems(events: SessionEvent[]): WorkingLogItem[] {
  const ordered = [...events].sort((a, b) => a.seq - b.seq);
  const items: WorkingLogItem[] = [];
  const turnMap = new Map<string, TurnGroup>();

  for (const event of ordered) {
    if (!event.turn_id) {
      items.push({ kind: "event", event });
      continue;
    }

    let turn = turnMap.get(event.turn_id);
    if (!turn) {
      turn = {
        kind: "turn",
        turnId: event.turn_id,
        startedAt: event.ts,
        events: [],
      };
      turnMap.set(event.turn_id, turn);
      items.push(turn);
    }
    turn.events.push(event);
  }

  return items;
}

export function formatRelativeTime(ts: string | null | undefined): string {
  if (!ts) return "--";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;

  const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diffSec < 0 || diffSec < MINUTE) return "just now";
  if (diffSec < HOUR) return `${Math.floor(diffSec / MINUTE)}m ago`;
  if (diffSec < DAY) return `${Math.floor(diffSec / HOUR)}h ago`;
  if (diffSec < DAY * 30) return `${Math.floor(diffSec / DAY)}d ago`;

  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return "--";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatCount(value: number | undefined): string {
  const safe = value ?? 0;
  if (safe < 1000) return String(safe);
  const formatted = (safe / 1000).toFixed(1);
  return formatted.endsWith(".0") ? `${formatted.slice(0, -2)}k` : `${formatted}k`;
}

export function sessionDisplayState(
  status: SessionStatus,
): { label: string; dotClass: string; textClass: string } {
  switch (status) {
    case "active":
      return {
        label: "active",
        dotClass: "bg-accent animate-pulse",
        textClass: "text-accent",
      };
    case "briefing":
      return {
        label: "briefing",
        dotClass: "bg-accent",
        textClass: "text-accent",
      };
    case "ended":
      return {
        label: "briefed",
        dotClass: "bg-success",
        textClass: "text-success",
      };
    case "dropped":
      return {
        label: "dropped",
        dotClass: "bg-hal-muted",
        textClass: "text-hal-muted",
      };
  }
}

export function summarizeSession(manifest: SessionManifest): string {
  const mounted = manifest.mounted_threads.length;
  const turns = manifest.turn_count;
  return `${turns} turn${turns === 1 ? "" : "s"} · ${mounted} thread${mounted === 1 ? "" : "s"}`;
}

export function isInteractiveSession(status: SessionStatus): boolean {
  return status === "active" || status === "briefing";
}

export function eventSummary(event: SessionEvent): string {
  switch (event.type) {
    case "session.created":
      return "Session created";
    case "session.scope_updated": {
      const added = stringList(event.payload.added_threads).join(", ");
      const removed = stringList(event.payload.removed_threads).join(", ");
      if (added && removed) return `Scope updated: +${added} / -${removed}`;
      if (added) return `Scope updated: +${added}`;
      if (removed) return `Scope updated: -${removed}`;
      return "Scope updated";
    }
    case "session.ended":
      return `Session ended: ${stringValue(event.payload.reason) ?? "completed"}`;
    case "session.compacted":
      return "Session history compacted";
    case "context.compiled": {
      const recalled = numberValue(event.payload.search_results) ?? 0;
      const tokens = numberValue(event.payload.estimated_input_tokens);
      return `Context compiled${tokens ? ` · ${formatCount(tokens)} tok` : ""} · ${recalled} recalls`;
    }
    case "loop.started":
      return "Loop started";
    case "loop.iteration_started":
      return `Iteration ${numberValue(event.payload.iteration) ?? "?"} started`;
    case "llm.request_started":
      return "LLM request started";
    case "llm.response_completed": {
      const hasTools = Boolean(event.payload.has_tool_calls);
      return hasTools ? "LLM response planned tool calls" : "LLM response completed";
    }
    case "tool.call_started":
      return `Tool started: ${stringValue(event.payload.tool) ?? "unknown"}`;
    case "tool.call_completed":
      return `Tool completed: ${stringValue(event.payload.tool) ?? "unknown"}`;
    case "hook.injected":
      return `Hook injected: ${stringValue(event.payload.kind) ?? "context"}`;
    case "message.injected":
      return `Message injected: ${stringValue(event.payload.kind) ?? "runtime"}`;
    case "brief.started":
      return "Brief worker started";
    case "brief.completed":
      return "Brief worker completed";
    case "status.changed": {
      const status = stringValue(event.payload.status) ?? "updated";
      const message = stringValue(event.payload.message);
      return message ?? `Status changed: ${status}`;
    }
    case "subagent.completed":
      return `Subagent completed: ${stringValue(event.payload.label) ?? "worker"}`;
    case "turn.completed":
      return "Turn completed";
    case "turn.failed":
      return "Turn failed";
    default:
      return event.type;
  }
}

export function extractTextBlock(event: SessionEvent): string | null {
  switch (event.type) {
    case "user.message":
      return stringValue(event.payload.content);
    case "assistant.message_completed":
      return stringValue(event.payload.content);
    case "hook.injected":
      return stringValue(event.payload.content);
    case "message.injected":
      return stringValue(event.payload.content) ?? stringValue(event.payload.prefixed_content);
    default:
      return null;
  }
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.length > 0)
    : [];
}
