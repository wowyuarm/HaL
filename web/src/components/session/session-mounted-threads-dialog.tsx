import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import type { SessionManifest, ThreadSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

const SCOPE_PAGE_SIZE = 3
const EMPTY_GOAL_FALLBACK = 'No goal yet.'

interface SessionMountedThreadsDialogProps {
  open: boolean
  session: SessionManifest | null
  threads: ThreadSummary[]
  submitting?: boolean
  onClose: () => void
  onSubmit: (input: { addThreads: string[]; removeThreads: string[] }) => Promise<void> | void
}

export function SessionMountedThreadsDialog({
  open,
  session,
  threads,
  submitting = false,
  onClose,
  onSubmit,
}: SessionMountedThreadsDialogProps) {
  const baselineMounted = useMemo(() => new Set(session?.mounted_threads ?? []), [session])
  const [mountedThreads, setMountedThreads] = useState<Set<string>>(new Set())
  const [page, setPage] = useState(0)

  useEffect(() => {
    if (!open) return
    setMountedThreads(new Set(session?.mounted_threads ?? []))
    setPage(0)
  }, [open, session])

  if (!open || !session) return null

  const primaryThread = session.primary_thread
  const candidateThreads = threads.filter((thread) => thread.slug !== primaryThread)
  const totalPages = Math.max(1, Math.ceil(candidateThreads.length / SCOPE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pageStart = currentPage * SCOPE_PAGE_SIZE
  const visibleThreads = candidateThreads.slice(pageStart, pageStart + SCOPE_PAGE_SIZE)
  const hasChanges =
    [...mountedThreads].some((slug) => !baselineMounted.has(slug)) ||
    [...baselineMounted].some((slug) => !mountedThreads.has(slug))
  const primaryThreadSummary = primaryThread
    ? threads.find((thread) => thread.slug === primaryThread) ?? null
    : null

  const handleSubmit = async () => {
    const nextMounted = new Set(mountedThreads)
    if (primaryThread) nextMounted.add(primaryThread)

    const addThreads = [...nextMounted].filter((slug) => !baselineMounted.has(slug)).sort()
    const removeThreads = [...baselineMounted].filter((slug) => !nextMounted.has(slug)).sort()
    await onSubmit({ addThreads, removeThreads })
  }

  return (
    <div className="bg-hal-canvas/80 fixed inset-0 z-50 flex items-center justify-center px-4 backdrop-blur-sm">
      <div className="w-full max-w-[36rem] rounded-xl border border-border bg-hal-panel shadow-popover">
        <header className="border-b border-subtle px-4 py-3.5">
          <h2 className="text-subheading text-hal-primary">Scope</h2>
        </header>

        <div className="max-h-[70vh] overflow-y-auto px-4 py-3">
          <div className="rounded-lg border border-subtle bg-hal-canvas/55 px-3 py-2.5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-caption font-medium uppercase tracking-[0.16em] text-hal-muted">
                  Main
                </p>
                <p className="mt-1 truncate text-body font-medium text-hal-primary">
                  {primaryThreadSummary?.name ?? primaryThread ?? 'No primary thread'}
                </p>
                {primaryThread ? (
                  <p className="mt-1 font-mono text-caption text-hal-muted">{primaryThread}</p>
                ) : null}
              </div>
              <span className="rounded-sm border border-subtle px-2 py-0.5 font-mono text-caption text-hal-muted">
                fixed
              </span>
            </div>
            <p className="mt-2 truncate text-caption text-hal-muted">
              {primaryThreadSummary?.description || 'The main thread stays in scope for this session.'}
            </p>
          </div>

          <div className="mt-3.5 flex items-center justify-between gap-3">
            <div>
              <p className="text-caption font-medium uppercase tracking-[0.16em] text-hal-muted">
                Support
              </p>
              <p className="mt-1 text-caption text-hal-muted">
                {candidateThreads.length > 0 ? `page ${currentPage + 1} / ${totalPages}` : 'No threads'}
              </p>
            </div>
            {candidateThreads.length > SCOPE_PAGE_SIZE ? (
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((currentValue) => Math.max(0, currentValue - 1))}
                  disabled={currentPage === 0}
                  className="h-7.5 border border-subtle px-2.5"
                >
                  Prev
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    setPage((currentValue) => Math.min(totalPages - 1, currentValue + 1))
                  }
                  disabled={currentPage >= totalPages - 1}
                  className="h-7.5 border border-subtle px-2.5"
                >
                  Next
                </Button>
              </div>
            ) : null}
          </div>

          <div className="mt-2 space-y-1.5">
            {visibleThreads.length === 0 ? (
              <div className="rounded-lg border border-subtle bg-hal-canvas/45 px-4 py-4 text-center text-caption text-hal-muted">
                No supporting threads available.
              </div>
            ) : (
              visibleThreads.map((thread) => {
                const checked = mountedThreads.has(thread.slug)
                return (
                  <button
                    key={thread.slug}
                    type="button"
                    onClick={() => {
                      setMountedThreads((current) => {
                        const next = new Set(current)
                        if (checked) {
                          next.delete(thread.slug)
                        } else {
                          next.add(thread.slug)
                        }
                        if (primaryThread) next.add(primaryThread)
                        return next
                      })
                    }}
                    className={cn(
                      'w-full rounded-lg border border-subtle px-3 py-2.5 text-left transition-colors duration-fast ease-standard',
                      checked
                        ? 'border-accent bg-hal-selection/70'
                        : 'bg-transparent hover:bg-hal-hover',
                      checked ? 'border-l-2 border-l-accent' : 'border-l-2 border-l-transparent',
                    )}
                    aria-pressed={checked}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-body font-medium text-hal-primary">
                          {thread.name}
                        </p>
                        <p className="mt-1 font-mono text-caption text-hal-muted">
                          {thread.slug}
                        </p>
                        <p className="mt-1.5 truncate text-caption text-hal-muted">
                          {thread.description || EMPTY_GOAL_FALLBACK}
                        </p>
                      </div>
                      <span
                        className={cn(
                          'mt-0.5 shrink-0 font-mono text-caption',
                          checked
                            ? 'text-accent'
                            : 'text-hal-muted',
                        )}
                      >
                        {checked ? 'Remove' : 'Add'}
                      </span>
                    </div>
                  </button>
                )
              })
            )}
          </div>
        </div>

        <footer className="border-t border-subtle px-4 py-3.5">
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={onClose}
              disabled={submitting}
              className="h-8 w-full"
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void handleSubmit()}
              disabled={submitting || !hasChanges}
              className="h-8 w-full"
            >
              {submitting ? 'Scoping...' : 'Scope'}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  )
}
