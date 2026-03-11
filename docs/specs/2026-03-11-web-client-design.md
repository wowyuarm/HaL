# HaL Web Client — Design Spec

**Date:** 2026-03-11
**Status:** Approved
**Scope:** MVP (Phase 1)

## 1. Motivation

HaL is evolving from an async IM-based interaction model (Telegram) to a
simultaneous online collaboration system. Telegram's limitations:

- Poor reading experience for long, structured responses
- No visibility into tool activity or context state during processing
- No real-time collaboration affordances (intervene mid-loop, inspect context)
- IM framing ("messages") conflicts with HaL's thread-centric collaboration model

The web client provides a dedicated collaboration surface that embodies HaL's
design invariants.

## 2. Design Decisions

| Dimension        | Choice                | Rationale                                      |
|------------------|-----------------------|------------------------------------------------|
| Spatial metaphor | Research Desk         | Thread sidebar + main conversation + context   |
| Color palette    | Mineral (light-first) | Warm, steady, professional — not SaaS/terminal |
| Visual feel      | Architectural         | Thin borders, small radii, restrained motion   |
| Message style    | Document Flow         | No bubbles; flat layout with accent left-bar   |
| Frontend stack   | React + shadcn/ui     | Composable, lightweight, full visual control   |
| Runtime          | assistant-ui ExternalStoreRuntime | Engine owns state; client is a mirror |
| Transport        | WebSocket (JSON)      | Async-native, bidirectional, extensible        |

## 3. System Architecture

```
HaL Engine (Python)
├── AgentEngine ── MessageBus ── WebChannel (new BaseChannel impl)
│                                    │
│                              WebSocket Server (aiohttp)
│                                    │
════════════════════════════════════════════  Network
                                     │
Web Client (React)                   │
├── WebSocket connection ◄───────────┘
├── Client Store (Zustand) ◄── engine state mirror
├── ExternalStoreRuntime ◄── assistant-ui adapter
└── React UI (shadcn/ui) ◄── Document Flow components
```

### Data flow principle

**Unidirectional truth:** Engine → WebSocket → Client Store → UI.
The client holds no independent state. It is a projection of engine state.

### WebChannel integration

`WebChannel` extends `BaseChannel` with additional bus event subscriptions.
Beyond the standard `send(OutboundMessage)` path, it subscribes to:

- **ToolCallEvent** → pushes tool call status updates (Phase 2, live progress)
- **Engine status** → pushes `status` messages on processing start/end

For Phase 1, most data flows through `send()` with enriched `OutboundMessage`
metadata. The engine populates `metadata.tool_calls` and `metadata.tokens`
before publishing outbound messages. Context summary and thread list are
pushed by `WebChannel` itself, which reads workspace state directly
(thread repository, context metrics) on connect and after each engine turn.

This means `WebChannel` has two dependencies beyond `BaseChannel`:
1. `MessageBus` (inherited) — for standard message flow
2. `WorkspaceLayout` — for reading thread list and context metrics

Both are injected at construction time via `ChannelManager._init_channels()`.

### WebSocket protocol

#### Connection lifecycle

On connect, the server sends a `snapshot` message containing full state. This
is also sent on reconnect, allowing the client to rebuild its store from
scratch without local persistence.

```jsonc
// Server → Client (on connect)
{ "type": "snapshot",
  "session_id": "s_abc123",
  "active_thread": "thread-slug",
  "threads": [
    { "slug": "auth-refactor", "name": "Auth Refactor", "scope": "project",
      "last_active": "2026-03-11T14:02:00Z" }
  ],
  "history": [
    { "id": "msg_001", "role": "user", "content": "...", "ts": "...",
      "metadata": {} },
    { "id": "msg_002", "role": "assistant", "content": "...", "ts": "...",
      "metadata": { "tool_calls": [
        { "id": "tc_01", "name": "fs_read", "args_summary": "auth.py",
          "status": "completed" }
      ] } }
  ],
  "context_summary": { "tokens": 12000, "tools": 14, "history": 8 },
  "status": "idle"
}
```

#### Client → Server

```jsonc
{ "type": "message", "content": "..." }
{ "type": "command", "name": "brief" | "drop" | "context", "args": {} }
{ "type": "select_thread", "slug": "thread-slug" }
```

#### Server → Client (incremental updates)

