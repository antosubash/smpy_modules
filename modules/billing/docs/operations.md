# Billing operations

## Install

1. Add the packages to the host (exact framework pin in the host, ranges in
   modules):

   ```toml
   dependencies = [
       "simple_module_tenants==0.0.35",
       "simple_module_billing",
   ]
   ```

2. Run with multi-tenancy on: `SM_MULTI_TENANT=true`. Without it no request has
   an active organisation and the tenant Billing page always redirects to
   `/tenants/`. The admin screens work either way.
3. Migrations live in the host. Autogenerate after installing, give the first
   billing revision `branch_labels = ("billing",)` (and the first tenants
   revision `("tenants",)` if the host didn't have tenants yet), read it, then
   apply:

   ```bash
   make migration msg="billing"
   make migrate          # alembic upgrade heads — one head per branch label
   ```

   Billing can be removed on its own with `alembic downgrade billing@base`.
4. Start the app. On every startup billing seeds a free **Free** plan if no
   default plan exists, builds the configured provider, and installs itself as
   `app.state.tenants.entitlements`.

## Settings

Stored in the database (Settings screen, `/admin/billing/connection`, or
`scripts/set_setting.py sm_billing <field> <value>`). Billing reads **no**
environment variables — an `SM_BILLING_*` line does nothing.

| Field | Default | Notes |
|---|---|---|
| `provider` | `manual` | `manual` or `stripe`. Read at startup: changing it needs a restart. |
| `stripe_secret_key` | — | `sk_live_…` / `sk_test_…`. Enter it on the connection screen, which encrypts it (`enc:v1:…`, Fernet keyed on the app's `secret_key`). A plaintext value still works and logs a one-time warning. |
| `stripe_webhook_secret` | — | `whsec_…`, same storage. |
| `return_base_url` | — | `https://app.example.com`. Origin for Checkout/portal return links. Blank uses the request's host — set it behind a proxy. |

> **Rotating the app's `secret_key` makes stored Stripe secrets unreadable.**
> Billing then falls back to `manual` at startup and the connection screen
> says why. Re-enter both secrets after a rotation.

## Connecting Stripe

1. In Stripe, create a Product and a recurring Price per interval you sell
   (monthly, yearly). For per-seat plans use per-unit pricing.
2. On **Admin → Billing → Plans**, create a plan per product and paste the
   `price_…` IDs. With Stripe active, each ID is checked on save.
3. On **Stripe connection**, enter the secret key and webhook signing secret
   and save.
4. In Stripe → Developers → Webhooks, add an endpoint at
   `https://<your host>/billing/webhooks/stripe` with the events
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`. Copy its
   signing secret into step 3 if you haven't.
5. **Stripe → Settings → Billing → Subscriptions and emails → Manage failed
   payments → "If all retries for a payment fail": choose "mark the
   subscription as unpaid".** This one setting is what gives organisations a
   grace period (`past_due`, still working) and then suspends them (`unpaid`).
   If it is set to cancel, a non-paying organisation drops to the free plan
   instead of being suspended.
6. Enable the Customer Portal (Stripe → Settings → Billing → Customer portal).
   **Do not let the portal switch customers to prices that belong to no plan**
   here: billing maps every subscription to a plan by its price, and an unknown
   price on a live subscription fails until a plan carries it.
7. Set `provider = stripe` on the Settings screen and restart.

To try it locally with test keys:

```bash
stripe listen --forward-to localhost:8000/billing/webhooks/stripe
# paste the whsec_… it prints into the connection screen
```

## Reconcile

```bash
smpy billing reconcile             # every organisation with a Stripe subscription
smpy billing reconcile --tenant ID # one organisation
```

Re-reads each subscription from Stripe, applies it exactly as a webhook would
(status, plan, period, suspension), and pushes the member count to Stripe for
per-seat plans whose quantity drifted. Safe to run while the app is live and
safe to repeat. Exit code 1 if any organisation failed (each is printed); the
others are still synced. Run it after a webhook outage, after restoring a
backup, or on a schedule as a backstop.

## Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Organisation paid but is still on the free plan | webhook not arriving, or failing | Stripe → Webhooks → endpoint → recent deliveries; `billing_webhook_event` rows with `processed_at IS NULL` and their `error`. Fix the cause, then `smpy billing reconcile --tenant ID` (or **Resync**). |
| Webhook deliveries return 400 | wrong signing secret | Re-enter the endpoint's `whsec_…` on the connection screen. |
| Webhook deliveries return 404 | provider isn't `stripe`, or it fell back to manual | Connection screen banner; restart after setting `provider = stripe`. |
| Webhook error `unknown_price` | the subscription's price is on no plan (portal plan switching, a price created by hand) | Add the price to a plan (or a new plan), then reconcile. |
| Event row reads `SyncError: unknown_tenant` with status 200 | a subscription from another product on the same Stripe account, or a deleted organisation | Nothing to do; it is acknowledged on purpose so Stripe doesn't disable the endpoint. |
| Organisation shows **Suspended (unpaid)** | retries ran out | The owner pays from **Billing → Pay now**; the next webhook reactivates it. To lift it by hand on the manual provider, assign **Active**. |
| Organisation shows **Suspended** (no "unpaid") | an administrator suspended it on the Organisations screen | Billing never lifts this; reactivate it there. |
| Owner can't downgrade: "remove N first" | members plus pending invitations exceed the target plan's seats | Remove members or revoke invitations. |
| Per-seat quantity at Stripe differs from members | a membership change happened while Stripe was unreachable | `smpy billing reconcile`. |
| "Changing a price that is in use" when editing a plan | a live subscription bills on that price | Create a new plan with the new price; move organisations to it. |
| Connection screen: "cannot be decrypted" | app `secret_key` changed | Re-enter both Stripe secrets. |
| Checkout says "already subscribed" but the page shows the free plan | a subscription exists at Stripe the app hasn't recorded | `smpy billing reconcile --tenant ID`. |

## Data and deletion

Billing's tables (`billing_plan`, `billing_customer`, `billing_subscription`,
`billing_webhook_event`) hold `tenant_id` as a plain column: one module cannot
hold a foreign key into another module's tables. **Deleting an organisation
neither cancels its Stripe subscription nor removes its billing rows** — the
`tenants` module publishes no deletion event yet. Cancel the subscription in
Stripe before deleting an organisation. `billing_webhook_event` grows by one
row per delivery; prune processed rows older than Stripe's retry window
(three days) if it matters.
