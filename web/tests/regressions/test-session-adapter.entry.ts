import assert from 'node:assert/strict'

import { convertSessionEvents } from '../../src/lib/session-adapter'
import type { SessionEvent } from '../../src/lib/types'

const SESSION_ID = 'session-adapter'
const TURN_ID = 'turn-1'
const BASE_TS = '2026-03-29T09:00:00Z'

function makeEvent(input: {
  seq: number
  type: string
  turnId?: string | null
  actor?: SessionEvent['actor']
  payload?: SessionEvent['payload']
  refs?: SessionEvent['refs']
}): SessionEvent {
  return {
    v: 1,
    seq: input.seq,
    ts: BASE_TS,
    session_id: SESSION_ID,
    turn_id: Object.prototype.hasOwnProperty.call(input, 'turnId')
      ? (input.turnId ?? null)
      : TURN_ID,
    type: input.type,
    actor: input.actor ?? 'engine',
    refs: input.refs ?? {},
    payload: input.payload ?? {},
  }
}

function runTest(name: string, fn: () => void): void {
  try {
    fn()
    console.log(`PASS ${name}`)
  } catch (error) {
    console.error(`FAIL ${name}`)
    throw error
  }
}

runTest('maps user attachments and preserves background resume origin', () => {
  const messages = convertSessionEvents([
    makeEvent({
      seq: 1,
      type: 'turn.started',
      payload: { origin: 'background_resume' },
    }),
    makeEvent({
      seq: 2,
      type: 'user.message',
      actor: 'user',
      payload: {
        content: 'resume this',
        attachments: [
          {
            type: 'image',
            name: 'diagram.png',
            contentType: 'image/png',
            content: [
              { type: 'image', image: 'data:image/png;base64,abc', filename: 'diagram.png' },
            ],
          },
          {
            type: 'file',
            name: 'notes.txt',
            content: [
              { type: 'file', mimeType: 'text/plain', data: 'hello', filename: 'notes.txt' },
            ],
          },
        ],
      },
    }),
    makeEvent({
      seq: 3,
      type: 'assistant.message_completed',
      payload: { content: 'done' },
    }),
    makeEvent({
      seq: 4,
      type: 'turn.completed',
    }),
  ])

  assert.equal(messages.length, 2)
  assert.equal(messages[0]?.role, 'user')
  assert.equal(messages[0]?.halMeta.origin, 'background_resume')
  assert.equal(messages[0]?.attachments?.length, 2)
  assert.deepEqual(
    messages[0]?.attachments?.map((item) => item.type),
    ['image', 'file'],
  )
  assert.equal(messages[1]?.role, 'assistant')
  assert.equal(messages[1]?.halMeta.origin, 'background_resume')
  assert.deepEqual(messages[1]?.status, { type: 'complete', reason: 'stop' })
})

runTest('failed turns without assistant output still surface an assistant error message', () => {
  const messages = convertSessionEvents([
    makeEvent({
      seq: 1,
      type: 'turn.started',
    }),
    makeEvent({
      seq: 2,
      type: 'user.message',
      actor: 'user',
      payload: { content: 'hello' },
    }),
    makeEvent({
      seq: 3,
      type: 'turn.failed',
      payload: { error: 'Tool crashed' },
    }),
  ])

  assert.equal(messages.length, 2)
  assert.equal(messages[1]?.role, 'assistant')
  assert.equal(messages[1]?.content[0]?.type, 'text')
  assert.equal(messages[1]?.content[0]?.text, 'Tool crashed')
  assert.deepEqual(messages[1]?.status, {
    type: 'incomplete',
    reason: 'error',
    error: 'Tool crashed',
  })
  assert.equal(messages[1]?.halMeta.turnState, 'failed')
})

runTest('brief lifecycle status changes become assistant command messages', () => {
  const messages = convertSessionEvents([
    makeEvent({
      seq: 1,
      turnId: null,
      type: 'status.changed',
      payload: {
        kind: 'session_brief_start',
        status: 'briefing',
        message: 'Brief started.',
      },
    }),
    makeEvent({
      seq: 2,
      turnId: null,
      type: 'status.changed',
      payload: {
        kind: 'session_brief_failed',
        status: 'active',
        message: 'Brief failed.',
      },
    }),
  ])

  assert.equal(messages.length, 2)
  assert.equal(messages[0]?.role, 'assistant')
  assert.equal(messages[0]?.halMeta.isCommand, true)
  assert.equal(messages[0]?.halMeta.lifecycleKind, 'brief')
  assert.equal(messages[0]?.halMeta.lifecycleState, 'start')
  assert.deepEqual(messages[0]?.status, { type: 'complete', reason: 'stop' })

  assert.equal(messages[1]?.role, 'assistant')
  assert.equal(messages[1]?.halMeta.lifecycleState, 'failed')
  assert.deepEqual(messages[1]?.status, {
    type: 'incomplete',
    reason: 'error',
    error: 'Brief failed.',
  })
})

runTest('scope updates summarize added and removed threads', () => {
  const messages = convertSessionEvents([
    makeEvent({
      seq: 1,
      turnId: null,
      type: 'session.scope_updated',
      payload: {
        added_threads: ['memory-bank'],
        removed_threads: ['research-notes'],
      },
    }),
  ])

  assert.equal(messages.length, 1)
  assert.equal(messages[0]?.role, 'system')
  assert.equal(messages[0]?.content[0]?.type, 'text')
  assert.equal(messages[0]?.content[0]?.text, 'Scope updated: +memory-bank / \u2212research-notes')
})

runTest('session compact events become standalone system rows', () => {
  const messages = convertSessionEvents([
    makeEvent({
      seq: 1,
      turnId: null,
      type: 'session.compacted',
      payload: {
        before_tokens: 12345,
        after_tokens: 678,
        before_request_bytes: 900000,
        after_request_bytes: 72000,
        passes: 1,
      },
    }),
    makeEvent({
      seq: 2,
      turnId: null,
      type: 'session.compaction_failed',
      payload: {
        error: 'api unavailable',
      },
    }),
  ])

  assert.equal(messages.length, 2)
  assert.equal(messages[0]?.role, 'system')
  assert.equal(messages[0]?.halMeta.systemTone, 'muted')
  assert.equal(messages[0]?.content[0]?.type, 'text')
  assert.equal(
    messages[0]?.content[0]?.text,
    'Session compacted · tokens 12,345 -> 678 · bytes 900,000 -> 72,000 · 1 pass',
  )

  assert.equal(messages[1]?.role, 'system')
  assert.equal(messages[1]?.halMeta.systemTone, 'danger')
  assert.equal(messages[1]?.content[0]?.type, 'text')
  assert.equal(
    messages[1]?.content[0]?.text,
    'Session compact failed · history unchanged · api unavailable',
  )
})
