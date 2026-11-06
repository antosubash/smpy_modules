# Operations

What has to be running, and set, for campaigns to go out.

## The worker and beat must run

Campaigns are sent only by the `newsletter.dispatch` beat task, which runs on the
`newsletter` queue every minute. Run both:

```bash
make worker   # serves the images, newsletter and celery queues
make beat     # schedules newsletter.dispatch and the hourly reconcile
```

With `SM_BG_TASKS_TASK_ALWAYS_EAGER=true` and **no beat**, nothing is dispatched:
eager mode runs a task inline when something calls it, and nothing calls this
one. A campaign then sits in `scheduled` and never starts. `make dev` starts
neither.

## The secret

The worker has no app, so it finds the secret key itself: `SM_SECRET_KEY` in the
environment or the `.env` the framework locates, else the host's stored
`host.secret_key` (written the first time the app boots without a key). With
neither, **the tick refuses and logs at ERROR**, before it recovers, freezes or
connects. Campaigns stay as they are until it is fixed; until then the only
sign is the log (`newsletter.dispatch refused: SecretMissing`). The same refusal
applies to a stored SMTP password the key cannot decrypt, an unreadable settings
row, and, on the `smtp` transport, a plaintext password: the worker refuses a
non-empty SMTP password stored without `enc:v1:`, so re-save it through
`PUT /api/newsletter/settings/smtp-password`.

The secret signs the unsubscribe links as well. If it is rotated, links already
sent stop verifying (they answer the same page, but unsubscribe nobody) and the
encrypted password is unreadable until it is saved again. A worker keeps
decrypting the SMTP password with the first secret it resolved until it
restarts (tokens re-resolve the secret each tick), so restart the workers after
a rotation.

## Unsubscribe links in access logs

The module never logs a full send token, but uvicorn's access log and any
proxy's record the path `/newsletter/u/<token>` of every click and one-click
POST. A token is an opt-out capability for one address: redact that path in
the access logs, or rotate and restrict them. The same logs also record
`/newsletter/o/<token>.gif` and `/newsletter/c/<token>/<N>`. Those tokens are
bound to their purpose and cannot unsubscribe anyone, but a holder of a leaked
one can inflate that one send's open or click totals and tie a send id to a
reader's activity, so redact those prefixes too.

## The console transport in a worker

Campaign mail "sent" by the `console` transport in a Celery worker is captured
in that worker's in-process ring, not the web process's, so the outbox screen
(`GET /api/newsletter/outbox`) never shows it; only test sends (sent by the web
process) appear there. The worker's log records only that each message went
out (a reference and the recipient's domain).

## The DKIM checklist

The unsubscribe headers only count if the signature covers them. Before the
first real send:

1. Enable DKIM for the sending domain in the Google Admin console.
2. Send a test to a mailbox you can read.
3. In its original headers, check that `DKIM-Signature: ... h=` lists
   `List-Unsubscribe` and `List-Unsubscribe-Post`.

If either is missing from `h=`, mailbox providers may ignore one-click
unsubscribe; do not send to the list yet.

## The relay

The `smtp` transport talks to `smtp-relay.gmail.com` (port 587 with STARTTLS, or
465 with implicit TLS) and needs `https://` for `content_base` and
`public_base` when a campaign is scheduled, and again, on the stored snapshot,
before each tick sends (a campaign scheduled on the console transport pauses
with `https_required` once the transport is `smtp`).

- **Headroom.** `daily_limit` and `per_minute_limit` are the rolling 24 hour and
  60 second windows, counted over every tenant of the install, test sends
  included. Set them below the relay's real cap; the Workspace relay's daily cap
  is per account, and anything else that sends through it spends the same quota.
  A campaign too big for one day continues the next day by itself.
- **What a pause means.** A campaign `paused` with `smtp_rejected` was refused
  by the relay with something that is not a mailbox bounce (a policy or quota
  refusal, a bare 5xx). `smtp_auth` means the login was refused, and pauses
  every sending campaign. `list_unavailable` means its list was deleted or
  stopped being a list. `audience_unavailable` means records refused the
  audience's stored filter terms at freeze (the detail is records' reason,
  e.g. `not_indexed` after a field lost its index): unschedule, fix the
  segment or the field, and schedule again. `https_required` means the campaign was rendered with an
  `http://` base (scheduled on the console transport) and the transport is now
  `smtp`. `manual` is a person's pause. The detail shows the relay's
  reply verbatim.
- **Resuming.** Fix the cause (the password, the relay's allow list, the list),
  then Resume on the campaign screen (`newsletter.send`). `https_required` is
  not fixed by changing the address: the render is a snapshot. A campaign
  paused at freeze (never started: the panel offers Unschedule) goes back to
  draft with Unschedule; fix the addresses to `https://` and schedule it again,
  which re-renders it. The same works for `list_unavailable` at freeze. One that
  had already started sending has its audience frozen, so cancel it and
  schedule a new campaign. A paused row goes back
  to `queued`, so nothing is skipped or duplicated. If it cannot be fixed,
  Cancel instead. A `421` or `4.7.x` reply is not a pause: it ends the tick and
  the rows retry later.
- **Outcome unknown.** A row that failed with `outcome_unknown` may or may not
  have been delivered. It is never resent; it counts against the budget.
