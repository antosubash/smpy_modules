# Reminders

A signed-in user who can see a published event chooses **Remind me**, picks one or more lead times
(15 minutes, 1 hour, 1 day, 1 week before) and gets one email per occurrence and lead before it
starts. The control is in the console only: the calendar's detail popover and the event editor. The
public pages carry none, so they stay cacheable and show nothing about who is signed in.

## For the people who get them

- **My reminders** (`/admin/events/reminders`, the sidebar's *Reminders*) lists your follows, lets you
  change the times of one or remove it, and shows your own counts for the last 30 days.
- A follow is on the **whole event**: for a series, every occurrence. It is never per occurrence.
- **Nothing is ever sent for** a cancelled or skipped occurrence, an unpublished or trashed event, a
  trashed calendar, or an event you can no longer see. A **moved** occurrence is reminded once, at its
  new time, and the mail says where it came from; the old time is never reminded. A **rescheduled**
  one is reminded for the new start.
- Times are in the **event's** time zone, named (`CEST`); the page shows yours (the browser's).
  Nothing is guessed about where the reader is.
- **Losing access** (a share removed, the calendar made private, the event unpublished) keeps your
  follow but sends nothing. It is listed as *An event you can no longer see* with a Remove button,
  and it still counts toward the limit of 200 events, which is why it is listed.
- The mail's *Stop or change your reminders* link is the Reminders page. It needs a sign-in: there is
  no token and no link a mail scanner could trigger.

## Who can be reminded, and who cannot

At send time the worker re-checks, for every recipient, that the account is active, belongs to the
tenant, has a usable address (one line; not marked unverified by the directory), holds `events.view`
and can see the event. Any doubt is a refusal, counted by reason, never retried.

**The limit, stated plainly.** A Celery worker builds no app, so it has no user directory, no
membership store and no permission registry, and the framework offers no way to ask what a user holds
outside a request (upstream simple_module_python **#1005**). The worker therefore builds the host app
headless (below) and resolves access with the same code the private feeds use. That principal **never
grants more than a request principal would** (a test walks users, calendars and event states), and it
can grant **less**: the membership role (`tenant:<role>`) a live request carries has no public read.
A user whose only right to see events comes from that role gets **no reminder**.

That is never silent. When someone follows or opens an event, the same send-time check runs in the
request, and if it would refuse them the response says so (`deliverable: false`, code
`reminders_no_access`): the control and the Reminders page show *Reminders cannot be sent for this
event with your current access.* The follow is kept; a re-grant or the upstream fix resumes it.

## Guarantees and their cost

- **At most once.** A reminder goes to a recipient at most once per event, occurrence, start and lead.
  The claim row in `events_reminder_sent` (unique key, tenant first) is **committed before any mail is
  attempted**; two workers, a redelivered beat message or an overlapping tick can all compute the same
  candidate and exactly one sends.
- **A crash can lose one reminder.** States: `claimed` (committed; a 2-minute lease), `sending` (just
  before the transport is called), `sent` or `failed` (final). A row that crashed while `claimed`
  provably sent nothing and is reclaimed after the lease; a `sending` row may have sent and is **never
  reclaimed**: that reminder is lost, never repeated. It is counted *unfinished* once it is older
  than 5 minutes.
- **A failed send is not retried.** `failed` is final (`send_failed`, `send_timeout`, `too_late`): a late reminder
  is worth little and a duplicate is worse. A mail outage writes at most three `failed` rows per
  pass (the breaker), and the rest wait for the next pass while still inside their grace window.
- **Late, never early or flooding.** A reminder is due at start minus lead, as an exact duration in
  UTC (a one-day lead across a clock change is exactly 24 hours; an all-day event starts at local
  midnight of its zone). It goes out from one beat early until a grace window after, per lead; later
  than that it is stale and never sent, and never after the start.

| Constant | Value |
| --- | --- |
| `REMINDER_LEADS` | 15, 60, 1440, 10080 |
| `MAX_LEAD_MINUTES` | 10080 |
| `FOLLOWS_PER_USER` | 200 |
| `FOLLOW_RATE` | 30/minute |
| `MINE_PAGE_SIZE` | 50 |
| `MINE_PAGE_MAX` | 100 |
| `REMINDER_EARLY` | 60 s |
| `REMINDER_CATCHUP` | 15: 300 s, 60: 900 s, 1440: 21600 s, 10080: 21600 s |
| `REMINDER_TICK_SECONDS` | 60 |
| `REMINDER_CANDIDATES_MAX` | 5000 |
| `REMINDER_SEND_BUDGET` | 300 |
| `REMINDER_TENANT_BUDGET` | 100 |
| `REMINDER_TICK_BUDGET` | 45 s |
| `REMINDER_BREAKER_FAILURES` | 3 |
| `REMINDER_SEND_TIMEOUT` | 30 s |
| `REMINDER_CLAIM_LEASE` | 120 s |
| `REMINDER_TOO_LATE_LOOKBACK` | 300 s |
| `REMINDER_TOO_LATE_BATCH` | 500 |
| `REMINDER_UNFINISHED_AFTER` | 300 s |
| `REMINDER_RUNTIME_TTL` | 600 s |
| `REMINDER_SUBJECT_MAX` | 200 |
| `LEDGER_DAYS` | 90 |
| `LEDGER_PRUNE_BATCH` | 1000 |
| `LEDGER_PRUNE_MAX_BATCHES` | 20 |
| `STATS_WINDOW_DAYS` | 30 |

The send and tenant budgets are per pass; at one pass a minute they are the rate. Tenants are served
in an order that rotates every minute, so none starves another: each gets `REMINDER_TENANT_BUDGET`
(100) first, then a tenant that still has due reminders takes what is left of the install-wide
`REMINDER_SEND_BUDGET` (300), still inside the 45 s and the failure breaker.

**What a big event experiences.** A 15-minute lead is due for a 5-minute grace window plus one beat,
so about six passes. One tenant alone can send up to 300 in each pass: **a 1,000-follower event is
mailed in four passes**, and about 1,800 followers is the most one tenant can have mailed on that
lead; with several tenants busy at once each gets at least 100 per pass, about 600 per event. A
reminder the window closes on unsent is **not silently lost**: within five minutes the beat writes a
terminal `too_late` ledger row for each follower who was following when it was due and may still see
the event (at most 500 per tenant and pass, never mail). It is counted in that user's and the
managers' delivery counts as "Not sent: too many reminders were due at once". A 1-hour lead has a
15-minute window, so about 4,500 followers fit; longer leads have six hours. The table is checked against
`sm_events/core/constants/reminders_limits.py` by a test.

## What it needs

1. **A mail transport that delivers.** The mail module's SMTP backend; the console backend only logs
   and reminders then report themselves unavailable. Mail goes only through `simple_module_core.mail`.
2. **The host's `public_base_url`.** Links are built from it, never from a request's `Host`; unset, the
   control is replaced by the reason and nothing is sent. (It is read from the live host settings, so
   saving it on the Settings screen applies at once.)
3. **A worker serving the `events` queue and a beat** (`make worker`, `make beat`), with a
   `SM_SECRET_KEY` in the environment or the database. The scheduler's absence **cannot be detected**:
   follows are accepted and nothing is mailed. The Reminders page does not say so; if nothing arrives, check
   the beat. CI's `Background tasks` job proves the path (`scripts/bg_tasks_smoke.py` and
   `scripts/bg_tasks_smoke_events.py`, the reminder step).

