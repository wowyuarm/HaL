import type { SessionManifest } from "@/lib/types";
import {
  formatRelativeTime,
  formatTimestamp,
  sessionDisplayState,
  summarizeSession,
} from "@/lib/runtime";
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
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-muted">
            Sessions
          </p>
          <p className="mt-1 text-xs text-muted">
            One session = one observable collaboration run.
          </p>
        </div>
        <button
          type="button"
          onClick={onCreate}
          disabled={creating}
          className={cn(
            "rounded-md border border-border bg-elevated px-3 py-1.5 text-xs font-medium text-foreground",
            "transition-colors duration-fast ease-standard hover:bg-panel",
            "disabled:cursor-not-allowed disabled:opacity-60",
          )}
        >
          {creating ? "Creating..." : "New Session"}
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {sessions.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-elevated px-3 py-4 text-sm text-muted">
            No sessions yet for this thread.
          </div>
        ) : (
          sessions.map((session) => {
            const display = sessionDisplayState(session.status);
            const isSelected = session.session_id === selectedSessionId;
            return (
              <button
                key={session.session_id}
                type="button"
                onClick={() => onSelect(session.session_id)}
                className={cn(
                  "w-full rounded-md border px-3 py-3 text-left transition-colors duration-fast ease-standard",
                  "hover:bg-elevated",
                  isSelected
                    ? "border-accent bg-accent-subtle"
                    : "border-border bg-background",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn("inline-block h-2 w-2 rounded-full", display.dotClass)} />
                      <span className="truncate font-mono text-xs text-foreground">
                        {session.session_id}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-foreground">
                      {summarizeSession(session)}
                    </p>
                  </div>
                  <span className={cn("shrink-0 text-xs font-medium uppercase tracking-wide", display.textClass)}>
                    {display.label}
                  </span>
                </div>
                <div className="mt-3 flex items-center justify-between gap-4 text-xs text-muted">
                  <span>{formatRelativeTime(session.created_at)}</span>
                  <span>{formatTimestamp(session.created_at)}</span>
                </div>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}
