import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'

import { useHalRuntime } from '@/lib/use-hal-runtime'
import { useHalStore } from '@/lib/store'
import type { SessionEvent, SessionManifest } from '@/lib/types'

const { useExternalStoreRuntimeMock } = vi.hoisted(() => ({
  useExternalStoreRuntimeMock: vi.fn((input) => input),
}))

vi.mock('@assistant-ui/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@assistant-ui/react')>()
  return {
    ...actual,
    useExternalStoreRuntime: useExternalStoreRuntimeMock,
  }
})

vi.mock('@/lib/api', () => ({
  submitSessionTurn: vi.fn(),
}))

const INITIAL_STATE = useHalStore.getState()

function resetStore(): void {
  useHalStore.setState({
    ...INITIAL_STATE,
    threads: [],
    threadDetails: {},
    sessionManifests: {},
    sessionEvents: {},
    activeThreadSlug: null,
    selectedSessionId: null,
    reviewPanel: null,
    socketState: 'disconnected',
    loadingThreads: false,
    loadingThreadSlug: null,
    loadingSessionId: null,
    creatingSession: false,
    updatingScopeSessionId: null,
    mutatingArchiveSessionId: null,
    showArchived: false,
    activeThreadRequestId: 0,
    lastError: null,
  })
}

function makeManifest(input: Partial<SessionManifest> = {}): SessionManifest {
  return {
    session_id: input.session_id ?? 'session-1',
    status: input.status ?? 'active',
    title: input.title ?? null,
    created_at: input.created_at ?? '2026-03-29T09:00:00Z',
    ended_at: input.ended_at ?? null,
    channel: null,
    chat_id: null,
    primary_thread: input.primary_thread ?? 'alpha',
    mounted_threads: input.mounted_threads ?? ['alpha'],
    touched_threads: input.touched_threads ?? ['alpha'],
    turn_count: input.turn_count ?? 1,
    last_event_seq: input.last_event_seq ?? 4,
    archived_at: input.archived_at ?? null,
  }
}

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
    ts: '2026-03-29T09:00:00Z',
    session_id: 'session-1',
    turn_id: Object.prototype.hasOwnProperty.call(input, 'turnId')
      ? (input.turnId ?? null)
      : 'turn-1',
    type: input.type,
    actor: input.actor ?? 'engine',
    refs: input.refs ?? {},
    payload: input.payload ?? {},
  }
}

