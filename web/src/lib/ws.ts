import { useCallback, useEffect, useRef } from "react";

import { useHalStore } from "@/lib/store";
import type { SessionClientEnvelope, SessionServerEnvelope, SessionStatus } from "@/lib/types";

const INITIAL_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;
const BACKOFF_BASE = 2;

function resolveWsUrl(sessionId: string): string {
  const proto = globalThis.location?.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${globalThis.location?.host}/sessions/${sessionId}/ws`;
}

function parseEnvelope(raw: string): SessionServerEnvelope | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "type" in parsed &&
      typeof (parsed as Record<string, unknown>).type === "string"
    ) {
      return parsed as SessionServerEnvelope;
    }
    return null;
  } catch {
    return null;
  }
}

export interface UseSessionSocketReturn {
  send: (message: SessionClientEnvelope) => boolean;
}

export function useSessionSocket(
  sessionId: string | null,
  status: SessionStatus | null,
): UseSessionSocketReturn {
  const socketRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);
  const enabled = Boolean(sessionId && (status === "active" || status === "briefing"));

  const send = useCallback((message: SessionClientEnvelope): boolean => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(message));
    return true;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    const store = useHalStore.getState();

    const clearRetryTimer = () => {
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };

    if (!enabled || !sessionId) {
      clearRetryTimer();
      const ws = socketRef.current;
      if (ws) {
        ws.close();
        socketRef.current = null;
      }
      store.setSocketState("disconnected");
      return () => {
        mountedRef.current = false;
        clearRetryTimer();
      };
    }

    const scheduleReconnect = () => {
      if (!mountedRef.current) return;
      const delay = Math.min(
        INITIAL_RETRY_MS * BACKOFF_BASE ** attemptRef.current,
        MAX_RETRY_MS,
      );
      attemptRef.current += 1;
      retryTimerRef.current = setTimeout(connect, delay);
    };

    function dispatch(envelope: SessionServerEnvelope) {
      const nextStore = useHalStore.getState();
      switch (envelope.type) {
        case "session_snapshot":
          nextStore.applySessionSnapshot(envelope.manifest, envelope.recent_events);
          break;
        case "session_event":
          nextStore.appendSessionEvent(envelope.event);
          break;
        case "error":
          nextStore.setError(envelope.message);
          break;
      }
    }

    function connect() {
      clearRetryTimer();
      if (!mountedRef.current) return;
      if (!sessionId) return;

      store.setSocketState("connecting");
      const ws = new WebSocket(resolveWsUrl(sessionId));
      socketRef.current = ws;

      const isLive = () => mountedRef.current && socketRef.current === ws;

      ws.onopen = () => {
        if (!isLive()) return;
        attemptRef.current = 0;
        const nextStore = useHalStore.getState();
        nextStore.setSocketState("live");
        nextStore.setError(null);
      };

      ws.onmessage = (event: MessageEvent) => {
        if (!isLive() || typeof event.data !== "string") return;
        const envelope = parseEnvelope(event.data);
        if (!envelope) return;
        dispatch(envelope);
      };

      ws.onerror = () => {
        if (!isLive()) return;
        useHalStore.getState().setError("Session socket error.");
      };

      ws.onclose = () => {
        if (!isLive()) return;
        socketRef.current = null;
        useHalStore.getState().setSocketState("disconnected");
        scheduleReconnect();
      };
    }

    connect();

    return () => {
      mountedRef.current = false;
      clearRetryTimer();
      const ws = socketRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
        socketRef.current = null;
      }
      useHalStore.getState().setSocketState("disconnected");
    };
  }, [enabled, sessionId]);

  return { send };
}
