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

import { useMemo } from 'react'
import { useExternalStoreRuntime } from '@assistant-ui/react'

import type { SessionEvent, SessionManifest } from '@/lib/types'
import { convertSessionEvents, type SessionMessage } from '@/lib/session-adapter'
import { useHalStore } from '@/lib/store'
import type { ThreadMessageLike } from '@assistant-ui/react'

// ---------------------------------------------------------------------------
// SessionMessage → ThreadMessageLike converter
// ---------------------------------------------------------------------------

function toThreadMessageLike(msg: SessionMessage): ThreadMessageLike {
  const base: ThreadMessageLike = {
    role: msg.role,
    id: msg.id,
    content: msg.content,
    createdAt: msg.createdAt,
    ...(msg.role === 'user' && msg.attachments?.length
      ? { attachments: msg.attachments }
      : undefined),
    metadata: {
      custom: msg.halMeta as Record<string, unknown>,
    },
  }

  // assistant-ui throws if status is set on non-assistant messages.
  return msg.role === 'assistant' && msg.status ? { ...base, status: msg.status } : base
}

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
  )
  const manifest: SessionManifest | undefined = useHalStore((s) =>
    sessionId ? s.sessionManifests[sessionId] : undefined,
  )

  // Convert events → messages (memoized on events reference).
  const messages = useMemo(() => convertSessionEvents(events), [events])

  // Derived state.
  const canSend = Boolean(sessionId && manifest?.status === 'active')

  // Build the adapter.
  const runtime = useExternalStoreRuntime<SessionMessage>({
    messages,
    convertMessage: toThreadMessageLike,
    // HaL accepts mid-loop user follow-ups and routes them into the current
    // turn's process trail. assistant-ui treats thread-level "running" as a
    // hard send lock, so keep the external runtime idle and rely on
    // message-level assistant status for live rendering.
    isRunning: false,
    isDisabled: !canSend,
    onNew: async () => {},

    // HaL does not support turn cancellation yet.
    // onCancel: async () => {},
  })

  return runtime
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EMPTY_EVENTS: SessionEvent[] = []
