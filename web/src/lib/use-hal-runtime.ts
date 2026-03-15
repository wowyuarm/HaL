/**
 * useHalRuntime — bridge between HaL session state and assistant-ui.
 *
 * Creates an ExternalStoreRuntime that reads SessionEvents from the
 * Zustand store, converts them to SessionMessages via session-adapter,
 * and exposes send/cancel callbacks for the assistant-ui primitives.
 *
 * This hook is the single integration point between HaL's data layer
 * and assistant-ui's rendering layer.
 */

import { useMemo } from "react";
import { useExternalStoreRuntime } from "@assistant-ui/react";

import type { SessionEvent, SessionManifest } from "@/lib/types";
import { convertSessionEvents, type SessionMessage } from "@/lib/session-adapter";
import { submitSessionTurn } from "@/lib/api";
import { useHalStore } from "@/lib/store";
import type { ThreadMessageLike } from "@assistant-ui/react";

// ---------------------------------------------------------------------------
// SessionMessage → ThreadMessageLike converter
// ---------------------------------------------------------------------------

function toThreadMessageLike(msg: SessionMessage): ThreadMessageLike {
  const base: ThreadMessageLike = {
    role: msg.role,
    id: msg.id,
    content: msg.content,
    createdAt: msg.createdAt,
    metadata: {
      custom: msg.halMeta as Record<string, unknown>,
    },
  };

  // assistant-ui throws if status is set on non-assistant messages.
  return msg.role === "assistant" && msg.status
    ? { ...base, status: msg.status }
    : base;
}

// ---------------------------------------------------------------------------
// Turn-running detection
// ---------------------------------------------------------------------------

/** Check if the last turn in the event stream is still running. */
function detectRunningTurn(events: SessionEvent[]): boolean {
  // Walk backwards to find the most recent turn lifecycle event.
  for (let i = events.length - 1; i >= 0; i--) {
    const type = events[i]!.type;
    if (type === "turn.completed" || type === "turn.failed") return false;
    if (type === "turn.started") return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Create an assistant-ui runtime backed by HaL session state.
 *
 * @param sessionId  The currently selected session ID (null = no session).
 * @param socketState  Current WebSocket connection state.
 *
 * Reads events and manifest from the Zustand store. The runtime
 * automatically updates when the store changes.
 */
export function useHalRuntime(sessionId: string | null) {
  // Store selectors — fine-grained to minimize re-renders.
  const events: SessionEvent[] = useHalStore(
    (s) => (sessionId ? s.sessionEvents[sessionId] : undefined) ?? EMPTY_EVENTS,
  );
  const manifest: SessionManifest | undefined = useHalStore(
    (s) => (sessionId ? s.sessionManifests[sessionId] : undefined),
  );
  const setError = useHalStore((s) => s.setError);

  // Convert events → messages (memoized on events reference).
  const messages = useMemo(() => convertSessionEvents(events), [events]);

  // Derived state.
  const isRunning = Boolean(
    sessionId && manifest?.status === "active" && detectRunningTurn(events),
  );
  const canSend = Boolean(sessionId && manifest?.status === "active");

  // Build the adapter.
  const runtime = useExternalStoreRuntime<SessionMessage>({
    messages,
    convertMessage: toThreadMessageLike,
    isRunning,
    isDisabled: !canSend,

    onNew: async (appendMessage) => {
      if (!sessionId) return;
      // Extract text content from assistant-ui's AppendMessage.
      const textPart = appendMessage.content.find(
        (p): p is { type: "text"; text: string } => p.type === "text",
      );
      if (!textPart?.text) return;

      try {
        const submission = await submitSessionTurn(sessionId, {
          content: textPart.text,
        });
        // Read latest store state to avoid stale closure on socketState.
        const {
          socketState: latestSocketState,
          applySessionManifest,
          loadSessionEvents,
        } = useHalStore.getState();
        if (latestSocketState !== "live") {
          applySessionManifest(submission.session);
          await loadSessionEvents(sessionId);
        }
      } catch (error) {
        setError(error instanceof Error ? error.message : "Failed to submit turn.");
      }
    },

    // HaL does not support turn cancellation yet.
    // onCancel: async () => {},
  });

  return runtime;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EMPTY_EVENTS: SessionEvent[] = [];
