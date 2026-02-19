# Tool System

All agent tools in HaL extend the abstract `Tool` class and are managed by a `ToolRegistry`.

## Tool Contract

Every tool must implement:

```python
class Tool(ABC):
    name: str                           # Unique identifier (e.g., "fs", "exec")
    description: str                    # Shown to the LLM
    parameters: dict[str, Any]          # JSON Schema for parameters

    async def execute(self, **params) -> str:
        """Execute the tool and return a string result."""

    def get_side_effects(self, params) -> dict | None:
        """Return side-effect metadata, or None if read-only."""

    def validate_params(self, params) -> list[str]:
        """Validate against JSON schema. Returns error list."""
```

### Side-Effect Declaration

Tools that modify state override `get_side_effects()` to declare what they change:

| Tool | Side Effects |
|------|-------------|
| `FsTool` (write/edit) | `{"files_modified": ["path"]}` |
| `ExecTool` | `{"commands_run": ["cmd"]}` |
| Others | `None` (read-only) |

The engine uses this metadata to populate `LoopMetadata` for summary generation and audit.

## Built-in Tools

| Tool | Name | Actions | Description |
|------|------|---------|-------------|
| `FsTool` | `fs` | read, write, edit, list | Unified filesystem operations |
| `ExecTool` | `exec` | — | Shell command execution |
| `WebSearchTool` | `web_search` | — | Web search via Tavily API |
| `WebFetchTool` | `web_fetch` | — | Fetch and extract web page content |
| `SpawnTool` | `spawn` | — | Create background subagents |
| `MessageTool` | `message` | — | Send messages to other channels |
| `CronTool` | `cron` | add, remove, list, enable | Manage scheduled tasks |
| `RecallTool` | `recall` | — | Semantic memory search |

## Tool Registration

Tools are registered via `create_tools()` in `hal/core/runtime/tool_factory.py`:

```python
registry = create_tools(
    workspace=workspace,
    allowed_dir=allowed_dir,       # For path restriction
    exec_config=exec_config,       # Timeout, safety settings
    bus=bus,                        # For message tool
    subagent_manager=manager,      # For spawn tool
    cron_service=cron,             # For cron tool
    memory_search=memory_search,   # For recall tool
    web_search_api_key=api_key,    # For web search
)
```

Core tools (fs, exec) are always registered. Optional tools (message, spawn, cron, recall, web_search) are only registered when their dependencies are provided.

### Capability Filtering

The engine and subagents use different capability sets:
- **Engine**: Full tool set
- **Subagent**: Restricted (no message, spawn, or cron) to prevent recursive spawning and uncontrolled scheduling

## Parameter Validation

`ToolRegistry.execute()` validates parameters against the tool's JSON Schema before calling `execute()`. Validation checks:
- Required parameters are present
- Parameter types match the schema
- Enum values are valid

Invalid parameters return an error string to the LLM (not an exception), allowing it to self-correct.

## Security Model

### Path Restriction

When `tools.restrictToWorkspace` is `true`:
- `FsTool` restricts all file operations to the workspace directory
- `ExecTool` restricts the working directory
- Path validation uses `Path.relative_to()` (not string prefix matching) to prevent sibling-directory bypass

### Exec Safety

`ExecTool` includes a safety guard that checks commands for:
- Paths outside the working directory (when restricted)
- Dangerous patterns (configurable)
- Command timeout (configurable via `tools.exec.timeout`)

### Tool Sandboxing

Subagents receive a restricted tool set via `create_tools()` — they cannot:
- Send messages to channels (`message` tool excluded)
- Spawn further subagents (`spawn` tool excluded)
- Create scheduled tasks (`cron` tool excluded)
