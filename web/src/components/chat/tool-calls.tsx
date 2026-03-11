/**
 * ToolCalls — Collapsible list of tool invocations attached to a message.
 *
 * Default collapsed with "N tool calls" summary. Click to expand/collapse
 * with a 180ms CSS grid-row height transition.
 */

import { useState } from "react";

import type { ToolCall } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Status indicator symbol + color mapping. */
const STATUS_CONFIG = {
  completed: { symbol: "\u2713", className: "text-accent" },
  failed: { symbol: "\u2717", className: "text-danger" },
  running: { symbol: "\u27F3", className: "text-muted" },
} as const;

interface ToolCallsProps {
  toolCalls: ToolCall[];
  className?: string;
}

export function ToolCalls({ toolCalls, className }: ToolCallsProps) {
  const [expanded, setExpanded] = useState(false);

  if (toolCalls.length === 0) return null;

  return (
    <section className={cn("mt-3", className)}>
      {/* Toggle button */}
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="text-xs text-muted transition-colors duration-fast ease-standard hover:text-foreground"
        aria-expanded={expanded}
      >
        {expanded ? "\u25BE" : "\u25B8"} {toolCalls.length} tool call
        {toolCalls.length !== 1 && "s"}
      </button>

      {/* Expandable body — CSS grid-row transition for smooth height animation */}
      <div
        className="grid transition-[grid-template-rows] duration-normal ease-standard"
        style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          <div className="mt-2 space-y-1">
            {toolCalls.map((tc) => {
              const status = STATUS_CONFIG[tc.status];
              return (
                <div
                  key={tc.id}
                  className="flex items-center gap-3 rounded-sm border border-subtle px-3 py-1.5"
                >
                  {/* Status indicator (symbol + text) */}
                  <span className={cn("flex shrink-0 items-center gap-1 text-xs", status.className)}>
                    <span className="text-sm" aria-hidden>{status.symbol}</span>
                    {tc.status}
                  </span>

                  {/* Tool name */}
                  <span className="shrink-0 font-mono text-xs text-foreground">{tc.name}</span>

                  {/* Args summary */}
                  <span className="min-w-0 truncate text-xs text-muted">
                    {tc.args_summary}
                  </span>

                  {/* Error detail (failed only) */}
                  {tc.error && (
                    <span className="ml-auto shrink-0 text-xs text-danger">{tc.error}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
