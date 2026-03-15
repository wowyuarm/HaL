/**
 * SessionHeader — metadata bar above the conversation.
 *
 * Extracted from working-log.tsx SessionHeader. Shows session ID,
 * status, socket state, and action buttons (Brief, Drop, Scope, Brief panel).
 */

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { StatusDot } from "@/components/ui/status-dot";
import { Tag } from "@/components/ui/tag";
import { formatTimestamp } from "@/lib/runtime";
import type { SessionManifest, SessionStatus, SocketState } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SessionHeaderProps {
  session: SessionManifest;
  threadName: string | null;
  socketState: SocketState;
  eventsCount: number;
  briefPanelOpen: boolean;
  onEditScope: () => void;
  onBrief: () => void;
  onDrop: () => void;
  onToggleBriefPanel: () => void;
}

export function SessionHeader({
  session,
  threadName,
  socketState,
  eventsCount,
  briefPanelOpen,
  onEditScope,
  onBrief,
  onDrop,
  onToggleBriefPanel,
}: SessionHeaderProps) {
  const canEndSession = session.status === "active";
  const canEditScope = session.status === "active";
  const showSocketState = session.status === "active" || session.status === "briefing";

  return (
    <header className="shrink-0 border-b border-subtle px-5 py-4 md:px-6 md:py-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="min-w-0 truncate font-serif text-title tracking-[-0.03em] text-hal-primary">
              {threadName ?? session.primary_thread ?? "Working log"}
            </h2>
            <StatusBadge state={sessionBadgeState(session.status)}>
              {session.status}
            </StatusBadge>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-meta text-hal-muted">
            <StatusDot state={sessionDotState(session.status)} />
            <span className="font-mono text-hal-primary">
              {session.session_id.slice(0, 16)}...
            </span>
            <span>{formatTimestamp(session.created_at)}</span>
            <span>{session.turn_count} turns</span>
            <span>{eventsCount} events</span>
            {showSocketState && <Tag>{socketLabel(socketState)}</Tag>}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleBriefPanel}
            aria-pressed={briefPanelOpen}
            className={cn(briefPanelOpen && "bg-hal-panel text-hal-primary")}
          >
            {briefPanelOpen ? "Hide brief" : "Thread brief"}
          </Button>
          {canEditScope && (
            <Button variant="secondary" size="sm" onClick={onEditScope}>
              Scope
            </Button>
          )}
          {canEndSession && (
            <>
              <Button variant="primary" size="sm" onClick={onBrief}>
                Brief
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={onDrop}
                className="text-danger hover:border-danger hover:bg-hal-danger-subtle hover:text-danger"
              >
                Drop
              </Button>
            </>
          )}
        </div>
      </div>

      {session.mounted_threads.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-subtle pt-3">
          <span className="hal-meta-kicker">Threads</span>
          {session.mounted_threads.map((slug) => (
            <Tag
              key={slug}
              variant={slug === session.primary_thread ? "accent" : "default"}
            >
              {slug}
            </Tag>
          ))}
        </div>
      )}
    </header>
  );
}

// ---------------------------------------------------------------------------
// State mapping helpers
// ---------------------------------------------------------------------------

type DotState = "live" | "success" | "warning" | "danger" | "idle" | "muted";
type BadgeState = "live" | "success" | "warning" | "danger" | "muted";

function sessionDotState(status: SessionStatus): DotState {
  switch (status) {
    case "active": return "live";
    case "briefing": return "idle";
    case "ended": return "success";
    case "dropped": return "muted";
  }
}

function sessionBadgeState(status: SessionStatus): BadgeState {
  switch (status) {
    case "active": return "live";
    case "briefing": return "warning";
    case "ended": return "success";
    case "dropped": return "muted";
  }
}

function socketLabel(state: SocketState): string {
  switch (state) {
    case "live": return "stream live";
    case "connecting": return "connecting";
    case "disconnected": return "disconnected";
  }
}
