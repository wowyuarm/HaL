/**
 * MainArea — Center panel (flexible width).
 *
 * Three vertical sections:
 *   1. Title bar — thread name + scope tag
 *   2. Message area — scrollable conversation (placeholder)
 *   3. Composer — input area with send button (placeholder)
 *
 * This is a visual skeleton only — no interactivity yet.
 */
export function MainArea() {
  return (
    <main className="flex min-h-screen flex-1 flex-col bg-background">
      {/* Title bar */}
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-5">
        <h1 className="text-sm font-semibold text-foreground">Thread Title</h1>
        <span className="rounded-sm border border-border bg-elevated px-1.5 py-0.5 font-mono text-[11px] text-muted">
          project
        </span>
      </header>

      {/* Message area */}
      <div className="flex-1 overflow-y-auto px-5 py-6">
        <div className="mx-auto max-w-3xl">
          <p className="text-sm text-muted">Messages will appear here.</p>
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-border px-5 py-3">
        <div className="mx-auto flex max-w-3xl items-end gap-3">
          <div className="flex-1 rounded-md border border-border bg-inset px-3 py-2">
            <textarea
              className="w-full resize-none bg-transparent text-sm text-foreground outline-none placeholder:text-muted"
              placeholder="Type a message or /command..."
              rows={2}
              disabled
            />
          </div>
          <button
            type="button"
            disabled
            className="shrink-0 rounded-md bg-accent px-4 py-2 text-sm font-medium text-on-accent transition-colors duration-fast ease-standard disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </main>
  );
}
