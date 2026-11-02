# Module Layout Stack Implementation Plan

> **For agentic workers:** Use subagent-driven-development for each module, then the requested ship pipeline. Track stages in the durable local ledger.

**Goal:** Migrate AI, billing, news, pagebuilder and records to the images module layout in five stacked PRs.

**Architecture:** Each PR moves one module's implementation and tests into core, web, domain and ui areas. Imports, tooling, packaging and documentation follow the moves; public contracts and consumer discovery paths retain their behavior.

**Tech Stack:** Python/SQLModel/FastAPI, TypeScript/React, pytest, Vitest, Playwright.

**Spec:** `docs/module-layout.md`, plus the approved conversation design.

## Global Constraints

- Moves and necessary import/path updates only; no dependency, version, schema or behavior changes.
- Root retains consumer discovery paths, public contracts, static assets and package markers required by tooling.
- Areas have light initializers. Every Python module must import in a fresh interpreter.
- Tests mirror package areas; parity-managed pg_support.py stays at tests root.
- Frontend helpers and tests move under ui; pages stay at root. Exclude test helpers from wheels.
- Run headroom before heavy jobs, at most two heavy jobs and one full suite, PYTEST_WORKERS=8.
- Never read credential stores or secret files. Never merge, force-push or push main.

## Review Focus

- Framework and plugin discovery still resolve installed package entry points, pages, locales and models.
- Dotted mock targets follow moves while app.state attributes remain unchanged.
- Relative TS imports and locale JSON paths resolve from their new locations.
- Wheels include runtime source/static assets and exclude frontend tests/helpers.
- Test support and parity checks resolve paths at their changed depths.

## Shared migration procedure

For each task below:
- [ ] Add or extend discovery/layout tests before moving; verify the relevant check fails for the old layout.
- [ ] Script git moves and import/path rewrites. Preserve public contracts and any externally discovered names.
- [ ] Move tests to mirrored areas and shared helpers to support, updating path/depth assumptions.
- [ ] Update module layout documentation and repo progress table.
- [ ] Verify fresh imports, module tests, host/scripts tests, frontend tests, lint, typecheck and wheel contents; commit.
- [ ] Run ship: preflight/checkpoint, safe optimization, independent code-review loop, browser QA loop, verify/local CI, one PR targeting the prior branch.

### Task 1: AI

Branch `refactor/ai-module-layout`, base `main`.
Files: `modules/ai/**`, necessary path references in host/scripts/tests/tooling, layout progress table.
Move constants, crypto, settings, worker settings and shared state to core; resolution/discovery to connections; charging to metering; endpoints/dependencies/CSRF/HTTP service to web; components/utils to ui. Preserve contracts schemas/errors and module.py.
Produces: unchanged `sm_ai.contracts` consumed by images; first PR/base for billing.

### Task 2: Billing

Branch `refactor/billing-module-layout`, base AI branch.
Files: `modules/billing/**`, necessary callers/tooling/parity references and layout docs.
Move cross-cutting foundations to core; endpoints/schemas/HTTP reads to web; keep metering/providers as domain areas; group subscription lifecycle, sync, seats and teardown by responsibility. Preserve CLI discovery and models lookup.
Produces: unchanged billing contracts and behavior; second PR/base for news.

### Task 3: News

Branch `refactor/news-module-layout`, base billing branch.
Files: `modules/news/**`, necessary callers/tooling/parity references and layout docs.
Keep content domain, group scheduling, move tenancy/settings/foundations to core, HTTP code to web, UI to ui. Preserve models, locales, pages, contracts and pagebuilder block discovery.
Produces: third PR/base for pagebuilder.

### Task 4: Pagebuilder

Branch `refactor/pagebuilder-module-layout`, base news branch.
Files: `modules/pagebuilder/**`, necessary callers/tooling/parity references and layout docs.
Group content/workflow, media and scheduling features; foundations to core; endpoints/schemas/serving to web; frontend components/fields/conversion/hooks/utils to ui as appropriate. Preserve public contracts, puck block discovery and static paths.
Produces: fourth PR/base for records.

### Task 5: Records

Branch `refactor/records-module-layout`, base pagebuilder branch.
Files: `modules/records/**`, necessary callers/tooling/parity references and layout docs.
Group schema, record services, index, public submissions and seed/CLI by domain; foundations to core; HTTP to web; components/hooks/utils/page-tests to ui. Preserve discovered names and anonymous-write/tenant behavior.
Produces: final stacked PR; all five modules follow the standard.
