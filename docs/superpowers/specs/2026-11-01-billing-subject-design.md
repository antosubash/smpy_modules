# Billing subject: per-user billing on single-tenant hosts (#274)

## Goal and scope

A host can bill **each user** instead of the tenant. gis-data-portal needs this: every portal user has their own subscription and quotas. One personal tenant per user would break cross-user sharing.

**In scope:**
- A restart-only billing setting `subject_mode = tenant | user`. The default is `tenant`, which behaves exactly as today.
- In `user` mode on a single-tenant host, every billing feature is keyed by the signed-in user: subscriptions, checkout, portal, plan changes, metering, holds and entitlements.
- The owner page `/billing` and the `/api/billing/*` owner API work for a plain signed-in user, who manages their own subscription.
- Platform admin screens list and assign plans per user, and the usage admin shows per-user usage.
- When a user is deleted, their provider subscription is torn down, as deleting a tenant does today.
- Worker-side callers get helpers that build the same subject keys.

**Out of scope:**
- Per-user billing **inside** a multi-tenant host. `user` mode is refused there.
- Renaming the `tenant_id` columns and contract parameters to `subject_id`. That can be a follow-up PR that only moves code.
- Teaching images and ai worker paths to bill users. They keep billing the tenant (`default`); see Decisions.
- A `period_policy` setting. The issue says the calendar-month fallback in `metering/periods.py` covers the period policy: users without a provider period get calendar months, and Stripe subscribers get Stripe's period.

## Approach

**Chosen (B): the billing key stays one opaque string, now called the billing subject.**
- No billing table is tenant-filtered (`MultiTenantMixin`). Every billing query already names `tenant_id` explicitly, so the column already acts as a string that billing owns.
- A tenant subject is unchanged: the bare tenant id, or `default`.
- A user subject is `user:<uuid>` (41 characters). The prefix tells the two kinds apart and cannot collide with a tenant id, which is `uuid4().hex`.
- The work:
  1. widen the key to 64 characters;
  2. put one resolver in front of the three request entry points;
  3. stop treating the key as a `tenants_tenant.id` in the roughly 12 places that do.

**Rejected:**
- **(A) Separate `subject_type`/`subject_id` columns.** This rebuilds four primary keys and two unique constraints, backfills data, and changes the `UsageMeter` contract that ai and images call. It is the largest change and the hardest to reverse, and nothing needs it yet.
- **(C) B plus a rename to `subject_id` now.** It doubles the migration and breaks keyword callers. It is better done later as a rename-only PR.

## Design

**Setting.**
- `BillingSettings.subject_mode: Literal["tenant","user"] = "tenant"`, marked restart-only (`_RESTART`). It is read in `on_startup` from `app.state.sm_billing.settings`.
- Boot **refuses** `user` mode when `multi_tenant` is on. Otherwise the deleted-tenant sweep would see every user customer as a deleted tenant and cancel it.
- Boot **warns** when `user` mode finds `default` subscriptions or usage rows. They stay stranded and inert, and nothing moves them.

**Subject helpers, `sm_billing/subjects.py`.**
- `subject_for_tenant(tenant_id)`, `subject_for_user(user_id)`, `kind(subject) -> "tenant" | "user"`, and `tenant_of(subject)`. `tenant_of` gives the framework tenant to bind: `default` for a user subject.
- `for_request(request) -> str`:
  - `tenant` mode: the request's tenant, as today.
  - `user` mode: `user:<id>` for the signed-in user. With no user, a 401 `subject_required`.
- `exists(db, subject)`: a tenant row exists, or `default`; for a user subject, a user row exists.
- `names(db, subjects)`: tenant name and slug, or the user's email, for admin lists.
- Exported from `sm_billing.contracts`: `subject_for_user`, `subject_for_tenant`, `current_subject_mode(app)` (web process only), `worker_subject_mode()` (a worker, via `background_tasks.settings_for`) and `subject_for_request(request)` (for entitlement checks). Worker code never builds keys by hand.

**Entry points switched to `subjects`.**
- `RequiresQuota._tenant` (`metering/deps.py`), which also covers ai's `RequiresAiRequest`.
- `context.billing_context`. In `user` mode it synthesises `BillingContext(subject, role="owner")`, with no restore mode.
- `deps.ActiveTenant`, `require_owner` and `get_billing_service`. These depend on `tenants.require_active_tenant` today, which needs a tenant role that a single-tenant host never sets.

