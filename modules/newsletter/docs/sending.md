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
| unschedule (`newsletter.send`) | `scheduled`, or `paused` with `started_at` empty (never frozen), at `expected_revision` | `draft` | snapshot and send rows deleted; `scheduled_at` and the paused reason cleared; a `paused` campaign that started is `409 invalid_transition` |
| freeze (worker) | `scheduled` | `sending` | `started_at`, `recipient_count`, `suppressed_count` |
| freeze, list gone, audience refused by records or snapshot not https on `smtp` (worker) | `scheduled` | `paused` (`list_unavailable`, `audience_unavailable`, `https_required`) | `started_at` stays empty; nothing frozen |
| pause (`newsletter.send`) or auto-pause | `sending` | `paused` | reason |
| resume (`newsletter.send`) | `paused` | `sending` if `started_at` is set, else `scheduled` at now | reason cleared |
| cancel (`newsletter.send`) | `scheduled`, `sending`, `paused` | `cancelled` | `finished_at`; remaining `queued` rows become `cancelled` |
| finish (worker) | `sending` with no `queued` or `sending` row | `sent` | `finished_at` |

When no row matches, the campaign is re-read: missing is 404, a stale revision
on send or unschedule is `409 stale`, sending a non-draft is `409
not_a_draft`, anything else `409 invalid_transition`. The paused reason is
stored as `"<code>|<detail>"`; the codes are `manual`, `smtp_rejected`,
`smtp_auth`, `list_unavailable`, `https_required` and `audience_unavailable`, and the API returns them
split as
`paused_code` and `paused_detail`.

"Send now" is "scheduled for now": `POST /campaigns/{id}/send` without
`scheduled_at` schedules at the current time and the next dispatcher tick
freezes it, so the first message can take up to about a minute. A
`scheduled_at` must be timezone-aware and within `[now - 60 s, now + 366
days]`; anything else is `422 invalid_campaign`. `/estimate` applies the same
window to its `at`. The send dialog refuses a "Later" time that is already past
when Confirm is pressed, and never turns it into "now".

Scheduling checks, in order: draft and revision, list access, audience (`all`,
`tag:<choice>` or `segment:<id>`, resolved to records filter terms and
dry-run counted: `422 unknown_tag`, `unknown_segment`,
`segment_list_mismatch` or `invalid_segment`; the terms are stored on the
render and freeze reads them from there), the sender, the headers, a subject, at least one block
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
  with `list_unavailable` and the claim is released; on the `smtp` transport,
  so does a snapshot that is not `https://` (`https_required`). Nothing is
  frozen, so the campaign can be resumed (back to `scheduled`) or unscheduled
  to draft.
- **The audience is the snapshot.** The freeze reads the terms scheduling
  stored on the render (`audience_filters`; `[]`, as on a render written
  before audiences existed, is the whole list), never the segment: editing or
  deleting a segment after scheduling changes nothing until the campaign is
  unscheduled and scheduled again. When records refuses a stored term while
  freezing, `reindexing` leaves the campaign `scheduled` (a WARNING; the claim
  expires and a later tick retries), `not_a_list` pauses with
  `list_unavailable`, and any other reason pauses with `audience_unavailable`,
  records' reason as the detail. The refused page is rolled back; both pauses
  are conditional on the claim, like the one above.

## The dispatcher

`newsletter.dispatch` is a Celery beat task on the `newsletter` queue, every
60 s. A tick stops starting new work after 50 s (`TICK_SECONDS`; one recipient
in flight can run past it, up to its 45 s SMTP deadline) and a queued copy
expires after 55 s. Nothing else sends campaign mail.

1. Recover expired leases, then freeze what is due. Freezing shares the tick's
   time: a large freeze (about 100 pages for 100k subscribers) can use a whole
   tick, so nothing is sent that minute, for any tenant. It is only slower,
   never wrong: the claim and the per-page lease carry it on next tick.
   On the `smtp` transport a snapshot without `https://` for both
   `content_base` and `public_base` (an empty `content_base` counts as not) is
   refused: scheduling checked the transport configured *then*, and a switch
   from `console` to `smtp` must not send an `http://` snapshot through the
   real relay. A due campaign is paused with `https_required` at freeze, under
   its claim and before any row is written (`started_at` stays empty, so it can
   be unscheduled, fixed and scheduled again, which re-renders it). Every
   campaign already `sending` with such a snapshot is then paused too, each in
   its own tenant; that one has started, so it can only be cancelled. The rest
   go on; with none left, no connection is opened. Delivery re-checks the
   snapshot per recipient before any claim or attempt.
2. No row due (nothing `sending`, or every `queued` row still waiting for its
   `retry_at`, as during a 5 or 30 minute backoff), or no budget left (the
   24 h window full, or the 60 s window not freeing before the deadline):
   finish any campaign with no open rows and stop, with no relay connection
   (an idle or capped minute neither logs in nor lets a refused login pause
   every campaign).
3. Open one transport session for the tick. A refused login pauses every
   `sending` campaign (`smtp_auth`); any other connect or TLS failure only ends
   the tick.
