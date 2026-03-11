/**
 * HaL WebSocket connection manager.
 *
 * React hook that owns a single `/ws` connection to the engine backend,
 * forwards incoming envelopes into the Zustand store, and reconnects with
 * capped exponential backoff on disconnect.
 *
 * Usage:
 *   const { send, connected, lastMessage } = useWebSocket();
 *
 * Call this hook exactly once (in a top-level provider or App component).
 * Multiple mount points will open multiple sockets.
 */
import { useCallback, useEffect, useRef } from "react";

import {
  useHalStore,
  type ClientEnvelope,
  type ServerEnvelope,
} from "@/lib/store";

// ---------------------------------------------------------------------------
// Reconnect policy
// ---------------------------------------------------------------------------

/** Initial delay before the first reconnect attempt (ms). */
const INITIAL_RETRY_MS = 1_000;
/** Maximum delay between reconnect attempts (ms). */
const MAX_RETRY_MS = 30_000;
/** Exponential base for backoff (delay = INITIAL * BASE^attempt). */
const BACKOFF_BASE = 2;

// ---------------------------------------------------------------------------
// URL resolution
// ---------------------------------------------------------------------------

/**
 * Build the WebSocket URL.
 *
 * In development the Vite proxy rewrites `/ws` to `ws://localhost:8765/ws`,
 * so we always connect to the same origin.
 */
function resolveWsUrl(): string {
  const proto = globalThis.location?.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${globalThis.location?.host}/ws`;
}

// ---------------------------------------------------------------------------
// Payload parsing
// ---------------------------------------------------------------------------

/**
 * Attempt to parse a raw WebSocket frame as a known server envelope.
 * Returns `null` if the payload is not valid JSON or lacks a `type` field.
 */
function parseEnvelope(raw: string): ServerEnvelope | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "type" in parsed &&
      typeof (parsed as Record<string, unknown>).type === "string"
    ) {
      return parsed as ServerEnvelope;
    }
    return null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface UseWebSocketReturn {
  /** Send a typed client envelope.  Returns `true` if the socket was open. */
  send: (data: ClientEnvelope) => boolean;
  /** Whether the socket is currently open. */
  connected: boolean;
  /** Ref to the most recently received server envelope (not reactive). */
  lastMessage: React.RefObject<ServerEnvelope | null>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useWebSocket(): UseWebSocketReturn {
  const connected = useHalStore((s) => s.connected);

  const socketRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const lastMessageRef = useRef<ServerEnvelope | null>(null);

  // Track whether we're mounted so the cleanup closure can signal "stop".
  const mountedRef = useRef(true);

  // -- send -----------------------------------------------------------------

  const send = useCallback((data: ClientEnvelope): boolean => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(data));
    return true;
  }, []);

  // -- connection lifecycle -------------------------------------------------

  useEffect(() => {
    mountedRef.current = true;

    const clearRetryTimer = () => {
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };

    const scheduleReconnect = () => {
      if (!mountedRef.current) return;
      const delay = Math.min(
        INITIAL_RETRY_MS * BACKOFF_BASE ** attemptRef.current,
        MAX_RETRY_MS,
      );
      attemptRef.current += 1;
      retryTimerRef.current = setTimeout(connect, delay);
    };

    /** Dispatch a parsed server envelope to the store. */
    const dispatch = (env: ServerEnvelope) => {
      const store = useHalStore.getState();
      switch (env.type) {
        case "snapshot":
          store.handleSnapshot(env);
          break;
        case "message":
          store.handleMessage(env);
          break;
        case "status":
          store.handleStatus(env);
          break;
        case "threads":
          store.handleThreads(env);
          break;
        case "context_summary":
          store.handleContextSummary(env);
          break;
        case "error":
          store.handleError(env);
          break;
        default:
          // Protocol extensibility: unknown types are silently ignored.
          break;
      }
    };

    function connect() {
      clearRetryTimer();
      if (!mountedRef.current) return;

      const ws = new WebSocket(resolveWsUrl());
      socketRef.current = ws;

      // Guard against stale events from a previous socket instance (can
      // happen during React 18 StrictMode double-mount or fast reconnects).
      const isLive = () => mountedRef.current && socketRef.current === ws;

      ws.onopen = () => {
        if (!isLive()) return;
        attemptRef.current = 0;
        useHalStore.getState().setConnected(true);
      };

      ws.onmessage = (event: MessageEvent) => {
        if (!isLive()) return;
        if (typeof event.data !== "string") return;

        const env = parseEnvelope(event.data);
        if (!env) return;

        lastMessageRef.current = env;
        dispatch(env);
      };

      ws.onerror = () => {
        if (!isLive()) return;
        // The browser will also fire `onclose` after an error, so we only
        // need to surface the error — reconnect logic lives in onclose.
        useHalStore.getState().handleError("WebSocket connection error.");
      };

      ws.onclose = () => {
        if (!isLive()) return;
        socketRef.current = null;
        useHalStore.getState().setConnected(false);
        scheduleReconnect();
      };
    }

    connect();

    // -- cleanup on unmount ------------------------------------------------
    return () => {
      mountedRef.current = false;
      clearRetryTimer();

      const ws = socketRef.current;
      if (ws) {
        // Null all handlers to prevent stale events from a closing socket
        // from mutating the store after unmount.
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
        socketRef.current = null;
      }
      useHalStore.getState().setConnected(false);
    };
  }, []);

  return { send, connected, lastMessage: lastMessageRef };
}
