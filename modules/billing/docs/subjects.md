# Billing subject: organisations or users

A **billing subject** is whoever holds a subscription and a usage counter.
Every billing table keys on one string (the `tenant_id` column), and the
`subject_mode` setting decides what that string names.

| Mode | Subject | Use it for |
|---|---|---|
| `tenant` (default) | the tenant id, or `default` on a single-tenant host | organisations that subscribe and pay together |
| `user` | `user:<uuid>`, e.g. `user:0b9c…` (lowercase, hyphenated) | a single-tenant host where each person subscribes as themselves |

## Switching mode

Set `subject_mode` on the Settings screen or with
`scripts/set_setting.py sm_billing subject_mode user`, then **restart**: the
mode is read once at startup. At boot, in `user` mode, billing:

- **refuses to start** when `multi_tenant` is on: user mode replaces the
  active-organisation checks (`deps.require_active`) with the signed-in user,
  which only makes sense where there are no organisations
  (`sm_billing/core/subject_boot.py`);
- maps `billing.view` and `billing.manage` onto the framework's `user` role,
  so every signed-in user can open their own Billing page;
- subscribes the `UserDeleted` teardown (below);
- logs a warning when it applies (see [Rows do not move](#rows-do-not-move)).

In `tenant` mode nothing changes.

## Rows do not move

Switching changes which rows are *visible*, not where they live.
Subscriptions and usage recorded under `default` before the switch stay
stranded and inert in `user` mode, and billing logs
`billing.subject_mode.stranded_default_rows` at boot when it finds any.
Nothing migrates them; switching back makes them live again, and the
`user:<uuid>` rows then stay unused. Choose the mode before you sell anything,
or reassign plans by hand (**Subscriptions** screen) after switching.

## What changes in `user` mode

- **Requests.** A route using `RequiresQuota`, and the Billing page, bill the
  signed-in user. Signed out they answer `401 subject_required`; they never
  fall back to `default`, which would put every anonymous caller on one
  counter.
- **Never suspended.** A user is not a tenant, so no status ever suspends them.
  A `canceled`, `unpaid` or otherwise lapsed subscription *downgrades* the user
  to the default plan; nothing is written to `tenants`.
- **No seats.** A per-seat plan cannot go to a user: checkout, plan change and
  the admin **Assign** all answer `422 per_seat_requires_tenant`, and the
  Billing page does not offer one (`BillingService.public_plans`). The page
  speaks to the user, not an organisation, and shows no seat counts.
- **Reconcile** runs bound to tenant `default`, never to a user id.
- **Admin screens.** **Subscriptions** lists users by email (not
  organisations) and assigns a plan per user; **Usage** works per user. Assigning
  is mode-strict: only an existing user in `user` mode, only an organisation in
  `tenant` mode (`admin_users.require_subject`); rows left from the other mode
  are repaired through the Usage admin.
- **Finding a row.** The Subscriptions list pages 50 rows at a time (Previous /
  Next under the table, keeping the search and status); the search narrows it.
  In `user` mode it matches part of an email (case-insensitive), or a
  `user:<uuid>` subject or bare UUID exactly; in `tenant` mode, part of an
  organisation's name or slug, or its id. The API
  (`GET /api/billing/admin/subscriptions?q=&offset=`) returns 200 rows a page.
- **Deleting a user** cancels their provider subscription at once (the same
  teardown a deleted tenant gets). A failed attempt is retried with backoff by
  `smpy billing reconcile` and the scheduled reconcile, whose sweep finds
  customers whose user is gone (`user_sweep.py`, `sweep.py`). The local
  billing rows are kept for audit.

## The subject format

A user subject is exactly `user:` plus the user's id in canonical form
(lowercase, hyphenated; `user_uuid` in `sm_billing/core/subject_keys.py`). An uppercase or
dashless spelling parses as the same UUID but names no user, so billing rejects
it. At 41 characters it fits the key columns, which migration `a7c2e4d81b35`
widens from 32 to 64 (`host/migrations/versions/`). A tenant id is a 32-character
hex string, so the two kinds cannot collide.

## Entitlements in user mode

`app.state.tenants.entitlements` (`limit`, `has_feature`) answers for
whichever subject it is given. In `user` mode, `request.state.tenant_id` is
`default` for every caller, so passing it checks the host's plan, not the
user's. Take the subject from the request instead:

```python
from sm_billing.contracts import subject_for_request

entitlements = request.app.state.tenants.entitlements
subject = subject_for_request(request)  # tenant id in tenant mode, user:<uuid> in user mode
if not await entitlements.has_feature(subject, "sso"):
    ...
limit = await entitlements.limit(subject, "exports.per_month")
```

`subject_for_request` raises billing's `401 subject_required` for a signed-out
caller in `user` mode, and the tenant rules (`default`, or `403
tenant_required`) in `tenant` mode, exactly as `RequiresQuota` does.

## For callers that run outside a request

A worker or a job has no request to ask, so it must not build the key by hand.
Import the helpers from the contracts package:

```python
from sm_billing.contracts import (
    worker_subject_mode,    # () -> "tenant" | "user", read from the database
    subject_for_tenant,     # (tenant_id) -> the tenant's subject
    subject_for_user,       # (user_id) -> "user:<uuid>", canonical whatever the spelling
)

usage = getattr(app.state, "billing_usage", None)
if usage is not None:
    subject = (
        subject_for_user(owner_id)
        if worker_subject_mode() == "user"
        else subject_for_tenant(tenant_id)
    )
    await usage.consume(subject, "ai.requests", 1, job_id, source="ai")
```

- **`worker_subject_mode()`** reads the stored setting through
  `background_tasks.settings_for(BillingSettings, "sm_billing")` (cached about
  30 s), so it needs the framework's `simple_module_background_tasks`, as every
  Celery worker has; billing does not depend on it and imports it only when
  called. It returns the stored value, which after a change can differ from
  the mode the web process booted with until that restarts.
- **`current_subject_mode(app)`** is for web-process code only: it reads what
  billing's `on_startup` stored on the app. A worker has no such app and would
  always get `"tenant"`.
- **`subject_for_user`** accepts a `UUID` or any spelling of one (hex,
  uppercase) and returns the canonical key; anything else raises `ValueError`.

The first argument of every `UsageMeter` method is the billing subject (the
parameter is still called `tenant_id`; renaming it is deferred). The key
helpers import nothing heavy, so a Celery worker can load them without the app.

## Images bills the collection's owner

In `user` mode images bills `user:<collection.owner_id>`, in the web process
and in the workers alike (`sm_images/core/billing/subject.py`). One image has
one payer, so its storage hold is swapped, grown and released under one
subject for its whole life. Sharing a collection does not move the bill: the
owner pays for what others upload into it.

- **Covered.** The storage hold taken at upload or import, pipeline growth,
  settle, repair and release, and the AI steps' `ai.requests`
  (`consume_requests`). `ai.requests` is no longer split: a request made in a
  route and a request made by a worker both bill the user. An AI charge uses
  the owner as of now.
- **Recorded, not re-derived.** The subject a hold was taken under is written
  to `images_billing_op.subject` and `images_image.storage_subject`. Settle,
  repair and growth replay it, so a mode switch or a change of owner never
  sends a swap to a subject that does not hold the key. It is always written
  explicitly, `default` included in `tenant` mode. `NULL` (rows from before
  #284, or billing off) means the row's tenant, so old holds stay on `default`
  and keep settling and releasing as before.
- **No hold yet.** An image that names no hold bills the owner. Repair
  corrects such an image under the subject of the op it examines.
- **Upload pre-checks.** The advisory check reads the owner's headroom, and
  opening a direct or ZIP upload compares it with the declared sizes of the
  open uploads into collections of the same owner only: another user's open
  upload is held against that user's gauge, not this one's room. The
  open-upload cap (`max_open_uploads_per_tenant`) and the admission lock stay
  per tenant; the cap bounds concurrency, it is not a quota.
- **Unbillable owner.** An owner with no valid user row (deleted, or not a
  UUID) falls back to the tenant. Images logs
  `images.billing.owner_unbillable collection=<id>` once per collection.
- **Worker lag.** A worker reads the mode through `worker_subject_mode()`,
  cached about 30 s, so a new hold follows a mode switch about 30 s after the
  restart. Holds already taken keep their recorded subject.
- **Rows do not move.** Holds taken under `default` before the switch stay
  there, as in [Rows do not move](#rows-do-not-move).

A new images billing call takes its subject from the op or the image, or from
`sm_images.core.billing.subject`; it never builds one by hand.

## Stripe Customer Portal in user mode

A user cannot hold a per-seat plan, and billing only blocks that on its own
routes. In `user` mode, keep every per-seat product and price out of the
Customer Portal's plan-switching configuration (Stripe → Settings → Billing →
Customer portal → Subscriptions), or a user could switch themselves onto one
there; the webhook would then mirror a per-seat subscription onto a user.
