/**
 * ThreadDetailPanel -- Compact thread overview with sessions below.
 */

import { SessionList } from "@/components/session/session-list";
import { Button } from "@/components/ui/button";
import type { ThreadDetail } from "@/lib/types";

interface ThreadDetailProps {
  thread: ThreadDetail | null;
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
  onToggleBriefPanel: () => void;
  creatingSession?: boolean;
}

export function ThreadDetailPanel({
  thread,
  selectedSessionId,
  onSelectSession,
  onCreateSession,
  onToggleBriefPanel,
  creatingSession = false,
}: ThreadDetailProps) {
  if (!thread) {
    return (
      <section className="flex h-full items-center justify-center rounded-md border border-dashed border-border p-6 text-body text-hal-muted">
        Select a thread to inspect its sessions.
      </section>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-subtle">
        <div className="mx-auto flex w-full max-w-6xl items-start justify-between gap-4 px-5 py-4 md:px-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h2 className="truncate text-subheading font-semibold text-hal-primary">
                {thread.name}
              </h2>
              {thread.status ? (
                <span
                  className={
                    thread.status === "active"
                      ? "text-meta text-accent"
                      : "text-meta text-hal-muted"
                  }
                >
                  {thread.status}
                </span>
              ) : null}
            </div>
            <p className="mt-1 truncate text-meta text-hal-muted">
              {thread.description || "No description."}
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={onToggleBriefPanel}>
            Thread brief
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl px-5 py-6 md:px-6">
          <SessionList
            sessions={thread.sessions}
            selectedSessionId={selectedSessionId}
            onSelect={onSelectSession}
            onCreate={onCreateSession}
            creating={creatingSession}
          />
        </div>
      </div>
    </section>
  );
}
