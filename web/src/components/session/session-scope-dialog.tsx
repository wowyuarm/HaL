import { useEffect, useState } from "react";

import type { ThreadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SessionScopeDialogProps {
  open: boolean;
  threads: ThreadSummary[];
  initialPrimarySlug: string | null;
  creating?: boolean;
  onClose: () => void;
  onSubmit: (input: { primaryThread: string; mountedThreads: string[] }) => Promise<void> | void;
}

export function SessionScopeDialog({
  open,
  threads,
  initialPrimarySlug,
  creating = false,
  onClose,
  onSubmit,
}: SessionScopeDialogProps) {
  const [primaryThread, setPrimaryThread] = useState<string>("");
  const [extraMountedThreads, setExtraMountedThreads] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!open) return;
    const fallbackPrimary = initialPrimarySlug ?? threads[0]?.slug ?? "";
    setPrimaryThread(fallbackPrimary);
    setExtraMountedThreads(new Set());
  }, [initialPrimarySlug, open, threads]);

  if (!open) return null;

  const mountedThreads = new Set(extraMountedThreads);
  if (primaryThread) {
    mountedThreads.add(primaryThread);
  }

  const handleSubmit = async () => {
    if (!primaryThread) return;
    await onSubmit({
      primaryThread,
      mountedThreads: [...mountedThreads].sort(),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-hal-canvas/80 px-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-xl border border-border bg-hal-panel shadow-2xl">
        <header className="border-b border-border px-5 py-4">
          <h2 className="text-base font-semibold text-hal-primary">New Scoped Session</h2>
          <p className="mt-1 text-sm text-hal-muted">
            Pick the primary thread and any additional briefs you want mounted into this run.
          </p>
        </header>

        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">
          <div className="mb-4 grid gap-3 rounded-lg border border-border bg-hal-float p-4 text-sm text-hal-muted md:grid-cols-2">
            <div>
              <p className="text-xs font-medium uppercase tracking-widest text-hal-primary">
                Primary Thread
              </p>
              <p className="mt-2">
                Receives the new session entry and acts as the default landing place after briefing.
              </p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-widest text-hal-primary">
                Mounted Threads
              </p>
              <p className="mt-2">
                Their `BRIEF.md` content is explicitly mounted into the session context from turn one.
              </p>
            </div>
          </div>

          <div className="space-y-2">
            {threads.map((thread) => {
              const checked = mountedThreads.has(thread.slug);
              const isPrimary = thread.slug === primaryThread;
              return (
                <div
                  key={thread.slug}
                  className={cn(
                    "flex items-start gap-4 rounded-lg border px-4 py-3 transition-colors duration-fast ease-standard",
                    isPrimary ? "border-accent bg-accent-subtle" : "border-border bg-hal-canvas hover:bg-hal-float",
                  )}
                >
                  <input
                    type="radio"
                    name="primary-thread"
                    className="mt-1"
                    checked={isPrimary}
                    onChange={() => {
                      setPrimaryThread(thread.slug);
                    }}
                  />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-hal-primary">{thread.name}</p>
                        <p className="mt-1 text-xs text-hal-muted">{thread.description || "No description."}</p>
                      </div>
                      <span className="rounded-sm border border-border bg-hal-panel px-2 py-0.5 font-mono text-[11px] text-hal-muted">
                        {thread.scope || "thread"}
                      </span>
                    </div>

                    <div className="mt-3 flex items-center justify-between gap-3">
                      <span className="text-xs text-hal-muted">{thread.slug}</span>
                      <span className="flex items-center gap-2 text-xs text-hal-primary">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={isPrimary}
                          onChange={(event) => {
                            setExtraMountedThreads((current) => {
                              const next = new Set(current);
                              if (event.target.checked) {
                                next.add(thread.slug);
                              } else {
                                next.delete(thread.slug);
                              }
                              return next;
                            });
                          }}
                        />
                        mount brief
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-border px-5 py-4">
          <div className="text-xs text-hal-muted">
            Primary is always mounted. You can add extra threads now and adjust scope later.
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={creating}
              className="rounded-md border border-border bg-hal-canvas px-3 py-1.5 text-sm text-hal-primary transition-colors duration-fast ease-standard hover:bg-hal-float disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!primaryThread || creating}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition-colors duration-fast ease-standard hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {creating ? "Creating..." : "Start Session"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
