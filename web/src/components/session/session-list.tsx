/**
 * SessionList -- Thread-detail session list with design system primitives.
 *
 * Each session item uses StatusDot, StatusBadge, and design system tokens
 * for a consistent, restrained visual style.
 */

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { StatusDot } from "@/components/ui/status-dot";
import type { SessionManifest, SessionStatus } from "@/lib/types";
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
          <p className="text-caption uppercase tracking-widest text-hal-muted">
            Sessions
          </p>
          <p className="mt-1 text-meta text-hal-muted">
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

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {sessions.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-hal-float px-3 py-4 text-body text-hal-muted">
            No sessions yet for this thread.
          </div>
        ) : (
          sessions.map((session) => {
            const isSelected = session.session_id === selectedSessionId;
            return (
              <button
                key={session.session_id}
                type="button"
                onClick={() => onSelect(session.session_id)}
                className={cn(
                  "w-full rounded-md border px-3 py-3 text-left transition-colors duration-fast ease-standard",
                  isSelected
                    ? "border-border bg-hal-float"
                    : "border-subtle hover:border-border hover:bg-hal-float",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "h-4 w-0.5 rounded-full bg-transparent",
                          isSelected && "bg-accent",
                        )}
                        aria-hidden="true"
                      />
                      <StatusDot state={sessionDotState(session.status)} />
                      <span className="truncate font-mono text-meta text-hal-primary">
                        {session.session_id}
                      </span>
                    </div>
                    <p className="mt-2 text-meta text-hal-primary">
                      {summarizeSession(session)}
                    </p>
                  </div>
                  <StatusBadge state={sessionBadgeState(session.status)}>
                    {sessionDisplayState(session.status).label}
                  </StatusBadge>
                </div>
                <div className="mt-3 flex items-center justify-between gap-4 text-caption text-hal-muted">
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

// ---------------------------------------------------------------------------
// State mapping helpers
// ---------------------------------------------------------------------------

type DotState = "live" | "success" | "warning" | "danger" | "idle" | "muted";
type BadgeState = "live" | "success" | "warning" | "danger" | "muted";

function sessionDotState(status: SessionStatus): DotState {
  switch (status) {
    case "active":
      return "live";
    case "briefing":
      return "idle";
    case "ended":
      return "success";
    case "dropped":
      return "muted";
  }
}

function sessionBadgeState(status: SessionStatus): BadgeState {
  switch (status) {
    case "active":
      return "live";
    case "briefing":
      return "warning";
    case "ended":
      return "success";
    case "dropped":
      return "muted";
  }
}