4. Work in **slices**, each inside the install-wide dispatch lock: read the
   budget (rolling 24 h and 60 s, counted across every tenant), send at most
   `min(budget left, SLICE)` recipients (`SLICE = 10` counted sends), release.
   A slice also ends after `MAX_SLICE_STEPS = 50` steps, skipped rows
   included, so a run of skips never holds the lock. A test send therefore
   waits at most one slice.
   When only the 60 s window is full, the tick waits outside the lock until
   its oldest attempt leaves it, as long as that comes before the deadline,
   and goes on: the previous tick's sends landed just after it started, so
   they are still inside the minute when the next tick starts, and stopping
   there would send only every other minute. Throughput is therefore
   `min(daily_limit, per_minute_limit x 1440)` a day, the rate the progress
   estimate uses. A full 24 h window stops the tick at once.
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
in flight ends that row `cancelled`. On Postgres, two lock orders keep these
writes free of deadlocks. For a campaign that has started (the only one whose
rows a result, an open or a click touches), recording a result, skipping a
suppressed row, recovering an expired lease, the open and click counters and
cancel lock the send rows first and the campaign row last.
For a campaign that never started, unschedule, freeze pages and cancel lock
the campaign row first. No transaction mixes the two, because a never-started
campaign has sent nothing to record or track. A cancel that finds the campaign
started meanwhile rolls back to a savepoint, releasing the campaign row, before
it takes the started order.

PR 6's people screens add two more paths, both taking **records' lock domain
first** (its type lock, then the record row) and newsletter rows after: the
suppression lift (`lock_confirmation`, then the conditional suppression delete,
then the lift insert) and the admin unsubscribe (records' unsubscribe, then the
suppression upsert). Only an unsubscribe takes the address's opt-out lock, before
its type and row locks; the lift takes none. PR 7's import takes the opt-out
locks of a whole batch, ascending, before its type lock. Neither touches campaign, send or click rows, so the two
orders above are unaffected. Audience changes and `schedule` touch only the
campaign row (reading a segment takes no lock). See [`audience.md`](audience.md).

On SQLite the lock is a lease row (120 s) and the reservation is fenced on it,
so a taken-over lease can never spend budget another holder counted. On
Postgres it is a session advisory lock. One recipient's SMTP work is bounded by
a 45 s deadline (20 s per command).

An unavailable list **mid-campaign** (deleted, or no longer a list) pauses only
that campaign with `list_unavailable`; the tick continues with the others. Only
relay-wide signals stop a tick: a `421` or `4.7.x` reply, an `smtp_rejected`
pause, a connect or auth failure, a lost lock, the budget, or the deadline.

## Test sends

`POST /api/newsletter/campaigns/{id}/test-send` (`newsletter.send`, and read
access to the campaign's list) sends the saved campaign, `[TEST] ` before the
subject, to up to five addresses. The mechanics (the lock, the all-or-nothing
budget, the ledger rows) are in [`content.md`](content.md#test-send). Who it
may go to (#348):

- **Who is vouched for.** The caller's own address (the signed-in user's
  email); an active account of the campaign's organisation, found through the
  framework's user directory by exact address and, on a multi-tenant host, kept
  only when the tenants module says it is a member of the tenant newsletter
  bound for the request (the resolved one, never `user.tenant_id`; on a
  single-tenant host every active account belongs to the one organisation); and
  the addresses in the setting `test_send_extra_recipients` (SYSTEM scope, up to
  20, for a shared review inbox). With no user directory, or on a multi-tenant
  host no membership store, only the caller and the list are vouched for.
- **Anything else** answers `recipient_not_allowed` for that address alone.
- **Suppressed.** A vouched-for address with a `complaint` or `unsubscribed`
  row in the tenant's `newsletter_suppression` (any list: opt-outs are
  tenant-wide), matched by the table's hash of the normalised address,
  answers `suppressed`, without saying which. A bounce or a cleaned import row
  does not refuse a test.
- A refused address is never sent, writes no `newsletter_send_attempt` row and
  uses no budget: the refusals are decided before the dispatch lock, admission
  counts only the addresses actually sent, and when every address is refused
  the lock is not taken at all.

Each result carries the `outcome` (`accepted`, `rejected`, `unknown`, `failed`,
`recipient_not_allowed`, `suppressed`) and a stable `code`: `smtp_<reply>` for a
relay answer (`smtp_250`, `smtp_550`), `dispatch_busy` when the lock's lease was
lost before that address, otherwise `null`. The relay's reply text is not
returned: it is in the attempt row's `detail` and, for an answer other than
`accepted`, in the server log (`newsletter.test_send.not_accepted`, with the
campaign and attempt ids).

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
  The exception is a POST that fails inside (a database error): nothing is
  committed and the page comes back with its button as a `503`: the reader can
  press it again, and a mailbox provider sending the one-click POST sees a
  failure it retries rather than a success.
- **No CSRF, on purpose.** The one-click POST comes from the mailbox provider
  with no session or cookie. The signed token is the capability.
- **Rate limits:** 60 per minute per IP on GET, 300 on POST (one-click posts
  arrive from the providers' shared egress IPs; a refused one loses an opt-out).
- The page speaks the host's `i18n_default_locale`, like the email footer.

## Tokens

Each message carries three purpose-bound tokens (T17): `u` (unsubscribe), `o`
(open) and `c` (click). Each has the shape `{tenant}.{campaign_id}.{send_id}.{mac}`,
where `mac` is the base64url of an HMAC-SHA256 over
`newsletter|{purpose}|{tenant}|{campaign}|{send}` truncated to 128 bits. A token
minted for one purpose fails the other routes, so a leaked open or click URL
cannot unsubscribe anyone (see [`tracking.md`](tracking.md)). A token is split
from the right, because a tenant may contain dots. Tokens are minted at send
time and never stored; the open and click tokens only when that kind of tracking
is on. The secret is the host's `secret_key` in the web process and
`core/secret.py`'s resolution in a worker (see [`operations.md`](operations.md)).
