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
- **Events.** On `MembershipAdded` and `MembershipRemoved`, billing keeps the
  Stripe quantity of a per-seat plan equal to the member count. On
  `TenantDeleted` it cancels the tenant's subscription at Stripe (see
  *Deleting a tenant* below).

**Full documentation** lives in [`docs/`](docs/index.md):
[user guide](docs/user-guide.md) (admin screens and the owner's Billing page),
[API reference](docs/api-reference.md) (endpoints, errors, gating a feature on
a plan), [operations](docs/operations.md) (install, Stripe setup,
reconcile, troubleshooting) and [architecture](docs/architecture.md).

## Install

```bash
pip install simple_module_billing
```

The package depends on `simple_module_tenants>=0.0.36`. The host has to run
with `SM_MULTI_TENANT=true`, because the tenant billing screen needs an active
organisation. Billing ships SQLModel tables but no migrations. Autogenerate a
revision in the host and give its first revision
`branch_labels = ("billing",)`, so the module can be removed on its own with
`alembic downgrade billing@base`. Autogenerate again after upgrading billing,
since a release can add a column (`billing_customer.teardown_done_at` and two backoff columns, after
0.0.11).

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
| `POST /api/billing/checkout` `{plan_id, interval}` | Returns a Checkout `{url}` (first paid plan only) |
| `POST /api/billing/portal` | Returns a Customer Portal `{url}` |
| `POST /api/billing/change-plan` `{plan_id, interval}` | Paid → paid with proration; paid → free cancels at period end. Returns 409 `too_many_members` if the target's seats are fewer than those in use. |
| `/admin/billing/plans`, `/subscriptions`, `/connection` | Admin screens |
| `/api/billing/admin/plans` … `/subscriptions/{tenant_id}/assign` … `/connection` | Admin API |
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
  and `billing_webhook_event` stay, and the customer row is what maps Stripe's
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
- **Not in v1:** per-tenant limit overrides, coupons, usage metering, more
  than one subscription per tenant, and translated UI text.
