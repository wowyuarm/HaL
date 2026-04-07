import { Plus, X } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface WorkspaceTabView {
  id: string
  title: string
  active: boolean
}

interface WorkspaceTabsProps {
  tabs: WorkspaceTabView[]
  onAdd: () => void
  onActivate: (tabId: string) => void
  onClose: (tabId: string) => void
}

export function WorkspaceTabs({ tabs, onAdd, onActivate, onClose }: WorkspaceTabsProps) {
  return (
    <div className="relative z-10 border-b border-subtle bg-hal-veil/90 backdrop-blur-sm">
      <div className="flex items-center gap-1 px-3 py-2 md:px-4">
        <button
          type="button"
          onClick={onAdd}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-subtle text-hal-muted transition-colors hover:border-border hover:text-hal-primary"
          aria-label="Add workspace tab"
        >
          <Plus className="h-4 w-4" />
        </button>

        <div role="tablist" aria-label="Workspace tabs" className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={cn(
                'group flex min-w-[8.5rem] max-w-[14rem] items-stretch overflow-hidden rounded-md border transition-colors',
                tab.active
                  ? 'border-accent bg-hal-paper text-hal-primary'
                  : 'border-subtle bg-transparent text-hal-muted hover:border-border hover:text-hal-primary',
              )}
            >
              <button
                type="button"
                role="tab"
                aria-selected={tab.active}
                onClick={() => onActivate(tab.id)}
                className="min-w-0 flex-1 border-l-2 border-l-transparent px-3 py-1.5 text-left"
              >
                <span
                  className={cn(
                    'block truncate font-mono text-meta',
                    tab.active && 'text-hal-primary',
                  )}
                >
                  {tab.title}
                </span>
              </button>

              <button
                type="button"
                onClick={() => onClose(tab.id)}
                className="flex h-auto w-8 shrink-0 items-center justify-center border-l border-subtle/80 text-hal-muted transition-colors hover:text-hal-primary"
                aria-label={`Close ${tab.title} tab`}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
