# Billing API reference

All routes are JSON. Every `POST`/`PUT` needs the session's CSRF token in an
`X-CSRF-Token` header; the billing pages expose it as the `csrf_token` Inertia
prop (`simple_module_hosting.csrf.get_csrf_token`). The webhook is the only
exception. Errors are `{"detail": "<code>", …}`; the full table is at the end.

## Gating a feature on a plan (from another module)

Never import billing. Ask the `tenants` entitlement seam, which billing fills
in at startup (without billing it answers "unlimited, every feature"):

```python
from tenants.contracts.entitlements import ensure_within_limit

entitlements = request.app.state.tenants.entitlements

# A count-based limit: raises EntitlementExceededError → HTTP 402
# {"detail": "plan_limit", "key": "storage.gb", "limit": 5}
await ensure_within_limit(entitlements, tenant_id, "storage.gb", current=used, adding=1)

# A yes/no feature
if not await entitlements.has_feature(tenant_id, "sso"):
    raise HTTPException(403, "Your plan does not include single sign-on.")

# The raw number: None = unlimited, 0 = forbidden
limit = await entitlements.limit(tenant_id, "exports.per_month")
```

Name keys `<module>.<thing>` (`storage.gb`, `exports.per_month`). An
administrator then sets them per plan in the plan editor's Limits and Features.
To have a key suggested in the editor, add it to `KNOWN_LIMIT_KEYS` in
`sm_billing/constants.py`.

## Tenant API — `/api/billing`

The organisation is always the session's **active tenant**; no route takes a
tenant id from the client.

### `GET /api/billing/status`

Permission: `billing.view` (tenant owner and admin). Also answers for the owner
of an organisation billing suspended (restore mode).

```json
{
  "plan": {"id": 2, "key": "team", "name": "Team", "pricing_model": "per_seat",
           "currency": "eur", "amount_month": 900, "amount_year": null,
           "stripe_price_month": "price_…", "stripe_price_year": null,
           "trial_days": 14, "limits": {"tenants.seats": 10}, "features": ["sso"],
           "description": "", "is_default": false, "is_public": true,
           "sort_order": 1, "archived_at": null},
  "subscription": {"status": "active", "interval": "month", "quantity": 4,
                   "trial_end": null, "current_period_end": "2026-11-01T00:00:00Z",
                   "cancel_at_period_end": false, "has_provider_subscription": true},
  "seats": {"used": 4, "limit": 10},
  "provider": "stripe",
  "checkout_available": true,
  "portal_available": true
}
```

`plan` is the plan **in force** (the default plan when the subscription has
lapsed). `subscription` is `null` for an organisation that never subscribed.
`seats.used` counts members plus pending invitations — the number the seat
limit is enforced against.

### `POST /api/billing/checkout`

Permission: `billing.manage` and tenant role `owner`. Body
`{"plan_id": 2, "interval": "month" | "year"}` (interval defaults to `month`).
Returns `{"url": "https://checkout.stripe.com/…"}`; redirect the browser there.
Nothing is granted until Stripe's webhook arrives.

Creates the Stripe customer on first use, expires the organisation's previous
open Checkout session, applies the plan's trial only if the organisation never
had a Stripe subscription, and sets the quantity to the member count for
per-seat plans.

Errors: `checkout_unavailable` 409 (manual provider), `plan_not_found` 404
(unknown, archived or hidden plan), `plan_is_free` 400,
`interval_unavailable` 400, `already_subscribed` 409 (a live subscription
exists locally or at Stripe — use change-plan), `too_many_members` 409,
`tenant_owner_required` 403, `provider_error` 502.

### `POST /api/billing/portal`

Permission: tenant role `owner` (with `billing.manage`, or restore mode for a
billing-suspended organisation). No body. Returns `{"url": "https://billing.stripe.com/…"}`.

Errors: `checkout_unavailable` 409, `no_customer` 409 (never checked out),
`tenant_owner_required` 403.

### `POST /api/billing/change-plan`

Permission: `billing.manage` and tenant role `owner`. Body as checkout. Paid →
paid moves the Stripe subscription with proration; → free sets it to cancel at
period end. The local row is re-synced from Stripe's answer and the new status
is returned (same shape as `GET /status`).

Errors: `no_subscription` 409 (use checkout), `already_on_plan` 409,
`too_many_members` 409 (`{"detail": "too_many_members", "used": 7, "limit": 5}`),
plus the checkout errors.

## Admin API — `/api/billing/admin`

Read routes need `billing.platform.view`; writes need `billing.platform.manage`.
Platform admins (role `admin`) hold both.

| Method & path | Body | Returns |
|---|---|---|
| `GET /plans` | — | every plan, archived included |
| `POST /plans` | plan (below) | the plan, 201 |
| `PUT /plans/{id}` | plan (same `key`) | the plan |
| `POST /plans/{id}/archive` | — | the plan |
| `GET /subscriptions?status=&offset=` | — | one row per organisation (200 per page) |
| `POST /subscriptions/{tenant_id}/assign` | `{"plan_id", "status", "interval"?}` | the row — manual provider only |
| `POST /subscriptions/{tenant_id}/resync` | — | the row — Stripe only |
| `GET /connection` | — | connection status (never the secrets) |
| `PUT /connection` | see below | connection status |

