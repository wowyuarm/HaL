/**
 * Session-to-message adapter for assistant-ui.
 *
 * Converts a flat array of HaL SessionEvents into an array of
 * SessionMessage objects that can be fed to assistant-ui's
 * ExternalStoreRuntime via a `convertMessage` callback.
 *
 * The adapter keeps the main thread focused on user / assistant / system
 * messages, while turn-level process detail is derived separately from the
 * underlying SessionEvents.
 */

import type { CompleteAttachment } from '@assistant-ui/react'

import type { SessionEvent, WebAttachmentInput, WebAttachmentPart } from '@/lib/types'
import type { ProcessPreview, ProcessTone } from '@/lib/process'
import { buildTurnProcessView } from '@/lib/process'
import { bySeq, getFiniteNumber, getString, getStringArray } from '@/lib/event-helpers'

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/** Content part compatible with assistant-ui ThreadMessageLike. */
export type ContentPart = TextPart

export interface TextPart {
  readonly type: 'text'
  readonly text: string
}

/** JSON-safe value type compatible with assistant-ui's ReadonlyJSONValue. */
type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

/**
 * Message status aligned with assistant-ui's MessageStatus union.
 * Re-declared here to avoid importing from @assistant-ui/core internals.
 */
export type SessionMessageStatus =
  | { readonly type: 'running' }
  | { readonly type: 'complete'; readonly reason: 'stop' | 'unknown' }
  | {
      readonly type: 'incomplete'
      readonly reason: 'error' | 'cancelled' | 'other'
      readonly error?: JsonValue
    }

/** HaL-specific metadata attached to each SessionMessage. */
export interface HalMessageMeta {
  turnId?: string
  turnState?: 'running' | 'completed' | 'failed'
  origin?: 'interactive' | 'background_resume'
  isCommand?: boolean
  lifecycleKind?: 'brief'
  lifecycleState?: 'start' | 'complete' | 'failed'
  processPreview?: ProcessPreview
  systemTone?: ProcessTone
}

/**
 * Intermediate message type bridging HaL events and assistant-ui.
 *
 * Fed to ExternalStoreRuntime as the T parameter, then converted
 * to ThreadMessageLike via a `convertMessage` callback.
 */
export interface SessionMessage {
  readonly id: string
  readonly role: 'user' | 'assistant' | 'system'
  readonly turnId: string | null
  readonly createdAt: Date
  readonly content: readonly ContentPart[]
  readonly attachments?: readonly CompleteAttachment[]
  /** Status is only valid for assistant messages — assistant-ui throws on others. */
  readonly status?: SessionMessageStatus
  readonly halMeta: HalMessageMeta
}

// ---------------------------------------------------------------------------
// Event classification
// ---------------------------------------------------------------------------

/** Session-level activity events (standalone, no turn_id). */
const SESSION_ACTIVITY_EVENTS = new Set([
  'message.injected',
  'session.scope_updated',
  'brief.completed',
  'status.changed',
])

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
  if (events.length === 0) return []

  const ordered = [...events].sort(bySeq)

  // Partition into turn groups and standalone session events.
  const turnGroups = new Map<string, SessionEvent[]>()
  const standaloneEvents: SessionEvent[] = []

  for (const event of ordered) {
    if (event.turn_id) {
      let group = turnGroups.get(event.turn_id)
      if (!group) {
        group = []
        turnGroups.set(event.turn_id, group)
      }
      group.push(event)
    } else if (SESSION_ACTIVITY_EVENTS.has(event.type)) {
      standaloneEvents.push(event)
    }
    // Events without turn_id that aren't session activity → ignored
  }

  // Build messages with a seq key for final interleaving.
  const tagged: Array<{ seq: number; messages: SessionMessage[] }> = []

  for (const [turnId, group] of turnGroups) {
    const leadSeq = group[0]?.seq ?? 0
    tagged.push({ seq: leadSeq, messages: buildTurnMessages(turnId, group) })
  }

  for (const event of standaloneEvents) {
    const msg = buildStandaloneMessage(event)
    if (msg) {
      tagged.push({ seq: event.seq, messages: [msg] })
    }
  }

  // Flatten and sort by seq.
  return tagged.sort((a, b) => a.seq - b.seq).flatMap((entry) => entry.messages)
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
  const sorted = [...events].sort(bySeq)
  const messages: SessionMessage[] = []

  // Detect turn lifecycle events.
  const startedEvent = sorted.find((e) => e.type === 'turn.started')
  const completedEvent = sorted.find((e) => e.type === 'turn.completed')
  const failedEvent = sorted.find((e) => e.type === 'turn.failed')

  // Determine turn state.
  const turnState: 'running' | 'completed' | 'failed' = failedEvent
    ? 'failed'
    : completedEvent
      ? 'completed'
      : 'running'

  const origin = deriveTurnOrigin(startedEvent)
  const trigger = getString(startedEvent?.payload ?? {}, 'trigger')
  const isCommand = trigger === 'command'

  const processView = buildTurnProcessView(sorted, turnState)

  // --- User message ---
  const userEvent = sorted.find((e) => e.type === 'user.message')
  if (userEvent) {
    const content = getString(userEvent.payload, 'content') ?? ''
    const attachments = readUserAttachments(userEvent.payload.attachments)
    messages.push({
      id: `${turnId}_user`,
      role: 'user',
      turnId,
      createdAt: new Date(userEvent.ts),
      content: [{ type: 'text', text: content }],
      ...(attachments.length > 0 ? { attachments } : undefined),
      halMeta: { origin, isCommand },
    })
  }

  // --- Assistant message (process summary + final output) ---
  const assistantEvent = sorted.find((e) => e.type === 'assistant.message_completed')

  if (assistantEvent || processView.entries.length > 0 || failedEvent) {
    const contentParts: ContentPart[] = []

    if (assistantEvent) {
      const text = getString(assistantEvent.payload, 'content') ?? ''
      if (text) {
        contentParts.push({ type: 'text', text })
      }
    } else if (failedEvent) {
      // No assistant output, but the turn failed — show error as text.
      const error = getString(failedEvent.payload, 'error') ?? 'Turn failed'
      contentParts.push({ type: 'text', text: error })
    }

    // Determine assistant message status.
    let status: SessionMessageStatus
    if (turnState === 'running') {
      status = { type: 'running' }
    } else if (turnState === 'failed') {
      const error = getString(failedEvent!.payload, 'error')
      status = { type: 'incomplete', reason: 'error', error }
    } else {
      status = { type: 'complete', reason: 'stop' }
    }

    const ts = assistantEvent?.ts ?? failedEvent?.ts ?? completedEvent?.ts ?? sorted[0]!.ts

    messages.push({
      id: `${turnId}_assistant`,
      role: 'assistant',
      turnId,
      createdAt: new Date(ts),
      content: contentParts.length > 0 ? contentParts : [{ type: 'text', text: '' }],
      status,
      halMeta: {
        turnId,
        turnState,
        origin,
        isCommand,
        processPreview: processView.preview,
      },
    })
  }

  return messages
}

