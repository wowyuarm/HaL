/**
 * WorkingLog — Dual-layer session working log.
 *
 * Renders a structured view of session events using the two-tier model from
 * view-models.ts: an Activity layer (human-relevant content) and an Evidence
 * layer (diagnostic events, expanded on demand per turn).
 *
 * Top-level structure:
 *   SessionHeader -> scrollable TurnCard / SessionActivityRow list -> Composer
 */

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Composer } from "@/components/chat/composer";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/status-badge";
import { StatusDot } from "@/components/ui/status-dot";
import { Tag } from "@/components/ui/tag";
import {
  formatRelativeTime,
  formatTimestamp,
  isInteractiveSession,
  sessionDisplayState,
} from "@/lib/runtime";
import type { SessionEvent, SessionManifest, SessionStatus, SocketState } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  buildWorkingLog,
  type ActivityItem,
  type SessionActivityItem,
  type TurnViewModel,
} from "@/lib/view-models";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Distance from bottom (px) within which auto-scroll remains active. */
const AUTO_SCROLL_THRESHOLD = 120;

/** Maximum characters shown in evidence payload previews. */
const PAYLOAD_PREVIEW_LIMIT = 160;

// ---------------------------------------------------------------------------
// Props (unchanged — must stay compatible with App.tsx)
// ---------------------------------------------------------------------------

interface WorkingLogProps {
  session: SessionManifest | null;
  threadName?: string | null;
  events: SessionEvent[];
  socketState: SocketState;
  scopeEditable?: boolean;
  loading?: boolean;
  error?: string | null;
  briefPanelOpen?: boolean;
  onSend: (content: string) => void;
  onEditScope: () => void;
  onBrief: () => void;
  onDrop: () => void;
  onToggleBriefPanel: () => void;
}

// ---------------------------------------------------------------------------
// WorkingLog (root)
// ---------------------------------------------------------------------------

