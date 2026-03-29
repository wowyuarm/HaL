import assert from 'node:assert/strict'

import { buildTurnProcessView } from '../../src/lib/process'
import type { SessionEvent } from '../../src/lib/types'

const SESSION_ID = 'session-process-follow-up'
const TURN_ID = 'turn-1'
const BASE_TS = '2026-03-29T09:00:00Z'

function makeEvent(input: {
  seq: number
  type: string
  actor?: SessionEvent['actor']
  payload?: SessionEvent['payload']
  refs?: SessionEvent['refs']
}): SessionEvent {
  return {
    v: 1,
    seq: input.seq,
    ts: BASE_TS,
    session_id: SESSION_ID,
    turn_id: TURN_ID,
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

runTest('user follow-up notes carry human-authored tone and highlight the running preview', () => {
  const view = buildTurnProcessView(
    [
      makeEvent({
        seq: 1,
        type: 'llm.response_completed',
        payload: {
          has_tool_calls: true,
          content_preview: 'Checking the files before replying.',
        },
      }),
      makeEvent({
        seq: 2,
        type: 'tool.call_started',
        actor: 'tool',
        payload: { tool: 'fs', args: { action: 'read', path: '/tmp/notes.md' } },
      }),
      makeEvent({
        seq: 3,
        type: 'message.injected',
        actor: 'user',
        payload: {
          kind: 'user_follow_up',
          raw_content: 'Also cover the edge cases.',
          content: 'Also cover the edge cases.',
        },
      }),
    ],
    'running',
  )

  const followUpNote = view.entries.find(
    (entry) => entry.kind === 'note' && entry.note.label === 'input',
  )

  assert.ok(followUpNote && followUpNote.kind === 'note')
  assert.equal(followUpNote.note.tone, 'human-authored')
  assert.equal(followUpNote.note.detail, 'Also cover the edge cases.')
  assert.equal(view.preview.hasHumanIntervention, true)
  assert.equal(view.preview.hintText, 'New input: Also cover the edge cases.')
})

runTest('attachment-only follow-up notes still show up as human input immediately', () => {
  const view = buildTurnProcessView(
    [
      makeEvent({
        seq: 1,
        type: 'llm.response_completed',
        payload: {
          has_tool_calls: true,
          content_preview: 'Checking the files before replying.',
        },
      }),
      makeEvent({
        seq: 2,
        type: 'tool.call_started',
        actor: 'tool',
        payload: { tool: 'fs', args: { action: 'read', path: '/tmp/notes.md' } },
      }),
      makeEvent({
        seq: 3,
        type: 'message.injected',
        actor: 'user',
        payload: {
          kind: 'user_follow_up',
          raw_content: '',
          content: '',
          attachments: [
            {
              type: 'document',
              name: 'notes.md',
              path: 'data/media/received/session-1/notes.md',
            },
          ],
        },
      }),
    ],
    'running',
  )

  const followUpNote = view.entries.find(
    (entry) => entry.kind === 'note' && entry.note.label === 'input',
  )

  assert.ok(followUpNote && followUpNote.kind === 'note')
  assert.equal(followUpNote.note.tone, 'human-authored')
  assert.equal(followUpNote.note.detail, 'Attached 1 file')
  assert.deepEqual(followUpNote.note.items, ['notes.md · data/media/received/session-1/notes.md'])
  assert.equal(view.preview.hasHumanIntervention, true)
  assert.equal(view.preview.hintText, 'New input: Attached 1 file')
})
