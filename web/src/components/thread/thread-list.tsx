/**
 * ThreadList -- Sidebar thread navigation list.
 *
 * Renders thread entries plus compact session counters for the
 * session-first working-log runtime. Uses design system tokens
 * for active state, typography, and metadata.
 */

import { formatRelativeTime } from "@/lib/runtime";
import type { ThreadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { StatusDot } from "@/components/ui/status-dot";
import { StatusBadge } from "@/components/ui/status-badge";

interface ThreadListProps {
  threads: ThreadSummary[];
  activeThread: string | null;
  onSelect: (slug: string) => void;
  className?: string;
}

export function ThreadList({ threads, activeThread, onSelect, className }: ThreadListProps) {
  if (threads.length === 0) {
    return <p className="px-2 text-meta text-hal-muted">No threads yet.</p>;
  }

  return (
    <nav className={className} aria-label="Thread list">
      {threads.map((thread) => {
        const isActive = thread.slug === activeThread;
        const hasActiveSessions = (thread.session_counts.active ?? 0) > 0;
        const statusLabel = threadStatusLabel(thread.status);

        return (
          <button
            key={thread.slug}
            type="button"
            onClick={() => onSelect(thread.slug)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "group relative flex w-full flex-col overflow-hidden rounded-[18px] border px-4 py-3.5 text-left",
              "transition-all duration-fast ease-standard",
              "bg-[rgba(255,255,255,0.28)] hover:-translate-y-px hover:border-border hover:bg-hal-float",
              isActive && "border-accent bg-hal-float shadow-sm",
            )}
          >
            <div
              aria-hidden="true"
              className={cn(
                "absolute inset-y-0 left-0 w-1 rounded-r-full bg-transparent transition-colors duration-fast ease-standard",
                isActive && "bg-human",
              )}
            />
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  {hasActiveSessions ? <StatusDot state="live" /> : null}
                  <span className="truncate font-serif text-[18px] font-semibold tracking-[-0.02em] text-hal-primary">
                    {thread.name}
                  </span>
                </div>
                <p className="mt-2 text-meta leading-6 text-hal-muted">
                  {thread.description || "No scope description yet."}
                </p>
              </div>
              <div className="pt-0.5">
                <StatusBadge state={threadBadgeState(thread.status, hasActiveSessions)}>
                  {statusLabel}
                </StatusBadge>
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between gap-3 border-t border-subtle pt-3 text-meta text-hal-muted">
              <span className="truncate font-mono">
                {thread.slug}
              </span>
              <span className="shrink-0">
                {thread.updated_at
                  ? `${formatRelativeTime(thread.updated_at)} · ${formatCounts(thread.session_counts)}`
                  : formatCounts(thread.session_counts)}
              </span>
            </div>
          </button>
        );
      })}
    </nav>
  );
}

function formatCounts(counts: ThreadSummary["session_counts"]): string {
  const active = counts.active ?? 0;
  const briefing = counts.briefing ?? 0;
  const ended = counts.ended ?? 0;
  const dropped = counts.dropped ?? 0;
  const total = active + briefing + ended + dropped;
  if (total === 0) return "0 sessions";
  return `${total} session${total === 1 ? "" : "s"}`;
}

function threadStatusLabel(status: string): string {
  switch (status) {
    case "active":
      return "active";
    case "inactive":
      return "idle";
    default:
      return status || "thread";
  }
}

function threadBadgeState(
  status: string,
  hasActiveSessions: boolean,
): "live" | "muted" | "warning" {
  if (hasActiveSessions || status === "active") return "live";
  if (status === "inactive") return "muted";
  return "warning";
}