export function WorkingLog({
  session,
  threadName = null,
  events,
  socketState,
  scopeEditable = false,
  loading = false,
  error = null,
  briefPanelOpen = false,
  onSend,
  onEditScope,
  onBrief,
  onDrop,
  onToggleBriefPanel,
}: WorkingLogProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const wasNearBottomRef = useRef(true);
  const [expandedTurns, setExpandedTurns] = useState<Set<string>>(() => new Set());

  const items = buildWorkingLog(events);
  const display = session ? sessionDisplayState(session.status) : null;
  const canSend = Boolean(session && session.status === "active");
  const canEndSession = Boolean(session && session.status === "active");
  const canEditScope = Boolean(scopeEditable && session?.status === "active");
  const interactive = Boolean(session && isInteractiveSession(session.status));

  // Track whether user is near bottom for auto-scroll decisions.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = viewport;
      wasNearBottomRef.current =
        scrollHeight - scrollTop - clientHeight < AUTO_SCROLL_THRESHOLD;
    };

    viewport.addEventListener("scroll", handleScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", handleScroll);
  }, []);

  // Auto-scroll to bottom when new events arrive, only if user was near bottom.
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !wasNearBottomRef.current) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [events]);

  const toggleTurnEvidence = (turnId: string) => {
    setExpandedTurns((prev) => {
      const next = new Set(prev);
      if (next.has(turnId)) {
        next.delete(turnId);
      } else {
        next.add(turnId);
      }
      return next;
    });
  };

  // Empty state: no session selected.
  if (!session) {
    return (
      <section className="hal-paper hal-sheet flex h-full items-center justify-center rounded-[24px] border border-dashed border-border p-8 text-body text-hal-muted">
        Select a session to inspect its working log.
      </section>
    );
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* ── Session header ── */}
      <SessionHeader
        session={session}
        threadName={threadName}
        socketState={socketState}
        displayLabel={display?.label ?? "unknown"}
        canEditScope={canEditScope}
        canEndSession={canEndSession}
        eventsCount={events.length}
        briefPanelOpen={briefPanelOpen}
        onEditScope={onEditScope}
        onBrief={onBrief}
        onDrop={onDrop}
        onToggleBriefPanel={onToggleBriefPanel}
      />

      {/* ── Scrollable working log body ── */}
      <div ref={viewportRef} className="min-h-0 flex-1 overflow-y-auto px-1 py-4 md:px-2 md:py-5">
        <div className="mx-auto max-w-5xl space-y-4">
          {error ? (
            <Panel
              surface="base"
              border
              className="rounded-[18px] border-danger bg-hal-danger-subtle px-4 py-3 text-body text-danger"
            >
              {error}
            </Panel>
          ) : null}

          {loading ? (
            <Panel
              surface="base"
              border
              className="rounded-[18px] px-4 py-4 text-body text-hal-muted"
            >
              Loading session history...
            </Panel>
          ) : items.length === 0 ? (
            <Panel
              surface="base"
              border
              className="hal-paper hal-sheet rounded-[22px] border-dashed px-5 py-6 text-body text-hal-muted"
            >
              <p className="hal-rule-label">Working Log</p>
              <p className="mt-4 max-w-xl text-[15px] leading-7 text-hal-muted">
                No observable events have been recorded for this session yet. If this is an active
                run, the log will fill in as the event stream reconnects or new turns begin.
              </p>
            </Panel>
          ) : (
            <div className="space-y-3">
              {items.map((item) =>
                item.kind === "turn" ? (
                  <TurnCard
                    key={item.turn.turnId}
                    turn={item.turn}
                    expanded={expandedTurns.has(item.turn.turnId)}
                    onToggleEvidence={() => toggleTurnEvidence(item.turn.turnId)}
                  />
                ) : (
                  <SessionActivityRow key={item.item.seq} item={item.item} />
                ),
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Composer ── */}
      {interactive ? (
        <Composer
          onSend={onSend}
          disabled={!canSend}
          placeholder={
            canSend
              ? "Describe the next step, question, or direction for this session..."
              : "This session is finishing its brief. Wait for the compiled result."
          }
        />
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// SessionHeader
// ---------------------------------------------------------------------------

function SessionHeader({
  session,
  threadName,
  socketState,
  displayLabel,
  canEditScope,
  canEndSession,
  eventsCount,
  briefPanelOpen,
  onEditScope,
  onBrief,
  onDrop,
  onToggleBriefPanel,
}: {
  session: SessionManifest;
  threadName: string | null;
  socketState: SocketState;
  displayLabel: string;
  canEditScope: boolean;
  canEndSession: boolean;
  eventsCount: number;
  briefPanelOpen: boolean;
  onEditScope: () => void;
  onBrief: () => void;
  onDrop: () => void;
  onToggleBriefPanel: () => void;
}) {
  const showSocketState = session.status === "active" || session.status === "briefing";

  return (
    <header className="hal-paper hal-sheet shrink-0 rounded-[24px] border border-border px-5 py-5 md:px-6 md:py-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="hal-rule-label">Session</p>
          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            <h2 className="min-w-0 truncate font-serif text-[28px] leading-none tracking-[-0.03em] text-hal-primary md:text-[34px]">
              {threadName ?? session.primary_thread ?? "Working log"}
            </h2>
            <StatusBadge state={sessionBadgeState(session.status)}>
              {displayLabel}
            </StatusBadge>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-meta text-hal-muted">
            <StatusDot state={sessionDotState(session.status)} />
            <span className="font-mono text-hal-primary">{session.session_id}</span>
            <span>{formatTimestamp(session.created_at)}</span>
            <span>{session.turn_count} turns</span>
            <span>{eventsCount} events</span>
            {showSocketState ? <Tag>{socketLabel(socketState)}</Tag> : null}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleBriefPanel}
            aria-pressed={briefPanelOpen}
            className={cn(
              briefPanelOpen && "bg-hal-panel text-hal-primary",
            )}
          >
            {briefPanelOpen ? "Hide brief" : "Thread brief"}
          </Button>
          {canEditScope ? (
            <Button variant="secondary" size="sm" onClick={onEditScope}>
              Scope
            </Button>
          ) : null}
          {canEndSession ? (
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
          ) : null}
        </div>
      </div>

      {/* Row 3: mounted thread tags */}
      {session.mounted_threads.length > 0 ? (
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-subtle pt-4">
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
      ) : null}
    </header>
  );
}

// ---------------------------------------------------------------------------
// TurnCard
// ---------------------------------------------------------------------------

function TurnCard({
  turn,
  expanded,
  onToggleEvidence,
}: {
  turn: TurnViewModel;
  expanded: boolean;
  onToggleEvidence: () => void;
}) {
  // Evidence seam: 2px left border. Active color when expanded or turn is running.
  const seamActive = expanded || turn.state === "running";
  const seamColor = seamActive
    ? "var(--turn-seam-active)"
    : "var(--turn-seam-color)";

  return (
    <article
      className={cn(
        "hal-paper overflow-hidden rounded-[20px] border border-border bg-hal-panel shadow-sm",
        turn.hasEvidence && "border-l-[2px]",
      )}
      style={turn.hasEvidence ? { borderLeftColor: seamColor } : undefined}
    >
      {/* Turn header */}
      <header className="flex items-center justify-between gap-3 border-b border-subtle px-4 py-3.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-caption text-hal-muted">{turn.turnId}</span>
          <StatusBadge state={turnBadgeState(turn.state)}>{turn.state}</StatusBadge>
          {turn.origin === "background_resume" ? (
            <Tag>background</Tag>
          ) : null}
        </div>

        <div className="flex items-center gap-3">
          <span
            className="text-caption text-hal-muted"
            title={formatTimestamp(turn.startedAt)}
          >
            {formatRelativeTime(turn.startedAt)}
          </span>
          {turn.hasEvidence ? (
            <button
              type="button"
              onClick={onToggleEvidence}
              aria-expanded={expanded}
              className="rounded-full border border-subtle px-2.5 py-1 text-caption font-medium uppercase tracking-[0.12em] text-hal-muted transition-colors duration-fast ease-standard hover:border-border hover:text-hal-primary"
            >
              {expanded ? "hide evidence" : `evidence (${totalEvidenceCount(turn)})`}
            </button>
          ) : null}
        </div>
      </header>

      {/* Activity layer */}
      <div className="space-y-3 px-4 py-4">
        {turn.activityItems.length === 0 ? (
          <p className="text-body text-hal-muted">No activity captured.</p>
        ) : (
          turn.activityItems.map((item) => (
            <ActivityRow key={item.seq} item={item} turn={turn} />
          ))
        )}
      </div>

      {/* Evidence layer (expanded) */}
      {turn.hasEvidence && expanded ? (
        <div className="border-t border-subtle">
          <EvidenceBlock turn={turn} />
        </div>
      ) : null}
    </article>
  );
}

// ---------------------------------------------------------------------------
// ActivityRow — dispatches on item.kind
// ---------------------------------------------------------------------------

function ActivityRow({
  item,
  turn,
}: {
  item: ActivityItem;
  turn: TurnViewModel;
}) {
  switch (item.kind) {
    case "user_message":
      return <UserMessageRow item={item} />;
    case "assistant_output":
      return <AssistantOutputRow item={item} turn={turn} />;
    case "tool_result":
      return <ToolResultRow item={item} />;
    case "message_injected":
      return <MessageInjectedRow item={item} />;
    case "subagent_completed":
      return <SubagentCompletedRow item={item} />;
    case "turn_failed":
      return <TurnFailedRow item={item} />;
    default:
      return null;
  }
}

function UserMessageRow({ item }: { item: ActivityItem }) {
  return (
    <Panel
      surface="base"
      border
      className="rounded-[18px] border-l-2 border-l-human bg-hal-human-subtle px-4 py-3.5"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <Tag variant="human">You</Tag>
        <span
          className="text-caption text-hal-muted"
          title={formatTimestamp(item.ts)}
        >
          {formatRelativeTime(item.ts)}
        </span>
      </div>
      <MarkdownBlock content={item.content} />
    </Panel>
  );
}

function AssistantOutputRow({
  item,
  turn,
}: {
  item: ActivityItem;
  turn: TurnViewModel;
}) {
  // Match the convenience projection to get tools/iterations metadata.
  const output =
    turn.assistantOutput?.seq === item.seq ? turn.assistantOutput : undefined;

  return (
    <Panel
      surface="base"
      border
      className="rounded-[18px] border-l-2 border-l-accent bg-[rgba(255,255,255,0.72)] px-4 py-3.5"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Tag variant="accent">HaL</Tag>
          {output?.iterations ? (
            <span className="text-caption text-hal-muted">
              {output.iterations} iteration{output.iterations === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>
        <span
          className="text-caption text-hal-muted"
          title={formatTimestamp(item.ts)}
        >
          {formatRelativeTime(item.ts)}
        </span>
      </div>

      <MarkdownBlock content={item.content} />

      {output?.toolsUsed && output.toolsUsed.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {output.toolsUsed.map((tool) => (
            <Tag key={`${item.seq}-${tool}`}>{tool}</Tag>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

function ToolResultRow({ item }: { item: ActivityItem }) {
  return (
    <div className="flex items-center gap-2 rounded-[16px] border border-subtle bg-[rgba(255,255,255,0.38)] px-3 py-2">
      <StatusDot state={toolDotState(item.status)} />
      <span className="font-mono text-meta text-hal-primary">
        {item.toolName ?? "tool"}
      </span>
      <span className="min-w-0 flex-1 truncate text-meta text-hal-muted">
        {item.brief ?? "completed"}
      </span>
      <span
        className="shrink-0 text-caption text-hal-muted"
        title={formatTimestamp(item.ts)}
      >
        {formatRelativeTime(item.ts)}
      </span>
    </div>
  );
}

function MessageInjectedRow({ item }: { item: ActivityItem }) {
  return (
    <Panel surface="inset" className="rounded-[18px] px-4 py-3.5">
      <div className="mb-2 flex items-center justify-between gap-3">
        <Tag>Injected</Tag>
        <span
          className="text-caption text-hal-muted"
          title={formatTimestamp(item.ts)}
        >
          {formatRelativeTime(item.ts)}
        </span>
      </div>
      <MarkdownBlock content={item.content} muted />
    </Panel>
  );
}

function SubagentCompletedRow({ item }: { item: ActivityItem }) {
  return (
    <div className="flex items-center gap-2 rounded-[16px] border border-subtle bg-[rgba(255,255,255,0.3)] px-3 py-2">
      <StatusBadge state={workerBadgeState(item.status)}>
        {item.status ?? "completed"}
      </StatusBadge>
      <span className="text-meta text-hal-primary">Subagent</span>
      {item.brief ? (
        <span className="min-w-0 flex-1 truncate text-meta text-hal-muted">
          {item.brief}
        </span>
      ) : null}
      <span
        className="shrink-0 text-caption text-hal-muted"
        title={formatTimestamp(item.ts)}
      >
        {formatRelativeTime(item.ts)}
      </span>
    </div>
  );
}

function TurnFailedRow({ item }: { item: ActivityItem }) {
  return (
    <Panel
      surface="base"
      border
      className="rounded-[18px] border-danger bg-hal-danger-subtle px-4 py-3.5"
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <StatusBadge state="danger">failed</StatusBadge>
        <span
          className="text-caption text-danger"
          title={formatTimestamp(item.ts)}
        >
          {formatRelativeTime(item.ts)}
        </span>
      </div>
      <p className="text-body text-danger">
        {item.error ?? "Turn failed without an error payload."}
      </p>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// EvidenceBlock — inset record well for diagnostic events
// ---------------------------------------------------------------------------

function EvidenceBlock({ turn }: { turn: TurnViewModel }) {
  const counts = [
    { label: "context", value: turn.evidenceCounts.context },
    { label: "loop", value: turn.evidenceCounts.loop },
    { label: "tool", value: turn.evidenceCounts.tool },
    { label: "injection", value: turn.evidenceCounts.injection },
    { label: "worker", value: turn.evidenceCounts.worker },
  ].filter((c) => c.value > 0);

  return (
    <div className="rounded-b-[18px] bg-hal-inset px-4 py-3.5">
      {/* Evidence summary counts */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-meta font-medium text-hal-primary">Evidence</span>
        {counts.map((c) => (
          <Tag key={c.label}>
            {c.label}: {c.value}
          </Tag>
        ))}
      </div>

      {/* Flat event list */}
      <div className="mt-3 space-y-1.5">
        {turn.evidenceEvents.map((event) => (
          <div
            key={event.seq}
            className="flex items-start gap-2 rounded-[14px] border border-subtle bg-hal-canvas px-3 py-2"
          >
            <span
              className="shrink-0 font-mono text-caption text-hal-muted"
              title={formatTimestamp(event.ts)}
            >
              {formatTimestamp(event.ts)}
            </span>
            <Tag>{event.type}</Tag>
            <code className="min-w-0 flex-1 truncate font-mono text-caption text-hal-primary">
              {summarizePayload(event)}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SessionActivityRow — compact session-level events
// ---------------------------------------------------------------------------

function SessionActivityRow({ item }: { item: SessionActivityItem }) {
  return (
    <div className="flex items-center gap-2 rounded-[16px] border border-subtle bg-[rgba(255,255,255,0.3)] px-3 py-2">
      <StatusBadge state={sessionActivityBadgeState(item.kind)}>
        {item.title}
      </StatusBadge>
      {item.brief ? (
        <span className="min-w-0 flex-1 truncate text-meta text-hal-muted">
          {item.brief}
        </span>
      ) : null}
      <span
        className="ml-auto shrink-0 text-caption text-hal-muted"
        title={formatTimestamp(item.ts)}
      >
        {formatRelativeTime(item.ts)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MarkdownBlock — shared prose renderer
// ---------------------------------------------------------------------------

function MarkdownBlock({
  content,
  muted = false,
}: {
  content?: string;
  muted?: boolean;
}) {
  const text = content?.trim().length ? content : "_No content_";

  return (
    <div
      className={cn(
        "prose prose-mineral max-w-none text-body",
        muted && "opacity-70",
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
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

function turnBadgeState(state: TurnViewModel["state"]): BadgeState {
  switch (state) {
    case "running":
      return "live";
    case "completed":
      return "success";
    case "failed":
      return "danger";
  }
}

function toolDotState(status?: string): DotState {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "running":
      return "live";
    default:
      return "muted";
  }
}

function workerBadgeState(status?: string): BadgeState {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
      return "danger";
    case "running":
      return "live";
    default:
      return "muted";
  }
}

function sessionActivityBadgeState(kind: SessionActivityItem["kind"]): BadgeState {
  switch (kind) {
    case "scope_updated":
      return "warning";
    case "brief_completed":
      return "success";
  }
}

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

function socketLabel(state: SocketState): string {
  switch (state) {
    case "live":
      return "stream live";
    case "connecting":
      return "connecting";
    case "disconnected":
      return "disconnected";
  }
}

function totalEvidenceCount(turn: TurnViewModel): number {
  const c = turn.evidenceCounts;
  return c.context + c.loop + c.tool + c.injection + c.worker;
}

function summarizePayload(event: SessionEvent): string {
  const payload = event.payload;
  if (Object.keys(payload).length > 0) {
    return truncateStr(JSON.stringify(payload));
  }
  const refs = event.refs;
  if (Object.keys(refs).length > 0) {
    return truncateStr(JSON.stringify(refs));
  }
  return "no payload";
}

function truncateStr(value: string): string {
  if (value.length <= PAYLOAD_PREVIEW_LIMIT) return value;
  return `${value.slice(0, PAYLOAD_PREVIEW_LIMIT - 3)}...`;
}
