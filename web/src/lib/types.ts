/** Session lifecycle states persisted by the backend. */
export type SessionStatus = "active" | "briefing" | "ended" | "dropped";

/** Live socket connection state for the selected session. */
export type SocketState = "disconnected" | "connecting" | "live";

/** Generic JSON object payload. */
export type JsonObject = Record<string, unknown>;

/** Sidebar thread summary returned by `/threads`. */
export interface ThreadSummary {
  slug: string;
  name: string;
  status: string;
  scope: string;
  description: string;
  updated_at: string | null;
  session_counts: Partial<Record<SessionStatus, number>>;
}

/** Durable session manifest returned by the native web runtime. */
export interface SessionManifest {
  session_id: string;
  status: SessionStatus;
  created_at: string;
  ended_at: string | null;
  channel: string | null;
  chat_id: string | null;
  primary_thread: string | null;
  mounted_threads: string[];
  touched_threads: string[];
  turn_count: number;
  last_event_seq: number;
}

/** Full thread detail returned by `/threads/{slug}`. */
export interface ThreadDetail extends ThreadSummary {
  brief_markdown: string;
  sessions: SessionManifest[];
}

/** Durable session event entry from `working-log.jsonl`. */
export interface SessionEvent {
  v: number;
  seq: number;
  ts: string;
  session_id: string;
  turn_id: string | null;
  type: string;
  actor: "user" | "engine" | "tool" | "worker";
  refs: JsonObject;
  payload: JsonObject;
}

/** Initial WebSocket frame for a live session connection. */
export interface SessionSnapshotEnvelope {
  type: "session_snapshot";
  manifest: SessionManifest;
  recent_events: SessionEvent[];
}

/** Incremental live event frame for a session WebSocket. */
export interface SessionEventEnvelope {
  type: "session_event";
  event: SessionEvent;
}

/** Error frame sent by the web server. */
export interface SessionErrorEnvelope {
  type: "error";
  message: string;
}

export type SessionServerEnvelope =
  | SessionSnapshotEnvelope
  | SessionEventEnvelope
  | SessionErrorEnvelope;

/** Inbound session command: append a new user turn. */
export interface SubmitTurnEnvelope {
  type: "submit_turn";
  content: string;
}

/** Inbound lifecycle control command. */
export interface EndSessionEnvelope {
  type: "end_session";
  reason: "brief" | "drop";
  user_prompt?: string;
}

/** Inbound mounted-thread scope update. */
export interface UpdateScopeEnvelope {
  type: "update_scope";
  add_threads: string[];
  remove_threads: string[];
}

export type SessionClientEnvelope =
  | SubmitTurnEnvelope
  | EndSessionEnvelope
  | UpdateScopeEnvelope;
