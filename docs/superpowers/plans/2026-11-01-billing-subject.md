# Billing subject (#274) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single-tenant host can bill each signed-in user (`user:<uuid>`) instead of `default`, behind a restart-only `subject_mode` setting.

**Architecture:** The billing key (`tenant_id` columns, contract `tenant_id` parameters) becomes an opaque **billing subject**: a tenant id or `default` (unchanged) or `user:<uuid>`. One module, `sm_billing/subjects.py`, owns building, parsing, resolving and naming subjects. Every place that assumed a `tenants_tenant` row asks it instead. In `tenant` mode (the default) nothing observable changes.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic, pytest + pytest-asyncio, React/Inertia (TypeScript), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-01-billing-subject-design.md`

## Global Constraints

- **Subject strings:**
  - a tenant subject is the tenant id, or `"default"` on a single-tenant host;
  - a user subject is `"user:" + str(user_id)`, 41 characters for a UUID;
  - the prefix constant is `USER_SUBJECT_PREFIX = "user:"`.
- **Width:** `_TENANT_ID_LEN = 64` in `models.py` and `TENANT_MAX = 64` in `metering/validate.py`. One Alembic revision widens six columns to `VARCHAR(64)`.
- **Setting:** `BillingSettings.subject_mode: Literal["tenant", "user"] = "tenant"`, marked `json_schema_extra=_RESTART`. It is read only in `on_startup` (from `app.state.sm_billing.settings`), never at construction (CLAUDE.md).
- **Boot guards:**
  - `user` mode plus `multi_tenant` raises at startup with a message naming both settings;
  - stranded `"default"` rows produce one WARNING;
  - images/ai worker metering staying on the tenant produces one WARNING when `sm_images` or `sm_ai` is installed.
- **Error codes:** `subject_required` (401) when user mode has no signed-in user; `per_seat_requires_tenant` (422).
- **Repo rules:**
  - 300-line cap per file (`scripts/check_file_size.py`); split by responsibility rather than trimming;
  - billing commits outside a request with `finalize_session`, never `commit()`;
  - migrations live only in `host/migrations/versions/`;
  - every new UI string gets `en.json` and `de.json` keys (`scripts/check_locales.py`);
  - never `ruff format` whole modules.
- **Tenant mode:** the existing billing suite must pass unchanged. Don't edit its assertions.

## Review Focus

1. **A signed-out request in user mode.** `RequiresQuota` and `/api/billing/*` must answer 401 `subject_required`, never charge `default`. → Task 3 test `test_signed_out_user_mode_is_401`.
2. **Two users' usage, holds and subscriptions never mix.** Same meter, same idempotency key, different users must be two charges. → Task 3 test `test_two_users_same_key_are_separate`.
3. **Postgres length.** A 41-character subject must insert into every widened table on Postgres. SQLite ignores lengths. → Task 1 test `test_user_subject_fits_every_table` (runs in the billing Postgres CI job).
4. **The deleted-tenant sweep with a user-subject customer row present** (a leftover from switching modes) must not tear it down. → Task 4 test `test_sweep_ignores_user_subjects`.
5. **Reconcile of a user subscription** must bind `tenant_context("default")`, not the user id. → Task 4 test `test_reconcile_binds_the_subjects_tenant`.

---

### Task 1: Subject helpers, setting, width migration

**Files:**
- Create: `modules/billing/sm_billing/subjects.py`
- Modify: `modules/billing/sm_billing/settings.py` (add `subject_mode`), `modules/billing/sm_billing/models.py:37`, `modules/billing/sm_billing/metering/validate.py:18`, `modules/billing/sm_billing/constants.py` (`USER_SUBJECT_PREFIX`, `SUBJECT_MODE_TENANT="tenant"`, `SUBJECT_MODE_USER="user"`, `SUBJECTS_STATE_ATTR="billing_subject_mode"`)
- Create: `host/migrations/versions/<rev>_billing_subject_width.py` (down_revision `f5b1c3e8a207`, no branch label)
- Test: `modules/billing/tests/test_subjects.py`

**Interfaces:**
- Produces, in `sm_billing.subjects`:
  - `subject_for_tenant(tenant_id: str) -> str` (identity);
  - `subject_for_user(user_id: str | UUID) -> str` (`"user:" + str(user_id)`);
  - `kind(subject: str) -> Literal["tenant","user"]`;
  - `user_id_of(subject: str) -> str | None`;
  - `tenant_of(subject: str) -> str` (`"default"` for a user subject, else the subject);
  - `subject_mode(app) -> Literal["tenant","user"]` (reads `app.state.billing_subject_mode`, default `"tenant"`);
  - `async exists(db, subject) -> bool` (`"default"` → True; tenant → `db.get(Tenant, id)`; user → `db.get(User, UUID)`);
  - `async names(db, subjects: list[str]) -> dict[str, tuple[str, str]]` (subject → (name, slug); a user gives `(email, "")`; unknown gives `(subject, "")`).

- [ ] Write tests:
  - `test_round_trip` (`kind`, `user_id_of`, `tenant_of` for `"default"`, a hex tenant id, and `user:<uuid>`);
  - `test_width_limits` (`check_call` accepts 64 characters and rejects 65; use the existing `metering/validate.py` checker);
  - `test_exists_and_names` (a tenant row, a user row, a missing user);
  - `test_user_subject_fits_every_table`: insert a 41-character subject into `Customer`, `Subscription`, `UsageEvent`, `UsagePeriod`, `UsageGauge` and `UsageHold` and read each back.
- [ ] Run the tests and see them fail: `cd modules/billing && uv run pytest -q tests/test_subjects.py`.
- [ ] Implement the helpers, constants, setting (label and description like its neighbours, `_RESTART`) and width constants.
- [ ] Write the migration with `op.batch_alter_table` per table, `alter_column("tenant_id", existing_type=sa.String(32), type_=sa.String(64), existing_nullable=False)`, and a downgrade back to 32.
- [ ] Verify:
  - `uv run python scripts/check_migration_heads.py` (one head);
  - from the repo root on a throwaway SQLite URL: `uv run --project host alembic -c host/alembic.ini upgrade heads`, then `check`;
  - the same on a throwaway Postgres database on dev-services, dropped afterwards;
  - the Task 1 tests pass.
- [ ] Commit `feat(billing-subject): subject helpers, subject_mode setting, 64-char key`.

### Task 2: Boot: mode on app.state, guards, permissions

**Files:**
- Modify: `modules/billing/sm_billing/startup.py` (or a new `sm_billing/subject_boot.py` if `startup.py` would pass 280 lines), `modules/billing/sm_billing/module.py` (call it from `on_startup`)
- Test: `modules/billing/tests/test_subject_mode_boot.py`

**Interfaces:**
- Consumes: Task 1 `subject_mode`, constants.
- Produces: `async apply_subject_mode(app) -> None`, which:
  - sets `app.state.billing_subject_mode` from settings;
  - raises `RuntimeError("billing subject_mode=user needs a single-tenant host (multi_tenant is on)")` when the mode is user and `is_multi_tenant(app)`;
  - in user mode, calls `app.state.sm.permissions.map_role("user", [PERM_VIEW, PERM_MANAGE])` (find the registry attribute the framework uses; `users.constants.USER_ROLE_NAME`);
  - logs WARNING `billing.subject_mode.stranded_default_rows` when a `Subscription` or `UsagePeriod` row has `tenant_id == "default"`;
  - logs WARNING `billing.subject_mode.tenant_billed_callers` naming the installed images/ai modules.

- [ ] Write tests:
  - `test_tenant_mode_is_default_and_inert` (no map_role, no warnings);
  - `test_user_mode_refused_on_multi_tenant`;
  - `test_user_mode_grants_view_and_manage_to_user_role` (a plain user's permission set includes `billing.view` and `billing.manage`; resolve it through the registry, not just the map);
  - `test_stranded_default_rows_warn`.
- [ ] Run them and see them fail. Implement. Run them and see them pass. If `map_role` after boot does not reach the permission cache, use `add_grant_source` (risk in spec) and note it in the commit.
- [ ] Commit `feat(billing-subject): subject_mode boot guards and user-role permissions`.

### Task 3: Request entry points resolve the subject

**Files:**
- Modify: `modules/billing/sm_billing/subjects.py` (add `for_request`), `modules/billing/sm_billing/metering/deps.py:69-76`, `modules/billing/sm_billing/context.py`, `modules/billing/sm_billing/deps.py`
- Test: `modules/billing/tests/test_user_mode_api.py` (+ a `user_mode_app` fixture in `tests/conftest.py` that sets `subject_mode="user"` before startup, following the `settings` fixture)

**Interfaces:**
- Produces: `for_request(request) -> str` in `subjects`:
  - tenant mode: the existing `_tenant` logic (the request tenant, else `"default"` single-tenant, else `BillingError("tenant_required",403)`);
  - user mode: `subject_for_user(request.state.user.id)`, else `BillingError("subject_required", 401)`.
- `billing_context` in user mode returns `BillingContext(tenant_id=<user subject>, role=c.TENANT_ROLE_OWNER)` (no restore). `deps.ActiveTenant`/`require_owner`/`get_billing_service` stop requiring `tenants.require_active_tenant` in user mode, and build from `billing_context` instead.

- [ ] Write tests, in user mode with the manual provider and two users from `make_user`:
  - `test_status_is_per_user`;
  - `test_checkout_and_change_plan_act_on_own_subject` (a `Subscription.tenant_id == "user:<id>"` row);
  - `test_usage_is_per_user`;
  - `test_requires_quota_charges_the_caller`;
  - `test_two_users_same_key_are_separate`;
  - `test_signed_out_user_mode_is_401`.
- [ ] Run them and see them fail. Implement. Run them and see them pass, and run the whole billing suite (`uv run pytest -q -n 8`) to show tenant mode is unchanged.
- [ ] Commit `feat(billing-subject): requests bill the signed-in user in user mode`.

### Task 4: Kind-aware lifecycle, sync, sweep, reconcile, seats, checkout

**Files:**
- Modify:
  - `sync.py` (`_tenant_for` uses `subjects.exists`);
  - `lifecycle.py` (`apply_lifecycle` and `tenant_gone`: user subjects never suspend; `tenant_gone` is False for them);
  - `sweep.py` (`_orphans` excludes `Customer.tenant_id LIKE 'user:%'`);
  - `teardown.py` (refuses user subjects from `TenantDeleted`; keep it under 300 lines);
  - `reconcile.py:63` and `teardown.py:220` (`tenant_context(tenant_of(subject))`);
  - `checkout.py` (`_customer` name from `subjects.names`; per-seat plan on a user subject → `BillingError("per_seat_requires_tenant", 422)` in checkout and change_plan);
  - `seats.py` (`push_quantity` returns early for user subjects).
- Test: `modules/billing/tests/test_subject_kinds.py`

- [ ] Write tests:
  - `test_unpaid_user_subscription_downgrades_without_suspension`;
  - `test_sync_maps_a_user_subject_via_customer_row`;
  - `test_sweep_ignores_user_subjects` (multi-tenant app fixture, with a `Customer(tenant_id="user:…")` present);
  - `test_reconcile_binds_the_subjects_tenant` (capture `tenant_context` argument);
  - `test_per_seat_plan_refused_for_user` (checkout and change-plan → 422 `per_seat_requires_tenant`);
  - `test_seat_push_skips_user_subjects`.
- [ ] Fail, implement, pass. Run the whole billing suite.
- [ ] Commit `feat(billing-subject): lifecycle, sync, sweep, reconcile and seats know user subjects`.

### Task 5: Teardown on UserDeleted

**Files:**
- Create: `modules/billing/sm_billing/user_teardown.py`
- Modify: `module.py`/the startup hook from Task 2 to subscribe it in user mode only.
- Test: `modules/billing/tests/test_user_deleted.py`

**Interfaces:** Consumes `simple_module_core.user_events.UserDeleted` and the existing `teardown_claim` path keyed by `Customer.tenant_id` (read `teardown.py` and `teardown_claim.py`; reuse, don't copy). Produces `subscribe_user_teardown(app) -> None`.

- [ ] Write tests:
  - `test_user_deleted_cancels_their_subscription` (fake provider records the cancel; the customer is marked torn down);
  - `test_user_deleted_without_customer_is_a_noop`;
  - `test_not_subscribed_in_tenant_mode`.
- [ ] Fail, implement, pass. Commit `feat(billing-subject): tear down a deleted user's subscription`.

### Task 6: Admin screens and usage admin per user

**Files:**
- Modify: `admin.py` (`subscription_rows`, `assign`, `one_row`), `metering/admin.py:85-91` (`require_tenant` uses `subjects.exists`), `metering/report.py:185-193` (names via `subjects.names`)
- Modify the frontend: `pages/Subscriptions.tsx`/`components/SubscriptionsTable.tsx` (a `subjectMode` prop: the column header reads User/Email instead of Organisation/Slug), `locales/en.json` + `de.json`, and the view that renders Subscriptions (pass `subject_mode`).
- Test: `modules/billing/tests/test_admin_user_mode.py`; `components/BillingTables.test.tsx` (header switches).

**Interfaces:** In user mode, `subscription_rows` selects `users_user` (id, email, is_active) outer-joined to `Subscription` on `Subscription.tenant_id == "user:" || cast(User.id)`. Build the join key in SQL in a way that works on SQLite and Postgres, or select subscriptions and users separately and merge in Python with the same paging. It returns the existing `SubscriptionRow` schema with `tenant_id=<subject>`, `tenant_name=email`, `tenant_slug=""`, `tenant_status="active"|"inactive"`. `assign`/`one_row` accept a user subject when `exists`.

- [ ] Write tests:
  - `test_admin_lists_users_in_user_mode`;
  - `test_admin_assigns_a_plan_to_a_user`;
  - `test_usage_admin_reads_a_user_subject`;
  - `test_unknown_user_subject_is_404`;
  - the vitest header test.
- [ ] Fail, implement, pass; run `make test-js` and the billing suite. Commit `feat(billing-subject): admin screens list and assign per user`.

### Task 7: Contracts, docs

**Files:**
- Modify: `modules/billing/sm_billing/contracts/__init__.py` (export `subject_for_user`, `subject_for_tenant`, `subject_mode as current_subject_mode`), the contract docstrings in `contracts/metering.py` ("billing subject: a tenant id, `default`, or `user:<id>`"), `modules/billing/docs/` (new `subjects.md`, linked from the docs index), `modules/billing/README.md` (one paragraph), `CLAUDE.md` (one sentence in the billing paragraph: subject mode, restart-only, refused on multi-tenant).
- Test: `modules/billing/tests/test_contracts_exports.py` (names importable from `sm_billing.contracts`).

- [ ] Write the test, implement, run `make lint` (readme checks included), and commit `docs(billing-subject): contracts and docs`.

### Task 8: End-to-end in user mode

**Files:**
- Modify: `tests/e2e/start-test-server.sh` (when `E2E_BILLING_USER=1`: `scripts/set_setting.py sm_billing subject_mode user` before boot), `playwright.config.ts` (the env passthrough, like `E2E_MULTI_TENANT`, and `testIgnore` of the new spec unless the env is set), `.github/workflows/ci.yml` (job `E2E (billing per user)` modelled on `E2E (multi-tenant)`, running only `billing-user.spec.ts`)
- Create: `tests/e2e/billing-user.spec.ts`

- [ ] Write the spec:
  - create a second, non-admin user (seed as other specs do);
  - that user opens `/billing` and sees the default plan and their own usage;
  - the admin assigns them a plan on the Subscriptions screen, which lists them by email;
  - the user reloads and sees the plan;
  - the admin's own `/billing` is unaffected.
- [ ] Run it locally: `E2E_BILLING_USER=1 npx playwright test billing-user` (wait-for-headroom first). Commit `test(billing-subject): e2e for per-user billing`.
