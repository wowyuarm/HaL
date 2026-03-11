/**
 * HaL client store — engine state mirror.
 *
 * Zustand store that holds the canonical client-side projection of engine
 * state.  Every field is populated by server-pushed WebSocket events; the
 * UI is a pure function of this store.
 *
 * The only optimistic write is `addUserMessage`, which inserts a local
 * placeholder before the server acknowledges it.
 */
import { create } from "zustand";

import type {
  ContextSummaryData,
  Message,
  MessageMetadata,
  MessageRole,
  Thread,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Engine status
// ---------------------------------------------------------------------------

export type EngineStatus = "idle" | "processing";

// ---------------------------------------------------------------------------
// WebSocket envelope types (server → client)
// ---------------------------------------------------------------------------

export interface SnapshotPayload {
  type: "snapshot";
  session_id: string;
  active_thread: string | null;
  threads: Thread[];
  history: Message[];
  context_summary: ContextSummaryData;
  status: EngineStatus;
}

export interface MessagePayload {
  type: "message";
  id: string;
  role: MessageRole;
  content: string;
  ts: string;
  metadata?: MessageMetadata;
}

export interface StatusPayload {
  type: "status";
  state: EngineStatus;
}

export interface ThreadsPayload {
  type: "threads";
  list: Thread[];
}

export interface ContextSummaryPayload extends ContextSummaryData {
  type: "context_summary";
}

export interface ErrorPayload {
  type: "error";
  message: string;
}

/** Union of all server-to-client envelopes. */
export type ServerEnvelope =
  | SnapshotPayload
  | MessagePayload
  | StatusPayload
  | ThreadsPayload
  | ContextSummaryPayload
  | ErrorPayload;

// ---------------------------------------------------------------------------
// WebSocket envelope types (client → server)
// ---------------------------------------------------------------------------

export interface ClientMessageEnvelope {
  type: "message";
  content: string;
}

export interface ClientCommandEnvelope {
  type: "command";
  name: "brief" | "drop" | "context";
  args: Record<string, unknown>;
}

export interface ClientSelectThreadEnvelope {
  type: "select_thread";
  slug: string;
}

export type ClientEnvelope =
  | ClientMessageEnvelope
  | ClientCommandEnvelope
  | ClientSelectThreadEnvelope;

// ---------------------------------------------------------------------------
// Store shape
// ---------------------------------------------------------------------------

/** Default context summary before the first snapshot arrives. */
const EMPTY_CONTEXT: ContextSummaryData = { tokens: 0, tools: 0, history: 0 };

/** Prefix for client-generated message IDs (before server acknowledges). */
const LOCAL_ID_PREFIX = "local_";

interface HalStore {
  // Connection
  connected: boolean;
  setConnected: (v: boolean) => void;

  // Session
  sessionId: string | null;
  status: EngineStatus;

  // Threads
  threads: Thread[];
  activeThread: string | null;
  selectThread: (slug: string) => void;

  // Messages
  messages: Message[];

  // Context
  contextSummary: ContextSummaryData;

  // Error surface (latest error, cleared on next snapshot)
  lastError: string | null;

  // Server-event handlers
  handleSnapshot: (data: SnapshotPayload) => void;
  handleMessage: (data: MessagePayload) => void;
  handleStatus: (data: StatusPayload) => void;
  handleThreads: (data: ThreadsPayload) => void;
  handleContextSummary: (data: ContextSummaryPayload) => void;
  handleError: (data: ErrorPayload | string) => void;

  // Optimistic user action
  addUserMessage: (content: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Generate a client-side message ID (crypto.randomUUID with fallback). */
function generateLocalId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `${LOCAL_ID_PREFIX}${crypto.randomUUID()}`;
  }
  // Fallback for environments without crypto.randomUUID
  return `${LOCAL_ID_PREFIX}${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Insert or replace a message in the list by ID.
 *
 * If the server pushes a message whose ID matches an existing entry (e.g. a
 * local optimistic insert later echoed back), the server version wins.
 */
function upsertMessage(messages: Message[], incoming: Message): Message[] {
  const idx = messages.findIndex((m) => m.id === incoming.id);
  if (idx === -1) return [...messages, incoming];

  const updated = messages.slice();
  updated[idx] = incoming;
  return updated;
}

// ---------------------------------------------------------------------------
// Store creation
// ---------------------------------------------------------------------------

export const useHalStore = create<HalStore>((set, get) => ({
  // -- Connection -----------------------------------------------------------
  connected: false,
  setConnected: (v) => set({ connected: v }),

  // -- Session --------------------------------------------------------------
  sessionId: null,
  status: "idle",

  // -- Threads --------------------------------------------------------------
  threads: [],
  activeThread: null,
  selectThread: (slug) => {
    const { threads } = get();
    if (threads.some((t) => t.slug === slug)) {
      set({ activeThread: slug });
    }
  },

  // -- Messages -------------------------------------------------------------
  messages: [],

  // -- Context --------------------------------------------------------------
  contextSummary: EMPTY_CONTEXT,

  // -- Error ----------------------------------------------------------------
  lastError: null,

  // -- Server-event handlers ------------------------------------------------

  handleSnapshot: (data) =>
    set({
      sessionId: data.session_id,
      activeThread: data.active_thread,
      threads: data.threads,
      messages: data.history,
      contextSummary: data.context_summary,
      status: data.status,
      lastError: null,
    }),

  handleMessage: (data) =>
    set((state) => ({
      messages: upsertMessage(state.messages, {
        id: data.id,
        role: data.role,
        content: data.content,
        ts: data.ts,
        metadata: data.metadata,
      }),
    })),

  handleStatus: (data) => set({ status: data.state }),

  handleThreads: (data) =>
    set((state) => {
      const activeStillExists = data.list.some(
        (t) => t.slug === state.activeThread,
      );
      return {
        threads: data.list,
        activeThread: activeStillExists
          ? state.activeThread
          : (data.list[0]?.slug ?? null),
      };
    }),

  handleContextSummary: (data) =>
    set({
      contextSummary: { tokens: data.tokens, tools: data.tools, history: data.history },
    }),

  handleError: (data) =>
    set({
      lastError: typeof data === "string" ? data : data.message,
    }),

  // -- Optimistic user action -----------------------------------------------

  addUserMessage: (content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: generateLocalId(),
          role: "user",
          content,
          ts: new Date().toISOString(),
        },
      ],
    })),
}));