describe('useHalRuntime', () => {
  afterEach(() => {
    resetStore()
    useExternalStoreRuntimeMock.mockClear()
  })

  it('keeps the composer enabled while a turn is still running', () => {
    useHalStore.setState({
      sessionManifests: {
        'session-1': makeManifest(),
      },
      sessionEvents: {
        'session-1': [
          makeEvent({ seq: 1, type: 'turn.started' }),
          makeEvent({
            seq: 2,
            type: 'user.message',
            actor: 'user',
            payload: { content: 'Initial request' },
          }),
          makeEvent({
            seq: 3,
            type: 'message.injected',
            payload: {
              kind: 'turn_context',
              content: 'Turn context prepared for alpha',
            },
            refs: { mounted_threads: ['alpha'] },
          }),
        ],
      },
    })

    renderHook(() => useHalRuntime('session-1'))

    expect(useExternalStoreRuntimeMock).toHaveBeenCalledTimes(1)
    const config = useExternalStoreRuntimeMock.mock.calls[0]?.[0]
    expect(config.isDisabled).toBe(false)
    expect(config.isRunning).toBe(false)
  })

  it('refreshes the running assistant preview as soon as a follow-up is injected', () => {
    useHalStore.setState({
      sessionManifests: {
        'session-1': makeManifest(),
      },
      sessionEvents: {
        'session-1': [
          makeEvent({ seq: 1, type: 'turn.started' }),
          makeEvent({
            seq: 2,
            type: 'user.message',
            actor: 'user',
            payload: { content: 'sleep一会儿' },
          }),
          makeEvent({
            seq: 3,
            type: 'llm.response_completed',
            payload: {
              has_tool_calls: true,
              content_preview: '我先等一下，再回来继续。',
            },
          }),
          makeEvent({
            seq: 4,
            type: 'tool.call_started',
            actor: 'tool',
            payload: { tool: 'exec', args: { command: 'sleep 30' } },
          }),
        ],
      },
    })

    renderHook(() => useHalRuntime('session-1'))

    let config = useExternalStoreRuntimeMock.mock.calls.at(-1)?.[0]
    let assistantMessage = config.messages.find((message: { role: string }) => message.role === 'assistant')
    expect(assistantMessage?.halMeta.processPreview?.hintText).toBe('我先等一下，再回来继续。')

    act(() => {
      useHalStore.getState().appendSessionEvent(
        makeEvent({
          seq: 5,
          type: 'message.injected',
          actor: 'user',
          payload: {
            kind: 'user_follow_up',
            raw_content: '现在能收到吗',
            content: '现在能收到吗',
          },
        }),
      )
    })

    config = useExternalStoreRuntimeMock.mock.calls.at(-1)?.[0]
    assistantMessage = config.messages.find((message: { role: string }) => message.role === 'assistant')
    expect(assistantMessage?.halMeta.processPreview?.hintText).toBe('New input: 现在能收到吗')
  })

  it('shows an intervention in the running turn preview immediately without adding a new user bubble', () => {
    useHalStore.setState({
      sessionManifests: {
        'session-1': makeManifest(),
      },
      sessionEvents: {
        'session-1': [
          makeEvent({ seq: 1, type: 'turn.started' }),
          makeEvent({
            seq: 2,
            type: 'user.message',
            actor: 'user',
            payload: { content: '再来一次sleep' },
          }),
          makeEvent({
            seq: 3,
            type: 'llm.response_completed',
            payload: {
              has_tool_calls: true,
              content_preview: '我再 sleep 30 秒，你中途继续插话。',
            },
          }),
          makeEvent({
            seq: 4,
            type: 'tool.call_started',
            actor: 'tool',
            payload: { tool: 'exec', args: { command: 'sleep 30' } },
          }),
        ],
      },
    })

    renderHook(() => useHalRuntime('session-1'))

    act(() => {
      useHalStore.getState().addOptimisticIntervention('session-1', {
        content: '现在能看到我这条消息吗',
      })
    })

    const config = useExternalStoreRuntimeMock.mock.calls.at(-1)?.[0]
    const userMessages = config.messages.filter((message: { role: string }) => message.role === 'user')
    const assistantMessage = config.messages.find((message: { role: string }) => message.role === 'assistant')

    expect(userMessages).toHaveLength(1)
    expect(assistantMessage?.halMeta.processPreview?.hintText).toBe('New input: 现在能看到我这条消息吗')
    expect(assistantMessage?.halMeta.processPreview?.hasHumanIntervention).toBe(true)
  })

  it('shows an attachment-only intervention in the running turn preview without adding a new user bubble', () => {
    useHalStore.setState({
      sessionManifests: {
        'session-1': makeManifest(),
      },
      sessionEvents: {
        'session-1': [
          makeEvent({ seq: 1, type: 'turn.started' }),
          makeEvent({
            seq: 2,
            type: 'user.message',
            actor: 'user',
            payload: { content: '再来一次sleep' },
          }),
          makeEvent({
            seq: 3,
            type: 'llm.response_completed',
            payload: {
              has_tool_calls: true,
              content_preview: '我再 sleep 30 秒，你中途继续插话。',
            },
          }),
          makeEvent({
            seq: 4,
            type: 'tool.call_started',
            actor: 'tool',
            payload: { tool: 'exec', args: { command: 'sleep 30' } },
          }),
        ],
      },
    })

    renderHook(() => useHalRuntime('session-1'))

    act(() => {
      useHalStore.getState().addOptimisticIntervention('session-1', {
        content: '',
        attachments: [{ name: 'notes.md', type: 'document', path: '' }],
      })
    })

    const config = useExternalStoreRuntimeMock.mock.calls.at(-1)?.[0]
    const userMessages = config.messages.filter((message: { role: string }) => message.role === 'user')
    const assistantMessage = config.messages.find((message: { role: string }) => message.role === 'assistant')

    expect(userMessages).toHaveLength(1)
    expect(assistantMessage?.halMeta.processPreview?.hintText).toBe('New input: Attached 1 file')
    expect(assistantMessage?.halMeta.processPreview?.hasHumanIntervention).toBe(true)
  })
})
