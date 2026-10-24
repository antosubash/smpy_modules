# Billing operations

## Install

1. Add the packages to the host (exact framework pin in the host, ranges in
   modules):

   ```toml
   dependencies = [
       "simple_module_tenants==0.0.38",
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
   make migrate          # alembic upgrade heads (the history has a single head)
   ```

   After upgrading billing, autogenerate again: a release can add a column
   (the first release after 0.0.11 adds `billing_customer.teardown_done_at`,
   for the deleted-tenant sweep), and billing reads it on every reconcile.

   The `billing` branch label names the revision; it does **not** make
   `alembic downgrade billing@base` remove billing alone. Autogenerate chains
   every revision off the current head, so that command walks everything
   beneath it. Upstream #333 was closed in 0.0.36 as a docs correction, not a
   behaviour change (antosubash/simple_module_python#333).
4. Start the app. On every startup billing seeds a free **Free** plan if no
   default plan exists, builds the configured provider, and installs itself as
   `app.state.tenants.entitlements`.

## Settings

Stored in the database (Settings screen, `/admin/billing/connection`, or
`scripts/set_setting.py sm_billing <field> <value>`). Billing reads **no**
environment variables — an `SM_BILLING_*` line does nothing.

| Field | Default | Notes |
|---|---|---|
| `provider` | `manual` | `manual` or `stripe`. Takes effect on save, no restart (see [Switching provider](#switching-provider)). |
| `stripe_secret_key` | — | `sk_live_…` / `sk_test_…`. Enter it on the connection screen, which encrypts it (`enc:v1:…`, Fernet keyed on the app's `secret_key`). A plaintext value still works and logs a one-time warning. |
| `stripe_webhook_secret` | — | `whsec_…`, same storage. |
| `return_base_url` | — | `https://app.example.com`. Origin for Checkout/portal return links. Blank uses the request's host — set it behind a proxy. |
| `reconcile_interval_minutes` | `0` | Run [reconcile](#reconcile) inside the app every N minutes over subscriptions not synced for N minutes. `0` is off. Takes effect on save: the loop starts, stops or re-times itself. `60` suits most deployments. |

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
7. Set `provider = stripe` on the Settings screen. It takes effect on save.

## Switching provider

Saving `provider`, either Stripe secret or `reconcile_interval_minutes` — on
the Settings screen or the connection screen — rebuilds the provider and the
reconcile loop in the running process; no restart.

- **manual → stripe**: the next request uses Stripe (checkout, portal, price
  checks on plan save, seat pushes). If a secret is missing or can't be
  decrypted, billing stays on `manual` and the connection screen says why;
  saving the missing secret completes the switch. A configured
  `reconcile_interval_minutes` starts its loop.
- **stripe → manual**: Stripe calls stop; the reconcile loop stops. Webhook
  deliveries get **404 `stripe_not_configured`** — Stripe retries them for up
  to three days, so switching back within that window processes them (each
  event once). Subscriptions stay as last synced; run `smpy billing reconcile`
  after switching back.
- **Rotating the webhook signing secret**: applies on save. Deliveries signed
  with the old secret get 400 until the Stripe endpoint uses the new one.
- A request already in flight finishes with the provider it started with.

- **Other workers and instances.** The framework's hot-swap reaches only the
  process that served the save. Every other one re-reads the stored provider
  fields (one indexed query) before each billing request, webhook, seat push
  and reconcile tenant, and rebuilds when they differ — so a worker never
  writes through a provider the database no longer names. Its reconcile loop
  starts, stops or re-times at its next tick (or its next billing request).
- **`scripts/set_setting.py`** writes the database only. The provider fields
  are picked up the same way, at the next billing request; any other billing
  setting written that way is read at the next boot.

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
others are still synced. Run it after a webhook outage or after restoring a
backup.

### Scheduled reconcile

Nothing re-reads Stripe on its own unless you turn it on: a missed webhook or a
seat push that failed while Stripe was unreachable otherwise stays wrong until
someone runs the command above. Set `reconcile_interval_minutes` (Settings
screen, or `scripts/set_setting.py sm_billing reconcile_interval_minutes 60`)
(on save from the Settings screen; a `set_setting.py` value at the next boot),
and the app runs the same per-organisation sync on a loop:

- Every N minutes it picks the subscriptions whose `synced_at` is older than N
  minutes, oldest first. A webhook or a **Resync** refreshes `synced_at`, so a
  subscription Stripe already told us about is not fetched again.
- Each organisation is synced bound to its own tenant and committed with
  `finalize_session`, so a suspension or reactivation publishes
  `TenantStatusChanged` and clears the membership cache exactly as a webhook
  would. One organisation failing is logged and the rest carry on; its claim is
  released, so the next tick retries it (a failure after the snapshot was applied, i.e. the seat push, keeps the fresh stamp and retries one interval later).
- **Several app instances are safe.** Every process runs the loop, but each
  organisation is claimed with a conditional `UPDATE` on its `synced_at`
  before Stripe is called, so in any window exactly one instance fetches it.
  The sync itself is idempotent anyway (a quantity is *set*, not added).
- **Rate limits.** Organisations are synced one at a time with a 0.2 s pause
  (a few Stripe calls a second; the SDK also retries a 429 with backoff). Each
  Stripe error doubles the pause, up to 30 s, and five in a row end the tick —
  an outage is waited out until the next interval, not hammered. An
  organisation whose sync failed on the previous tick (its subscription was
  deleted in Stripe, say) is retried after the others, so a few permanently
  failing ones cannot end every tick before the healthy ones are reached.

Prefer an external scheduler (cron, a Kubernetes CronJob)? Leave the setting at
`0` and run `smpy billing reconcile` from there.

**Admin → Billing → Subscriptions** shows, under Stripe, how old the oldest
`synced_at` is, how many subscriptions were never synced, how many webhook
rows are unprocessed, and whether the scheduled reconcile is running. An old
"oldest sync" with the loop off, or any unprocessed webhook, is worth a look.

## Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Organisation paid but is still on the free plan | webhook not arriving, or failing | The subscriptions screen's "Unprocessed webhooks" count; Stripe → Webhooks → endpoint → recent deliveries; `billing_webhook_event` rows with `processed_at IS NULL` and their `error`. Fix the cause, then `smpy billing reconcile --tenant ID` (or **Resync**). |
| Webhook deliveries return 400 | wrong signing secret | Re-enter the endpoint's `whsec_…` on the connection screen. |
| Webhook deliveries return 404 | provider isn't `stripe`, or it fell back to manual | Connection screen banner; set `provider = stripe` and any missing secret. |
| Webhook error `unknown_price` | the subscription's price is on no plan (portal plan switching, a price created by hand) | Add the price to a plan (or a new plan), then reconcile. |
| Event row reads `SyncError: unknown_tenant` with status 200 | a subscription from another product on the same Stripe account, or a deleted organisation | Nothing to do; it is acknowledged on purpose so Stripe doesn't disable the endpoint. |
| Organisation shows **Suspended (unpaid)** | retries ran out | The owner pays from **Billing → Pay now**; the next webhook reactivates it. To lift it by hand on the manual provider, assign **Active**. |
| Organisation shows **Suspended** (no "unpaid") | an administrator suspended it on the Organisations screen | Billing never lifts this; reactivate it there. |
| Owner can't downgrade: "remove N first" | members plus pending invitations exceed the target plan's seats | Remove members or revoke invitations. |
| Per-seat quantity at Stripe differs from members | a membership change happened while Stripe was unreachable | The scheduled reconcile pushes it within one to two intervals; without it, `smpy billing reconcile`. |
| "Changing a price that is in use" when editing a plan | a live subscription bills on that price | Create a new plan with the new price; move organisations to it. |
| Connection screen: "cannot be decrypted" | app `secret_key` changed | Re-enter both Stripe secrets. |
| Checkout says "already subscribed" but the page shows the free plan | a subscription exists at Stripe the app hasn't recorded | `smpy billing reconcile --tenant ID`. |

## Data and deletion

Billing's tables (`billing_plan`, `billing_customer`, `billing_subscription`,
`billing_webhook_event`) hold `tenant_id` as a plain column: one module cannot
hold a foreign key into another module's tables, so deleting an organisation
does not cascade into them.

**Deleting an organisation cancels its Stripe subscription immediately**
(framework 0.0.38's `TenantDeleted`): every subscription of its Stripe customer
that still bills or grants access is canceled — no proration credit, no final
invoice, Stripe's defaults — an open Checkout session is expired, and the
local row is re-fetched to `canceled`. The billing rows are **kept** for audit
and so that Stripe's own `customer.subscription.deleted` webhook still maps to
them. If Stripe is unreachable at that moment the delete is not held up: the
log says `could not cancel the subscription of deleted tenant`, and the next
reconcile (the scheduled one, or `smpy billing reconcile`) cancels it — a
reconcile never re-applies a subscription whose organisation is gone. Every
reconcile also sweeps the Stripe customers whose organisation is gone and whose
teardown has not completed (`billing_customer.teardown_done_at` unset). That
reaches what no subscription row points at: a subscription not mirrored yet,
and an open Checkout session that could not be expired, which stays recorded
unless Stripe reports it completed or expired. A finished teardown is
stamped, and the sweep skips it from then on. Organisations deleted before
this release are swept too, on the first reconcile after the upgrade. "Still
bills" means any status that has not ended (`canceled`, `incomplete_expired`),
so `incomplete` and `paused` are canceled too. Under the
`manual` provider nothing reaches Stripe; a log line asks you to cancel there
if the organisation had a Stripe subscription from before the switch.

`billing_webhook_event` grows by one
row per delivery; prune processed rows older than Stripe's retry window
(three days) if it matters.
