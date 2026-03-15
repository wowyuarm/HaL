/**
 * HalAssistantMessage — renders an assistant message with tool call parts.
 *
 * Uses assistant-ui primitives for context binding. Tool calls render as
 * compact rows (matching HaL's existing ToolResultRow style). Text parts
 * render as markdown with prose-mineral styling.
 */

import { MessagePrimitive, useMessage } from "@assistant-ui/react";
import type { TextMessagePartProps, ToolCallMessagePartProps } from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { StatusDot } from "@/components/ui/status-dot";
import { Tag } from "@/components/ui/tag";
import { summarizeEvidenceKinds } from "@/lib/evidence";
import { formatRelativeTime, formatTimestamp } from "@/lib/runtime";
import type { HalMessageMeta } from "@/lib/session-adapter";
import { useHalStore } from "@/lib/store";

export function HalAssistantMessage() {
  const createdAt = useMessage((s) => s.createdAt);
  const isRunning = useMessage((s) => s.status?.type === "running");
  const isFailed = useMessage((s) => s.status?.type === "incomplete");
  const custom = useMessage(
    (s) => s.metadata?.custom as HalMessageMeta | undefined,
  );
  const openInspector = useHalStore((s) => s.openInspector);
  const ts = createdAt?.toISOString() ?? "";

  const evidenceCounts = custom?.evidenceCounts;
  const totalEvidence = evidenceCounts
    ? Object.values(evidenceCounts).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <MessagePrimitive.Root
      className={
        isFailed
          ? "rounded-md border border-danger bg-hal-danger-subtle px-4 py-3.5"
          : "rounded-md border border-border border-l-2 border-l-accent bg-hal-panel px-4 py-3.5"
      }
    >
      {/* Header */}
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Tag variant="accent">HaL</Tag>
          {isRunning && <StatusDot state="live" />}
          {custom?.origin === "background_resume" && <Tag>background</Tag>}
        </div>
        <div className="flex items-center gap-2">
          {ts && (
            <span className="text-caption text-hal-muted" title={formatTimestamp(ts)}>
              {formatRelativeTime(ts)}
            </span>
          )}
        </div>
      </div>

      {/* Content parts */}
      <MessagePrimitive.Content components={ASSISTANT_CONTENT_COMPONENTS} />

      {totalEvidence > 0 && custom?.turnId && evidenceCounts && (
        <button
          type="button"
          onClick={() => openInspector(custom.turnId!)}
          className="group mt-3 flex w-full items-stretch overflow-hidden rounded-md border border-subtle bg-hal-paper text-left transition-all duration-fast ease-standard hover:border-accent hover:bg-hal-float"
        >
          <span className="w-[3px] shrink-0 bg-[color:var(--turn-seam-color)] transition-colors duration-fast ease-standard group-hover:bg-[color:var(--turn-seam-active)]" />
          <span className="flex min-w-0 flex-1 items-center justify-between gap-3 px-3 py-2.5">
            <span className="min-w-0">
              <span className="hal-meta-kicker">Evidence</span>
              <span className="mt-1 block truncate text-meta text-hal-primary">
                {summarizeEvidenceKinds(evidenceCounts)}
              </span>
            </span>
            <span className="shrink-0 text-caption text-hal-muted">
              {totalEvidence} record{totalEvidence === 1 ? "" : "s"}
            </span>
          </span>
        </button>
      )}
    </MessagePrimitive.Root>
  );
}

function AssistantTextPart({ text }: TextMessagePartProps) {
  if (!text?.trim()) return null;

  return (
    <div className="prose prose-mineral max-w-none text-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function HalToolCallPart({ toolName, result, isError }: ToolCallMessagePartProps) {
  const dotState = isError ? "danger" : "success";
  const brief = typeof result === "string" ? truncate(result, 100) : "completed";

  return (
    <div className="my-1.5 flex items-center gap-2 rounded-md border border-subtle bg-hal-paper px-3 py-2">
      <StatusDot state={dotState} />
      <span className="font-mono text-meta text-hal-primary">{toolName}</span>
      <span className="min-w-0 flex-1 truncate text-meta text-hal-muted">{brief}</span>
    </div>
  );
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 3)}...`;
}

const ASSISTANT_CONTENT_COMPONENTS = {
  Text: AssistantTextPart,
  tools: { Fallback: HalToolCallPart },
} as const;
