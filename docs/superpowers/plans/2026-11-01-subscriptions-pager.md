# Subscriptions Pager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Page the admin Subscriptions screen (50 per page) in both subject modes, the way billing's Usage screen pages.

**Architecture:** A count beside `admin.subscription_rows` sharing one filter builder per mode; the Inertia view serves a `Paged<SubscriptionRow>`; the page renders the framework `PaginationBar`. The JSON API is unchanged.

**Tech Stack:** FastAPI + SQLModel, Inertia React, vitest, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-subscriptions-pager-design.md`

## Global Constraints

- `c.ADMIN_PAGE_SIZE: Final = 50` in `modules/billing/sm_billing/constants.py`; `ADMIN_ROW_LIMIT` (200) stays the API's page size.
- `GET /api/billing/admin/subscriptions` keeps its bare-list response and `offset`.
- Clamp the served page with `sm_billing.metering.report.page_numbers` (stale link → last page; non-integer or < 1 → 1).
- 300-line cap per file; en and de locale keys change together (`scripts/check_locales.py`).
- `billing` commits outside requests with `finalize_session` (not relevant here: read-only).

## Review Focus

- A filter (status, `q`) that the count applies differently from the rows → pager total wrong. Test count == len(all rows) per mode with filters.
- `page=abc`, `page=0`, `page=999` → 200 with a sensible page, never 422/500.
- Changing status/search while on page 3 → back to page 1.
- User mode with a non-canonical `tenant_id` path is unaffected (one_row still uses `subscription_rows`).
- Empty list (0 rows) → empty state, no pager.

---

### Task 1: Server — count and paged view

**Files:**
- Modify: `modules/billing/sm_billing/admin.py`, `modules/billing/sm_billing/admin_users.py`, `modules/billing/sm_billing/endpoints/admin_views.py`, `modules/billing/sm_billing/constants.py`, the schemas module holding `SubscriptionRow` (add `SubscriptionPageOut(items, total, page, per_page, pages)` next to it, mirroring `UsageEventPageOut`).
- Test: `modules/billing/tests/test_admin_pager.py` (new).

**Interfaces:**
- Produces: `admin.subscription_count(db, app, *, status: str | None = None, q: str | None = None) -> int`; view prop `subscriptions: {items, total, page, per_page, pages}` (replaces `rows` and `row_limit`).

- [ ] Tests first: count equals rows for tenant and user mode, with status and `q`; view on 51+ subjects serves 50 then the rest on `?page=2`; `?page=999` serves the last page; `?page=abc` and `?page=0` serve page 1; the existing `offset` API test still passes.
- [ ] Factor each mode's select/filters into one helper used by rows and count.
- [ ] Run `uv run pytest modules/billing/tests -n 8 -q -k "admin or subject"`; commit `feat(subscriptions-pager): paged admin subscriptions view`.

### Task 2: UI, e2e, docs

**Files:**
- Modify: `pages/Subscriptions.tsx`, `components/SubscriptionsFilters.tsx` (+ its test), `utils/types.ts`, `locales/en.json`, `locales/de.json` (drop `subscriptions.limit_notice`), `tests/e2e/billing-user.spec.ts` (step to page 2), billing docs mentioning the 200 limit / "first 200" notice (`docs/subjects.md`, `operations.md`, `api-reference.md`, `user-guide.md`, `architecture.md` as applicable).
- Test: `components/SubscriptionsPager` behaviour in a vitest beside the page's components (e.g. `components/Subscriptions.pager.test.tsx`) — never a new file under `pages/`.

- [ ] Tests first: pager hidden for one page; shown for two; clicking page 2 calls `router.get('/admin/billing/subscriptions', {status, q, page: '2'})`; a filter change omits `page`.
- [ ] Implement with `PaginationBar` (`hideWhenSinglePage`), a `query(filters, page)` helper like Usage's.
- [ ] Run `make lint` and the billing vitest; commit `feat(subscriptions-pager): page navigation on the Subscriptions screen`.