`availability` reports the first reason it cannot deliver: `disabled`, `no_public_base_url`,
`no_mail_transport`, `console_mail`. Managers see the reason; others see
that reminders are unavailable. While unavailable, adding or changing a follow is a 503; stopping
always works.

**What the page cannot know.** The web process answers `availability`, and it cannot see whether a
beat is running or whether the worker's headless app can be built (a missing secret key, a failed
build or role overlay). In those cases follows are accepted and nothing is mailed; the beat logs the
reason by exception class and its pass reports `unavailable`. Check the worker log, not the page.

**How fresh the access check is.** Whether someone may still be reminded is decided at send time,
from the worker's own view, which is not instant. A **direct** `events.*` grant revoked in the web
process can still allow a reminder for **up to 30 s** (the framework's direct-grant source caches
per user for `GRANTS_TTL_SECONDS` and the worker has no invalidation); a **role** change is replayed
from the permissions module once per pass, so it applies within **one tick**. An account that is
deactivated, a lost membership and an unpublished, cancelled, moved or trashed event are read fresh
at claim time. A test pins the 30 s so a framework change is noticed.

## The headless worker app

`worker_app.py` calls the framework's own `create_app(merge_host_settings())` **without starting its
lifespan**, once per worker process (rebuilt after 10 minutes, so a new `public_base_url` is
picked up). Measured on the demo host: about 16 s and 200 MB the first time, then nothing. It must run
from the host's project root, as `make worker` does (the framework finds the host's templates there),
imports no host package, and **never provisions a secret key**: with none in the environment or the
database it refuses to build, because building would otherwise create the deployment's session key.
A failed build (or an unreadable role overlay) makes the worker unavailable for a minute, is logged once
by exception class and is not retried inside that window. Web and worker images must be installed
identically (the same modules). The permission screen's role edits are replayed from the permissions
module's own service once per pass.

## Privacy

- A follow is **personal data of one user**: tenant-bound and user-bound, with no route that takes
  another user's id. Someone else's follow id answers the same 404 as a missing one.
- Managers see **counts only**: sent, failed by reason and unfinished for the last 30 days. Never who.
- User ids are stored in one canonical form and matched **exactly** (only a UUID has alternative
  spellings): `Bob` and `bob` are two people.
- A recipient's address, the subject, the body and an exception's message never appear in a log line,
  a ledger code or an API error. The mail carries nothing about anyone else and no tracking (no pixel,
  no image, no redirect link). Follows and ledger rows go with their user, membership or tenant; the
  ledger is pruned 90 days after the occurrence.
