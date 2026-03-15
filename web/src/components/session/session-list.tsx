/**
 * SessionList -- Spacious thread-detail session list.
 */

import { Button } from "@/components/ui/button";
import type { SessionManifest } from "@/lib/types";
import { formatTimestamp, sessionDisplayState } from "@/lib/runtime";
import { cn } from "@/lib/utils";

interface SessionListProps {
  sessions: SessionManifest[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onCreate: () => void;
  creating?: boolean;
}

export function SessionList({
  sessions,
  selectedSessionId,
  onSelect,
  onCreate,
  creating = false,
}: SessionListProps) {
  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <p className="hal-rule-label">Sessions</p>
          <p className="mt-2 text-meta text-hal-muted">
            One session = one observable collaboration run.
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={onCreate}
          disabled={creating}
        >
          {creating ? "Creating..." : "New Session"}
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-hal-float px-4 py-5 text-body text-hal-muted">
            No sessions yet for this thread.
          </div>
        ) : (
          <div className="divide-y divide-subtle">
            {sessions.map((session) => {
              const isSelected = session.session_id === selectedSessionId;
              const status = sessionDisplayState(session.status);
              const extraThreads = session.mounted_threads.filter(
                (slug) => slug !== session.primary_thread,
              );

              return (
                <button
                  key={session.session_id}
                  type="button"
                  onClick={() => onSelect(session.session_id)}
                  className={cn(
                    "w-full px-1 py-4 text-left transition-colors duration-fast ease-standard",
                    isSelected ? "bg-hal-panel" : "hover:bg-hal-float",
                  )}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta">
                        <span className="text-hal-primary">{formatTimestamp(session.created_at)}</span>
                        <span className="text-hal-muted">
                          {session.turn_count} turn{session.turn_count === 1 ? "" : "s"}
                        </span>
                      </div>
                      {extraThreads.length > 0 ? (
                        <p className="mt-1 truncate text-meta text-hal-muted">
                          {extraThreads.join(", ")}
                        </p>
                      ) : null}
                    </div>
                    <span className={cn("shrink-0 text-meta font-medium", status.textClass)}>
                      {status.label}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
