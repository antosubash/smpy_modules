# Billing module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `simple_module_billing` — DB-defined plans, Stripe Checkout/Portal/webhooks, a manual provider, and a `PlanEntitlements` provider that turns a tenant's plan into the limits `simple_module_tenants` enforces.

**Architecture:** Webhook-driven local mirror. Billing owns four tables keyed by `tenant_id`; webhooks re-fetch the subscription from the provider and upsert locally; entitlement checks read local tables only. A `BillingProvider` protocol isolates Stripe; `ManualProvider` lets admins assign plans without payment.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, simple_module_* 0.0.35 (core, db, hosting, inertia, settings, tenants), `stripe` 16.x, `cryptography` (Fernet), typer (CLI seam), React 19 + Inertia + `@simple-module-py/ui`, pytest/simple_module_test, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-billing-module-design.md`

## Global Constraints

- Package import name `sm_billing`; distribution `simple_module_billing`; `ModuleMeta.name = "Billing"`; lockstep version = root `pyproject.toml` version (`0.0.7`).
- Framework deps are ranges: `simple_module_core|db|hosting|inertia|settings|tenants >=0.0.35,<0.1`. Never `==` in the module. Host pins `simple_module_tenants==0.0.35`.
- `stripe>=16,<17`, `cryptography>=42`, `typer>=0.12`.
- Settings subclass `simple_module_core.settings_base.DbBackedSettings` (no env/.env). Restart-required fields use `json_schema_extra={"requires_restart": True}`; read them in `on_startup` from `app.state.sm_billing.settings`.
- No migrations in the module; one host revision with `branch_labels = ("billing",)`.
- Every `.py/.ts/.tsx` ≤ 300 lines. No literal permission/page/module strings outside `constants.py` (check_hardcoded_strings).
- Only real Inertia pages under `sm_billing/pages/`.
- Tenant status changes go through `TenantService.set_status(tenant_id, TenantStatus.X)`.
- Event handlers get only the event: open `app.state.sm.db.session_factory()` and commit explicitly; never raise out of a handler.
- CSRF: `Depends(RequiresCsrf())` on the tenant + admin API routers, `get_csrf_token(request)` passed as the `csrf_token` page prop; the webhook router has no CSRF.
- UI copy hardcoded English (repo-wide i18n deferred).

## Review Focus

1. A webhook for a subscription whose tenant has no `billing_customer` row (e.g. created in the Stripe dashboard with `metadata.tenant_id`) → still linked via metadata; with neither metadata nor customer → recorded error + 500, never the default plan. (Task 7 test `test_webhook_unknown_tenant_records_error`.)
2. Archiving a plan that tenants are subscribed to → their entitlements keep working; the plan disappears from the picker only. (Task 4 `test_archived_plan_still_resolves`.)
3. Two deliveries of different events for the same subscription concurrently → unique `tenant_id` holds; the loser retries via 500 and converges. (Task 7 `test_webhook_replay_after_failure_converges`.)
4. A logged-in user with no active tenant opening `/billing` → redirected to `/tenants/?reason=tenant_required`, not a 500. (Task 11 `test_billing_page_without_tenant_redirects`.)
5. Paid → free when the tenant has more members than the free plan's seats → 409 with the count, nothing sent to the provider. (Task 9 `test_change_plan_seat_guard`.)

---

## File map

```
modules/billing/
  pyproject.toml package.json tsconfig.json README.md
  sm_billing/
    __init__.py
    constants.py      # names, perms, pages, statuses, routes
    settings.py       # BillingSettings(DbBackedSettings)
    services.py       # BillingServices dataclass on app.state.sm_billing
    module.py         # BillingModule hooks
    models.py         # Plan, Customer, Subscription, WebhookEvent
    crypto.py         # enc:v1 Fernet, secret from app
    plans.py          # PlanService: CRUD, invariants, seed_default
    resolve.py        # effective_plan(db, tenant_id)
    entitlements.py   # PlanEntitlements
    lifecycle.py      # decide() + apply_lifecycle()
    contracts/provider.py   # Protocol + dataclasses + errors
    providers/manual.py providers/stripe.py providers/factory.py
    sync.py           # apply_snapshot()
    webhooks.py       # process_webhook()
    checkout.py       # BillingService: status/checkout/portal/change_plan
    seats.py          # membership handlers + push_quantity
    reconcile.py      # reconcile(app, tenant_id=None)
    cli.py            # typer app: reconcile
    deps.py           # FastAPI deps
    schemas.py        # pydantic I/O models
    endpoints/api.py admin_api.py webhooks.py views.py
    pages/Billing.tsx Plans.tsx Subscriptions.tsx Connection.tsx
    components/*.tsx  utils/api.ts utils/format.ts (+ *.test.ts)
  tests/ conftest.py fake_provider.py test_*.py
host/pyproject.toml host/migrations/versions/<rev>_billing.py
pyproject.toml (testpaths) .github/workflows/ci.yml release.yml
tests/e2e/billing.spec.ts
```

### Task 1: Scaffold, settings, module wiring

**Files:** create `modules/billing/{pyproject.toml,package.json,tsconfig.json,README.md}`, `sm_billing/{__init__,constants,settings,services,module}.py`, `tests/{conftest.py,test_module.py}`; modify `host/pyproject.toml`, root `pyproject.toml` testpaths, `.github/workflows/ci.yml`, `release.yml`.

**Produces:** `constants.PACKAGE="sm_billing"`, `MODULE_NAME="Billing"`, `PERM_VIEW="billing.view"`, `PERM_MANAGE="billing.manage"`, `PERM_PLATFORM_VIEW="billing.platform.view"`, `PERM_PLATFORM_MANAGE="billing.platform.manage"`, `ROLE_TENANT_OWNER="tenant:owner"`, `ROLE_TENANT_ADMIN="tenant:admin"`, `PROVIDER_MANUAL/STRIPE`, `BillingSettings(provider, stripe_secret_key, stripe_webhook_secret, return_base_url)`, `BillingServices(settings, provider=None)`.

- [ ] Test: `BillingSettings()` ignores `SM_BILLING_PROVIDER` env; `provider` field carries `requires_restart`; the app fixture (modules incl. Tenants, Billing) exposes `app.state.sm_billing`; `tenant:owner` resolves to `billing.view`+`billing.manage`, `tenant:admin` to `billing.view`; `tenant:member` gets neither.
- [ ] Implement; `uv sync --all-packages --all-extras`; tests pass; commit.

### Task 2: Models + host migration

**Files:** `sm_billing/models.py`, `tests/test_models.py`, `host/migrations/versions/*_billing.py`.

**Produces:** `Plan`, `Customer`, `Subscription`, `WebhookEvent` exactly as spec §1 (`limits: dict` and `features: list` via `sa_column=Column(JSON)`).

- [ ] Test: create a tenant row + plan + subscription; unique `tenant_id` on subscription; FK cascade on tenant delete (Postgres only, skipped on SQLite).
- [ ] `make migration msg="billing"`, add `branch_labels = ("billing",)`, review, `make migrate`; commit.

### Task 3: Crypto

**Files:** `sm_billing/crypto.py`, `tests/test_crypto.py`. Copy of `sm_ai.crypto` with `BillingKeyUnreadableError`, `set_secret_provider`, `encrypt_value`, `decrypt_value(stored, field)`.

- [ ] Tests: round trip; wrong secret → `BillingKeyUnreadableError`; plaintext passthrough logs once; empty → "".

### Task 4: Plans + resolution + entitlements

**Files:** `plans.py`, `resolve.py`, `entitlements.py`, tests `test_plans.py`, `test_entitlements.py`.

**Produces:**
```python
class PlanError(Exception): code: str  # -> 400/409 in API
class PlanService:
    def __init__(self, db: AsyncSession): ...
    async def list(self, *, include_archived=True) -> list[Plan]
    async def get(self, plan_id: int) -> Plan | None
    async def by_key(self, key: str) -> Plan | None
    async def by_price(self, price_id: str) -> tuple[Plan, str] | None  # (plan, interval)
    async def create(self, data: PlanIn) -> Plan
    async def update(self, plan_id: int, data: PlanIn) -> Plan
    async def archive(self, plan_id: int) -> Plan
    async def default(self) -> Plan
async def seed_default_plan(session_factory) -> None
async def effective_plan(db, tenant_id) -> tuple[Plan, Subscription | None]
class PlanEntitlements:  # EntitlementProvider
    def __init__(self, session_factory): ...
```
- [ ] Tests: invariants (one default; default free; free has no prices/trial; paid needs a price; key unique; archive default refused); seed idempotent; resolution per status table; archived plan still resolves; `limit` absent→None, `0`→0; `has_feature`; tenants' invitation endpoint returns 402 at the plan's `tenants.seats`.

### Task 5: Lifecycle

**Files:** `lifecycle.py`, `tests/test_lifecycle.py`.

```python
@dataclass(frozen=True)
class Actions: set_status: TenantStatus | None; suspended_by_billing: bool
def decide(status: str, suspended_by_billing: bool, tenant_status: str) -> Actions
async def apply_lifecycle(db, app, sub: Subscription) -> None
```
- [ ] Tests: every row of spec §3 table, incl. admin-suspended tenant never reactivated and `unpaid` on an already-suspended (admin) tenant leaving `suspended_by_billing` false.

### Task 6: Provider contracts, manual provider, fake provider, factory

**Files:** `contracts/provider.py`, `providers/manual.py`, `providers/factory.py`, `tests/fake_provider.py`, `tests/test_providers.py`.

`build_provider(settings) -> BillingProvider` returns Manual when `provider=="manual"` or Stripe secrets missing (logs error); else StripeProvider (Task 8).

### Task 7: Sync + webhook processing + endpoint

**Files:** `sync.py`, `webhooks.py`, `endpoints/webhooks.py`, `tests/test_webhooks.py`.

```python
async def apply_snapshot(db, app, snap: SubscriptionSnapshot) -> Subscription  # raises SyncError
async def process_webhook(app, provider, body: bytes, headers) -> int  # HTTP status
```
Public route: `registry.add_exact("/billing/webhooks/stripe", methods={"POST"})`.

- [ ] Tests (FakeProvider): bad signature 400; first delivery creates subscription; duplicate id no-op; failure records `error` and 500, replay converges; unknown price → error; unknown tenant → error; `deleted` → canceled → default plan; `unpaid` suspends; public-route registry covers the path.

### Task 8: StripeProvider

**Files:** `providers/stripe.py`, `tests/test_stripe_provider.py`, `tests/fixtures/subscription.json`.

- [ ] Tests: `parse_webhook` with a payload signed locally (`stripe.WebhookSignature` scheme `t=..,v1=hmac`) accepted, tampered rejected; snapshot mapping from fixture JSON (status, price, quantity, epoch→UTC datetimes, metadata tenant); methods call the `StripeClient` (mocked `http_client`) with expected params (checkout `client_reference_id`, `subscription_data.metadata.tenant_id`, `trial_period_days` only when >0).

### Task 9: Billing service (checkout / portal / change plan / status)

**Files:** `checkout.py`, `schemas.py`, `deps.py`, `endpoints/api.py`, `tests/test_billing_api.py`.

Routes (prefix `/api/billing`): `GET /status`, `POST /checkout {plan_id, interval}`, `POST /portal`, `POST /change-plan {plan_id, interval}`. Gates: view → `PERM_VIEW`; mutations → `PERM_MANAGE` + active tenant role `owner` (platform admins outside a tenant are refused by `require_active_tenant`).

- [ ] Tests: status shape; checkout under manual → 409 `checkout_unavailable`; checkout under fake → url + customer row created once; paid→paid calls `change_plan`; paid→free calls `cancel_at_period_end`; seat guard 409; member role 403; CSRF required.

### Task 10: Seat sync + reconcile + CLI

**Files:** `seats.py`, `reconcile.py`, `cli.py`, `tests/test_seats.py`, `tests/test_reconcile.py`; pyproject entry point `[project.entry-points."simple_module_cli.cli_plugins"] billing = "sm_billing.cli:app"`.

- [ ] Tests: adding a member on a per-seat sub pushes quantity; flat plan doesn't; provider failure swallowed; reconcile refreshes status and pushes drifted quantity; CLI `--help` lists `reconcile`.

### Task 11: Admin API + views

**Files:** `endpoints/admin_api.py`, `endpoints/views.py`, `tests/test_admin_api.py`, `tests/test_views.py`.

Admin API (`/api/billing/admin`): `GET/POST /plans`, `PUT /plans/{id}`, `POST /plans/{id}/archive`, `GET /subscriptions?status=`, `POST /subscriptions/{tenant_id}/resync`, `POST /subscriptions/{tenant_id}/assign {plan_id, status}` (manual only), `GET/PUT /connection`. Views: `/billing/` (tenant), `/billing/admin/plans`, `/billing/admin/subscriptions`, `/billing/admin/connection`.

- [ ] Tests: platform perms enforced; `verify_price` checked under stripe; connection PUT encrypts and GET masks; assign writes sub + lifecycle; views render page names with props; no-tenant redirect.

### Task 12: Frontend pages

**Files:** `pages/{Billing,Plans,Subscriptions,Connection}.tsx`, `components/*`, `utils/{api,format}.ts`, `*.test.ts(x)`.

- [ ] Vitest: `formatMoney`, `planCta(current, target)` (checkout/change/downgrade/current), limits-row editor validation; `make typecheck`, `npx biome check`.

### Task 13: Docs, lint, e2e

- [ ] README (Install, Usage, settings, permissions, routes, Stripe setup incl. "mark unpaid", tenant deletion caveat); `docs/adding-a-module` untouched.
- [ ] `tests/e2e/billing.spec.ts`: admin creates plan with `tenants.seats=1`, assigns it (manual), second invite → 402 shown.
- [ ] `make lint && make test && make build && make e2e`.
