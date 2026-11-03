# Newsletter module (`simple_module_newsletter`) — design

Date: 2026-11-03
Status: approved 2026-11-03

## Intent

The maintainer runs a newsletter on Mailchimp: about **60,000 contacts**, a few
**segments and tags**, and a signup form on the website. Issues are **written
fresh**, though pulling in news articles and pages would help. Most of
Mailchimp goes unused. The goal is to replace it with the core: manage who is
subscribed, write and send an issue, and see how it did.

Success means the next issue goes out from this module, to the same people
Mailchimp would have sent it to (everyone who left stays gone), with basic
numbers afterwards.

## Goals

1. **Subscribers** with tags, collected by the website signup form, with
   double opt-in and one-click unsubscribe.
2. **Segments**: saved filters over subscribers.
3. **Campaigns**: write an issue, optionally insert news articles and pages,
   send a test, then send now or schedule. Audience: the whole list, a segment
   or a tag.
4. **Sending over SMTP** (the Google Workspace relay, `smtp-relay.gmail.com`), throttled with a **daily
   cap**. A campaign over the cap continues the next day (the maintainer
   accepted multi-day sends). **SES later**, behind a provider seam.
5. **Basic analytics** per campaign: sent, failed, bounced (synchronous only),
   opens (approximate), clicks per link, unsubscribes.
6. **One-time import** of the Mailchimp export, keeping statuses and tags.

## Non-goals (v1)

Automations and drip sequences; A/B tests; landing pages; per-person activity
timelines; cross-campaign reports; asynchronous bounce processing (bounce
emails arriving in the sender's mailbox); SES or any second provider (only
the seam); a visual template designer beyond the block editor below.

## Anti-goals: a failure even if it works

- **Mailing someone who unsubscribed**, bounced hard or was unsubscribed in
  Mailchimp. Suppression wins over every other rule, including the import.
- **Mailing one address twice** for the same campaign: after a worker crash,
  a retry or a resumed day.
- **Getting the company's Workspace account suspended**: the sender never
  exceeds the configured daily cap or per-minute rate.
- **A second, competing subscriber list.** Records already has one (below);
  the module must not create a parallel list with its own form and
  unsubscribe flow.
- **Leaking across tenants**: every entry point binds a tenant, as in the
  other modules.

## The key decision: subscribers live in records

Issue #101 already built a **newsletter list** in records
(`modules/records/docs/api-reference.md` § Newsletter lists): a record type of
kind `subscription`, one record per address (`sm_email`), statuses
`pending` / `confirmed` / `unsubscribed`, double opt-in, signed confirm and
unsubscribe links, suppression on unsubscribe, a purge of never-confirmed
signups, a **Form (Records)** page-builder block, CSV import and export,
`multiselect` fields, and an indexed filter grammar
(`?filter=field:op:value`, repeatable and ANDed, with `in:`). `links.py` says
its unsubscribe token "stays stable so a future campaign sender can build the
same one". This module is that campaign sender.

So **records owns subscribers and the signup**, and **newsletter owns
campaigns, segments, sending, tracking and the Mailchimp import**. Newsletter
reads and writes subscribers only through new `sm_records.contracts`
functions (the contracts rule), never through records' tables.

- **Tags** are a `multiselect` field on the list type, named `tags`, with its
  options defined on the type and **indexed** so it can be filtered.
  Newsletter's "create list" action creates the type from records'
  *Newsletter list* preset plus `tags` (and `first_name`/`last_name`, which
  Mailchimp exports).
- **The signup form** is records' existing block. Interest checkboxes on
  signup, if wanted, are `tags` marked public; nothing new is needed.
- **Trade-off accepted:** the subscriber list *is* a records list (with its
  screen, filters and export), so subscriber management happens partly in
  the records UI. Newsletter adds a subscriber screen that wraps the contract
  (search, tag and untag, unsubscribe, status counts) so day-to-day work
  doesn't need it. The alternative, standalone tables, would duplicate
  #101's opt-in, links, retention and form, and give two answers to "is this
  address subscribed".

### Records changes this needs (shipped first, as their own PR)

All behind `sm_records.contracts.newsletter` (new), tenant pinned inside each
function as the pagebuilder search contract does:

1. `iter_subscribers(session, *, tenant_id, type_key, filters, after, limit)`
   returns confirmed, non-trashed subscribers matching records-grammar
   filters, keyset-paginated by id. The hit is `{uuid, email, locale,
   first_name?, last_name?, tags}`.
