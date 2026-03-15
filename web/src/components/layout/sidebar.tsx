/**
 * Sidebar — persistent left panel with thread→session tree navigation.
 *
 * Shows threads as expandable groups. Each thread expands to show its
 * sessions with status indicators. Supports collapse to icon rail.
 */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeft, Plus } from "lucide-react";

import { StatusBadge } from "@/components/ui/status-badge";
import { StatusDot } from "@/components/ui/status-dot";
import { formatRelativeTime } from "@/lib/runtime";
import type { SessionManifest, SessionStatus, ThreadDetail, ThreadSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SidebarProps {
  threads: ThreadSummary[];
  threadDetails: Record<string, ThreadDetail>;
  activeThreadSlug: string | null;
  selectedSessionId: string | null;
  collapsed: boolean;
  onSelectThread: (slug: string) => void;
  onSelectSession: (sessionId: string) => void;
  onToggleCollapse: () => void;
  onNewSession: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Sidebar({
  threads,
  threadDetails,
  activeThreadSlug,
  selectedSessionId,
  collapsed,
  onSelectThread,
  onSelectSession,
  onToggleCollapse,
  onNewSession,
}: SidebarProps) {
  // Track which threads are expanded in the tree.
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(
    () => new Set(activeThreadSlug ? [activeThreadSlug] : []),
  );

  // Auto-expand when activeThreadSlug changes externally.
  useEffect(() => {
    if (!activeThreadSlug) return;
    setExpandedThreads((prev) => {
      if (prev.has(activeThreadSlug)) return prev;
      const next = new Set(prev);
      next.add(activeThreadSlug);
      return next;
    });
  }, [activeThreadSlug]);

  const toggleExpand = (slug: string) => {
    setExpandedThreads((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  };

  const handleThreadClick = (slug: string) => {
    onSelectThread(slug);
    // Auto-expand on selection.
    setExpandedThreads((prev) => new Set(prev).add(slug));
  };

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
                onClick={() => handleThreadClick(thread.slug)}
                title={thread.name}
                className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-lg border text-caption font-semibold uppercase tracking-[0.12em] transition-colors",
                  isActive
                    ? "border-accent bg-hal-float text-hal-primary shadow-sm"
                    : "border-subtle text-hal-muted hover:border-border hover:text-hal-primary",
                )}
              >
                {threadMonogram(thread.name, thread.slug)}
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

      {/* Thread tree */}
      <nav className="flex-1 overflow-y-auto px-2 py-2" aria-label="Thread navigation">
        {threads.length === 0 ? (
          <p className="px-2 py-4 text-meta text-hal-muted">No threads yet.</p>
        ) : (
          <div className="space-y-0.5">
            {threads.map((thread) => {
              const isActive = thread.slug === activeThreadSlug;
              const isExpanded = expandedThreads.has(thread.slug);
              const detail = threadDetails[thread.slug];
              const sessions = detail?.sessions ?? [];
              const hasActiveSessions = (thread.session_counts.active ?? 0) > 0;

              return (
                <div key={thread.slug}>
                  {/* Thread row */}
                  <div className="flex items-center">
                    <button
                      type="button"
                      onClick={() => toggleExpand(thread.slug)}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-hal-muted hover:text-hal-primary"
                      aria-label={isExpanded ? "Collapse" : "Expand"}
                    >
                      {sessions.length > 0 ? (
                        isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )
                      ) : (
                        <span className="h-3.5 w-3.5" />
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={() => handleThreadClick(thread.slug)}
                      className={cn(
                        "flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors",
                        isActive
                          ? "bg-hal-float text-hal-primary"
                          : "text-hal-muted hover:bg-hal-float hover:text-hal-primary",
                      )}
                    >
                      {hasActiveSessions && <StatusDot state="live" />}
                      <span className="min-w-0 truncate text-meta font-medium">
                        {thread.name}
                      </span>
                      <span className="ml-auto shrink-0 text-caption text-hal-muted">
                        {formatSessionCount(thread.session_counts)}
                      </span>
                    </button>
                  </div>

                  {/* Session list (expanded) */}
                  {isExpanded && sessions.length > 0 && (
                    <div className="ml-7 space-y-px pb-1">
                      {sessions.map((session) => (
                        <SessionRow
                          key={session.session_id}
                          session={session}
                          isSelected={session.session_id === selectedSessionId}
                          onSelect={() => onSelectSession(session.session_id)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </nav>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Session row
// ---------------------------------------------------------------------------

function SessionRow({
  session,
  isSelected,
  onSelect,
}: {
  session: SessionManifest;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors",
        isSelected
          ? "bg-hal-float text-hal-primary"
          : "text-hal-muted hover:bg-hal-float hover:text-hal-primary",
      )}
    >
      <StatusDot state={sessionDotState(session.status)} />
      <span className="min-w-0 flex-1 truncate font-mono text-caption">
        {session.session_id.slice(2, 16)}
      </span>
      <span className="shrink-0 text-caption text-hal-muted">
        {formatRelativeTime(session.created_at)}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sessionDotState(status: SessionStatus): "live" | "success" | "idle" | "muted" {
  switch (status) {
    case "active": return "live";
    case "briefing": return "idle";
    case "ended": return "success";
    case "dropped": return "muted";
  }
}

function formatSessionCount(counts: ThreadSummary["session_counts"]): string {
  const total =
    (counts.active ?? 0) + (counts.briefing ?? 0) + (counts.ended ?? 0) + (counts.dropped ?? 0);
  return total.toString();
}

function threadMonogram(name: string, slug: string): string {
  const parts = slug.split("-").filter(Boolean);
  if (parts.length >= 2) return `${parts[0]![0]}${parts[1]![0]}`.toUpperCase();
  const clean = name.replace(/[^A-Za-z0-9]/g, "").trim();
  return clean.length >= 2 ? clean.slice(0, 2).toUpperCase() : clean[0]?.toUpperCase() ?? "?";
}
