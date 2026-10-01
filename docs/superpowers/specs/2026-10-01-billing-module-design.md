# Billing module (`simple_module_billing`) — design

Date: 2026-10-01
Status: approved (sections 1–5 approved in brainstorming)

## Context

The framework shipped tenancy in v0.0.35 (`simple_module_tenants`): tenants,
memberships, invitations, subdomain resolution and suspend/reactivate. Its
design (`simple_module_python/docs/plans/2026-09-27-saas-tenancy-design.md`)
leaves billing out on purpose and fixes the seams a `billing` module in this
repo plugs into:

- `EntitlementProvider` on `app.state.tenants.entitlements`
  (`limit(tenant_id, key) -> int | None`, `has_feature(tenant_id, key) -> bool`).
  `tenants` already enforces `tenants.seats` on members and invitations and
  maps `EntitlementExceededError` to HTTP 402.
- `TenantService.suspend` / `reactivate` for payment failure and recovery.
- Events `TenantCreated`, `TenantStatusChanged`, `MembershipAdded`,
  `MembershipRemoved`, published after commit.
- Billing owns its tables keyed by `tenant_id`; nothing is added to
  `tenants_tenant`.

This module is the commercial layer on top: plans, subscriptions, Stripe, and
the entitlement provider that turns a plan into limits.

## Scope

**In:** DB-defined plans (admin-edited), flat or per-seat pricing, a free
default plan, trials, Stripe Checkout + Customer Portal + webhooks, seat sync,
grace-then-suspend on non-payment, a pluggable provider with a `manual`
implementation, reconcile CLI, tenant and admin screens.

**Out:** per-tenant limit overrides, coupons/add-ons, usage metering, more
than one subscription per tenant, embedded Stripe Elements, self-serve
signup/onboarding, invoices rendered in-app (the Stripe portal shows them),
UI i18n (repo-wide deferred work — see CLAUDE.md), cancelling the Stripe
subscription when a tenant is deleted (needs a `TenantDeleted` event in the
framework first; until then the README tells admins to cancel in Stripe
before deleting).

## Decisions

| Question | Decision |
|---|---|
| Plans' source of truth | `billing_plan` rows edited on an admin screen. Billing owns entitlements; Stripe owns money only. |
| Pricing | Per plan: `free`, `flat` or `per_seat`. |
| Free plan / trials | Exactly one free default plan; paid plans may set `trial_days`. |
| Non-payment | `past_due` keeps access with a banner; `unpaid` suspends; paid again reactivates; cancel drops to the free plan. |
| State flow | Webhook-driven local mirror; entitlement checks read local tables only. |
| Payment UI | Stripe-hosted Checkout and Portal — no card data touches the app. |
| Customer creation | Lazily at first checkout, not on `TenantCreated` (free tenants never need one; keeps Stripe off the signup path). |

## 1. Data model

