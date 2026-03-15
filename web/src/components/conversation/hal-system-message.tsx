/**
 * HalSystemMessage — compact notification row for session-level events.
 *
 * Renders scope updates, brief completions, and injected messages as
 * centered notification rows, not conversation bubbles.
 */

import { MessagePrimitive, useMessage } from "@assistant-ui/react";

import { formatRelativeTime, formatTimestamp } from "@/lib/runtime";

export function HalSystemMessage() {
  const createdAt = useMessage((s) => s.createdAt);
  const firstText = useMessage((s) => {
    const part = s.content[0];
    return part?.type === "text" ? part.text : "";
  });
  const ts = createdAt?.toISOString() ?? "";

  const badgeState = firstText.startsWith("Scope")
    ? "warning"
    : firstText.startsWith("Brief")
      ? "success"
      : "muted";

  const title = firstText.startsWith("Scope")
    ? "Scope"
    : firstText.startsWith("Brief")
      ? "Brief"
      : "System";

  const titleClass =
    badgeState === "warning"
      ? "text-warning font-semibold"
      : badgeState === "success"
        ? "text-success font-semibold"
        : "text-hal-muted font-semibold";

  return (
    <MessagePrimitive.Root className="flex items-center gap-2 rounded-md border border-subtle bg-hal-paper px-3 py-1.5">
      <span className={`text-caption ${titleClass}`}>{title}</span>
      <span className="min-w-0 flex-1 truncate text-meta text-hal-muted">{firstText}</span>
      {ts && (
        <span
          className="ml-auto shrink-0 text-caption text-hal-muted"
          title={formatTimestamp(ts)}
        >
          {formatRelativeTime(ts)}
        </span>
      )}
    </MessagePrimitive.Root>
  );
}
