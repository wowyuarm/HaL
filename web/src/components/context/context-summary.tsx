/**
 * ContextSummary — Engine status indicator and compact context metrics.
 *
 * Shows a colored dot for engine state (idle/processing/disconnected),
 * and three metric rows: ctx tokens, tools available, history messages.
 * Token counts are formatted as "12.1k" when exceeding 999.
 */

import type { ContextSummaryData } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ContextSummaryProps {
  summary: ContextSummaryData;
  status: "idle" | "processing";
  connected: boolean;
  className?: string;
}

/** Row definitions for the metrics display. */
const METRIC_ROWS = [
  { key: "tokens", label: "ctx" },
  { key: "tools", label: "tools" },
  { key: "history", label: "hist" },
] as const;

export function ContextSummary({ summary, status, connected, className }: ContextSummaryProps) {
  const stateDisplay = resolveStateDisplay(status, connected);

  return (
    <div className={cn("rounded-md border border-border bg-elevated p-3", className)}>
      {/* Engine state indicator */}
      <div className={cn("mb-2 flex items-center gap-1.5 text-xs", stateDisplay.textClass)}>
        <span
          className={cn("inline-block h-1.5 w-1.5 rounded-full", stateDisplay.dotClass)}
          aria-hidden
        />
        {stateDisplay.label}
      </div>

      {/* Key metrics */}
      <dl className="space-y-1 font-mono text-xs tabular-nums text-muted">
        {METRIC_ROWS.map((row) => (
          <div key={row.label} className="flex items-center justify-between gap-4">
            <dt>{row.label}</dt>
            <dd className="text-foreground">
              {connected ? formatMetricValue(summary[row.key]) : "--"}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Derive dot style, text class, and label from connection + processing state. */
function resolveStateDisplay(status: "idle" | "processing", connected: boolean) {
  if (!connected) {
    return { dotClass: "bg-muted", textClass: "text-muted", label: "disconnected" };
  }
  if (status === "processing") {
    return { dotClass: "bg-accent animate-pulse", textClass: "text-accent", label: "processing" };
  }
  return { dotClass: "bg-accent", textClass: "text-accent", label: "idle" };
}

/**
 * Format a numeric metric for compact display.
 * Values <= 999 shown as-is. Larger values always show one decimal: "1.2k", "12.1k".
 * Trailing ".0" is stripped for clean integers (e.g. 2000 -> "2k").
 */
function formatMetricValue(value: number): string {
  if (value <= 999) return String(value);

  const formatted = (value / 1000).toFixed(1);
  // Strip trailing ".0" for clean display (e.g. 2000 -> "2k" not "2.0k").
  return formatted.endsWith(".0") ? `${formatted.slice(0, -2)}k` : `${formatted}k`;
}