**Places that stop assuming a tenant row.**
- `sync._tenant_for`: uses `exists`, keeping the customer-row fallback.
- `lifecycle.apply_lifecycle` and `tenant_gone`: user subjects are never suspended; they downgrade to the default plan.
- `sweep._orphans` and `teardown`: these handle tenant subjects only.
- `reconcile_one`: binds `tenant_context(tenant_of(subject))`, never a user id.
- `checkout._customer`: names the provider customer from `names`.
- `seats.push_quantity`: does nothing for a user subject.
- `admin.assign`/`one_row` and `metering/admin.require_tenant`: use `exists`.
- `report._tenant_names`: uses `names`.
- `admin.subscription_rows`: in `user` mode the list is driven from `users_user`, outer-joined to subscriptions, in the same shape as the tenant list today.

**Per-seat plans.** A per-seat plan cannot go to a user subject. Checkout, admin assign and plan change refuse it with 422 `per_seat_requires_tenant`.

**Teardown on user deletion.** A `UserDeleted` handler, registered in `user` mode only, runs the existing teardown claim path for `user:<id>`. That path cancels the provider subscription and marks the customer row.

**Permissions.** In `user` mode, `on_startup` maps `billing.view` and `billing.manage` onto the framework's `user` role with `registry.map_role`, so every signed-in user can open their own billing page. The platform permissions are unchanged. In `tenant` mode nothing changes.

**Schema.** One migration, chained after `f5b1c3e8a207`, widens `tenant_id` from 32 to 64 characters on six tables:
- `billing_customer` (primary key);
- `billing_subscription`;
- `billing_usage_event`;
- `billing_usage_period` (primary key);
- `billing_usage_gauge` (primary key);
- `billing_usage_hold`.

`_TENANT_ID_LEN` and `TENANT_MAX` both become 64. No data moves. The migration uses `batch_alter_table` on SQLite, and `alembic check` must pass on SQLite and Postgres.

**Docs.** `modules/billing/docs/` gets a "Billing subject" page covering:
- both modes and how to switch;
- the stranded `default` rows;
- "user subjects downgrade, never suspend";
- the worker-caller helpers;
- the images/ai caveat.

The contract docstrings say "billing subject (a tenant id or `user:<id>`)".

## Decisions made (override any at approval)

1. **The key format is `user:<uuid>`.** A bare `uuid.hex` would collide with tenant ids.
2. **The column keeps the name `tenant_id`.** The rename is deferred.
3. **images and ai keep billing the tenant in `user` mode.** Their worker paths pass the row's tenant (`default`); ai's request-time `RequiresAiRequest` bills the user, so `ai.requests` is split across the two subjects. Boot logs one warning naming them. Making them bill per user (through the collection owner) is a follow-up issue. Refusing to boot instead would lock any host with images out of `user` mode.
4. **No `period_policy`.** Stripe subscribers follow Stripe's period, everyone else calendar months, as today.
5. **One owner page.** The same `/billing` page, fed a synthesised owner context, not a second page.
6. **User subjects are never suspended.** An unpaid subscription falls back to the default plan.
7. **Switching modes is the operator's call.** Old-mode rows stay where they are, with a boot warning.

## Testing

- **Unit:** subject helpers (kinds, round trips, width at 64 and at 65 characters); the multi-tenant refusal at boot; the stranded-rows warning; per-seat refusal; lifecycle downgrade without suspension; sweep and teardown skip user subjects; the `UserDeleted` teardown.
- **API (billing harness in `user` mode):**
  - a plain user's `/api/billing/status`, `/checkout` (manual provider), `/change-plan` and `/usage` act on their own subject;
  - two users' usage and holds stay separate;
  - `RequiresQuota` charges the caller's subject, and gives 401 when signed out;
  - admin list, assign and usage-admin work by user.
- **Tenant mode:** the whole existing billing suite runs unchanged as the regression net.
- **Postgres:** the migration, plus a user-subject insert at 41 characters. SQLite does not enforce the length, so this test is required.
- **e2e:** one spec boots the host in `user` mode and checks that a second (non-admin) user sees their own billing page, gets a plan from the admin, and sees their own usage. The multi-tenant e2e job stays in `tenant` mode.
- **QA:** both users' billing pages, the admin subscriptions list in `user` mode, and the German strings.

## Risks

- The demo host's e2e server would need a `user`-mode boot. If one server cannot serve both modes, the spec starts its own host (the multi-tenant job is the precedent).
- **`map_role` at `on_startup` might run after the permission cache is first read.** If so, the permission source moves to `add_grant_source`. That is a small, contained change.
- Admin screens are the largest UI change. The user list could be long, so it reuses the existing tenant list's paging.
