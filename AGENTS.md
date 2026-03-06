# Repository Guidelines

## Project Structure & Module Organization
`hal/` contains runtime code: `core/` (engine/runtime/memory/subagent/bootstrap), `capabilities/` (tools/skills), `channels/`, `infra/`, and `cli/` (Typer command package).  
`tests/` mirrors package layout (`tests/core/`, `tests/capabilities/tools/`, etc.).  
Keep source and tests in matching paths.

## Architecture North Star
- Treat HaL as a stateful collaboration kernel, not a chatbot with more history.
- Filesystem state is the durable source of truth; append-only events are evidence; context is a compiled working set.
- Keep semantic layers separate from mechanisms:
  `Thread`, `Episode`, `Memory`, `Skill`, and `Artifact` are domain objects; event bus / loop / hooks are runtime mechanisms; providers / channels / Milvus are infra.
- Prefer stable working-set layers over repeated dynamic reinjection:
  stable prefix -> session baseline -> frozen checkpoints -> live tail.
- `Thread` and `Skill` may share loading infrastructure, but they are not the same semantic type.
- Prefer explicit workspace/repository abstractions over ad hoc `Path` reads and writes inside engine logic when refactoring persistent state flows.
- When changing context or workspace architecture, align with docs/design/architecture-v3.md.
- For long-running architecture batches, also align with docs/design/architecture-v3-execution.md as the execution anchor.
- After each architecture commit batch, re-read both design docs above before continuing implementation.

## Build, Test, and Development Commands
- `pip install -e ".[dev]"`: editable install with test/lint dependencies.
- `pytest tests/`: run the full test suite.
- `pytest tests/core/test_engine.py::test_name`: run a single test.
- `ruff check hal/ && ruff format hal/`: lint and format Python code.
- `hal --version`: verify CLI wiring.

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

## Configuration & Constants Policy
- Key runtime behaviors must be configurable via global config (`hal/infra/config/schema.py` + `~/.hal/config.yaml`), not hidden in call sites or constructor hardcoding.
- New config keys must include clear inline comments in the config template so operators understand intent and safe ranges.
- Avoid magic numbers/strings inside execution logic; define module-level `UPPER_SNAKE_CASE` constants near the top of the file and reference those symbols in code paths.
- Per-job/user payload can carry task data, but global guardrail policies (for example tool allowlists, default windows, limits) should come from global config.

## Testing Guidelines
Testing uses `pytest` with `pytest-asyncio` (`asyncio_mode = auto`).  
Place tests in mirrored paths and name files `test_<feature>.py`.  
Mock external LLM/web integrations; do not run real API calls in tests.  
Use `tmp_path` and the shared `tmp_home` fixture (`tests/conftest.py`) for filesystem/config isolation.  
No fixed coverage threshold is configured; add regression tests for bug fixes.

## HaL Quality Improvement Playbook
- Refactor in small, behavior-preserving batches (usually 1-3 related functions/files per batch).
- After each batch, run both targeted tests and a full quality scan:
  - `PYTHONPATH=. pytest <targeted test paths> -q`
  - Day-to-day quality gating: `uvx pyscn@latest analyze --json --no-open hal/`
  - Milestone/regression check: `uvx pyscn@latest analyze --json --no-open .`
- Treat full-project `pyscn` output as the source of truth; local function improvements can still reduce global health score.
- Interpret `tests/` quality findings pragmatically:
  - Prioritize `hal/` findings for refactor work.
  - Use `tests/` findings mainly when they indicate real maintainability or reliability risk, not just metric noise (for example LCOM in large test classes).
- Manage complexity-vs-duplication tradeoffs explicitly:
  - Prefer helper extraction with strong domain semantics.
  - Avoid introducing several near-identical helper shapes that clone detection flags as Type-1/Type-2 duplication.
- If a refactor causes score regression (especially clone score), revert that specific change and try a different decomposition strategy.
- Keep commits single-purpose and runnable; for quality refactors, use `refactor(scope): ...` style messages.
- Before PR/merge, run full validation: `pytest tests/`, `ruff check hal/ && ruff format hal/`, and one fresh `pyscn` report.
- Record the latest `.pyscn/reports/analyze_*.json` or `.html` path in PR notes so reviewers can compare baselines.

## Commit & Pull Request Guidelines
Follow observed commit style: `type(scope): imperative summary` (for example `feat(memory): ...`, `fix(exec): ...`, `refactor(cli): ...`).  
For non-trivial changes, include a short body using concise prose or `-` bullet points (match recent repository history style).
Example:
`feat(memory): clarify RRF scoring and harden recall indexing pipeline`  
`- Label retrieval values as rrf_score in output and context blocks`  
`- Add chunk_heading_max_level config to reduce over-fragmentation`
Keep commits focused and runnable. Before opening a PR, run `pytest tests/` and `ruff check hal/ && ruff format hal/`.  
PRs should include purpose, key files changed, config/migration notes, and verification steps (commands plus short output snippets). Link related issues when applicable.

## Security & Configuration Tips
Never commit secrets. Store tokens/keys in `~/.hal/auth.yaml`; keep non-secret settings in `~/.hal/config.yaml`.  
If you modify filesystem or command-execution tools, validate behavior with `tools.restrict_to_workspace` enabled.
