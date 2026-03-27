import assert from 'node:assert/strict'

import { buildTurnProcessView } from '../src/lib/process'
import type { SessionEvent } from '../src/lib/types'

const SESSION_ID = 'session-process-preview'
const TURN_ID = 'turn-1'
const BASE_TS = '2026-03-27T09:00:00Z'

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

function buildSampleEvents(): SessionEvent[] {
  return [
    makeEvent({
      seq: 1,
      type: 'context.compiled',
      payload: { search_results: 1 },
      refs: { mounted_threads: ['shared-reading'], recalled_threads: ['memory-bank'] },
    }),
    makeEvent({
      seq: 2,
      type: 'llm.response_completed',
      payload: {
        has_tool_calls: true,
        content_preview: 'I am checking source background before writing the answer.',
      },
    }),
    makeEvent({
      seq: 3,
      type: 'tool.call_started',
      actor: 'tool',
      payload: { tool: 'web_search', args: { query: 'Anthropic ARR February 2026' } },
    }),
    makeEvent({
      seq: 4,
      type: 'tool.call_completed',
      actor: 'tool',
      payload: { tool: 'web_search', args: { query: 'Anthropic ARR February 2026' } },
    }),
    makeEvent({
      seq: 5,
      type: 'tool.call_started',
      actor: 'tool',
      payload: { tool: 'web_search', args: { query: 'MiniMax valuation public market' } },
    }),
    makeEvent({
      seq: 6,
      type: 'tool.call_completed',
      actor: 'tool',
      payload: { tool: 'web_search', args: { query: 'MiniMax valuation public market' } },
    }),
    makeEvent({
      seq: 7,
      type: 'tool.call_started',
      actor: 'tool',
      payload: { tool: 'web_fetch', args: { url: 'https://x.com/example/status/123' } },
    }),
    makeEvent({
      seq: 8,
      type: 'tool.call_completed',
      actor: 'tool',
      payload: { tool: 'web_fetch', args: { url: 'https://x.com/example/status/123' } },
    }),
    makeEvent({
      seq: 9,
      type: 'tool.call_started',
      actor: 'tool',
      payload: { tool: 'fs', args: { action: 'read', path: '/tmp/BRIEF.md' } },
    }),
    makeEvent({
      seq: 10,
      type: 'tool.call_completed',
      actor: 'tool',
      payload: { tool: 'fs', args: { action: 'read', path: '/tmp/BRIEF.md' } },
    }),
  ]
}

runTest('running preview separates hint from accumulated counts', () => {
  const preview = buildTurnProcessView(buildSampleEvents(), 'running').preview as {
    hintText?: string | null
    countSummaryText?: string | null
  }

  assert.equal(preview.hintText, 'I am checking source background before writing the answer.')
  assert.equal(preview.countSummaryText, '2 searches · 1 fetch · 1 read')
})

runTest('completed preview keeps final counts and removes hint', () => {
  const events = [
    ...buildSampleEvents(),
    makeEvent({
      seq: 11,
      type: 'assistant.message_completed',
      payload: { content: 'Answer ready.' },
    }),
    makeEvent({
      seq: 12,
      type: 'turn.completed',
      payload: {},
    }),
  ]
  const preview = buildTurnProcessView(events, 'completed').preview as {
    hintText?: string | null
    countSummaryText?: string | null
    summaryText?: string | null
  }

  assert.equal(preview.hintText ?? null, null)
  assert.equal(preview.countSummaryText, '2 searches · 1 fetch · 1 read')
  assert.equal(preview.summaryText, '2 searches · 1 fetch · 1 read')
})

runTest('recall count only comes from explicit recall tool calls', () => {
  const events = [
    ...buildSampleEvents(),
    makeEvent({
      seq: 11,
      type: 'tool.call_started',
      actor: 'tool',
      payload: { tool: 'recall', args: { query: 'source background' } },
    }),
    makeEvent({
      seq: 12,
      type: 'tool.call_completed',
      actor: 'tool',
      payload: { tool: 'recall', args: { query: 'source background' } },
    }),
  ]
  const preview = buildTurnProcessView(events, 'running').preview as {
    countSummaryText?: string | null
  }

  assert.equal(preview.countSummaryText, '2 searches · 1 fetch · 1 recall · 1 read')
})

runTest('direct reply uses the direct-response fallback copy', () => {
  const events = [
    makeEvent({
      seq: 0,
      type: 'context.compiled',
      payload: { search_results: 3 },
      refs: { primary_thread: 'research-incubator', mounted_threads: ['research-incubator'] },
    }),
    makeEvent({
      seq: 1,
      type: 'message.injected',
      payload: {
        kind: 'turn_context',
        source: 'engine',
        content: 'Turn context prepared for research-incubator',
      },
      refs: { primary_thread: 'research-incubator', mounted_threads: ['research-incubator'] },
    }),
    makeEvent({
      seq: 2,
      type: 'llm.response_completed',
      payload: { has_tool_calls: false, content_preview: 'This is a direct answer.' },
    }),
    makeEvent({
      seq: 3,
      type: 'assistant.message_completed',
      payload: { content: 'This is a direct answer.' },
    }),
    makeEvent({
      seq: 4,
      type: 'turn.completed',
      payload: {},
    }),
  ]
  const preview = buildTurnProcessView(events, 'completed').preview

  assert.equal(preview.hintText, null)
  assert.equal(preview.countSummaryText, null)
  assert.equal(preview.summaryText, 'replied directly')
})
