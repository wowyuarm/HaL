# Web Test Structure

Frontend tests live here so they stay separate from development utilities in `web/scripts/`.

## Layers

- `unit/`
  Vitest + Testing Library tests for components, hooks, and small helpers.
- `regressions/`
  Bundled node-side regression tests for core logic that is easier to verify outside jsdom, such as store transitions, process summaries, and session-event adaptation.
- `setup.ts`
  Shared frontend test setup.

## Commands

```bash
cd web && npm test
cd web && npm run test:unit
cd web && npm run test:regressions
```

## Placement Rules

- Put new component and helper tests in `unit/`.
- Put tests that need the bundled node harness in `regressions/`.
- Keep `web/scripts/` for development utilities like config cleanup, not test cases.