function readUserAttachments(value: unknown): CompleteAttachment[] {
  if (!Array.isArray(value)) return []

  return value
    .map((item, index) => toCompleteAttachment(item, index))
    .filter((item): item is CompleteAttachment => item !== null)
}

function toCompleteAttachment(value: unknown, index: number): CompleteAttachment | null {
  if (!value || typeof value !== 'object') return null

  const input = value as WebAttachmentInput
  const name = typeof input.name === 'string' ? input.name.trim() : ''
  if (!name) return null

  const type =
    input.type === 'image' || input.type === 'document' || input.type === 'file'
      ? input.type
      : 'file'
  const content = Array.isArray(input.content)
    ? input.content
        .map((part) => toAttachmentPart(part))
        .filter((part): part is CompleteAttachment['content'][number] => part !== null)
    : []
  if (content.length === 0) return null

  return {
    id: `${name}:${index}`,
    type,
    name,
    ...(typeof input.contentType === 'string' && input.contentType.trim()
      ? { contentType: input.contentType }
      : undefined),
    status: { type: 'complete' },
    content,
  }
}

function toAttachmentPart(
  part: WebAttachmentPart | null | undefined,
): CompleteAttachment['content'][number] | null {
  if (!part) return null

  switch (part.type) {
    case 'text':
      return typeof part.text === 'string' ? { type: 'text', text: part.text } : null
    case 'image':
      if (typeof part.image !== 'string' || !part.image.trim()) return null
      return {
        type: 'image',
        image: part.image,
        ...(typeof part.filename === 'string' && part.filename.trim()
          ? { filename: part.filename }
          : undefined),
      }
    case 'file':
      if (typeof part.mimeType !== 'string' || !part.mimeType.trim()) return null
      return {
        type: 'file',
        mimeType: part.mimeType,
        data: typeof part.data === 'string' ? part.data : '',
        ...(typeof part.filename === 'string' && part.filename.trim()
          ? { filename: part.filename }
          : undefined),
      }
    default:
      return null
  }
}

// ---------------------------------------------------------------------------
// Standalone (session-level) messages
// ---------------------------------------------------------------------------

