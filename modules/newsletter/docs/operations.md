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

## Postgres connections: direct or session pooling

On Postgres the install-wide dispatch lock (`sending/lock.py`) is a
**session-level** advisory lock: `pg_try_advisory_lock` on one dedicated
connection, held for the whole send and released with `pg_advisory_unlock` on
the same connection. A session lock belongs to the server connection that took
it.

So every process that sends — the web process (test sends) and the workers that
run `newsletter.dispatch` — must reach Postgres **directly, or through a pooler
in session mode**. Behind a pooler in **transaction** mode (PgBouncer's
`pool_mode = transaction`, and most managed "transaction pooler" endpoints)
consecutive statements can run on different server connections, so the lock can
be taken on one and released on another. The symptoms:

- every send, test sends included, answers `dispatch_busy`, because a lock is
  held by a server connection that nothing will ever unlock; or
- two senders hold the lock at once, and the rolling budget is overrun.

Point `SM_DATABASE_URL` for these processes at the database itself or at a
session-mode pool. The transaction-level locks taken elsewhere
(`pg_advisory_xact_lock`: the settings write lock, and records' per-address
locks during an import) are released at commit and are safe under either mode.
`modules/images/docs/worker.md` gives the same advice for images' workers.

## Imports and the janitor

A Mailchimp import ([`import.md`](import.md)) is applied by the Celery task
`newsletter.run_import` on the same `newsletter` queue (`make worker` serves it
with `-c 4`, so a long import never starves the minute's dispatch tick). The
hourly beat task `newsletter.import_janitor` relaunches an import whose message
was lost and deletes staged imports older than 24 hours (from creation) and failed ones 24 hours after they failed (their staged
addresses with them). With Celery eager and no beat, an import still runs: the
request applies every slice inline; only the janitor does not run.

## The dispatch hook (e2e only)

`POST /api/newsletter/outbox/dispatch` (`newsletter.manage`, CSRF) runs one
dispatcher tick inside the web process, because the e2e server has no beat. It
answers 404, like `GET /outbox`, unless **all three** hold: the transport is
`console`, Celery is eager, and `SM_ENVIRONMENT` is `development` or `testing`.
`SM_ENVIRONMENT` defaults to `development`, so the hook also depends on the
other two conditions: a dev host on the console transport with eager tasks has
it. A production host is never eager, so it never has it, and the console
transport cannot send real mail. The e2e spec `newsletter.spec.ts` depends on
it; it is opt-in with `E2E_NEWSLETTER=1` and runs only in its own CI job,
`E2E (newsletter)`, against a non-bundle host with `SM_ENVIRONMENT=development`
(framework 0.0.42 serves `testing` pages under the production CSP, which blocks
the Vite dev server). The bundle shards ignore it. Run it locally with
`E2E_NEWSLETTER=1 npx playwright test`.

## The secret

The worker has no app, so it finds the secret key itself: `SM_SECRET_KEY` in the
environment or the `.env` the framework locates, else the host's stored
`host.secret_key` (written the first time the app boots without a key). With
neither, **the tick refuses and logs at ERROR**, before it recovers, freezes or
connects. Campaigns stay as they are until it is fixed; until then the only
sign is the log (`newsletter.dispatch refused: SecretMissing`). The same refusal
applies to a stored SMTP password the key cannot decrypt, an unreadable settings
row, and, on the `smtp` transport, a plaintext password: the worker refuses a
non-empty SMTP password stored without an `enc:` prefix (`enc:v2:`, or the
0.0.15 `enc:v1:`, still read until 0.1.0), so re-save it through
`PUT /api/newsletter/settings/smtp-password`.

The secret signs the unsubscribe, open and click links as well. Rotate it as
`docs/secret-key-rotation.md` (repo root) describes: with the old key in
`SM_SECRET_KEY_PREVIOUS` the password keeps decrypting, and
`scripts/reencrypt_secrets.py` re-encrypts it under the new key. The links are
**not** covered: those already sent stop verifying after a rotation (they answer
the same page, but unsubscribe nobody). A worker keeps decrypting the SMTP
password with the first secret it resolved until it restarts (tokens re-resolve
the secret each tick), so restart the workers after each step of a rotation.

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
