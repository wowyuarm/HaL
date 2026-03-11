/**
 * ThreadList — Sidebar thread navigation list.
 *
 * Renders each thread as a clickable row with name + relative time.
 * Active thread is highlighted with an accent left border and subtle background.
 */

import type { Thread } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Time thresholds (in seconds) for relative formatting. */
const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

interface ThreadListProps {
  threads: Thread[];
  activeThread: string | null;
  onSelect: (slug: string) => void;
  className?: string;
}

export function ThreadList({ threads, activeThread, onSelect, className }: ThreadListProps) {
  if (threads.length === 0) {
    return <p className="px-2 text-xs text-muted">No threads yet.</p>;
  }

  return (
    <nav className={cn("space-y-0.5", className)} aria-label="Thread list">
      {threads.map((thread) => {
        const isActive = thread.slug === activeThread;

        return (
          <button
            key={thread.slug}
            type="button"
            onClick={() => onSelect(thread.slug)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex w-full flex-col rounded-md px-3 py-2 text-left",
              "transition-colors duration-fast ease-standard",
              "hover:bg-elevated",
              isActive && "border-l-2 border-l-accent bg-accent-subtle",
            )}
          >
            <span className="truncate text-sm font-medium text-foreground">
              {thread.name}
            </span>
            <span className="mt-0.5 text-xs text-muted">
              {formatRelativeTime(thread.last_active)}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

/**
 * Format an ISO timestamp as a relative time string (e.g. "2h ago").
 * Falls back to an absolute date for anything older than 30 days.
 */
function formatRelativeTime(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;

  const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);

  if (diffSec < 0) return "just now";
  if (diffSec < MINUTE) return "just now";
  if (diffSec < HOUR) {
    const mins = Math.floor(diffSec / MINUTE);
    return `${mins}m ago`;
  }
  if (diffSec < DAY) {
    const hours = Math.floor(diffSec / HOUR);
    return `${hours}h ago`;
  }
  if (diffSec < DAY * 30) {
    const days = Math.floor(diffSec / DAY);
    return `${days}d ago`;
  }

  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
