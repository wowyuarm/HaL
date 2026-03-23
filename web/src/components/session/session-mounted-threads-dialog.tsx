import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import type { SessionManifest, ThreadSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

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

  useEffect(() => {
    if (!open) return
    setMountedThreads(new Set(session?.mounted_threads ?? []))
  }, [open, session])

  if (!open || !session) return null

  const primaryThread = session.primary_thread

  const handleSubmit = async () => {
    const nextMounted = new Set(mountedThreads)
    if (primaryThread) nextMounted.add(primaryThread)

    const addThreads = [...nextMounted].filter((slug) => !baselineMounted.has(slug)).sort()
    const removeThreads = [...baselineMounted].filter((slug) => !nextMounted.has(slug)).sort()
    await onSubmit({ addThreads, removeThreads })
  }

  return (
    <div className="bg-hal-canvas/80 fixed inset-0 z-50 flex items-center justify-center px-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-xl border border-border bg-hal-panel shadow-popover">
        <header className="border-b border-border px-5 py-4">
          <h2 className="text-subheading text-hal-primary">Edit Session Scope</h2>
          <p className="mt-1 text-body text-hal-muted">
            Adjust which thread briefs are explicitly mounted into this live session.
          </p>
        </header>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          <div className="mb-4 rounded-lg border border-border bg-hal-float p-4 text-body text-hal-muted">
            <p className="text-xs font-medium uppercase tracking-widest text-hal-primary">
              Primary Thread
            </p>
            <p className="mt-2">
              {primaryThread
                ? `${primaryThread} stays mounted and remains the default landing place for briefing.`
                : 'This session has no primary thread, so you can freely adjust the mounted set.'}
            </p>
          </div>

          <div className="space-y-2">
            {threads.map((thread) => {
              const checked = mountedThreads.has(thread.slug)
              const isPrimary = thread.slug === primaryThread
              return (
                <label
                  key={thread.slug}
                  className={cn(
                    'flex cursor-pointer items-start gap-4 rounded-lg border px-4 py-3 transition-colors duration-fast ease-standard',
                    checked
                      ? 'border-accent bg-accent-subtle'
                      : 'border-border bg-hal-canvas hover:bg-hal-hover',
                  )}
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={checked || isPrimary}
                    disabled={isPrimary}
                    onChange={(event) => {
                      setMountedThreads((current) => {
                        const next = new Set(current)
                        if (event.target.checked) {
                          next.add(thread.slug)
                        } else {
                          next.delete(thread.slug)
                        }
                        if (primaryThread) next.add(primaryThread)
                        return next
                      })
                    }}
                  />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-body font-medium text-hal-primary">
                          {thread.name}
                        </p>
                        <p className="mt-1 text-xs text-hal-muted">
                          {thread.description || 'No description.'}
                        </p>
                      </div>
                      <span className="rounded-sm border border-border bg-hal-panel px-2 py-0.5 font-mono text-caption text-hal-muted">
                        {thread.scope || 'thread'}
                      </span>
                    </div>

                    <div className="mt-3 flex items-center justify-between gap-3 text-xs">
                      <span className="font-mono text-hal-muted">{thread.slug}</span>
                      {isPrimary ? (
                        <span className="rounded-sm bg-accent-subtle px-2 py-0.5 font-mono font-medium text-accent">
                          primary
                        </span>
                      ) : (
                        <span className="font-mono text-hal-muted">
                          {checked ? 'mounted' : 'not mounted'}
                        </span>
                      )}
                    </div>
                  </div>
                </label>
              )
            })}
          </div>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-border px-5 py-4">
          <div className="text-xs text-hal-muted">
            Scope updates emit durable events and apply to the next turn's fresh context
            compilation.
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={submitting}
              className="rounded-md bg-accent px-3 py-1.5 font-mono text-body font-medium text-white transition-colors duration-fast ease-standard hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Applying...' : 'Apply Scope'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
