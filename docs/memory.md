# Memory System

HaL uses a multi-tier memory architecture coordinated by `MemoryManager` (`hal/core/memory/manager.py`).

## Components

### DailyLog (`daily_log.py`)

Append-only JSONL logs of all interactions, organized by date.

- **Location**: `<workspace>/logs/YYYY-MM-DD.jsonl`
- **Format**: Each line is a JSON object with `role`, `content`, `timestamp`, and optional metadata
- **Purpose**: Complete interaction record; source data for daily export and semantic search

### LongTermMemory (`long_term.py`)

Persistent knowledge stored in the workspace's `MEMORY.md` file.

- **Location**: `<workspace>/memory/MEMORY.md`
- **Format**: Markdown, structured by topic
- **Usage**: The agent reads and writes this file to store important facts, user preferences, and knowledge that should persist across sessions
- **Injected at**: Layer 3 of the context builder

### Semantic Search (`search.py`, `store.py`)

Optional vector-based memory search using Milvus Lite.

- **VectorStore** (`store.py`) — Manages a Milvus collection with embedding vectors
- **MemorySearch** (`search.py`) — Orchestrates search: chunks markdown, computes embeddings, queries the store
- **MarkdownChunker** (`chunker.py`) — Splits markdown files into overlapping chunks for indexing
- **DailyExporter** (`exporter.py`) — Converts daily JSONL logs into markdown files for indexing

### Search Pipeline

1. **Backfill** (on startup): Export existing daily logs → chunk → embed → index
2. **Daily export** (midnight): Export yesterday's log → chunk → embed → index
3. **Query** (per request): Embed the query → search the vector store → return top-K relevant chunks
4. **Auto-inject**: If enabled, top-K results are injected into Layer 3 of the context

### Configuration

In `~/.hal/config.yaml` under `memory_search`:

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | Enable semantic memory search |
| `embedding_model` | `text-embedding-3-small` | Model for computing embeddings |
| `embedding_provider` | `null` | Provider name for embeddings (auto-detected if null) |
| `embedding_dim` | `1536` | Embedding vector dimension |
| `max_chunk_size` | `1000` | Maximum chunk size in characters |
| `chunk_overlap_lines` | `3` | Number of overlapping lines between chunks |
| `milvus_uri` | `~/.hal/milvus.db` | Milvus Lite database path |
| `collection_name` | `hal_memory` | Milvus collection name |
| `auto_inject_top_k` | `3` | Number of chunks to auto-inject per request |

## Data Flow

```
User interaction
    │
    ▼
DailyLog (append JSONL)
    │
    ├──► LongTermMemory (agent writes MEMORY.md via fs tool)
    │
    └──► DailyExporter (midnight export)
            │
            ▼
        MarkdownChunker
            │
            ▼
        VectorStore (Milvus)
            │
            ▼
        MemorySearch.query() → Context Layer 3
```

## File Layout

```
<workspace>/
├── logs/                    # DailyLog JSONL files
│   ├── 2025-01-15.jsonl
│   └── ...
├── memory/
│   ├── MEMORY.md            # LongTermMemory
│   └── daily/               # Exported markdown (for indexing)
│       ├── 2025-01-15.md
│       └── ...
├── AGENTS.md                # Agent instructions (Layer 1)
├── SOUL.md                  # Agent personality (Layer 1)
└── USER.md                  # User information (Layer 1)
```
