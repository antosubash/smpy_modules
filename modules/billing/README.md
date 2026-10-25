# simple_module_billing

Plans, subscriptions and Stripe payments for multi-tenant SimpleModule apps.

Billing is the commercial layer on top of the framework's `tenants` module.
It changes none of the tenants code. Instead it plugs into the seams that
module exposes:

- **Entitlements.** Billing installs `PlanEntitlements` as
  `app.state.tenants.entitlements`. A tenant's plan then answers
  `limit(tenant_id, key)` and `has_feature(tenant_id, key)`. The seat limit
  that `tenants` already enforces on members and invitations (HTTP 402) is
  taken from the plan's `tenants.seats`.
- **Lifecycle.** When a subscription becomes `unpaid`, billing suspends the
  tenant through `TenantService.set_status`. When payment recovers, billing
  reactivates it. A tenant that an admin suspended by hand is never
  reactivated by billing.
- **Usage metering.** Billing installs a `UsageMeter` as
  `app.state.billing_usage`: race-safe, idempotent per-period counters and
  gauge holds, enforced against the plan's limits (see *Usage metering*
  below).
- **Events.** On `MembershipAdded` and `MembershipRemoved`, billing keeps the
  Stripe quantity of a per-seat plan equal to the member count. On
  `TenantDeleted` it cancels the tenant's subscription at Stripe (see
  *Deleting a tenant* below).

