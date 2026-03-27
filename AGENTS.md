# Repository Guidelines

## Project Structure & Module Organization
`hal/` contains runtime code: `runtime/` (engine/subagent/loop/session/brief/bootstrap), `context/`, `domain/`, `memory/`, `workspace/`, `capabilities/` (tools/skills), `channels/`, `infra/`, and `cli/` (Typer command package).  
`tests/` mirrors package layout (`tests/core/`, `tests/capabilities/tools/`, etc.).  
Keep source and tests in matching paths.

## Architecture North Star
- Read `DESIGN.md` first — it defines invariants and collaboration architecture.
- Keep semantic layers separate from mechanisms:
  `Thread`, `Episode`, `Memory`, `Skill`, and `Artifact` are domain objects; event bus / loop / hooks are runtime mechanisms; providers / channels / Milvus are infra.
- Session-first: `session_id` is the engine's sole identity key. Context is compiled fresh every turn — no frozen baselines.
- `Thread` and `Skill` may share loading infrastructure, but they are not the same semantic type.
- Prefer explicit workspace/repository abstractions over ad hoc `Path` reads and writes inside engine logic when refactoring persistent state flows.
- For frontend work, read `docs/specs/design-system.md` first, then follow the linked layer docs in `docs/specs/design/` for detailed rules. Use the `hal-design` skill.

## Frontend Engineering Notes
- Treat `docs/specs/design-system.md` as the frontend design entrypoint. Principle-level invariants live there; detailed rules live in their owning docs under `docs/specs/design/`. If a new UI rule stabilizes through iteration, write it back to the owning design doc instead of leaving it only in component code.
- Keep working-log and thread-detail body width aligned through shared code constants. Do not scatter raw width literals like `max-w-[49rem]` across new components.
- Reuse shared frontend patterns before adding more one-off class strings:
  `web/src/components/ui/hal-patterns.ts` holds layout width and bounded paper-object variants;
  `web/src/components/ui/hal-markdown.tsx` owns markdown rendering.
- Do not split markdown behavior across multiple styling systems. `HalMarkdown` + `web/src/styles/globals.css` is the primary path; avoid reintroducing parallel markdown rules in Tailwind typography config or per-message wrappers.
- Preserve working-log message grammar:
  assistant text lives in the page flow, user text may use a light bounded container, tool/system rows are secondary chrome, evidence remains the explicit bounded affordance.
- When tightening or loosening density, change shared variants or tokens first, not scattered per-component padding values.

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

## Commit & Pull Request Guidelines
Follow observed commit style: `type(scope): imperative summary` (for example `feat(memory): ...`, `fix(exec): ...`, `refactor(cli): ...`).  
For frontend commits, prefer a slightly more specific scope than plain `web` when one area is clearly affected: use `web-session`, `web-thread`, `web-ui`, `web-layout`, or `web-runtime`; keep plain `web` only for changes that intentionally span multiple frontend areas.  
For non-trivial changes, include a short body using `-` bullet points, each on its own real newline (never join bullets with literal `\n` strings — use a heredoc to pass multi-line messages).
Keep commits focused and runnable. Before opening a PR, run `pytest tests/` and `ruff check hal/ && ruff format hal/`.  
PRs should include purpose, key files changed, config/migration notes, and verification steps (commands plus short output snippets). Link related issues when applicable.

## Security & Configuration Tips
Never commit secrets. Store tokens/keys in `~/.hal/system/auth.yaml`; keep non-secret settings in `~/.hal/system/config.yaml`.  
If you modify filesystem or command-execution tools, validate behavior with `tools.restrict_to_workspace` enabled.
