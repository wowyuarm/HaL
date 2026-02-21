# Development Guide

## Setup

```bash
git clone https://github.com/wowyuarm/HaL.git
cd HaL
pip install -e ".[dev]"
```

Optional dependencies:

```bash
pip install -e ".[feishu]"    # Feishu channel support
```

## Testing

```bash
# Run all tests
pytest tests/

# Run a specific test file
pytest tests/capabilities/tools/test_fs_tool.py

# Run with verbose output
pytest tests/ -v

# Run a specific test
pytest tests/core/test_engine.py::test_function_name
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"` — async test functions are automatically detected.

### Test Fixtures

Common fixtures are defined in `tests/conftest.py`:
- `tmp_home` — Temporary home directory with `HAL_HOME` environment variable set

### Writing Tests

- Place tests in `tests/` mirroring the source directory structure
- Use `pytest.mark.asyncio` is not needed (auto mode)
- Mock external services (LLM calls, web requests) — never make real API calls in tests
- Use `tmp_path` or `tmp_home` for filesystem tests

## Linting & Formatting

```bash
# Check for lint errors
ruff check hal/

# Auto-fix lint errors
ruff check --fix hal/

# Format code
ruff format hal/
```

Ruff configuration (in `pyproject.toml`):
- Rules: `E, F, I, N, W` (E501 line length ignored)
- Line length: 100
- Target: Python 3.11+

Always run `ruff check --fix && ruff format` before committing.

## Project Structure

See [CLAUDE.md](../CLAUDE.md) for the full directory structure and architectural overview.

Key entry points:
- `hal/cli/commands.py` — CLI application (Typer)
- `hal/core/engine.py` — Agent engine
- `hal/core/runtime/loop.py` — Shared tool-calling loop
- `hal/core/runtime/tool_factory.py` — Tool registration

## Adding a New Tool

1. Create a class extending `Tool` in `hal/capabilities/tools/`:

```python
class MyTool(Tool):
    name = "my_tool"
    description = "What this tool does"
    parameters = { ... }  # JSON Schema

    async def execute(self, **params) -> str:
        ...
```

2. Register it in `hal/core/runtime/tool_factory.py`:

```python
# In create_tools():
registry.register(MyTool(...))
```

3. If the tool has side effects, override `get_side_effects()`.

4. Add tests in `tests/capabilities/tools/test_my_tool.py`.

## Adding a New Provider

1. Add a `ProviderSpec` to `PROVIDERS` in `hal/infra/providers/registry.py`
2. Add a field to `ProvidersConfig` in `hal/infra/config/schema.py`
3. Everything else derives automatically (env vars, model prefixing, `hal status` display)

## Debugging

### Verbose Gateway

```bash
hal gateway --verbose
```

Enables `DEBUG` level logging for all components.

### Inspecting Logs

Daily interaction logs are stored in `<workspace>/logs/YYYY-MM-DD.jsonl`. Each line is a JSON object with role, content, and timestamp.

### Common Issues

- **"No API key configured"** — Set a provider API key in `~/.hal/auth.yaml`
- **"Path outside allowed directory"** — The agent is trying to access files outside the workspace (when `restrict_to_workspace` is enabled)
- **Memory search unavailable** — Install optional dependencies: `pip install pymilvus`