2. `count_subscribers(...)`, with the same arguments, for "this segment has N
   people".
3. `subscriber_states(session, *, tenant_id, type_key, uuids)` returns
   `{uuid: (status, confirmed_at)}` for a batch, for the check made just
   before each send (`uuid` is not a filterable column, so `iter_subscribers`
   cannot answer this).
4. `unsubscribe(session, *, tenant_id, type_key, uuid, unless_confirmed_after)`
   runs the existing opt-in transition (suppression, nonce rotation,
   `SubscriptionChanged`). If the subscriber confirmed again after the given
   instant, it does nothing. This is how newsletter keeps records' rule that
   an old link never unsubscribes someone who signed up again (records gets
   the same effect from `sm_nonce`).
5. `import_subscribers(session, *, tenant_id, type_key, rows)` is a system
   write that may set `sm_status` (`confirmed` or `unsubscribed`) and stamps
   a consent snapshot `imported from Mailchimp on <date>`. It never moves an
   `unsubscribed` record back to `confirmed`.
6. `set_tags(session, *, tenant_id, type_key, uuid, add, remove)`.

**Campaign emails carry newsletter's own unsubscribe link, not records'**
(`/newsletter/u/{token}`: footer, `{{unsubscribe_url}}` and
`List-Unsubscribe`). Only that token knows the campaign, which the
per-campaign unsubscribe count needs. It is a second *page*, not a second
*flow*: its POST is records' transition, through contract 4. Records'
confirm and unsubscribe links in its own confirmation mail are unchanged,
and records' public POST needs no change.