```jsonc
// New message in conversation
{ "type": "message", "id": "msg_003", "role": "assistant", "content": "...",
  "ts": "2026-03-11T14:03:00Z",
  "metadata": {
    "tool_calls": [
      { "id": "tc_02", "name": "exec", "args_summary": "ruff check",
        "status": "completed" },
      { "id": "tc_03", "name": "fs_write", "args_summary": "auth.py",
        "status": "failed", "error": "permission denied" }
    ]
  }
}

// Engine status change
{ "type": "status", "state": "processing" | "idle" }

// Thread list update (after /brief creates episode, thread changes, etc.)
{ "type": "threads", "list": [...] }

// Context summary update (after each engine turn)
{ "type": "context_summary", "tokens": 12000, "tools": 14, "history": 8 }

// Error
{ "type": "error", "message": "..." }
```

#### Tool call schema

Each tool call in message metadata has:

```jsonc
{
  "id": "tc_01",              // Stable ID for deduplication
  "name": "fs_read",          // Tool name
  "args_summary": "auth.py",  // Human-readable argument summary
  "status": "completed" | "failed" | "running",
  "error": "..."              // Only present when status = "failed"
}
```

Phase 1 tool calls are post-hoc records (included in the final message).
Live tool-progress events are deferred to Phase 2 streaming work.

#### Thread switching

`select_thread` tells the engine to change the active thread context. The
server responds with a new `snapshot` for the selected thread's conversation
history. Phase 1 uses a single global session — switching threads changes
which thread's context is loaded, not the session itself.

Extensible without breaking changes — new `type` values are ignored by older
clients.

## 4. Visual Design Language

### 4.1 Color system (Light Mineral)

Semantic tokens, not raw values. Dark theme = swap one layer of mappings.

```
Token                   Light Value    Purpose
──────────────────────  ───────────    ─────────────────
--bg                    #F7F4EF        Page background (warm paper)
--bg-panel              #EFECE6        Sidebar, panels
--bg-elevated           #FFFFFF        Raised surfaces (cards, popovers)
--bg-inset              #E8E4DD        Recessed areas (input, code blocks)

--border                #D4CFC6        Default borders
--border-subtle         #E2DED7        Weak separators
--border-accent         #4A7A74        Accent border (selected state)

--text                  #24211D        Primary text
--text-muted            #7A756D        Secondary text
--text-on-accent        #FFFFFF        Text on accent surfaces

--accent                #4A7A74        System accent (deep teal)
--accent-subtle         #E8F0EF        Accent light background
--human                 #9A7840        Human intent marker (ochre)
--human-subtle          #F5EDE0        Human intent light background
--danger                #A25248        Error / danger
--danger-subtle         #FAEAE8        Error light background
```

### 4.2 Typography

| Voice | Font                    | Usage                                   |
|-------|-------------------------|-----------------------------------------|
| UI    | Inter / system sans     | Buttons, labels, nav, timestamps        |
| Prose | Inter (larger line-height) | Message body, BRIEF preview          |
| Data  | JetBrains Mono          | Code, token counts, event log, paths    |

No serif for now. Differentiate UI vs prose via size and line-height, not
typeface. Serif can be introduced later if reading experience demands it.

### 4.3 Borders, radii, shadows, motion

```
Radii       4px   Dense elements (badge, tag, inline code)
            6px   Cards, panels, inputs
            8px   Dialogs, modals
            No pill shapes

Borders     1px solid var(--border)
            Accent state: var(--border-accent)

Shadows     Popovers/modals only: 0 4px 12px rgba(0,0,0,0.08)
            Everything else: no shadow

Motion      120ms   State changes (hover, active, toggle)
            180ms   Panel expand/collapse
            ease-out curve
            No bounce / spring / parallax
            Tool call expand: height transition
            Loading: subtle pulse, no spinner dots
```

## 5. Layout

```
┌──────────┬──────────────────────────────────────────────┐
│          │  Thread Title                                │
│ THREADS  ├──────────────────────────────────────────────┤
│          │                                              │
│ ● active │  You                            14:02       │
│   item-b │  message content...                         │
│   item-c │                                              │
│          │  ────────────────────────────────────────    │
│          │                                              │
│ ──────── │  ▎ HaL                          14:03       │
│ CONTEXT  │  ▎ response with markdown...                │
│ ──────── │  ▎ ```python                                │
│ ◉ idle   │  ▎ code here                                │
│ ctx: 12k │  ▎ ```                                      │
│ tools: 14│  ▎ ▸ 2 tool calls                           │
│ hist: 8  │                                              │
│          ├──────────────────────────────────────────────┤
│          │  [input area]               (/cmd) [Send]   │
└──────────┴──────────────────────────────────────────────┘
```

