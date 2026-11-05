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
row, and a plaintext password: the worker refuses a non-empty SMTP password
stored without `enc:v1:`, so re-save it through
`PUT /api/newsletter/settings/smtp-password`.

The secret signs the unsubscribe links as well. If it is rotated, links already
sent stop verifying (they answer the same page, but unsubscribe nobody) and the
encrypted password is unreadable until it is saved again. A worker that
resolves its secret from the stored `host.secret_key` keeps the first value it
read until it restarts.

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
`public_base` when a campaign is scheduled.

- **Headroom.** `daily_limit` and `per_minute_limit` are the rolling 24 hour and
  60 second windows, counted over every tenant of the install, test sends
  included. Set them below the relay's real cap; the Workspace relay's daily cap
  is per account, and anything else that sends through it spends the same quota.
  A campaign too big for one day continues the next day by itself.
- **What a pause means.** A campaign `paused` with `smtp_rejected` was refused
  by the relay with something that is not a mailbox bounce (a policy or quota
  refusal, a bare 5xx). `smtp_auth` means the login was refused, and pauses
  every sending campaign. `list_unavailable` means its list was deleted or
  stopped being a list. `manual` is a person's pause. The detail shows the relay's
  reply verbatim.
- **Resuming.** Fix the cause (the password, the relay's allow list, the list),
  then Resume on the campaign screen (`newsletter.send`). A paused row goes back
  to `queued`, so nothing is skipped or duplicated. If it cannot be fixed,
  Cancel instead. A `421` or `4.7.x` reply is not a pause: it ends the tick and
  the rows retry later.
- **Outcome unknown.** A row that failed with `outcome_unknown` may or may not
  have been delivered. It is never resent; it counts against the budget.
