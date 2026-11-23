# Rules for contributors

The invariants a change to the events module must keep. The other pages say what the
module does for people who run it; this one says what a change must not break. Each
section names where the detail lives. `AGENTS.md` carries one line per rule.

## Access

Every calendar route goes through `sm_events.core.access.POLICY` and requires
`events.view`. Owners, edit shares and managers edit metadata; only owners and managers
change visibility, share, trash or restore; only managers transfer ownership.
`events.edit` grants creating calendars and writing events on internal or public ones,
never metadata edits on someone else's calendar.

- The share picker needs three trimmed characters. It matches a user whose label has no
  at-sign (any variant) by name or exact full address, and a user whose label has one only
  by the exact full address (compared NFC-normalised and case-insensitively); it never
  parses labels. It masks every address, bare or inside a label, unless the query is the
  full address.
- Calendar responses name an owner (`owner_name`) and revision rows name their actor
  (`actor_name`, same resolver, `web/services/names.py`) only for an active member of the
  bound tenant with a display name. A label that carries an address resolves to `null`,
  never a masked or raw address (that is the picker's, for owners and managers alone). A
  failing name lookup leaves the names `null` and never fails the list; the picker and the
  transfer eligibility check still fail closed.
- Events are read through `core/access/events.py`: a draft, an event in review or a
  scheduled one is visible only to a caller with `write_events` on its calendar, and a
  published or scheduled (locked) event is changed, trashed, restored or overridden only
  with write and `events.publish`.
- Every event write starts with `claim_revision` (the compare-and-set on
  `expected_revision`).
- Recurrence is expanded only in `calendar/occurrences.py`, and never without an `until`.
- The editor's HTML is cleaned by both sanitisers and never inserted as markup otherwise.
- The API takes a local wall clock plus an IANA timezone, never UTC (an instant is stored
  UTC).
- Bus events are also published durably (the `background_tasks` outbox, at least once, no
  ordering); an in-process subscriber misses changes made in a worker.

## The calendar (FullCalendar 7)

Import FullCalendar only under `sm_events/ui/calendar/adapter/`, and add only the MIT
packages on the allow-list (`boundaries.test.ts`, which checks the lockfile's licences
too). The adapter must load the interaction plugin or nothing drags. A grid change (an
instant in the grid's zone) is converted into the **event's** wall clock through
`ui/calendar/time/zones.ts`, never UTC or the grid's zone, and a drag never rewrites a rule
(a series "all" shifts the master). The calendar JS is a lazy chunk that no other screen may
request. See [the calendar](index.md#the-calendar).

## The public surface

Everything anonymous goes through `core/access/public.py`. Read `public_events()` and
`public_calendars()` (published events of public calendars of the bound tenant, never
trashed), or the occurrences read with `ANONYMOUS` and `include_unpublished=False`.

- Never build a predicate on `status` or `visibility`, take a viewer from the request, or
  answer "not here" in more than one way (`_not_found.py`: same status, body and `no-store`
  for every cause, a redirect to a hidden target included).
- Every new public route is added to `tests/web/public/leaks.py` (`surfaces()` and
  `ROUTE_SURFACES`) in the same commit; the route-table test fails otherwise.
- Feeds are built only in `feeds/` with `icalendar`, text passing through
  `feeds/sanitize.py`, reading rows through the gate, never the occurrences read.
- JSON-LD is serialised only by `_head.safe_json_ld` (Python) and `utils/jsonLd.ts`; the
  description is rendered from `content/richtext_tree.py`, never injected.
- Constants live in `core/constants/` (`public.py` for the public surface).
- **Production must set the host's `public_base_url`:** without it canonical, `og:url`,
  `hreflang`, feed and sitemap URLs follow the client's `Host` header (the response then
  varies on `Host`).

`sm_events.contracts.cards` and the blocks' `/api/events/public/*` routes are the public
projection too. Both start from the public gate; the contract pins the named tenant twice (a
card's `id` is for a consumer's own lookup and is never rendered publicly). The blocks
(`pagebuilder-blocks.ts`; only that file and `ui/blocks/` import pagebuilder) reference
calendars by slug and fetch at request time, storing no snapshot: a calendar that stopped
being public shows nothing. Their bounds are constants ([blocks.md](blocks.md) pins them
with a test).

## Worker and beat

`make worker` serves the `events` queue. Scheduled publishing needs beat, which enumerates
tenants under the framework's `all_tenants()` and then gives each tenant its own session and
`tenant_scope`, one savepoint per event. A scheduled publish in the worker emits no bus
event. `core/worker.py` is a parity-checked copy of newsletter's (family "worker runtime").
`sm_events.core.tenancy` is a copy of newsletter's (the fail-closed tenant guard).

## Registration seats

Events owns the seats (`events_registration_count` is the lock target;
`events_registration_seat` is unique per tenant, provider and holder) and records owns the
person; they meet only in `sm_events.contracts.registration`, which runs in the caller's
transaction and never commits. The lock order and the people side are in
[records' registration page](../../records/docs/registration.md#for-contributors).

## Private feeds and the .ics import

`/events/feed/{token}.ics` is the third documented token-bound public route (after
newsletter's `/u/` and records' form token): it binds the token row's tenant and answers one
padded 404 for every token state. Tokens are never logged (the redaction filter) and only
their SHA-256 is stored. `feeds/importing/scan.py` is the only `.ics` parser; no library
parses an upload. Imported items are always drafts. `create_core` and `apply_patch` live in
`content/_core.py`; only the write path and the importer import them. A stored URL never
carries credentials (`http_url`). A worker cannot re-check the importer, so the rights
captured at apply expire after one hour (`rights_expired`); eager hosts re-check every slice.
Log redaction covers the app only: redact `/feed/` in proxies and CDNs yourself. See
[feeds.md](feeds.md) and [import.md](import.md).

## Subscriptions

- Fetch a subscription URL only through `sm_events.feeds.subscriptions.fetch` (the pinned
  transport, every hop re-checked, never an `httpx.AsyncClient`: its request log would print
  the URL).
- The URL is stored only as `enc:v2:` (`url_enc`, a column target of
  `scripts/reencrypt_secrets.py`) and shown only as `url_display`; nothing that leaves
  `fetch_feed` carries it (a failure is a code with no cause).
- Build a fetch `Policy` only through `policy.effective(setting, may_use_private=sub.may_use_private)`.
  The flag is set only from the saver's `events.manage` (`flag_after_save`), never from a
  body, and a public subscription is never fetched with it.
- One function (`rules.fetch_wait`) decides when a fetch may start; never clear an unexpired
  lease.
- The per-server spacing (3 s per tenant) is on the validated IP actually connected to
  (`target_gate`: every hop and every address tried, IPv6 by /64), never on the typed host. A
  tick's budget is shared by tenants by seconds used (`refresh.refresh_async`).
- External items are plain text with no description: never render them as HTML, never
  re-export them (feeds build plugin calls only), never remind or card them.
- The browser suite does not fetch (loopback is always refused): seed through
  `tests/e2e/support/seed_external.py`.

See [subscriptions.md](subscriptions.md).

## Reminders are at most once

`events.reminders` claims a row in `events_reminder_sent` (unique per tenant, event,
occurrence, start, recipient and lead) and commits it before the send. A `sending` row is
never reclaimed and a failed send is never retried; only an expired `claimed` row (nothing
handed to the transport) may be reclaimed.

- Recipients are re-checked at send time and fail closed (`reminders/recipients.py`), through
  a headless app the worker builds (`reminders/worker_app.py`: no lifespan, never provisions
  a secret key) whose principal grants no more than a request would (upstream #1005: the
  membership role is unreadable, so such a user is told in the request, never silently).
- Follows are personal: tenant- and user-bound; managers see counts only. User ids match
  **exactly** unless they are UUIDs (`core/user_ids.py`).
- Mail goes only through `simple_module_core.mail`; links come from the live
  `public_base_url`.

See [reminders.md](reminders.md).

## Plugins

A plugin registers events sources and types from `events_extensions.py`, never from
`on_startup`. Same loader shape as images: `sm_events.calendar.plugins.extensions.load_extensions()`
imports the file in the web process and on a worker's first registry read, then freezes the
registry (`RegistryFrozenError`); ids are `<entry-point name>:<name>`; install the plugin
identically in the web image and every worker image. The UI registers lazily from
`events-extensions.ts` (loaders only; it imports only `@simple-module-py/events`).

- A plugin call never uses the host's session: it gets a read-only session of its own (own
  connection, cancellation-shielded cleanup, Postgres `statement_timeout`), a time and item
  budget and validated output.
- Visibility is decided by the calendar **and** the source (`public = True` only for data
  that is public in its own module, called with `viewer=None`).
- **Plugin settings are never secret**: they are stored in the clear and shown to whoever
  manages the calendar, so a settings model with a secret field is refused at registration.
- The `extra` of an event whose type is not installed is never validated, rewritten or
  dropped.
- A sibling reaches events only through `contracts.extensions`; records' optional `events`
  extra registers `records:dates` from `sm_records/events_extensions.py` and imports
  `sm_events` nowhere else.

See [extensions.md](extensions.md).
