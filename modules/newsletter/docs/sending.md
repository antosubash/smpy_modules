# Sending

How a scheduled campaign becomes mail. The design is ruling S1 to S20 of
`docs/superpowers/plans/2026-11-03-newsletter-pr4-sending.md` in the source
repository; this page says what the code does.

## The status machine

Every transition is one conditional `UPDATE` pinned to the campaign `id`, its
tenant and the allowed *from* statuses, with `revision = revision + 1`.

| Action (permission) | From | To | Also |
| --- | --- | --- | --- |
| send or schedule (`newsletter.send`) | `draft`, at `expected_revision` | `scheduled` | render snapshot written; `scheduled_at` |
| unschedule (`newsletter.send`) | `scheduled`, at `expected_revision` | `draft` | snapshot and send rows deleted; `scheduled_at` cleared |
| freeze (worker) | `scheduled` | `sending` | `started_at`, `recipient_count`, `suppressed_count` |
| freeze, list gone (worker) | `scheduled` | `paused` (`list_unavailable`) | `started_at` stays empty |
| pause (`newsletter.send`) or auto-pause | `sending` | `paused` | reason |
| resume (`newsletter.send`) | `paused` | `sending` if `started_at` is set, else `scheduled` at now | reason cleared |
| cancel (`newsletter.send`) | `scheduled`, `sending`, `paused` | `cancelled` | `finished_at`; remaining `queued` rows become `cancelled` |
| finish (worker) | `sending` with no `queued` or `sending` row | `sent` | `finished_at` |

When no row matches, the campaign is re-read: missing is 404, a stale revision
on send or unschedule is `409 stale`, sending a non-draft is `409
not_a_draft`, anything else `409 invalid_transition`. The paused reason is
stored as `"<code>|<detail>"`; the codes are `manual`, `smtp_rejected`,
`smtp_auth`, `list_unavailable` and `https_required`, and the API returns them
split as
`paused_code` and `paused_detail`.

"Send now" is "scheduled for now": `POST /campaigns/{id}/send` without
`scheduled_at` schedules at the current time and the next dispatcher tick
freezes it, so the first message can take up to about a minute. A
`scheduled_at` must be timezone-aware and within `[now - 60 s, now + 366
days]`; anything else is `422 invalid_campaign`. `/estimate` applies the same
window to its `at`. The send dialog refuses a "Later" time that is already past
when Confirm is pressed, and never turns it into "now".

Scheduling checks, in order: draft and revision, list access, audience (only
`all` is supported until PR 6; `tag:` and `segment:` are `422
audience_unsupported`), the sender, the headers, a subject, at least one block
(`422 empty_campaign`), absolute links (`422 public_base_url_required`), the
schedule window, HTTPS for both bases on the `smtp` transport (`422
https_required`; the console transport allows `http://`), and no
capability-bearing merge field (`{{unsubscribe_url}}`) in the subject or
preheader.

## The render snapshot

The campaign is rendered **once, in the request that schedules it**
(`campaigns/snapshot.py`) and stored in `newsletter_campaign_render`: subject,
HTML and text with the merge tags left in place, the formatted `From`,
`Reply-To`, the public base and the locale. It is written in the same
transaction as `draft -> scheduled`. The worker never renders; it only
personalises that snapshot (merge fields, the unsubscribe link and headers).

Consequence: a later change to the sender, branding or postal address does not
reach a campaign that is already scheduled or sending. **Unscheduling** deletes
the snapshot and returns the campaign to draft; scheduling again re-renders it
with the current sender, branding, address, content and both bases (the
snapshot stores `content_base` and `public_base`, which the dispatcher checks
for `https://` before SMTP delivery).

## Freeze

A due campaign (`scheduled` and `scheduled_at <= now`) is frozen by the
dispatcher tick: its audience becomes `newsletter_send` rows.

- The audience is resolved through records' `iter_subscribers`, 1000 at a time,
  one session per page; suppressed addresses get a row with status
  `suppressed`, so a re-run is a no-op and the counts come from rows.
- Rows are inserted ignoring `(tenant_id, campaign_id, record_uuid)`, so a
  crashed freeze can be continued. The row keeps `first_name` for the merge.
