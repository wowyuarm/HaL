import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { SessionList } from '@/components/session/session-list'
import type { SessionManifest } from '@/lib/types'

function makeSession(input: Partial<SessionManifest>): SessionManifest {
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
    turn_count: input.turn_count ?? 2,
    last_event_seq: input.last_event_seq ?? 4,
    archived_at: input.archived_at ?? null,
  }
}

describe('SessionList', () => {
  it('auto-expands the selected dropped group', () => {
    render(
      <SessionList
        currentThreadSlug="alpha"
        sessions={[
          makeSession({ session_id: 'active-1', status: 'active', title: 'Active run' }),
          makeSession({ session_id: 'dropped-1', status: 'dropped', title: 'Dropped run' }),
        ]}
        selectedSessionId="dropped-1"
        showArchived={false}
        onSelect={() => {}}
        onCreate={() => {}}
        onToggleShowArchived={() => {}}
        onUpdateSessionTitle={() => true}
        onEndSession={() => true}
        onArchiveSession={() => true}
        onRestoreSession={() => true}
        onPreviewEpisode={() => {}}
      />,
    )

    expect(screen.getByRole('button', { name: /dropped 1/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByRole('button', { name: /dropped run/i })).toBeInTheDocument()
  })

  it('normalizes mixed-script spacing before saving an edited title', async () => {
    const onUpdateSessionTitle = vi.fn().mockResolvedValue(true)

    render(
      <SessionList
        currentThreadSlug="alpha"
        sessions={[makeSession({ session_id: 'active-1', status: 'active', title: 'Old title' })]}
        selectedSessionId={null}
        showArchived={false}
        onSelect={() => {}}
        onCreate={() => {}}
        onToggleShowArchived={() => {}}
        onUpdateSessionTitle={onUpdateSessionTitle}
        onEndSession={() => true}
        onArchiveSession={() => true}
        onRestoreSession={() => true}
        onPreviewEpisode={() => {}}
      />,
    )

    fireEvent.pointerDown(screen.getByRole('button', { name: 'Session actions' }), {
      button: 0,
      ctrlKey: false,
    })
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Edit name' }))

    const input = screen.getByPlaceholderText('Untitled session')
    fireEvent.change(input, { target: { value: '  规划v2阶段3  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() =>
      expect(onUpdateSessionTitle).toHaveBeenCalledWith('active-1', {
        title: '规划 v2 阶段 3',
      }),
    )
    expect(screen.queryByPlaceholderText('Untitled session')).not.toBeInTheDocument()
  })
})