**Full documentation** lives in [`docs/`](docs/index.md):
[user guide](docs/user-guide.md) (admin screens and the owner's Billing page),
[API reference](docs/api-reference.md) (endpoints, errors, gating a feature on
a plan, metering usage), [operations](docs/operations.md) (install, Stripe
setup, reconcile, the usage sweeper, troubleshooting) and
[architecture](docs/architecture.md).

## Install

```bash
pip install simple_module_billing
```

The package depends on `simple_module_tenants>=0.0.36` and `fastapi>=0.121`
(for the function-scoped `RequiresQuota` dependency). The host has to run
with `SM_MULTI_TENANT=true`, because the tenant billing screen needs an active
organisation. Billing ships SQLModel tables but no migrations. Autogenerate a
revision in the host and give its first revision
`branch_labels = ("billing",)`. The label only names the revision:
`alembic downgrade billing@base` walks every revision beneath it, not billing
alone. Autogenerate again after upgrading billing, since a release can add a
column or a table (`billing_customer.teardown_done_at` and two backoff columns
after 0.0.11; the four `billing_usage_*` tables,
`billing_subscription.current_period_start` and
`billing_usage_period.provider_period` with usage metering).

The database must be Postgres or SQLite 3.35 or newer: usage metering
enforces limits with `INSERT … ON CONFLICT … DO UPDATE … WHERE … RETURNING`,
and startup refuses anything else. Nothing else is needed (no Redis): the
counters live in the database.

On first start, billing seeds a free default plan (`free`). It is idempotent,
so a fresh install entitles every tenant before an admin has opened the plan
editor.

## Usage

### Plans

Edit plans on **Admin → Billing → Plans** (`/admin/billing/plans`). Each plan
has the following:

| Field | Meaning |
|---|---|
| `pricing_model` | `free`, `flat` (one price) or `per_seat` (the Stripe quantity tracks members) |
| `stripe_price_month` / `stripe_price_year` | Stripe Price IDs. Under Stripe they are checked on save to exist, be active, and match the plan's currency and interval. |
| `amount_month` / `amount_year` | Minor units, for display only. Stripe charges whatever the price says. |
| `trial_days` | Trial length passed to Checkout. Free plans have no trial. |
| `limits` | `{key: int}`. **A key that is not set means unlimited; `0` forbids.** `tenants.seats` caps members plus pending invitations. |
| `features` | Keys that `has_feature` answers `true` for |

A Stripe price that a live subscription is billed on cannot be swapped or
removed (`409 price_in_use`): webhooks map a subscription to its plan through
its price. Create a new plan for new pricing instead. For the same reason, do
not let the Customer Portal switch customers to prices that belong to no plan.

Exactly one plan is the default. It must be free, and it can be neither
unset nor archived. To change the default, mark another free plan as default.
Plans are archived, never deleted. Tenants already on an archived plan keep
it, but it no longer appears in the plan picker.

A tenant's plan is decided like this:

- If the subscription status is `trialing`, `active` or `past_due`, the
  tenant gets the subscribed plan.
- In every other case (no subscription, `canceled`, `incomplete`, `unpaid`),
  the tenant gets the default plan.

Consumers ask the `tenants` protocol and never import billing:

```python
limit = await request.app.state.tenants.entitlements.limit(tenant_id, "storage.gb")
```

### Usage metering

For limits that are *used up* per billing period (API calls, AI tokens,
exports) or *held* at once (concurrent jobs), a module registers a meter and
counts against it. The meter key is a `Plan.limits` key, set per plan in the
plan editor, which suggests every registered meter. An absent key is
unlimited and `0` forbids.

```python
# In your module's on_startup: no billing import.
reg = getattr(app.state, "billing_meters", None)
if reg is not None:
    reg.define(key="ai.requests", kind="counter", label_key="ai.meters.requests")

# On a route: charge 1 per request, answer 402 quota_exceeded when used up.
from sm_billing.metering.deps import RequiresQuota

@router.post("/chat", dependencies=[RequiresQuota("ai.requests")])
async def chat(...): ...

# Or directly; None means billing is not installed, so nothing is limited.
usage = getattr(request.app.state, "billing_usage", None)
outcome = await usage.consume(tenant_id, "ai.requests", 1, job_id, source="ai")
if not outcome.ok:
    ...
```

- **Counters** reset each billing period: the Stripe period when there is
  one, else the UTC calendar month. `consume` checks and counts in one
  statement, `record` counts after the fact, `refund` reverses a call, `check`
  is an advisory read.
- **Gauges** are levels held by holds: `reserve`, `commit`, `release`,
  `extend` and `async with usage.holding(...)`. A hold that is neither
  committed nor extended lapses after its TTL, and the hold sweeper returns
  its capacity.
- **Idempotent.** Every call carries a key; a replay is never counted twice,
  and a key reused for a different call is a 409. With `RequiresQuota`, a
  replayed `Idempotency-Key` never re-runs the handler. The charge is refunded
  only when the handler raises.
- **Race-safe** on Postgres and SQLite: concurrent calls against limit N
  admit exactly N. Each write is its own short transaction, finished with
  `finalize_session`. `db=` joins the caller's transaction instead; pass it
  only when the rest of that transaction is short, because the counter's row
  lock is held until it commits.

Organisations see a **Usage** card on `/billing/`; platform admins get a
**Usage** tab (`/admin/billing/usage`) with filters, a per-organisation
ledger and open holds, and **Release**, **Recount** and **Adjust** (with a
required reason). The protocol is `sm_billing.contracts.metering`; upstream
issue antosubash/simple_module_python#616 tracks moving it into the
framework.

### Providers

Billing settings are stored in the database. They are registered with
`register_module_settings` and read no environment variables, so a
`SM_BILLING_*` variable has no effect.

| Setting | Notes |
|---|---|
| `provider` | `manual` (the default) or `stripe`. Takes effect on save, no restart. |
| `stripe_secret_key` | `sk_…`. Stored as `enc:v1:<fernet>`, encrypted with the app's `secret_key`. |
| `stripe_webhook_secret` | `whsec_…`, encrypted the same way. |
| `return_base_url` | Origin that Stripe returns visitors to. If empty, the request's own origin is used. |
| `reconcile_interval_minutes` | `0` (off) or N: re-read every subscription not synced for N minutes, on a loop inside the app. Takes effect on save, no restart. |
| `usage_hold_ttl_seconds` | `900`: how long a usage hold lasts unless its meter or caller sets a TTL. |
| `usage_sweep_interval_seconds` | `60`: how often lapsed holds are expired and the ledger purged; `0` turns the sweep off. |
| `usage_event_retention_days` | `400`: days the usage ledger is kept (`0` forever); the per-period totals are never purged. |

- **manual.** There is no payment. Admins assign a plan and status on
  **Admin → Billing → Subscriptions**. Setting `unpaid` suspends the tenant.
- **stripe.** Payment uses Stripe Checkout (first paid plan), the Customer
  Portal (cards, invoices, cancellation) and webhooks. If you choose `stripe`
  without both secrets, the app still boots on `manual`, and the Connection
  screen explains why.

### Stripe setup

1. Create a Product and recurring Prices in Stripe. Put their IDs on the
   plans.
2. Enter the secret key and webhook secret on **Admin → Billing → Stripe
   connection** (`/admin/billing/connection`). This screen encrypts them.
   Saving new secrets rebuilds the provider immediately.
3. Add a webhook endpoint at `https://<host>/billing/webhooks/stripe` for
   `checkout.session.completed` and `customer.subscription.created|updated|deleted`.
4. Under **Settings → Billing → Subscriptions → Manage failed payments**,
   choose **"mark the subscription as unpaid"**. This setting is what makes
   billing allow a grace period and then suspend. If it is set to "cancel",
   the tenant drops to the free plan instead of being suspended.
5. Enable the Customer Portal (Settings → Billing → Customer portal).

To try it locally:

```bash
stripe listen --forward-to localhost:8000/billing/webhooks/stripe
```

A tenant gets one trial: after any earlier Stripe subscription, Checkout runs
without `trial_days`. Starting a new Checkout expires the tenant's previous
open session, and Checkout is refused while Stripe still lists a live
subscription for the customer, so two tabs cannot buy two subscriptions.

The owner of an organisation that billing suspended can still open
`/billing/` in a pay-only "restore" mode (status and Customer Portal, no plan
changes); paying there reactivates it through the next webhook. An
organisation an admin suspended stays closed.

Webhooks are verified, deduplicated by event id, and never trusted for state:
each one re-fetches the subscription from Stripe, so events that arrive out
of order are harmless. A failed delivery records its error in
`billing_webhook_event` and returns 500, so Stripe retries it. A subscription
that maps to no tenant (another product on the same Stripe account, or a
tenant since deleted) is recorded and acknowledged with 200 instead, so it
cannot get the endpoint disabled. A cancellation or `unpaid` whose price no
plan knows is still applied, on the plan the tenant had.

### Reconcile

```bash
smpy billing reconcile [--tenant ID]
```

Re-fetches every Stripe subscription and pushes any drift in per-seat
quantity. It is safe to run while the app is live and safe to run twice. Use
it after missed webhooks or a Stripe outage. Set `reconcile_interval_minutes`
to have the app do it on a schedule, safely across several instances — see
[operations](docs/operations.md#scheduled-reconcile).

## Permissions

| Permission | Granted to |
|---|---|
| `billing.view` | tenant `owner`, `admin` |
| `billing.manage` | tenant `owner`. Checkout, plan changes and the portal also require the owner role in the active tenant. |
| `billing.platform.view` / `billing.platform.manage` | platform admins (the `admin` role holds `*`) |

## Routes

| Route | What |
|---|---|
| `GET /billing/` | Tenant screen: current plan, seats, plan picker, portal |
| `GET /api/billing/status` | Plan, subscription, seats, provider |
| `GET /api/billing/usage` | The organisation's meters: used, limit, when each counter resets |
| `POST /api/billing/checkout` `{plan_id, interval}` | Returns a Checkout `{url}` (first paid plan only) |
| `POST /api/billing/portal` | Returns a Customer Portal `{url}` |
| `POST /api/billing/change-plan` `{plan_id, interval}` | Paid → paid with proration; paid → free cancels at period end. Returns 409 `too_many_members` if the target's seats are fewer than those in use. |
| `/admin/billing/plans`, `/subscriptions`, `/connection`, `/usage` | Admin screens |
| `/api/billing/admin/plans` … `/subscriptions/{tenant_id}/assign` … `/connection` | Admin API |
| `/api/billing/admin/usage` … `/{tenant_id}/events`, `/holds`, `/adjust`, `/recount`, `/holds/{hold_id}/release` | Admin usage API (reads `billing.platform.view`, writes `billing.platform.manage`) |
| `POST /billing/webhooks/stripe` | Public. The signature is the authentication. |

Every API mutation needs the `X-CSRF-Token` header, which views expose as
the `csrf_token` prop.

## Known limits

- **Deleting a tenant.** On `TenantDeleted` (framework 0.0.38,
  `TenantService.delete_tenant`) billing cancels the tenant's Stripe
  subscription **immediately**, not at period end, along with any other live
  subscription of its Stripe customer, and expires an open Checkout session.
  The local row then turns `canceled` from a re-fetch. Billing's rows are
  **kept for audit**: `billing_subscription` (canceled), `billing_customer`
  and `billing_webhook_event` stay (so do the usage ledger and counters), and the customer row is what maps Stripe's
  late `customer.subscription.deleted` back to them. If Stripe fails, the
  delete still stands; the error is logged and the next reconcile cancels it.
  That includes a subscription not mirrored yet and an open checkout: reconcile
  sweeps every customer whose organisation is gone until its teardown completes
  (`billing_customer.teardown_done_at`), then skips it. A teardown that keeps
  failing backs off (from 15 minutes up to a day), whichever path tried it,
  and one atomic claim per organisation means only one worker at a time calls Stripe.
  Stripe's "no such customer" is retried too, because a key from another
  account or mode gives the same answer. A single-tenant host never sweeps. The Checkout session id
  is forgotten only once Stripe says the session is no longer open. Everything
  that has not ended is canceled, `incomplete` and `paused` included, across
  every page of the customer's subscriptions.
  A subscription that was never at a provider is marked canceled, and the
  customer's Stripe subscriptions, if it has any, are still canceled. Under the
  `manual` provider nothing reaches Stripe, and a tenant with a Stripe customer
  is logged for you to cancel there. On a framework older than 0.0.38 there is
  no event and no delete, so billing subscribes to nothing.
- **Usage metering (v1).** No module in this repo meters anything yet (the
  `ai` module's `ai.requests` is the planned first consumer; the demo host
  registers `demo.exports` and `demo.jobs`). Not in v1: storing the first
  response for a replayed `Idempotency-Key` (the replay gets 409
  `idempotency_replay`), reporting usage to Stripe metered prices, threshold
  events or emails, and an audit trail of refused calls (they are logged).
- **Not in v1:** per-tenant limit overrides, coupons, more
  than one subscription per tenant, and translated UI text.
