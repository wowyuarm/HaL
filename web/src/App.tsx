/**
 * App — Root component.
 *
 * Wires together the WebSocket connection, Zustand store, and all UI
 * components into the Research Desk layout.
 *
 * Phase 1 sends messages directly via WebSocket + optimistic store inserts.
 * assistant-ui ExternalStoreRuntime is kept as a dependency but not wired
 * here until Phase 2 streaming or assistant-ui primitives are needed.
 */
import { Composer } from "@/components/chat/composer";
import { MessageList } from "@/components/chat/message-list";
import { ContextSummary } from "@/components/context/context-summary";
import { ThreadList } from "@/components/thread/thread-list";
import { useHalStore } from "@/lib/store";
import { useWebSocket } from "@/lib/ws";

export default function App() {
  const { send, connected } = useWebSocket();

  const messages = useHalStore((s) => s.messages);
  const threads = useHalStore((s) => s.threads);
  const activeThread = useHalStore((s) => s.activeThread);
  const status = useHalStore((s) => s.status);
  const contextSummary = useHalStore((s) => s.contextSummary);

  // Thread selection is optimistic in Phase 1 (single-user, no ack needed).
  // Phase 2 should wait for server confirmation before updating activeThread.
  const handleSelectThread = (slug: string) => {
    const ok = send({ type: "select_thread", slug });
    if (ok) {
      useHalStore.getState().selectThread(slug);
    }
  };

  const handleSend = (content: string) => {
    let ok: boolean;

    if (content.startsWith("/")) {
      // Slash command
      const name = content.slice(1).split(/\s+/)[0];
      if (!name) return;
      ok = send({ type: "command", name: name as "brief" | "drop" | "context", args: {} });
    } else {
      // Regular message
      ok = send({ type: "message", content });
    }

    // Only insert optimistic message if the socket accepted the frame.
    if (ok) {
      useHalStore.getState().addUserMessage(content);
    }
  };

  const activeThreadData = threads.find((t) => t.slug === activeThread);

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <aside className="flex h-screen w-[240px] shrink-0 flex-col border-r border-border bg-panel">
        {/* Thread list */}
        <div className="flex-1 overflow-y-auto px-3 py-4">
          <p className="px-2 text-xs font-medium uppercase tracking-widest text-muted">
            Threads
          </p>
          <div className="mt-3">
            <ThreadList
              threads={threads}
              activeThread={activeThread}
              onSelect={handleSelectThread}
            />
          </div>
        </div>

        {/* Context summary */}
        <div className="border-t border-border px-3 py-4">
          <p className="px-2 text-xs font-medium uppercase tracking-widest text-muted">
            Context
          </p>
          <div className="mt-2">
            <ContextSummary
              summary={contextSummary}
              status={status}
              connected={connected}
            />
          </div>
        </div>
      </aside>

      {/* Main area */}
      <main className="flex h-screen flex-1 flex-col bg-background">
        {/* Title bar */}
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-5">
          <h1 className="text-sm font-semibold text-foreground">
            {activeThreadData?.name ?? "HaL"}
          </h1>
          {activeThreadData?.scope && (
            <span className="rounded-sm border border-border bg-elevated px-1.5 py-0.5 font-mono text-[11px] text-muted">
              {activeThreadData.scope}
            </span>
          )}
          {!connected && (
            <span className="rounded-sm bg-danger-subtle px-1.5 py-0.5 text-[11px] font-medium text-danger">
              disconnected
            </span>
          )}
        </header>

        {/* Message area */}
        <MessageList messages={messages} />

        {/* Composer */}
        <Composer
          onSend={handleSend}
          disabled={!connected || status === "processing"}
        />
      </main>
    </div>
  );
}