`Base = create_module_base("billing")`, `AuditMixin` on every table, `billing_`
prefix. No `MultiTenantMixin`: webhooks, reconcile and the admin list span
tenants by nature (same reasoning as `tenants`' own tables). Every query
filters on `tenant_id` explicitly.

**`billing_plan`**

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `key` | str(64), unique | slug, e.g. `free`, `team` |
| `name`, `description` | str | |
| `pricing_model` | `free` \| `flat` \| `per_seat` | |
| `currency` | str(3) | lowercase ISO, e.g. `eur` |
| `amount_month`, `amount_year` | int \| None | minor units, display only (Stripe charges the price) |
| `stripe_price_month`, `stripe_price_year` | str \| None, unique when set | |
| `trial_days` | int, default 0 | |
| `limits` | JSON object `{key: int}` | absent key = unlimited; `0` forbids |
| `features` | JSON list of str | |
| `is_default` | bool | exactly one; must be `free` |
| `is_public` | bool | shown in the tenant plan picker |
| `sort_order` | int | |
| `archived_at` | datetime \| None | archive, never delete |

Invariants enforced by the plan service: one default; the default is `free`
and not archived; a `free` plan has no prices; a paid plan has at least one
price; a `free` plan has `trial_days = 0`.

**`billing_customer`** — `tenant_id` PK (FK `tenants_tenant.id`, cascade),
`provider` (`stripe`/`manual`), `provider_customer_id` (unique, nullable),
`email`.

**`billing_subscription`**

| Column | Notes |
|---|---|
| `id` | int PK |
| `tenant_id` | unique, FK cascade — one current subscription per tenant |
| `plan_id` | FK `billing_plan.id` |
| `status` | `trialing` `active` `past_due` `unpaid` `canceled` `incomplete` |
| `interval` | `month` \| `year` \| None |
| `provider_subscription_id` | unique, nullable (manual) |
| `quantity` | int, default 1 |
| `trial_end`, `current_period_end` | datetime \| None (UTC) |
| `cancel_at_period_end` | bool |
| `suspended_by_billing` | bool — billing never reactivates a tenant an admin suspended |
| `synced_at` | datetime \| None — last provider fetch |

**`billing_webhook_event`** — `id` (provider event id, PK), `provider`, `type`,
`received_at`, `processed_at` (nullable), `error` (text, nullable).

**Effective plan resolution:** status in {`trialing`, `active`, `past_due`} →
the subscription's plan; otherwise (no row, `canceled`, `incomplete`,
`unpaid`) → the default plan. One indexed query, no cache in v1.

The default free plan is seeded in `on_startup` when no plan exists
(idempotent), not by a migration.

## 2. Provider protocol and webhook flow

`billing/contracts/provider.py` — a `Protocol` speaking plain dataclasses:

```python
class BillingProvider(Protocol):
    name: str
    supports_checkout: bool
    async def ensure_customer(self, tenant_id, name, email) -> str | None: ...
    async def checkout_url(self, *, customer_id, price_id, quantity, trial_days,
                           tenant_id, success_url, cancel_url) -> str: ...
    async def portal_url(self, customer_id, return_url) -> str: ...
    async def change_plan(self, subscription_id, price_id, quantity) -> None: ...
    async def set_quantity(self, subscription_id, quantity) -> None: ...
    async def cancel_at_period_end(self, subscription_id) -> None: ...
    def parse_webhook(self, body: bytes, headers: Mapping[str, str]) -> WebhookEvent: ...
    async def fetch_subscription(self, subscription_id) -> SubscriptionSnapshot: ...
    async def verify_price(self, price_id) -> PriceInfo: ...
```

`WebhookEvent(id, type, subscription_id | None, tenant_id | None,
customer_id | None)`; `SubscriptionSnapshot(id, customer_id, tenant_id,
status, price_id, quantity, trial_end, current_period_end,
cancel_at_period_end)`; `PriceInfo(id, currency, interval, active)`.
`InvalidWebhookSignature` and `ProviderError` live beside the protocol.

- **`StripeProvider`** — official `stripe` SDK (range-pinned dependency),
  `StripeClient` per provider instance, all calls async via the SDK's async
  methods.
- **`ManualProvider`** — `supports_checkout = False`; no customer, checkout,
  portal or webhooks (`parse_webhook` always raises). Admins assign plan and
  status on the admin screen, which writes the subscription row directly.
- **`FakeProvider`** (tests only) — records calls, returns scripted snapshots.

**Webhook** `POST /billing/webhooks/stripe` (public, unauthenticated,
CSRF-exempt, raw body):

1. `parse_webhook` verifies the `Stripe-Signature` header with the webhook
   secret → 400 on failure.
2. Insert `billing_webhook_event`; if the id already exists with
   `processed_at` set → 200, no-op. Existing with `processed_at` null → retry.
3. Ignore the payload object; **re-fetch the subscription**
   (`fetch_subscription`) so out-of-order delivery always writes current state.
4. Map `price_id` → `(plan, interval)` via `billing_plan`; map the tenant from
   `metadata.tenant_id`, falling back to `billing_customer`. Upsert
   `billing_subscription`, set `synced_at`, apply lifecycle (§3).