function buildStandaloneMessage(event: SessionEvent): SessionMessage | null {
  switch (event.type) {
    case 'message.injected': {
      const summary = summarizeStandaloneInject(event)
      return {
        id: `evt_${event.seq}`,
        role: 'system',
        turnId: null,
        createdAt: new Date(event.ts),
        content: [{ type: 'text', text: summary.text }],
        halMeta: { systemTone: summary.tone },
      }
    }

    case 'session.scope_updated': {
      const added = getStringArray(event.payload, 'added_threads')
      const removed = getStringArray(event.payload, 'removed_threads')
      const parts: string[] = []
      if (added.length > 0) parts.push(`+${added.join(', ')}`)
      if (removed.length > 0) parts.push(`\u2212${removed.join(', ')}`)
      const text = `Scope updated${parts.length > 0 ? `: ${parts.join(' / ')}` : ''}`
      return {
        id: `evt_${event.seq}`,
        role: 'system',
        turnId: null,
        createdAt: new Date(event.ts),
        content: [{ type: 'text', text }],
        halMeta: { systemTone: 'warning' },
      }
    }

    case 'brief.completed': {
      const briefStatus = getString(event.payload, 'status') ?? 'completed'
      const episodeId = getString(event.payload, 'episode_id')
      const parts: string[] = [`Brief ${briefStatus}`]
      if (episodeId) parts.push(`episode: ${episodeId}`)
      return {
        id: `evt_${event.seq}`,
        role: 'system',
        turnId: null,
        createdAt: new Date(event.ts),
        content: [{ type: 'text', text: parts.join(' \u00b7 ') }],
        halMeta: { systemTone: 'success' },
      }
    }

    case 'status.changed': {
      const kind = getString(event.payload, 'kind')
      const text =
        getString(event.payload, 'message') ??
        (() => {
          const status = getString(event.payload, 'status') ?? 'updated'
          return `Session status changed: ${status}`
        })()

      if (
        kind === 'session_brief_start' ||
        kind === 'session_brief_complete' ||
        kind === 'session_brief_failed'
      ) {
        const status: SessionMessageStatus =
          kind === 'session_brief_failed'
            ? { type: 'incomplete', reason: 'error', error: text }
            : { type: 'complete', reason: 'stop' }
        const lifecycleState =
          kind === 'session_brief_start'
            ? 'start'
            : kind === 'session_brief_failed'
              ? 'failed'
              : 'complete'

        return {
          id: `evt_${event.seq}`,
          role: 'assistant',
          turnId: null,
          createdAt: new Date(event.ts),
          content: [{ type: 'text', text }],
          status,
          halMeta: { isCommand: true, lifecycleKind: 'brief', lifecycleState },
        }
      }

      return {
        id: `evt_${event.seq}`,
        role: 'system',
        turnId: null,
        createdAt: new Date(event.ts),
        content: [{ type: 'text', text }],
        halMeta: { systemTone: 'muted' },
      }
    }

    default:
      return null
  }
}

function summarizeStandaloneInject(event: SessionEvent): {
  text: string
  tone: HalMessageMeta['systemTone']
} {
  const kind = getString(event.payload, 'kind') ?? 'runtime'
  const threads = getStringArray(event.refs, 'threads')

  switch (kind) {
    case 'primary_thread_snapshot':
      return {
        text:
          threads.length > 0
            ? `Primary thread snapshot added: ${threads.join(', ')}`
            : 'Primary thread snapshot added',
        tone: 'warning',
      }
    case 'scope_add_snapshot':
      return {
        text:
          threads.length > 0
            ? `Scope snapshot added: ${threads.join(', ')}`
            : 'Scope snapshot added',
        tone: 'warning',
      }
    case 'scope_remove':
      return {
        text: threads.length > 0 ? `Scope removed: ${threads.join(', ')}` : 'Scope updated',
        tone: 'warning',
      }
    case 'context_hint':
      return {
        text: summarizeStandaloneInjectBody(event) ?? 'Context hint added',
        tone: 'muted',
      }
    case 'system_reminder':
      return {
        text: summarizeStandaloneInjectBody(event) ?? 'System reminder added',
        tone: 'warning',
      }
    case 'subagent_runtime':
      return {
        text:
          getString(event.payload, 'label') ??
          summarizeStandaloneInjectBody(event) ??
          'Subtask update added',
        tone: getString(event.payload, 'status') === 'failed' ? 'danger' : 'muted',
      }
    case 'user_follow_up':
      return {
        text:
          getString(event.payload, 'raw_content') ??
          summarizeStandaloneInjectBody(event) ??
          'Follow-up input added',
        tone: 'warning',
      }
    default:
      return {
        text: summarizeStandaloneInjectBody(event) ?? 'Injected message added',
        tone: 'muted',
      }
  }
}

function summarizeStandaloneInjectBody(event: SessionEvent): string | null {
  const content =
    getString(event.payload, 'content') ?? getString(event.payload, 'prefixed_content') ?? ''
  const normalized = content.trim()
  if (!normalized) return null

  const [, ...rest] = normalized.split(/\n\s*\n/)
  const body = rest.join(' ').replace(/\s+/g, ' ').trim()
  if (body) return compactStandaloneText(body)

  return compactStandaloneText(normalized.replace(/\s+/g, ' '))
}

function compactStandaloneText(text: string): string {
  const normalized = text.trim()
  if (normalized.length <= 160) return normalized
  return `${normalized.slice(0, 157)}...`
}

// ---------------------------------------------------------------------------
// Turn origin
// ---------------------------------------------------------------------------

function deriveTurnOrigin(
  startedEvent: SessionEvent | undefined,
): 'interactive' | 'background_resume' {
  if (!startedEvent) return 'interactive'
  return getString(startedEvent.payload, 'origin') === 'background_resume'
    ? 'background_resume'
    : 'interactive'
}