- Freeze runs outside the dispatch lock (it spends no budget).
- **The fence.** A freeze has one owner per campaign and per `freeze_gen`,
  claimed by a conditional `UPDATE`. Each page renews the claim *inside* its
  own transaction and writes only while it holds it. The lease renews from the
  clock on each page and lasts five minutes; an expired claim is taken over
  and the old owner then writes nothing. Schedule, unschedule and
  cancel-from-`scheduled` bump `freeze_gen`, so an interrupted freeze cannot
  leak its rows into a rescheduled campaign.
- **The claim re-checks what it claims.** Its `UPDATE` also requires
  `scheduled_at <= ` the tick's cutoff, so a campaign unscheduled and
  rescheduled for later after the due list was read is not started. The list
  and audience the freeze uses come from the same read as the generation the
  claim pins (they change only on a draft), never from an earlier read.
- If the list is gone or no longer a list when freezing, the campaign pauses
  with `list_unavailable` and the claim is released.

## The dispatcher

`newsletter.dispatch` is a Celery beat task on the `newsletter` queue, every
60 s. A tick stops starting new work after 50 s (`TICK_SECONDS`; one recipient
in flight can run past it, up to its 45 s SMTP deadline) and a queued copy
expires after 55 s. Nothing else sends campaign mail.

1. Recover expired leases, then freeze what is due. Freezing shares the tick's
   time: a large freeze (about 100 pages for 100k subscribers) can use a whole
   tick, so nothing is sent that minute, for any tenant. It is only slower,
   never wrong: the claim and the per-page lease carry it on next tick.
   On the `smtp` transport, every `sending` campaign whose stored snapshot does
   not have `https://` for both `content_base` and `public_base` (an empty
   `content_base` counts as not) is then paused with `https_required`, each in
   its own tenant: scheduling checked the transport configured *then*, and a
   switch from `console` to `smtp` must not send an `http://` snapshot through
   the real relay. The rest go on; with none left, no connection is opened.
   Delivery re-checks the snapshot per recipient before any claim or attempt.
2. Nothing `sending`, or no budget left in either window: finish any campaign
   with no open rows and stop, with no relay connection (a capped day neither
   logs in every minute nor lets a refused login pause every campaign).
3. Open one transport session for the tick. A refused login pauses every
   `sending` campaign (`smtp_auth`); any other connect or TLS failure only ends
   the tick.
4. Work in **slices**, each inside the install-wide dispatch lock: read the
   budget (rolling 24 h and 60 s, counted across every tenant), send at most
   `min(budget left, SLICE)` recipients (`SLICE = 10` counted sends), release.
   A slice also ends after `MAX_SLICE_STEPS = 50` steps, skipped rows
   included, so a run of skips never holds the lock. A test send therefore
   waits at most one slice.
5. The oldest-started campaign goes first, across tenants. Several campaigns
   share the one budget, and a campaign that cannot finish today carries on the
   next day, as long as the worker and beat run.

Per recipient, in this order: re-read the campaign; take its next due row;
re-check the subscriber (still `confirmed` in records, not suppressed) and skip
the row with no SMTP call if not; compose from the snapshot; renew the lock;
**reserve** in one transaction (the lock fence, the conditional claim of the
row while its campaign is still `sending`, and a `pending` attempt row);
then SMTP. The attempt row is committed before the SMTP call, so a crash never
loses a count. Pause and cancel are conditional updates, so a pause or cancel
before the claim sends nothing and writes no attempt; a cancel while a send is
in flight ends that row `cancelled`.

On SQLite the lock is a lease row (120 s) and the reservation is fenced on it,
so a taken-over lease can never spend budget another holder counted. On
Postgres it is a session advisory lock. One recipient's SMTP work is bounded by
a 45 s deadline (20 s per command).

An unavailable list **mid-campaign** (deleted, or no longer a list) pauses only
that campaign with `list_unavailable`; the tick continues with the others. Only
relay-wide signals stop a tick: a `421` or `4.7.x` reply, an `smtp_rejected`
pause, a connect or auth failure, a lost lock, the budget, or the deadline.

## Verdicts

One pure function (`sending/classify.py`) maps each transport result:

| Transport result | Verdict | Row | Stops the tick |
| --- | --- | --- | --- |
| accepted | `sent` | `sent`, `sent_at` | no |
| unknown (connection dropped after the body) | `unknown` | `failed`, `outcome_unknown`, never retried | no |
| failed at stage `auth` | pause `smtp_auth` | back to `queued` | yes |
| failed at any other stage | `retry` | `queued` with `retry_at`, or `failed` / `retries_exhausted` | yes |
| rejected, no code (bad header, non-ASCII address) | `fail` | `failed`, `invalid_message` | no |
| rejected 4xx | `retry` | as above | only `421` or enhanced `4.7.x` (quota) |
| rejected 5xx at RCPT with enhanced `5.1.x` | `bounce` | `bounced`, plus a tenant-wide `hard_bounce` suppression | no |
| any other rejection | pause `smtp_rejected` | back to `queued` | yes |