5. Success → set `processed_at`, 200. Exception → roll back the sync, record
   `error` on the event row (separate commit), 500 so Stripe retries.
   Unknown price or tenant is an error (recorded, 500) — never silently
   granted the default plan.

Handled types: `checkout.session.completed`,
`customer.subscription.created|updated|deleted`. Others are recorded and
acknowledged without action.

**Checkout:** owner clicks Upgrade → `ensure_customer` (creates the
`billing_customer` row on first use) → `checkout_url` with `tenant_id` in
`client_reference_id` and subscription metadata, quantity = member count for
`per_seat` (1 otherwise), `trial_days` from the plan → redirect. Return to
`/billing?checkout=success`, which polls `GET /api/billing/status` until the
webhook lands. The redirect never grants a plan.

**Reconcile:** `smpy billing reconcile [--tenant ID]` (falls back to
`python -m billing.cli` if the framework has no CLI plugin seam) re-fetches
every subscription with a provider id, applies lifecycle, and pushes the
local member count when a per-seat quantity differs.

## 3. Entitlements, seats, lifecycle

**`PlanEntitlements`** installed in `on_startup` as
`app.state.tenants.entitlements`: `limit` → `plan.limits.get(key)`;
`has_feature` → `key in plan.features`. Consumers keep using the `tenants`
protocol and never import billing.

**Seat sync:** handlers on `MembershipAdded` / `MembershipRemoved` — when the
effective plan is `per_seat` and the subscription has a provider id, count
memberships and call `set_quantity` (Stripe prorates). A provider failure is
logged, never undoes the membership; reconcile corrects drift.

**Plan changes:** first paid plan → Checkout; paid → paid → `change_plan`
(proration) after an in-page confirm; paid → free → `cancel_at_period_end`.
A change is refused (409, "remove N members first") when current members
exceed the target plan's `tenants.seats`. Other limits only gate additions.

**Lifecycle** — a pure function
`decide(status, suspended_by_billing, tenant_status) -> Actions` plus an
applier calling `TenantService`:

| Status | Effect |
|---|---|
| `trialing`, `active` | plan entitlements; reactivate if `suspended_by_billing` |
| `past_due` | plan entitlements; tenant screen shows "payment failed" banner → portal |
| `unpaid` | `suspend` unless already suspended; set `suspended_by_billing` |
| `canceled`, `incomplete` | default plan; reactivate if `suspended_by_billing` |

A tenant suspended by an admin (`suspended_by_billing = false`) is never
reactivated by billing. Grace-then-suspend relies on Stripe's "if all retries
fail → mark the subscription as unpaid" setting; the README documents it
(with "cancel" the tenant drops to the free plan instead).

## 4. Screens, routes, permissions

Permissions (`billing/constants.py`), mapped onto tenant roles with
`registry.map_role(f"{TENANT_ROLE_PREFIX}{role}", ...)` as `tenants` does:

| Permission | Granted to |
|---|---|
| `Billing.View` | tenant `owner`, `admin` |
| `Billing.Manage` | tenant `owner` |
| `Billing.Platform.View`, `Billing.Platform.Manage` | platform admins |

(Exact string casing follows `tenants.constants` once read.)

**Tenant screen** `/billing` (sidebar "Billing"): current plan + status,
trial-ends notice, `past_due` banner, seats used/limit, plan picker (public,
non-archived, `sort_order`, month/year toggle), "Manage payment & invoices"
→ portal (Stripe only), `?checkout=success` polling. Plan-change confirm is
in-page — no browser dialogs.

**Admin screens:**
- `/admin/billing/plans` — list + create/edit (limits as key/number rows with
  `tenants.seats` suggested; features as tags; price IDs verified with
  `verify_price` against currency/interval on save under Stripe); archive;
  default toggle only on free plans.
- `/admin/billing/subscriptions` — every tenant with plan, status,
  `suspended_by_billing`, period end; status filter; "Resync" per row
  (Stripe); "Assign plan / set status" (manual provider).
