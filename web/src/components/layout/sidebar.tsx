/**
 * Sidebar — persistent left panel with flat thread navigation.
 *
 * Shows threads as a flat list. Clicking a thread drills into the
 * thread detail panel in the main area. Supports collapse to icon rail.
 */

import { PanelLeftClose, PanelLeft, Plus } from "lucide-react";

import { StatusDot } from "@/components/ui/status-dot";
import type { ThreadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SidebarProps {
  threads: ThreadSummary[];
  activeThreadSlug: string | null;
  collapsed: boolean;
  onSelectThread: (slug: string) => void;
  onToggleCollapse: () => void;
  onNewSession: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Sidebar({
  threads,
  activeThreadSlug,
  collapsed,
  onSelectThread,
  onToggleCollapse,
  onNewSession,
}: SidebarProps) {
  if (collapsed) {
    return (
      <aside className="relative z-10 flex min-h-0 flex-col items-center border-r border-subtle bg-hal-veil py-3 backdrop-blur-sm">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl text-hal-muted transition-colors hover:text-hal-primary"
          aria-label="Expand sidebar"
        >
          <PanelLeft className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={onNewSession}
          className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl border border-subtle text-hal-muted transition-colors hover:border-border hover:text-hal-primary"
          aria-label="New session"
        >
          <Plus className="h-4 w-4" />
        </button>

        <div className="flex flex-1 flex-col items-center gap-2 overflow-y-auto px-2 py-2">
          {threads.map((thread) => {
            const isActive = thread.slug === activeThreadSlug;
            return (
              <button
                key={thread.slug}
                type="button"
                onClick={() => onSelectThread(thread.slug)}
                title={thread.slug}
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-lg border text-caption font-semibold uppercase tracking-[0.12em] transition-colors",
                  isActive
                    ? "border-accent bg-hal-float text-hal-primary shadow-sm"
                    : "border-subtle text-hal-muted hover:border-border hover:text-hal-primary",
                )}
              >
                {threadMonogram(thread.slug)}
              </button>
            );
          })}
        </div>
      </aside>
    );
  }

  return (
    <aside className="relative z-10 flex min-h-0 w-[284px] flex-col border-r border-subtle bg-hal-veil backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-subtle px-4 py-3">
        <span className="hal-meta-kicker">Threads</span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onNewSession}
            className="flex h-8 items-center gap-1 rounded-lg border border-subtle px-2.5 text-caption text-hal-muted transition-colors hover:border-border hover:text-hal-primary"
            title="New session"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>New</span>
          </button>
          <button
            type="button"
            onClick={onToggleCollapse}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-hal-muted transition-colors hover:text-hal-primary"
            aria-label="Collapse sidebar"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Thread list */}
      <nav className="flex-1 overflow-y-auto px-2 py-2" aria-label="Thread navigation">
        {threads.length === 0 ? (
          <p className="px-2 py-4 text-meta text-hal-muted">No threads yet.</p>
        ) : (
          <div className="space-y-0.5">
            {threads.map((thread) => {
              const isActive = thread.slug === activeThreadSlug;
              const hasActiveSessions = (thread.session_counts.active ?? 0) > 0;

              return (
                <button
                  key={thread.slug}
                  type="button"
                  onClick={() => onSelectThread(thread.slug)}
                  title={thread.name}
                  className={cn(
                    "flex w-full min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors",
                    isActive
                      ? "bg-hal-float text-hal-primary"
                      : "text-hal-muted hover:bg-hal-float hover:text-hal-primary",
                  )}
                >
                  <StatusDot state={hasActiveSessions ? "live" : "muted"} />
                  <span className="min-w-0 truncate font-mono text-meta font-medium tracking-[0.01em]">
                    {thread.slug}
                  </span>
                  <span className="ml-auto shrink-0 text-caption text-hal-muted">
                    {formatSessionCount(thread.session_counts)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </nav>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatSessionCount(counts: ThreadSummary["session_counts"]): string {
  const total =
    (counts.active ?? 0) + (counts.briefing ?? 0) + (counts.ended ?? 0) + (counts.dropped ?? 0);
  return total.toString();
}

function threadMonogram(slug: string): string {
  const parts = slug.split("-").filter(Boolean);
  if (parts.length >= 2) return `${parts[0]![0]}${parts[1]![0]}`.toUpperCase();
  const clean = slug.replace(/[^A-Za-z0-9]/g, "").trim();
  return clean.length >= 2 ? clean.slice(0, 2).toUpperCase() : clean[0]?.toUpperCase() ?? "?";
}
