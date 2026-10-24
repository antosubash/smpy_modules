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

## Metering usage (from another module)

For limits that are *used up* per billing period (API calls, AI tokens,
exports), billing installs a `UsageMeter` as `app.state.billing_usage`. Never
import billing at runtime: read the attribute, and treat `None` as "billing is
not installed, nothing is limited". The protocol is
`sm_billing.contracts.metering`; import it only under `TYPE_CHECKING`.
(Upstream issue antosubash/simple_module_python#616 tracks moving it next to
`EntitlementProvider` in `tenants.contracts`.)

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sm_billing.contracts.metering import UsageMeter

usage: UsageMeter | None = getattr(request.app.state, "billing_usage", None)
if usage is not None:
    outcome = await usage.consume(
        tenant_id,
        "ai.requests",
        1,
        request.headers.get("Idempotency-Key") or job_id,
        source="ai",
    )
    if not outcome.ok:  # Exceeded: used + qty would pass the limit
        raise HTTPException(402, f"limit {outcome.limit} reached")
```

| Call | Does |
|---|---|
| `consume(tenant, meter, qty, key, *, source, db=None)` | atomic check-and-count against the current period → `Allowed(used, limit, period_end, replayed)`, `Exceeded(used, limit, requested, period_end)` or, for a refunded key, `Refunded`; a refusal writes nothing |
| `record(tenant, meter, qty, key, *, source, occurred_at=None, db=None)` | count usage reported after the fact, unconditionally (may pass the limit; the next `consume` is then refused) |
| `refund(tenant, meter, key)` | reverse that call in the period it counted against; idempotent |
| `check(tenant, meter, qty=1)` | advisory and read-only — a UI hint, never enforcement |

The meter key is a `Plan.limits` key, exactly like an entitlement: absent is
unlimited, `0` forbids. Quantities are positive integers in the meter's minor
unit. A replayed `key` returns the original outcome with `replayed=True` and is
never counted twice; keys ending `:refund` or starting `adjust:` are reserved.

A key answers only for the call it was first used with. Reusing it with a
different quantity, kind (`consume` versus `record`) or `source` raises
`IdempotencyConflict` (409 `idempotency_conflict`) instead of replaying an
admission it never paid for. A key whose call was refunded replays as
`Refunded` (`ok` is false): it is spent, so a retry that should count again
needs a new key. Tell the outcomes apart with `outcome.ok`.
Never put personal data in a key or `source`.

Each call runs in its own short transaction. Pass `db=` only when the business
write that follows must be atomic with the usage *and* the rest of that
transaction is short: the counter's row lock is held until the caller commits,
so every other call for that tenant and meter waits behind it. On SQLite a
`db=` call can fail closed with 503 `usage_busy` (see the error table).

### Guarding a route: `RequiresQuota`

```python
from sm_billing.metering.deps import RequiresQuota

@router.post("/chat", dependencies=[RequiresQuota("ai.requests")])
async def chat(...): ...
```

It charges `qty` (default 1) of a registered counter meter to the request's
tenant before the handler runs. A refusal is 402
`{"detail": "quota_exceeded", "meter", "limit", "used", "requested", "resets_at"}`.
The charge is refunded **only when the handler raises**; a handler that returns
an error response keeps it. The dependency is function-scoped
(`Depends(..., scope="function")`, FastAPI 0.121+, billing's floor), so it
exits when the handler returns: a failure delivering the response afterwards
(the client disconnected) is not the handler's and refunds nothing. Before
refunding it rolls back the request session (`get_db`, the one the handler
uses), so a handler that wrote and then raised leaves no lock for the refund
to wait behind.

**One `Idempotency-Key` per operation: the handler runs at most once per key.**
A replay never reaches the handler, so one unit of quota cannot buy repeated
runs:

| The key's first request | A repeat with the same key gets |
|---|---|
| succeeded, or is still running (a concurrent duplicate) | 409 `idempotency_replay`: never a re-run, never charged. The first response is not stored (v1), so treat it as "already done" |
| raised, and was refunded | 409 `idempotency_key_spent`: the key is spent. Send a new key to run (and be charged) again |
| was on another route | 409 `idempotency_conflict` |

Without the header every request is charged as its own operation. Keys over
121 characters, or ending `:refund` / starting `adjust:`, get 400
`invalid_idempotency_key`.

### Gauges and holds

For capacity held over time (concurrent jobs, reserved bytes), register a
`gauge` meter and hold it:

| Call | Does |
|---|---|
| `reserve(tenant, meter, qty, key, *, source, ttl=None)` | atomically hold `qty` within the limit → `Hold` or `Exceeded`; `ttl` (seconds) defaults to the meter's `hold_ttl_seconds`, else `usage_hold_ttl_seconds` |
| `commit(hold_id)` | keep it with no expiry (stays counted until released); idempotent; `HoldExpired` (409 `hold_expired`) once lapsed or released |
| `release(hold_id)` | return the capacity; `False` if already settled; `HoldNotFound` (404) for an unknown id |
| `extend(hold_id, ttl)` | heartbeat: push a held hold's expiry to `ttl` seconds from now |
| `holding(tenant, meter, qty, key, *, source, ttl=None)` | `async with`: reserve (raises `QuotaExceededError` → 402), release on exit. The block runs at most once per key: a replayed key raises 409 `idempotency_replay` |

A hold that is neither committed nor extended lapses, and the sweeper returns
its capacity. Meters are registered on `app.state.billing_meters` in the
consumer's `on_startup` (`reg.define(key=..., kind="counter" | "gauge", unit=...,
label_key=..., hold_ttl_seconds=...)`); a call on an unregistered meter, or one
of the other kind, raises `UnknownMeterError`.

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
exists locally or at Stripe: trialing, active, past_due or unpaid. Use
change-plan. An `incomplete` one, a first payment that failed, does not block,
so the owner can check out again; Stripe expires the abandoned one on its own), `too_many_members` 409,
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
| `idempotency_conflict` | 409 | a metered route | the idempotency key was first used for a different call (quantity, kind or source) |
| `idempotency_replay` | 409 | a `RequiresQuota` route, `holding()` | the key's operation already ran (or is running); it is never run twice |
| `idempotency_key_spent` | 409 | a `RequiresQuota` route | the key's first run raised and was refunded; use a new key |
| `invalid_idempotency_key` | 400 | a `RequiresQuota` route | the `Idempotency-Key` header is empty, too long or reserved |
| `quota_exceeded` | 402 | a `RequiresQuota` route, `holding()` | `{"meter", "limit", "used", "requested", "resets_at"}`; `resets_at` is `null` for a gauge |
| `hold_not_found` / `hold_expired` | 404 / 409 | hold calls | unknown hold id / the hold lapsed or was released (`{"status"}`) |
| `usage_busy` | 503 | a metered route (SQLite) | the metering write could not take the database lock; nothing was counted. `Retry-After: 1` |
| `provider_error` | 502 | any | Stripe refused; `{"message"}` |
| `plan_limit` | 402 | other modules | from `tenants`: `{"key", "limit"}` |
