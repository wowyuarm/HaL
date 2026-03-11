/**
 * Sidebar — Left panel (240px fixed width).
 *
 * Upper section: thread list placeholder.
 * Lower section: context summary with key metrics.
 *
 * This is a visual skeleton only — no interactivity yet.
 */

/** Metric row labels for the context summary section. */
const CONTEXT_METRICS = [
  { label: "ctx", value: "--" },
  { label: "tools", value: "--" },
  { label: "hist", value: "--" },
] as const;

export function Sidebar() {
  return (
    <aside className="flex h-screen w-[240px] shrink-0 flex-col border-r border-border bg-panel">
      {/* Thread list (upper) */}
      <div className="flex-1 overflow-y-auto px-3 py-4">
        <p className="px-2 text-xs font-medium uppercase tracking-widest text-muted">
          Threads
        </p>
      </div>

      {/* Context summary (lower) */}
      <div className="border-t border-border px-3 py-4">
        <p className="px-2 text-xs font-medium uppercase tracking-widest text-muted">
          Context
        </p>
        <div className="mt-2 rounded-md border border-border bg-elevated p-3">
          {/* Engine state indicator */}
          <div className="mb-2 flex items-center gap-1.5 text-xs text-accent">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent" />
            idle
          </div>
          {/* Key metrics */}
          <dl className="space-y-1 font-mono text-xs tabular-nums text-muted">
            {CONTEXT_METRICS.map((m) => (
              <div key={m.label} className="flex justify-between">
                <dt>{m.label}</dt>
                <dd className="text-foreground">{m.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </aside>
  );
}