**A news contract too (#3 of the review):** `news.contracts` exposes no
functions today. Newsletter's article cards need a tenant-pinned
`search_articles(session, *, tenant_id, pattern, limit)` and
`get_article_card(session, *, tenant_id, article_id, locale)` returning
title, excerpt, image URL and the public URL. These are modelled on
`pagebuilder.contracts.search`. They ship in the same first PR, and
newsletter's `news` extra gets a floor naming that release.

Records' `sm_status` vocabulary is **not** extended. Bounces and complaints
are newsletter's own suppressions (below).

## Module shape

PyPI `simple_module_newsletter`, package `sm_newsletter`, locale namespace
`newsletter` (`modules/newsletter`). It depends on `simple_module_records`
(required, `>=` floor with a `# floor:` comment naming the records release
with the contract) and optionally on `simple_module_news` and
`simple_module_pagebuilder` (extras `news` and `pagebuilder`, for article and
page cards). It is lockstep-versioned like the rest, and the framework range
pin follows `CLAUDE.md`.

**Layout follows `docs/module-layout.md`, with images as the reference:**

```
modules/newsletter/
  sm_newsletter/
    __init__.py  module.py  tasks.py  task_config.py  index.ts
    models/        campaign, segment, send, link, click, suppression
    contracts/     events (CampaignSent), nothing else in v1
    pages/         Inertia pages only
    locales/       en.json, de.json
    core/          constants, errors, events, settings/, tenancy/, clock/, access/
    web/           endpoints/ (admin API, public tracking + unsubscribe), schemas/, services/
    campaigns/     drafts, audience resolution, scheduling, test sends
    content/       block model, email renderer (HTML + text), article/page cards
    sending/       transport seam, smtp/, throttle, dispatcher, retries
    tracking/      open pixel, click redirect, link rewriting, counters
    imports/       Mailchimp CSV import
    ui/            components/<feature>/, hooks/, utils/ (i18n.ts as in news)
  tests/  docs/  README.md  NOTICE  pyproject.toml  package.json  tsconfig.json
```

No `pagebuilder-blocks.ts`: the signup block is records'. 300-line cap, one
head for migrations (`host/migrations/versions/`, first revision labelled
`("newsletter",)`), the locales check, and the pages rule all apply as for
every module.

**Tenancy:** `core/tenancy` is a copy of `sm_records.core.tenancy` (403
`tenant_required` admin, 404 public). Every table carries `MultiTenantMixin`.
Beat tasks enumerate tenants in one narrow read and work each tenant under
`tenant_context`, as images does.

**Permissions:** `newsletter.view` (campaigns, segments, reports),
`newsletter.edit` (drafts, segments, tags), `newsletter.send` (send a test,
schedule, send now, pause, cancel), `newsletter.manage` (lists, import,
settings). Reading subscribers also needs `records.view` on the list type, so
records' `allowed_roles` still applies.

**Settings** are DB-backed (`register_module_settings`, no env, SYSTEM scope),
like the other modules:

| Field | Default | Notes |
|---|---|---|
| `transport` | `smtp` | `smtp` only in v1; `console` in dev |
| `smtp_host`, `smtp_port`, `smtp_security` (`starttls`/`tls`), `smtp_username` | — | Google Workspace relay: `smtp-relay.gmail.com` (the only target in v1; `smtp.gmail.com` is not supported — its ~2,000/day cap makes a 60k send take a month) |
| `smtp_password` | — | encrypted at rest under `SM_SECRET_KEY` the way ai stores keys |
| `from_address`, `from_name`, `reply_to` | — | per-campaign override of name and reply-to only |
| `daily_limit` | `9500` | recipients per rolling 24 h, across all tenants (one account) |
| `per_minute_limit` | `30` | smooths bursts; Google throttles spikes |
| `tracking_opens`, `tracking_clicks` | `true` | off removes the pixel or the rewrite |
| `physical_address` | — | footer text; required by anti-spam law, the send refuses without it |

Newsletter has **its own SMTP settings**, separate from the framework's `mail`
module, for two reasons. The framework's `MailMessage` carries no headers, and
`List-Unsubscribe`, `List-Unsubscribe-Post` and `Precedence: bulk` are
required. And marketing mail should be able to go from a different account
than password resets. The transport uses `aiosmtplib` and keeps one
connection per batch.

## Data model (newsletter's tables)

- **`newsletter_campaign`**: name, subject, preheader, from-name and reply-to
  overrides, `body` (block JSON, below), `list_type_key`, audience (`all` |
  `segment:<id>` | `tag:<value>`), status `draft → scheduled → sending →
  sent`, plus `paused` and `cancelled`. Also `scheduled_at`, `started_at`,
  `finished_at`, and denormalised counters (recipients, sent, failed,
  bounced, unique opens, unique clicks, unsubscribes).
- **`newsletter_segment`**: name, `list_type_key`, `filters`, a list of
  records-grammar terms (ANDed). The editor shows rows of *field / condition /
  value* over the list's indexed fields, `tags` included. **OR across
  different fields is out of v1** (records' grammar is AND-only). OR within
  one field is `in:` ("tag is any of"), which covers most Mailchimp segments.
- **`newsletter_send`**: one row per recipient per campaign, written when the
  campaign **starts** (the audience is frozen then; later signups are not
  added). It holds `record_uuid`, the email, `status` (`queued`, `sent`,
  `failed`, `bounced`, `suppressed`, `skipped_unsubscribed`), attempts,
  `sent_at`, the last error, `opened_at` (first open) and an open count. It
  is unique on `(campaign_id, record_uuid)`, which is the no-duplicate
  guarantee.
- **`newsletter_link`** (campaign, position, url) and **`newsletter_click`**
  (send, link, at).
- **`newsletter_suppression`**: `(tenant, email_hash, reason, created_at)`
  with `hard_bounce`, `complaint`, `imported_cleaned` or `unsubscribed`,
  checked at freeze and again just before each send.
  - **Unsubscribes are mirrored here** from records' `SubscriptionChanged`
    events (status after = `unsubscribed`). The reason: an admin who
    hard-deletes or purges an unsubscribed record in the records UI would
    otherwise erase the only proof, and a later import would mail them.
  - **A fresh confirmation clears a suppression.** A `SubscriptionChanged` to
    `confirmed`, through double opt-in or a confirmed re-signup, removes the
    `unsubscribed`, `hard_bounce` and `imported_cleaned` rows for that
    address, because the person has just shown the address works and wants
    the mail. A `complaint` row is not cleared.
  - The subscriber screen shows a suppressed address with its reason. An
    admin with `newsletter.manage` can lift a `hard_bounce` or
    `imported_cleaned` suppression.

## Content: the editor and the email

The body is a **list of email blocks**: heading, rich text, image (from
pagebuilder media or an upload to file storage), button, divider, spacer,
**news article card** and **page card**. Cards are picked through
`news.contracts` and `pagebuilder.contracts.search` (tenant named by the
caller) and **snapshotted into the block** (title, excerpt, image, URL) when
inserted, so a later edit to the article doesn't change a sent issue. A
*Refresh* action re-pulls a card in a draft.

**The editor is Puck** with a newsletter-only block config (Puck is already
how pagebuilder edits and is in the dependency set). The config restricts
blocks to the list above and gives a fixed single-column, 600 px layout. A
server-side Python renderer turns the block JSON into **table-based,
inline-styled HTML** that works in Outlook and Gmail, plus a **plain-text
part**. The browser preview is that server render in an iframe, never Puck's
own render, so what you preview is what gets sent. Branding (logo, accent
colour) comes from the framework's `branding` module.

Every email gets a fixed footer the editor cannot remove: why you got this,
the physical address, and the unsubscribe link. Merge fields are limited to
`{{first_name}}` with a fallback, and `{{unsubscribe_url}}`.

## Sending

1. **Start** (send now, or beat finds a `scheduled` campaign due): resolve
   the audience through `iter_subscribers` in pages, subtract
   `newsletter_suppression`, and insert `newsletter_send` rows (`queued`) in
   batches. Set `sending`.
2. **Dispatch** is a beat task every minute. It takes the budget left in the
   rolling 24-hour window (counted from `sent_at` across every tenant) and
   the per-minute limit, claims that many `queued` rows oldest campaign first
   (`FOR UPDATE SKIP LOCKED` on Postgres; a single worker on SQLite), and
   sends each through the transport. It re-checks the record is still
   confirmed and unsuppressed right before sending.
3. **Per message:** render once per campaign and personalise per recipient
   (merge fields, rewritten links carrying the send's token, the pixel, and
   the `List-Unsubscribe: <https://…/newsletter/u/{token}>` and
   `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers).
4. **Results:**
   - A 2xx marks the row `sent`.
   - **Only a recipient-stage rejection with enhanced code `5.1.x`** (bad
     mailbox or domain) marks the row `bounced` and adds a `hard_bounce`
     suppression.
   - Any other 5xx (`5.4.5` quota, `5.7.x` policy or relay refusal, an
     unknown code) **pauses the campaign** with the server's text, leaving
     the row `queued`. So does an auth failure. The campaign never burns
     through the list, and a quota error never suppresses anyone.
   - A 4xx or connection failure retries with backoff, up to 3 attempts, then
     marks the row `failed`.
   - A `4.x` quota reply also stops this minute's dispatch.
5. When no `queued` rows remain, the campaign is `sent` and `CampaignSent` is
   emitted.

**The duplicate guard:** a row is marked `sending` with a lease before the
SMTP call and `sent` after it. A row whose lease expired is not resent
automatically. It becomes `failed` with *outcome unknown*, so a crash between
the SMTP accept and the commit errs towards one lost message rather than a
double send. *(Builder's call how the lease is implemented; records'
`delivery.py` claim protocol is the precedent.)*

**Secrets in workers:** the token MACs need the host's secret key, and a
Celery worker has no app. Newsletter copies ai's resolver
(`modules/ai/sm_ai/core/worker_settings.py`): `SM_SECRET_KEY` from env or
`.env` through `BootstrapSettings`, else the database's `host.secret_key`
row. With neither, dispatch refuses to start. The web process uses
`app.state` as records does. Tokens are minted at send time and never stored.

**Several campaigns at once:** they share the one account's budget, oldest
`started_at` first, so a later issue waits behind an earlier one. The
schedule dialog shows the **estimated finish** from the queue ahead of it and
the cap, and warns when it overlaps a campaign already sending.

**Pause, resume, cancel:** pause stops dispatch, and resume continues where
it left off. Cancel marks the remaining `queued` rows `cancelled`. The
campaign screen shows progress (*12,400 of 60,000 sent · about 5 more days
at 9,500/day*).

**Test send:** to up to 5 addresses typed in, with no rows or tracking, and
a `[TEST]` subject prefix. It counts against the daily cap.

## Tracking and analytics

Public routes under `/newsletter/` (no auth, tenant bound from the token, as
records' links do):

- `GET /newsletter/o/{token}.gif` returns a 1×1 GIF and sets `opened_at` and
  the count. Opens are labelled *approximate* in the UI (Apple Mail Privacy
  Protection preloads images).
- `GET /newsletter/c/{token}/{link}` records the click and returns a 302 to
  the stored URL. **It only redirects to the campaign's own stored links**,
  never a URL from the request, so it is not an open redirect. A click also
  sets `opened_at` if it is empty.
- `GET /newsletter/u/{token}` is a page with one *Unsubscribe* button
  (scanners fetch GETs). `POST` on the same URL, from that button or a
  one-click `List-Unsubscribe=One-Click` (RFC 8058, form-encoded, token in
  the path), calls records' `unsubscribe` with `unless_confirmed_after` set to
  the send's `sent_at`, and counts the unsubscribe against the campaign. It
  always answers the same way.

Tokens are HMAC over `(tenant, campaign, send id)` with a 128-bit MAC, like
records' links. A forged or unknown token gets the same answer as a real one
(pixel or redirect target excepted), so the routes are not an oracle.

The **report screen** per campaign shows recipients, sent, failed, bounced,
unique and total opens (approximate), unique clicks, a click table per link,
and unsubscribes. The campaign list shows sent date, recipients, open % and
click %. Counters update in the same transaction as the event.

## Mailchimp import

A screen under *Newsletter → Import*. Upload Mailchimp's audience export (the
ZIP or its CSVs: `subscribed`, `unsubscribed`, `cleaned`), pick the target
list, preview the counts, then apply. It runs as a background task with
progress.

| Mailchimp file | Becomes |
|---|---|
| subscribed | `confirmed`, consent snapshot "imported from Mailchimp", `TAGS` mapped to `tags` (new tag values added to the field's options), first and last name |
| unsubscribed | `unsubscribed` suppression record in records |
| cleaned | newsletter `imported_cleaned` suppression (and no subscriber) |

Matching is by lowercased email. Suppression always wins: an address in
`unsubscribed` or `cleaned` is never confirmed by a `subscribed` row, and an
address already unsubscribed here stays unsubscribed. Re-running the import is
a no-op. Mailchimp's *segments* are saved filters with no export, so they are
recreated by hand as newsletter segments; the import lists the tag values it
found to help with that.

## Screens

Newsletter in the console sidebar: **Campaigns** (list, editor with preview
and test send, schedule dialog, report), **Segments** (list, editor with a
live count), **Subscribers** (search, status counts, tag/untag, unsubscribe;
links to the records list for full editing), **Import**, and settings on the
framework Settings screen. English and German catalogues from the start.

## Testing

- Unit tests for the renderer (HTML and text snapshots), the throttle maths,
  token signing, and import mapping (each Mailchimp status, suppression
  precedence, re-run no-op).
- Service tests on SQLite and Postgres: freeze excludes suppressed and
  unsubscribed; one row per recipient; a crash mid-batch never resends;
  pause/resume/cancel; daily cap rollover across two "days" with a fake
  clock; tenant isolation on every route and task.
- A fake SMTP server (`aiosmtpd`) in tests for 2xx, 4xx and 5xx paths and
  header presence.
- Records' new contract functions are tested in records.
- An e2e spec (stands alone, per `CLAUDE.md`) covering: create a list, sign
  up through the block, confirm, write a campaign with an article card, send
  to a tag, see the report, click unsubscribe, and the subscriber shows as
  unsubscribed. The e2e server uses the `console` transport, plus a capture
  hook to read the sent message.

## Delivery order

1. Records and news PR: records' `contracts.newsletter` functions and news'
   article-card contract.
2. Newsletter scaffold (per `docs/adding-a-module.md`), models, settings,
   tenancy, permissions and migrations.
3. Campaigns, content and renderer, editor and preview, test send.
4. Sending: freeze, dispatcher, throttle, SMTP transport and retries.
5. Tracking and reports.
6. Segments and the subscriber screen.
7. Mailchimp import.
8. Docs (`modules/newsletter/docs/`) and e2e.

## Left to the builder

Lease and claim implementation details, the exact Puck config shape, renderer
internals (hand-written tables vs. a small template set), backoff timings,
page layouts within the existing console style, and how test sends surface
their result.

## Calls made without asking (check these)

- Subscribers live in **records**, not new tables (the key decision above).
- Double opt-in stays on for new website signups (records' default).
- Newsletter has its own SMTP settings, not the framework `mail` module's.
- Target is `smtp-relay.gmail.com` only (user decision), default daily cap
  9,500 (under the relay's ~10,000 recipients/day), so a 60k issue takes
  about 6½ days.
- One sender for the whole install (user accepted the default): SYSTEM-scope
  sender identity, footer and cap; tenant-safe, not per-tenant senders.
- The audience is frozen when sending starts.
- Opens and clicks tracking on by default, with a setting to turn it off.
- Segments are AND-only, plus "any of" within one field.
- Synchronous bounces only, and only `5.1.x` codes. Bounces that arrive later
  by mail wait for SES.
- Emails carry newsletter's unsubscribe page, which calls records'
  transition. An old link never unsubscribes someone who has since signed up
  again.
- Unsubscribes are mirrored into newsletter's suppressions, so deleting a
  record in the records UI can't make the address mailable again. A fresh
  confirmation clears bounce and import suppressions.
- News gets a small article contract in the first PR.
- Concurrent campaigns queue oldest-first on the shared cap, and the
  scheduler shows the estimated finish.
- A crash between the SMTP accept and the commit loses that one message
  rather than risking a double send.

## Amendments from the Codex plan review (2026-11-03)

These override anything above that contradicts them.

1. **Unsubscribe mirror is not trusted alone.** Records publishes
   `SubscriptionChanged` after commit through a volatile callback, and the
   event carries no address. So besides the event handler, newsletter runs a
   **reconcile** (beat, hourly, per tenant) that walks records' unsubscribed
   subscribers (`iter_subscribers(status="unsubscribed")`) and upserts
   `unsubscribed` suppressions; freeze and the import also consult records'
   status directly. Newsletter's own `/newsletter/u/` route writes its
   suppression row in the same transaction as the records unsubscribe. The
   remaining gap (crash, then an admin purge before the next reconcile) is
   accepted.
2. **Ambiguous SMTP outcomes are never retried.** Only failures known to have
   happened before the message was accepted are retried: connect, TLS or
   auth errors, and a 4xx on `MAIL`/`RCPT`/`DATA` start. A connection lost or
   a timeout after the message body was sent marks the row `failed` with
   *outcome unknown*, the same as an expired lease (records' `delivery.py`
   documents the same window).
3. **Eligibility vs. a concurrent unsubscribe.** The re-check just before
   sending is a read, not a lock; an unsubscribe that commits in the
   milliseconds between the check and the SMTP call can still get that one
   message. Accepted: one-click unsubscribes must be honoured within two days
   (Gmail/Yahoo), not atomically.
4. **One dispatcher at a time, and a budget ledger.** Dispatch takes a global
   lock (Postgres advisory lock; a lock row on SQLite) so two workers never
   spend the same budget. The rolling-24 h and per-minute budgets count every
   SMTP attempt that may have been accepted — `sent`, `outcome unknown` and
   test sends — from a `newsletter_send_attempt` log written before each SMTP
   call.
5. **Unsubscribe ships with sending.** The `/newsletter/u/` page and the
   one-click POST move from the tracking PR into the sending PR; no campaign
   can be sent by a build without them.
6. **Contracts never switch a bound tenant.** Records' and news' contract
   functions bind with records' `tenant_scope` semantics: re-entering the
   bound tenant is a no-op, naming another raises `TenantIsolationError`
   (news gets the same guard).
7. **Unsubscribe by an old link:** `unsubscribe(..., unless_confirmed_after)`
   writes only when the subscriber is `confirmed` with `sm_confirmed_at` at
   or before the cutoff; `pending` (a re-signup awaiting confirmation),
   `unsubscribed`, trashed and unknown are no-ops returning `False`. No
   generation id is added; the timestamp plus status is enough for one
   campaign link.
8. **`unsubscribe` returns whether this call wrote**, from the transition's
   `Outcome.wrote` (records' `opt_in.leave` is extended to expose it), so two
   concurrent calls attribute the unsubscribe once.
9. **Per-list authorisation.** Records exposes
   `can_read_list(session, *, tenant_id, type_key, roles)` built on its
   `role_blocked`; newsletter's admin screens call it with the caller's
   `CallerRoles`, and workers pass `roles=None` (records' "no caller").
10. **DKIM covers the unsubscribe headers.** RFC 8058 requires a valid DKIM
    signature covering `List-Unsubscribe` and `List-Unsubscribe-Post`.
    Workspace's relay signs with the domain's DKIM key once it is enabled in
    the Admin console. The module's docs (`docs/operations.md`) carry it as a
    deployment checklist item, with how to confirm it from a test message's
    `DKIM-Signature: … h=` list. No in-app verification in v1.
