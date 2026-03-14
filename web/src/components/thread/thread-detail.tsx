/**
 * ThreadDetailPanel -- Navigation-mode thread detail view.
 *
 * Shows thread name, description, scope tag, BRIEF.md prose rendering,
 * metadata (updated timestamp, session count), and session list below.
 * Uses Panel(raised) as the overall container per design system guidance.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { SessionList } from "@/components/session/session-list";
import { Panel } from "@/components/ui/panel";
import { Tag } from "@/components/ui/tag";
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

  return (
    <Panel
      surface="raised"
      border
      className="flex h-full min-h-0 flex-col"
    >
      {/* Thread header */}
      <header className="border-b border-subtle px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-heading text-hal-primary">
              {thread.name}
            </h2>
            <p className="mt-1 text-body text-hal-muted">
              {thread.description || "No description."}
            </p>
          </div>
          <Tag>{thread.scope || "thread"}</Tag>
        </div>

        <div className="mt-3 flex items-center gap-4 text-meta text-hal-muted">
          <span>Updated {formatTimestamp(thread.updated_at)}</span>
          <span>{formatCount(totalSessions)} sessions</span>
        </div>
      </header>

      {/* Scrollable body: BRIEF + session list */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {/* BRIEF.md */}
        <section className="mb-6">
          <p className="mb-3 text-caption uppercase tracking-widest text-hal-muted">
            BRIEF.md
          </p>
          <Panel surface="base" border className="px-4 py-3">
            <div className="prose prose-mineral max-w-none text-[15px] leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {thread.brief_markdown || "_This thread does not have a brief yet._"}
              </ReactMarkdown>
            </div>
          </Panel>
        </section>

        {/* Session list */}
        <SessionList
          sessions={thread.sessions}
          selectedSessionId={selectedSessionId}
          onSelect={onSelectSession}
          onCreate={onCreateSession}
          creating={creatingSession}
        />
      </div>
    </Panel>
  );
}