### Sidebar (left, 240px fixed, collapsible)

**Thread list (upper):**
- Thread name + relative last-active time
- Active thread: `--border-accent` left mark + `--accent-subtle` background
- Click to switch thread

**Context summary (lower):**
- Engine state indicator: idle / processing (accent subtle pulse when processing)
- Key metrics: context tokens, tool count, history message count
- Mono font, tabular figures

### Main area (center, flexible width)

**Thread title bar:**
- Thread name + scope tag

**Conversation (Document Flow):**
- User messages: undecorated, left-aligned, muted timestamp right
- HaL messages: 2px `--accent` left bar, light `--accent-subtle` background
- Separators: `--border-subtle` thin line between messages
- Tool calls: collapsed inside HaL message, `▸ N tool calls` expandable
  - Expanded: tool name + param summary + status (✓/✗/⟳)
- Markdown: headings, lists, code blocks (syntax highlight), tables, links
- Code blocks: `--bg-inset`, mono font, language label, copy button

**Composer (bottom):**
- `--bg-inset` textarea, multiline
- Slash command autocomplete (`/brief`, `/drop`, `/context`)
- Enter to send, Shift+Enter for newline
- Send button right-aligned

### No right panel in MVP

Context summary lives in sidebar lower section. Full context inspector or
BRIEF preview can be added later as a sidebar tab or right drawer.

## 6. Project Structure

### Frontend

```
web/                               # Frontend (React SPA, Vite)
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── src/
│   ├── main.tsx                   # Vite entry point
│   ├── App.tsx                    # Root component
│   ├── components/
│   │   ├── layout/                # sidebar, main-area
│   │   ├── thread/                # thread-list, thread-item
│   │   ├── chat/                  # message-list, message, tool-calls, composer
│   │   └── context/               # context-summary
│   ├── lib/
│   │   ├── ws.ts                  # WebSocket connection + reconnect
│   │   ├── store.ts               # Zustand store (engine mirror)
│   │   └── runtime.ts             # assistant-ui ExternalStoreRuntime adapter
│   └── styles/
│       ├── globals.css            # Design tokens (CSS variables)
│       └── fonts.css
└── public/
```

### Backend (new files)

```
hal/channels/web/                  # New WebSocket channel
├── __init__.py                    # WebChannel(BaseChannel)
├── server.py                      # WebSocket server (aiohttp)
└── protocol.py                    # Message serialization / deserialization
```

### Backend (modified files)

| File | Change |
|------|--------|
| `hal/infra/config/schema.py` | Add `WebConfig` to `ChannelsConfig` |
| `hal/channels/manager.py` | Register `WebChannel` in `_init_channels()` |
| `hal/cli/commands/` | Add `hal web` command |
| `pyproject.toml` | Add `aiohttp` dependency |

## 7. MVP Scope

### In scope (Phase 1)

- `hal/channels/web/` — WebSocket channel (BaseChannel impl)
- `hal web` CLI command
- WebSocket connection with auto-reconnect
- Message send/receive, Document Flow rendering
- Markdown rendering + code syntax highlighting
- Tool call collapse/expand display
- Thread list + switching
- Slash commands via input (`/brief`, `/drop`, `/context`)
- Context summary (tokens, tools, history, engine state)
- Light Mineral theme

### Out of scope (Phase 2+)

- Dark theme (same token layer, different values)
- Token streaming (start with complete message push)
- BRIEF.md preview panel
- Episode browser
- File / artifact viewer
- Voice / media input
- Per-thread independent sessions
- Tauri desktop packaging
- Production deployment (dev server only)

## 8. Future Evolution Notes

- **Per-thread sessions:** The web client's thread navigation naturally supports
  giving each thread its own session context. This changes /brief and /drop
  semantics from global to per-thread. Deferred to Phase 2.
- **Multi-thread parallel work:** With sidebar navigation, users can context-switch
  between threads without losing session state. This is a new capability not
  possible in the Telegram channel.
- **Streaming:** The protocol supports adding `{ "type": "stream", "delta": "..." }`
  without breaking existing message types. Requires engine-level changes to expose
  LLM token stream through the bus.
- **Dark theme:** Same semantic tokens, different value layer. Implementation cost
  is low once the token system is in place.

## 9. Launch

```bash
# Backend
hal web --port 8765

# Frontend (dev)
cd web && npm run dev    # Vite dev server, proxies ws://localhost:8765
```