Only a `5.1.x` refusal at RCPT is a bounce, so a quota or policy refusal never
suppresses anyone; everything else a relay refuses pauses the campaign for an
admin to read, then resume or cancel.

## Retries and backoff

Only errors known to have happened **before acceptance** are retried. At most
three counted attempts: the wait is 5 minutes after the first and 30 minutes
after the second, then the row is `failed` / `retries_exhausted`. A pause
verdict does not count as an attempt. An `unknown` outcome is never retried:
the message may have been delivered, and a duplicate is worse than a gap.

## The lease and outcome unknown

A claimed row is `sending` with a 10 minute `lease_until`, and its attempt row
`pending`, both committed before SMTP. At the start of each tick, a `sending`
row whose lease expired belonged to a sender that died between reservation and
result. It becomes `failed` / `outcome_unknown` and its attempt `unknown`.
It is never resent and **still counts against the budget**.

## Counters and progress

`sent`, `failed`, `bounced`, `suppressed` and `unsubscribe` counters move in the
same transaction as the row. `GET /campaigns/{id}/progress` counts rows by
status; `skipped_unsubscribed` has no denormalised counter. The estimate uses
`min(daily_limit, per_minute_limit x 1440)` per day and the queued rows of
earlier-started `sending` campaigns across tenants ("queue ahead"), so it is
approximate and says "about".

## Unsubscribe

`/newsletter/u/{token}`, public, not an Inertia page.

- **GET** renders a page with one plain `<form method="post">`, no script, and
  reads nothing: no statement, no tenant binding. A mail scanner that follows
  links unsubscribes nobody.
- **POST** (the button, or RFC 8058's `List-Unsubscribe=One-Click`; any body is
  accepted and none is read) runs records' `unsubscribe` with the cutoff of
  when this message went out: `send.sent_at`; for an unknown outcome (no
  `sent_at`) the latest `newsletter_send_attempt.attempted_at` of that send,
  because a campaign can run for days after `started_at`; else the campaign's
  `started_at`; else now. A person who confirmed again after the mail keeps the
  subscription. The suppression (`unsubscribed`, the
  campaign's list, source `unsubscribe_page`) is written in the same
  transaction when records wrote, and also when the subscriber is gone, trashed
  or already unsubscribed, or the type stopped being a list. It is never written
  for a `pending` subscriber or one who confirmed after the cutoff.
  `unsubscribe_count` moves only when records wrote.
- **Tenancy.** The tenant comes from the verified token, not from the request:
  links are built on `public_base_url`, which on a multi-tenant host is the
  apex where no tenant resolves, so `bind_public` would refuse every link. The
  MAC is verified before any statement; if the *host* resolved a tenant (the
  framework's `tenant_source` is `subdomain` or `fixed`) that differs from the
  token's, the token counts as forged. A tenant the visitor brought (a
  signed-in member's `session`, `header` or `claim`, or an `anon_header`) is
  ignored: a member of organisation A who clicks B's link on the apex is
  unsubscribed from B.
- **One answer.** A real, `test`, forged, oversized, already-used or
  other-tenant token gets the same 200 page, so the route is no oracle for which
  tokens exist. `/newsletter/u/test` (previews and test sends) is one of them.
- **No CSRF, on purpose.** The one-click POST comes from the mailbox provider
  with no session or cookie. The signed token is the capability.
- **Rate limits:** 60 per minute per IP on GET, 300 on POST (one-click posts
  arrive from the providers' shared egress IPs; a refused one loses an opt-out).
- The page speaks the host's `i18n_default_locale`, like the email footer.

## Tokens

One token per send: `{tenant}.{campaign_id}.{send_id}.{mac}`, where `mac` is the
base64url of an HMAC-SHA256 over `newsletter|send|{tenant}|{campaign}|{send}`
truncated to 128 bits. It is split from the right, because a tenant may contain
dots. Tokens are minted at send time and never stored. The secret is the host's
`secret_key` in the web process and `core/secret.py`'s resolution in a worker
(see [`operations.md`](operations.md)). PR 5 reuses the same token for opens and
clicks.
