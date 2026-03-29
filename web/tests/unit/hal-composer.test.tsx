import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { HalComposer } from '@/components/conversation/hal-composer'
import { useHalStore } from '@/lib/store'

vi.mock('@/lib/api', () => ({
  submitSessionTurn: vi.fn(),
}))

const { submitSessionTurn } = await import('@/lib/api')

const INITIAL_STATE = useHalStore.getState()

function resetStore(): void {
  useHalStore.setState({
    ...INITIAL_STATE,
    lastError: null,
  })
}

function makeSessionManifest(status: 'active' | 'briefing' = 'active') {
  return {
    session_id: 'session-1',
    status,
    title: null,
    created_at: '2026-03-29T09:00:00Z',
    ended_at: null,
    channel: null,
    chat_id: null,
    primary_thread: 'alpha',
    mounted_threads: ['alpha'],
    touched_threads: ['alpha'],
    turn_count: 1,
    last_event_seq: 3,
  } as const
}

describe('HalComposer', () => {
  afterEach(() => {
    resetStore()
    vi.clearAllMocks()
  })

  it('clears the draft immediately and keeps the composer usable while the request is still in flight', async () => {
    let resolveSubmission: ((value: Awaited<ReturnType<typeof submitSessionTurn>>) => void) | null =
      null
    vi.mocked(submitSessionTurn).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSubmission = resolve
        }),
    )

    render(<HalComposer sessionId="session-1" socketState="live" />)

    const textarea = screen.getByPlaceholderText('Continue collaborating...')
    fireEvent.change(textarea, { target: { value: 'Follow up while still running' } })

    const sendButton = screen.getByRole('button', { name: 'Send message' })
    expect(sendButton).toBeEnabled()

    fireEvent.click(sendButton)

    await waitFor(() =>
      expect(submitSessionTurn).toHaveBeenCalledWith('session-1', {
        content: 'Follow up while still running',
        attachments: [],
      }),
    )
    expect(textarea).toHaveValue('')
    expect(textarea).toBeEnabled()

    fireEvent.change(textarea, { target: { value: 'Second intervention' } })
    expect(textarea).toHaveValue('Second intervention')

    resolveSubmission?.({
      session: {
        session_id: 'session-1',
        status: 'active',
        title: null,
        created_at: '2026-03-29T09:00:00Z',
        ended_at: null,
        channel: null,
        chat_id: null,
        primary_thread: 'alpha',
        mounted_threads: ['alpha'],
        touched_threads: ['alpha'],
        turn_count: 1,
        last_event_seq: 3,
      },
      delivery: 'intervention_queued',
    })
  })

  it('keeps IME draft text stable during composition before committing it', async () => {
    render(<HalComposer sessionId="session-1" socketState="live" />)

    const textarea = screen.getByPlaceholderText('Continue collaborating...')
    fireEvent.compositionStart(textarea)
    fireEvent.change(textarea, { target: { value: 'w' } })
    expect(textarea).toHaveValue('w')

    fireEvent.change(textarea, { target: { value: 'ww' } })
    expect(textarea).toHaveValue('ww')

    fireEvent.compositionEnd(textarea, { data: '我', target: { value: '我' } })

    await waitFor(() => expect(textarea).toHaveValue('我'))
  })

  it('disables the composer while a session is briefing', () => {
    useHalStore.setState({
      sessionManifests: {
        'session-1': makeSessionManifest('briefing'),
      },
    })

    render(<HalComposer sessionId="session-1" socketState="live" />)

    expect(screen.getByPlaceholderText('Continue collaborating...')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Add attachment' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('keeps the file picker open to arbitrary attachments', () => {
    const { container } = render(<HalComposer sessionId="session-1" socketState="live" />)

    const fileInput = container.querySelector('input[type="file"]')
    expect(fileInput).not.toBeNull()
    expect(fileInput?.getAttribute('accept')).toBeNull()
  })

  it('grows the writing area before switching to internal scroll', () => {
    render(<HalComposer sessionId="session-1" socketState="live" />)

    const textarea = screen.getByPlaceholderText('Continue collaborating...') as HTMLTextAreaElement
    Object.defineProperty(textarea, 'scrollHeight', {
      configurable: true,
      value: 96,
    })

    fireEvent.change(textarea, { target: { value: 'Line 1\nLine 2\nLine 3\nLine 4' } })

    expect(textarea.style.height).toBe('96px')
    expect(textarea.style.overflowY).toBe('hidden')
  })

  it('caps the writing area height and enables scrolling once it reaches the limit', () => {
    render(<HalComposer sessionId="session-1" socketState="live" />)

    const textarea = screen.getByPlaceholderText('Continue collaborating...') as HTMLTextAreaElement
    Object.defineProperty(textarea, 'scrollHeight', {
      configurable: true,
      value: 192,
    })

    fireEvent.change(textarea, { target: { value: 'Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8' } })

    expect(textarea.style.height).toBe('128px')
    expect(textarea.style.overflowY).toBe('auto')
  })
})
