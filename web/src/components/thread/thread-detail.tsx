/**
 * ThreadDetailPanel -- Main-canvas thread detail view.
 *
 * Shows thread name, description, scope tag, BRIEF.md prose rendering,
 * metadata (updated timestamp, session count), and session list below.
 * The thread detail stays on the shared workspace canvas with the BRIEF
 * centered for reading comfort instead of wrapping the whole view in a card.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { SessionList } from "@/components/session/session-list";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatCount, formatTimestamp } from "@/lib/runtime";
import type { ThreadDetail } from "@/lib/types";

interface ThreadDetailProps {
  thread: ThreadDetail | null;
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
  creatingSession?: boolean;
}

export function ThreadDetailPanel({
  thread,
  selectedSessionId,
  onSelectSession,
  onCreateSession,
  creatingSession = false,
}: ThreadDetailProps) {
  if (!thread) {
    return (
      <section className="flex h-full items-center justify-center rounded-md border border-dashed border-border p-6 text-body text-hal-muted">
        Select a thread to inspect its brief and sessions.
      </section>
    );
  }

  const totalSessions =
    (thread.session_counts.active ?? 0) +
    (thread.session_counts.briefing ?? 0) +
    (thread.session_counts.ended ?? 0) +
    (thread.session_counts.dropped ?? 0);
  const updatedAt = thread.updated_at ?? thread.sessions[0]?.created_at ?? null;

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="mx-auto w-full max-w-6xl">
        <div className="hal-paper hal-sheet rounded-lg border border-border px-5 py-6 md:px-7 md:py-7">
          <p className="hal-rule-label">Thread</p>
          <div className="mt-4 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <h2 className="truncate font-serif text-title tracking-[-0.03em] text-hal-primary">
                {thread.name}
              </h2>
              <p className="mt-4 max-w-3xl text-reading text-hal-muted">
                {thread.description || "No description."}
              </p>
            </div>
            <div className="pt-1">
              <StatusBadge state={thread.status === "active" ? "live" : "muted"}>
                {thread.status || "thread"}
              </StatusBadge>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-subtle pt-4 text-meta text-hal-muted">
            <span>{updatedAt ? `Updated ${formatTimestamp(updatedAt)}` : "No update stamp yet"}</span>
            <span>{formatCount(totalSessions)} sessions</span>
            <span className="font-mono">{thread.slug}</span>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 py-6">
          <section className="hal-paper hal-sheet rounded-lg border border-border px-5 py-6 md:px-7 md:py-7">
            <p className="hal-rule-label">BRIEF.md</p>
            <div className="prose prose-mineral mt-5 max-w-none text-reading text-hal-primary">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {thread.brief_markdown || "_This thread does not have a brief yet._"}
              </ReactMarkdown>
            </div>
          </section>

          <section className="rounded-lg border border-subtle bg-hal-paper px-4 py-5 md:px-5 md:py-6">
            <SessionList
              sessions={thread.sessions}
              selectedSessionId={selectedSessionId}
              onSelect={onSelectSession}
              onCreate={onCreateSession}
              creating={creatingSession}
            />
          </section>
        </div>
      </div>
    </section>
  );
}
