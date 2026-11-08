# Analytics UI and query indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved Umami-style analytics dashboard, audit query indexes, and produce populated verified screenshots on PR #323.

**Architecture:** Keep report/API contracts and host shell. Split report presentation by chart, rankings and recent activity; keep toolbar/filter drafts separate. Query indexing changes own models, migrations and backend tests, with no frontend overlap.

**Tech Stack:** React/TypeScript, installed Recharts and framework UI, en/de catalogs; SQLModel/SQLAlchemy, SQLite/Postgres, Alembic, pytest, Vitest and Playwright.

**Spec:** `docs/superpowers/specs/2026-11-08-analytics-ui-design.md`

## Global Constraints

- All `.py`, `.ts`, `.tsx` files remain at most 300 lines; only real Inertia pages live in `pages/`.
- New UI copy uses typed module keys in both English and German. The controller owns catalog additions; workers request additional keys.
- No new runtime dependency, global branding change, fabricated metric or backend filter feature.
- Preserve exact UTC ranges, 366-day bound, All/Unknown distinction and geographic descendant clearing.
- Frontend workers own disjoint files; database worker owns backend/index files. No worker reverts another worker's edits.
- Before heavy work run `~/.codex/bin/wait-for-headroom`. At most two heavy jobs, one full suite, and `PYTEST_WORKERS=8`. No server while two workers are active.
- Reports/screenshots/raw benchmark data remain under the worktree git directory. No credential stores or `.env*` reads. No production data, merge or force push.

## Review Focus

- Draft filters/date inputs must not issue report requests before Apply; local tabs must not fetch.
- Changing/removing a country or region must clear descendants while preserving unrelated filters.
- Property changes must reset property-specific report controls and prevent stale responses.
- Narrow/dark/empty/error states must retain readable text, reachable actions and accurate data.
- Indexes must match tenancy, actual query shape and migration metadata without unbounded write/storage overhead.

### Task 1: Chart and grouped reporting

**Files:** Modify `ui/components/ReportView.tsx` and its test under `modules/analytics/sm_analytics/`; create `TrafficChart.tsx`, `RankingPanel.tsx`, `RecentActivity.tsx` and focused tests in the same area.

**Interfaces:** Preserve `ReportView({ report: Report, filters: Filters, onFilter: (filters: Filters) => void })`. Consume existing report payload only. Chart local state selects `pageviews | events`; grouped rankings preserve supported row filtering.

- [ ] Write failing tests for chart series selection, grouped tabs/show more, unsupported non-actionable rows, geo descendant clearing and readable recent names.
- [ ] Run focused Vitest and confirm intended failures.
- [ ] Implement the metric strip, large blue Recharts plot with table fallback, grouped rankings and recent activity; keep each file under the cap.
- [ ] Run focused tests, Biome and analytics TypeScript; record evidence and commit only owned files.
- [ ] Independent spec/quality review, fix and scoped re-review.

### Task 2: Compact dashboard and applied filters

**Files:** Modify `pages/Dashboard.tsx`, `ui/components/ReportFilters.tsx`, its test and `tests/e2e/analytics.spec.ts`; create `DateRangeControl.tsx`, `FilterChips.tsx`, `PropertySettings.tsx` and focused tests as needed.

**Interfaces:** Preserve `ReportFilters({ value: Filters, onChange: (filters: Filters) => void, report: Report | null })`; controller inserts it in the toolbar. Preserve existing property callbacks/permission checks. ReportView's interface stays unchanged.

- [ ] Write failing tests for draft/Apply behavior, preset/custom inclusive UTC ranges, cancel, chip removal/unknown labels/geo clearing and management permission gates.
- [ ] Run focused Vitest to confirm failures.
- [ ] Implement wrapping toolbar, compact date/filter controls, visible chips and secondary management using existing UI primitives; preserve destructive confirmation.
- [ ] Update the standalone E2E spec for menu/dialog/filter navigation while retaining real collection assertions.
- [ ] Run focused checks and commit owned files; independent review/fix gate.

### Task 3: Query/index audit and migration

**Files:** Own `sm_analytics/models/`, backend query helpers only if plans justify a change, a new `host/migrations/versions/` revision, `modules/analytics/tests/` regression tests and `modules/analytics/docs/index.md` indexing guidance. No UI edits.

**Interfaces:** Preserve API/report data semantics; all module queries stay tenant scoped. New indexes must agree between SQLModel metadata and Alembic upgrade/downgrade.

- [ ] Inventory statements and capture representative baseline EXPLAIN plans on SQLite/Postgres, including tenant-only retention and standalone region/city/path/event filters.
- [ ] Add a small failing index/migration/query-plan regression test for each justified gap.
- [ ] Add only justified indexes and the host migration; document query-to-index mapping and legitimate broad aggregate scans.
- [ ] Verify focused SQLite/Postgres tests, migration upgrade/downgrade/check and one head. Record before/after report/write timing and index size on owned benchmark databases.
- [ ] Commit owned files; independent review/fix gate.

### Task 4: Rich fixture, verification, screenshots and PR

**Files:** Temporary fixture/measurement/evidence helpers under `.git/.../verify/ui-redesign/`; update existing docs/PR metadata as needed. No screenshot/report commits.

**Interfaces:** Seed an isolated migrated host database with synthetic properties and realistic varied reporting data. Use the same production bundle and real API for verification and snapshots.

- [ ] Prepare reproducible 90-day mixed synthetic fixture with assertions for totals, geographic labels, approved events/properties, normalized application paths and recent activity.
- [ ] Run full frontend tests, lint/typechecks/rules/build, analytics backend/index checks and standalone production E2E serially under workstation caps.
- [ ] Perform independent final diff review and browser QA; fix in-scope regressions with targeted tests and re-review.
- [ ] Finish performance checks, then capture populated overview, filters, geo drill-down, events/properties, normalized app, mobile and dark screenshots. Inspect each image.
- [ ] Stop owned server/browser; generate local report, commit verified source, push feature branch and update PR #323. Upload snapshots only through authorized authenticated session; report any human-only authentication block. Wait for CI and audit tasks.
