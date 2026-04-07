import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import { WorkspaceTabs } from '@/components/layout/workspace-tabs'

describe('WorkspaceTabs', () => {
  it('renders thread tabs and marks the active tab', () => {
    render(
      <WorkspaceTabs
        tabs={[
          { id: 'tab-1', title: 'alpha', active: true },
          { id: 'tab-2', title: 'beta', active: false },
        ]}
        onAdd={() => {}}
        onActivate={() => {}}
        onClose={() => {}}
      />,
    )

    expect(screen.getByRole('tab', { name: 'alpha' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'beta' })).toHaveAttribute('aria-selected', 'false')
  })

  it('activates and closes tabs through callbacks', () => {
    const onActivate = vi.fn()
    const onClose = vi.fn()

    render(
      <WorkspaceTabs
        tabs={[
          { id: 'tab-1', title: 'alpha', active: true },
          { id: 'tab-2', title: 'beta', active: false },
        ]}
        onAdd={() => {}}
        onActivate={onActivate}
        onClose={onClose}
      />,
    )

    fireEvent.click(screen.getByRole('tab', { name: 'beta' }))
    expect(onActivate).toHaveBeenCalledWith('tab-2')

    fireEvent.click(screen.getByRole('button', { name: 'Close beta tab' }))
    expect(onClose).toHaveBeenCalledWith('tab-2')
  })
})
