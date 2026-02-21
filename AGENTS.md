# Repository Guidelines

## Project Structure & Module Organization
`hal/` contains runtime code: `core/` (engine/runtime/memory), `capabilities/` (tools/skills/scheduling), `channels/`, `infra/`, and `cli/` (Typer commands).  
`tests/` mirrors package layout (`tests/core/`, `tests/capabilities/tools/`, etc.).  
`docs/` stores notes; `scripts/` stores helper utilities. Keep source and tests in matching paths.

## Build, Test, and Development Commands
- `pip install -e ".[dev]"`: editable install with test/lint dependencies.
- `pytest tests/`: run the full test suite.
- `pytest tests/core/test_engine.py::test_name`: run a single test.
- `ruff check hal/ && ruff format hal/`: lint and format Python code.
- `hal onboard && hal agent -m "hello"`: initialize and smoke-test CLI wiring.

## Virtual Environment & Dependency Hygiene
Use a local virtual environment; do not install dependencies into system Python.
- `python -m venv .venv`: create an isolated environment.
- `source .venv/bin/activate`: activate before running `pip`, `pytest`, or `hal`.
- `pip install -U pip && pip install -e ".[dev]"`: install/update dev dependencies.
- `deactivate`: exit when done.
If env state drifts, recreate `.venv` and reinstall.

## Coding Style & Naming Conventions
Use Python 3.11+ with 4-space indentation, explicit type hints, and async-first APIs.  
Ruff is the style authority (`E,F,I,N,W`, line length 100, `E501` ignored).  
Naming conventions: `snake_case` for modules/functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.  
When adding tools or providers, register them in existing registries (for example `hal/core/runtime/tool_factory.py` and `hal/infra/providers/registry.py`).

## Testing Guidelines
Testing uses `pytest` with `pytest-asyncio` (`asyncio_mode = auto`).  
Place tests in mirrored paths and name files `test_<feature>.py`.  
Mock external LLM/web integrations; do not run real API calls in tests.  
Use `tmp_path` and the shared `tmp_home` fixture (`tests/conftest.py`) for filesystem/config isolation.  
No fixed coverage threshold is configured; add regression tests for bug fixes.

## Commit & Pull Request Guidelines
Follow observed commit style: `type(scope): imperative summary` (for example `feat(memory): ...`, `fix(exec): ...`, `refactor(cli): ...`).  
For non-trivial changes, commit messages must include a body (not only a title) describing why, what changed, and verification.
Example:
`feat(memory): improve recall ranking`  
`why/what/test: reduce summary bias; keep index compatibility; pytest tests/core/memory/test_search.py`
Keep commits focused and runnable. Before opening a PR, run `pytest tests/` and `ruff check hal/ && ruff format hal/`.  
PRs should include purpose, key files changed, config/migration notes, and verification steps (commands plus short output snippets). Link related issues when applicable.

## Security & Configuration Tips
Never commit secrets. Store tokens/keys in `~/.hal/auth.yaml`; keep non-secret settings in `~/.hal/config.yaml`.  
If you modify filesystem or command-execution tools, validate behavior with `tools.restrict_to_workspace` enabled.