**Plan body**

```json
{"key": "team", "name": "Team", "description": "", "pricing_model": "flat",
 "currency": "eur", "amount_month": 1900, "amount_year": 19000,
 "stripe_price_month": "price_…", "stripe_price_year": "price_…",
 "trial_days": 14, "limits": {"tenants.seats": 10}, "features": ["sso"],
 "is_default": false, "is_public": true, "sort_order": 0}
```

Amounts are minor units (cents), 0–2,000,000,000; limit values the same range;
`trial_days` 0–730; `sort_order` ±1,000,000. Plan keys match
`^[a-z0-9][a-z0-9_-]{0,63}$`; limit keys and features match
`^[a-z0-9][a-z0-9_.-]{0,99}$`. A blank price is stored as `null`. Out-of-range
or malformed values are a 422. Reads never re-apply these bounds, so a row
stored before a bound existed still lists.

**Subscription row**

```json
{"tenant_id": "…", "tenant_name": "Acme", "tenant_slug": "acme",
 "tenant_status": "active", "members": 4, "plan_id": 2, "plan_key": "team",
 "plan_name": "Team", "status": "active", "interval": "month", "quantity": 4,
 "current_period_end": "…", "cancel_at_period_end": false,
 "suspended_by_billing": false, "provider_subscription_id": "sub_…",
 "synced_at": "…"}
```

**Connection body** — `{"stripe_secret_key": "", "stripe_webhook_secret": "",
"clear_secret_key": false, "clear_webhook_secret": false,
"return_base_url": "https://app.example.com"}`. A blank secret keeps the stored
one; `clear_*` removes it. Secrets are trimmed and stored encrypted. The
response is `{"provider", "active_provider", "provider_error",
"has_secret_key", "has_webhook_secret", "return_base_url", "webhook_path"}`.

## Webhook — `POST /billing/webhooks/stripe`

Public (exempt from login), no CSRF; authenticated by the `Stripe-Signature`
header. Returns 404 unless the Stripe provider is running.

| Response | Meaning | Stripe |
|---|---|---|
| 400 `invalid_signature` | bad or missing signature | gives up on this delivery |
| 200 `processed` | subscription re-fetched and applied | done |
| 200 `duplicate` | event id already processed | done |
| 200 `ignored` | not an event billing handles | done |
| 200 `ignored_unknown_tenant` | subscription belongs to no organisation here | done; reason kept on the event row |
| 200 `ignored_nothing_to_apply` | unknown price on a lapsed subscription we never had | done; reason kept |
| 500 `processing_failed` | anything else (Stripe unreachable, unknown price on a live subscription…) | retries with backoff |

Handled events: `checkout.session.completed` and
`customer.subscription.created|updated|deleted`.

## Error codes

| `detail` | Status | Where | Meaning |
|---|---|---|---|
| `tenant_required` | 403 | tenant API | no active organisation in the session |
| `tenant_owner_required` | 403 | tenant API | only the owner may do this |
| `forbidden` | 403 | status, portal | missing `billing.view` / `billing.manage` (other routes return the framework's own 403) |
| `checkout_unavailable` | 409 | tenant API | manual provider: nothing to pay through |
| `already_subscribed` | 409 | checkout | a live subscription exists |
| `no_subscription` | 409 | change-plan | nothing to change yet |
| `already_on_plan` | 409 | change-plan | target equals current |
| `no_customer` | 409 | portal | never checked out |
| `too_many_members` | 409 | checkout, change-plan | `used` exceeds the target's `limit` |
| `plan_is_free` / `interval_unavailable` | 400 | checkout | wrong target |
| `plan_not_found` | 404 | both | unknown, archived or hidden |
| `plan_key_taken` / `price_taken` | 409 | admin plans | uniqueness (also under concurrent creates) |
| `plan_key_immutable` | 400 | admin plans | key changed on update |
| `price_in_use` | 409 | admin plans | a live subscription is billed on the price being changed |
| `paid_plan_needs_price` / `free_plan_has_price` / `free_plan_has_trial` / `default_must_be_free` | 400 | admin plans | plan invariants |
| `default_required` / `cannot_archive_default` | 409 | admin plans | there must always be one free default |
| `price_not_found` / `price_mismatch` | 400 | admin plans (Stripe) | `{"price", "reason"}` |
| `provider_managed` | 409 | assign | Stripe owns subscriptions; use resync |
| `no_provider_subscription` | 409 | resync | nothing at Stripe to read |
| `tenant_not_found` | 404 | assign, resync | |
| `invalid_return_url` | 400 | connection | `{"message"}` says the rule |
| `provider_unavailable` | 503 | any | no provider built (startup failed) |
| `provider_error` | 502 | any | Stripe refused; `{"message"}` |
| `plan_limit` | 402 | other modules | from `tenants`: `{"key", "limit"}` |
