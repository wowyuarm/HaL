import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { SessionMountedThreadsDialog } from '@/components/session/session-mounted-threads-dialog'
import type { SessionManifest, ThreadSummary } from '@/lib/types'

function makeSession(input?: Partial<SessionManifest>): SessionManifest {
  return {
    session_id: 'session-1',
    status: 'active',
    title: 'Session 1',
    created_at: '2026-03-29T09:00:00Z',
    ended_at: null,
    channel: null,
    chat_id: null,
    primary_thread: 'alpha',
    mounted_threads: ['alpha', 'beta'],
    touched_threads: ['alpha'],
    turn_count: 2,
    last_event_seq: 4,
    archived_at: null,
    ...input,
  }
}

function makeThread(slug: string, description = `${slug} desc`): ThreadSummary {
  return {
    slug,
    name: slug,
    status: 'active',
    scope: 'thread',
    description,
    updated_at: '2026-03-29T09:00:00Z',
    session_counts: { active: 1 },
  }
}

const THREADS = [
  makeThread('alpha', 'alpha desc'),
  makeThread('beta', 'beta desc'),
  makeThread('gamma', 'gamma desc'),
  makeThread('delta', 'delta desc'),
  makeThread('epsilon', 'epsilon desc'),
]

describe('SessionMountedThreadsDialog', () => {
  it('submits added and removed support threads while keeping the main thread fixed', async () => {
    const onSubmit = vi.fn()

    render(
      <SessionMountedThreadsDialog
        open
        session={makeSession()}
        threads={THREADS}
        onClose={() => {}}
        onSubmit={onSubmit}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /beta/i }))
    fireEvent.click(screen.getByRole('button', { name: /gamma/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Scope' }))

    expect(onSubmit).toHaveBeenCalledWith({
      addThreads: ['gamma'],
      removeThreads: ['beta'],
    })
  })

  it('resets the current page and mounted selections when reopened for another session', () => {
    const { rerender } = render(
      <SessionMountedThreadsDialog
        open
        session={makeSession()}
        threads={THREADS}
        onClose={() => {}}
        onSubmit={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByRole('button', { name: /epsilon/i })).toBeInTheDocument()

    rerender(
      <SessionMountedThreadsDialog
        open={false}
        session={makeSession()}
        threads={THREADS}
        onClose={() => {}}
        onSubmit={() => {}}
      />,
    )

    rerender(
      <SessionMountedThreadsDialog
        open
        session={makeSession({
          session_id: 'session-2',
          mounted_threads: ['alpha', 'delta'],
        })}
        threads={THREADS}
        onClose={() => {}}
        onSubmit={() => {}}
      />,
    )

    expect(screen.queryByRole('button', { name: /epsilon/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delta/i })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /beta/i })).toHaveAttribute('aria-pressed', 'false')
  })
})