- `/admin/billing/connection` — Stripe secret key + webhook secret entry,
  encrypted on save (§5); shows the webhook URL to paste into Stripe.

**JSON API** — `GET /api/billing/status`, `POST /api/billing/checkout`
→ `{url}`, `POST /api/billing/portal` → `{url}`,
`POST /api/billing/change-plan`; admin: plans CRUD + archive under
`/api/admin/billing/plans`, `POST /api/admin/billing/subscriptions/{tenant_id}/resync`,
`.../assign`, `PUT /api/admin/billing/connection`. Tenant routes resolve the
active tenant via the `tenants` deps — never a client-supplied `tenant_id`.
Inertia views and JSON APIs stay separate (SM018).

## 5. Settings, packaging, testing, layout

**`BillingSettings`** via `register_module_settings`, env/`.env`/secrets
sources dropped (like pagebuilder/news — no `SM_BILLING_*`):

| Field | Notes |
|---|---|
| `provider` | `manual` (default) / `stripe`; `json_schema_extra=_RESTART`; read from `app.state.billing.settings` in `on_startup` |
| `stripe_secret_key` | stored `enc:v1:<fernet>` (pattern of `sm_ai.crypto`, own copy in `billing/crypto.py` — billing must not depend on `ai`) |
| `stripe_webhook_secret` | same |
| `return_base_url` | optional origin for Checkout/portal return URLs; else request base URL |

Secrets are written through `/admin/billing/connection`, which encrypts;
a plaintext value (e.g. via `scripts/set_setting.py`) still works and logs a
one-time warning. `provider = stripe` without both secrets → error logged,
fall back to `manual`; the app still boots and the admin screens say why.

**Packaging:** `modules/billing/pyproject.toml` → `simple_module_billing`,
lockstep version; ranges only — `simple_module_core`, `_db`, `_hosting`,
`_settings`, `_tenants` `>=0.0.35,<0.1`, `stripe` major-range, `cryptography`;
entry point `billing = "billing.module:BillingModule"`. The host adds
`simple_module_tenants==0.0.35` and `simple_module_billing` (workspace
source). `scripts/bump_version.py` and its tests must cover the new module.

**Migration:** one autogenerated revision in `host/migrations/versions/` with
`branch_labels = ("billing",)`.

**Testing** — no network to Stripe in CI:

| Layer | Covers |
|---|---|
| Unit | `decide()` for every table row; effective-plan resolution; plan invariants; crypto round-trip |
| Integration (`FakeProvider`) | webhook idempotency, retry after failure, out-of-order events, unknown price/tenant, checkout + portal routes, change-plan incl. seat guard, seat sync on membership events, admin-suspended never reactivated, 402 on `tenants.seats` via `PlanEntitlements`, permission checks on every route, reconcile |
| Stripe adapter | signature verification on locally signed payloads with the real `stripe` verifier; snapshot mapping from recorded JSON fixtures |
| Frontend | Vitest: plan picker, status banners, plan editor validation |
| E2E | Playwright on the host with `ManualProvider`: create plan → assign → limit enforced |
| Manual | README walkthrough with `stripe listen --forward-to` in test mode |

**Layout** (every file ≤ 300 lines):

```
modules/billing/
  pyproject.toml  README.md
  billing/
    module.py constants.py settings.py models.py crypto.py
    contracts/provider.py
    providers/stripe.py providers/manual.py
    resolve.py entitlements.py lifecycle.py sync.py
    webhooks.py seats.py checkout.py plans.py cli.py
    endpoints/views.py api.py admin_views.py admin_api.py webhooks.py
    pages/            # Inertia pages only
    components/ hooks/ utils/
    tests/
```

## Open items to confirm in the plan

- How a module registers an `smpy` CLI subcommand.
- The tenants deps for "active tenant" and "user is owner" to reuse.
- Exact permission string convention in `tenants.constants`.
- How the settings module treats module-registered secret fields.
