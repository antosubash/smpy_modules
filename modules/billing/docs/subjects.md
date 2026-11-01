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

- **refuses to start** when `multi_tenant` is on. A user has no tenant, so the
  deleted-tenant sweep would see every user customer as a deleted tenant
  (`sm_billing/subject_boot.py`);
- maps `billing.view` and `billing.manage` onto the framework's `user` role,
  so every signed-in user can open their own Billing page;
- subscribes the `UserDeleted` teardown (below);
- logs two warnings when they apply (see
  [Rows do not move](#rows-do-not-move) and
  [images and ai](#images-and-ai-keep-billing-the-tenant)).

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
- **Finding a row.** The Subscriptions list shows at most 200 rows and has no
  pager; past that, use its search. In `user` mode it matches part of an email
  (case-insensitive), or a `user:<uuid>` subject or bare UUID exactly; in
  `tenant` mode, part of an organisation's name or slug, or its id. The page
  says when the list was cut (`GET /api/billing/admin/subscriptions?q=`).
- **Deleting a user** cancels their provider subscription at once (the same
  teardown a deleted tenant gets). A failed attempt is retried with backoff by
  `smpy billing reconcile` and the scheduled reconcile, whose sweep finds
  customers whose user is gone (`user_sweep.py`, `sweep.py`). The local
  billing rows are kept for audit.

## The subject format

A user subject is exactly `user:` plus the user's id in canonical form
(lowercase, hyphenated; `sm_billing/subjects.py` `user_uuid`). An uppercase or
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

## images and ai keep billing the tenant

The `images` and `ai` worker paths pass the row's tenant, which is `default` on
a single-tenant host, so in `user` mode their usage is metered against
`default`, not a user. Boot logs
`billing.subject_mode.tenant_billed_callers` naming whichever is installed
(`subject_boot.py`). Billing them per user is follow-up work; until then a
plan limit on one of their meters applies to the whole host in `user` mode.
