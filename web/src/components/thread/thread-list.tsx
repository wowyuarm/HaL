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
import { Tag } from "@/components/ui/tag";

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
    <nav className={cn("space-y-0.5", className)} aria-label="Thread list">
      {threads.map((thread) => {
        const isActive = thread.slug === activeThread;
        const hasActiveSessions = (thread.session_counts.active ?? 0) > 0;

        return (
          <button
            key={thread.slug}
            type="button"
            onClick={() => onSelect(thread.slug)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex w-full flex-col rounded-md px-3 py-2 text-left",
              "transition-colors duration-fast ease-standard",
              "hover:bg-hal-float",
              isActive && "border-l-2 border-l-accent bg-hal-live-subtle",
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                {hasActiveSessions ? <StatusDot state="live" /> : null}
                <span className="truncate text-body font-medium text-hal-primary">
                  {thread.name}
                </span>
              </div>
              <Tag>{thread.scope || "thread"}</Tag>
            </div>
            <div className="mt-1 flex items-center justify-between gap-3 text-meta text-hal-muted">
              <span className="truncate">
                {thread.updated_at ? formatRelativeTime(thread.updated_at) : "no recent update"}
              </span>
              <span className="shrink-0">
                {formatCounts(thread.session_counts)}
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
