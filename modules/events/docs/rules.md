# Rules for contributors

Start here when changing events. Follow the linked module docs for each feature's
rules; this page adds implementation boundaries they do not cover.
`AGENTS.md` carries a short pointer here.

## Access

Use `sm_events.core.access.POLICY` for calendars and `core/access/events.py` for
events. Follow the [access matrix and picker rules](index.md#access),
[unpublished-event visibility](index.md#the-occurrences-read),
[workflow locks](index.md#workflow) and [revision rules](index.md#revisions-and-conflicts).
Owner and actor names share `web/services/names.py`; never parse an address-bearing
label to recover a name.

- Every change to an existing event starts with `claim_revision` (the compare-and-set on
  `expected_revision`); creation starts at revision 1.
- Range reads go through `calendar/occurrences.py`; recurrence expansion uses
  `calendar/expand.py` and `calendar/rrule_walk.py`, never iterating without an `until`.
- Keep both [rich-text sanitisers](index.md#events-and-texts) and the
  [wall-clock API](index.md#times-and-all-day).
- Follow the [bus delivery rules](extensions.md#bus-events), including the import exception.

## The calendar (FullCalendar 7)

Keep the [FullCalendar import and licence boundary](index.md#fullcalendar),
the [event-time conversion and series-move rules](index.md#the-calendar), and
the [lazy loading and embedding contract](index.md#embedding-calendar).

## The public surface

Everything anonymous goes through `core/access/public.py`. Read `public_events()` and
`public_calendars()` (published events of public calendars of the bound tenant, never
trashed), or the occurrences read with `ANONYMOUS` and `include_unpublished=False`.

- Never build a predicate on `status` or `visibility` or take a viewer from the request.
  Use `_not_found.py` for [the common refusal](public.md#one-404), including
  [hidden redirect targets](public.md#renamed-slugs).
- Every new public route is added to `tests/web/public/leaks.py` (`surfaces()` and
  the corresponding `ROUTE_SURFACES` or `BLOCK_ROUTE_SURFACES`) in the same commit;
  the route-table test fails otherwise.
- Feeds are built only in `feeds/` with `icalendar`, text passing through
  `feeds/sanitize.py`, reading rows through the gate, never the occurrences read.
- JSON-LD is serialised only by `_head.safe_json_ld` (Python) and `ui/utils/jsonLd.ts`; the
  description is rendered from `content/richtext_tree.py`, never injected.
- Constants live in `core/constants/` (`public.py` for the public surface).
- **Production must set the host's `public_base_url`:** without it canonical, `og:url`,
  `hreflang`, feed and sitemap URLs follow the client's `Host` header (the response then
  varies on `Host`).

Follow [blocks.md](blocks.md) for cards, tenant pinning, public ids, request-time reads
and bounds (`tests/web/public/test_blocks_doc.py` pins the documented constants).
Only `pagebuilder-blocks.ts` and `ui/blocks/` import pagebuilder.

## Worker and beat

`make worker` serves the `events` queue. Scheduled publishing needs beat, which enumerates
tenants under the framework's `all_tenants()` and then gives each tenant its own session and
`tenant_scope`, one savepoint per event. A scheduled publish attaches the worker's bus and
emits `EventPublished` after commit, with durable delivery through the outbox in the same
transaction when the bus has a durable transport. If the worker cannot build a bus, it logs
that publishing will proceed without an announcement. `core/worker.py` is a parity-checked
copy of newsletter's (family "worker runtime").
`sm_events.core.tenancy` is a copy of newsletter's (the fail-closed tenant guard).

## Registration seats

Follow [records' registration contract and lock order](../../records/docs/registration.md#for-contributors).

## Private feeds and the .ics import

Keep the [private-token protection and proxy-log requirements](feeds.md), the
[bounded scanner](import.md#how-a-file-is-read) and
[importer-rights checks](import.md#rights-are-re-checked).
New items default to drafts; an explicit "Import and publish" also needs
`events.publish`, and private items stay drafts. Updates retain the existing publication
state, and private items never update a published or scheduled event. `create_core` and `apply_patch` live in
`content/_core.py`; only the write path and the importer import them. A stored URL never
carries credentials (`http_url`).

## Subscriptions

Follow the [fetch transport](subscriptions.md#how-a-fetch-is-made),
[address policy](subscriptions.md#the-address-policy),
[intranet switch](subscriptions.md#the-intranet-switch),
[refresh bounds](subscriptions.md#refresh-backoff-and-the-worker),
[external-item restrictions](subscriptions.md#what-an-external-event-can-never-do)
and [test setup](subscriptions.md#tests-make-no-real-network-connection).

- Nothing that leaves `fetch_feed` carries the URL (a failure is a code with no cause).
  API output uses `url_display`; [secret rotation](subscriptions.md#secrets-and-rotation)
  and [cross-module rules](../../../.agents/rules/cross-module-rules.md#stored-secrets-351) cover storage.
- Build a fetch `Policy` only through
  `policy.effective(setting, may_use_private=sub.may_use_private and not sub.public)`.
  The flag is set only from the saver's `events.manage` (`flag_after_save`), never from a
  body, and a public subscription is never fetched with it.
- One function (`rules.fetch_wait`) decides when a fetch may start; never clear an unexpired
  lease.
- `target_gate` enforces server spacing; `refresh.refresh_async` shares the tick's
  time budget. Keep the algorithms documented in the refresh bounds above.

## Reminders are at most once

Keep the [ledger states and delivery guarantees](reminders.md#guarantees-and-their-cost),
[recipient checks](reminders.md#who-can-be-reminded-and-who-cannot),
[headless worker constraints](reminders.md#the-headless-worker-app) and
[privacy rules](reminders.md#privacy). The ledger is `events_reminder_sent`, unique on
`(tenant_id, event_id, occurrence_key, starts_at, recipient_id, lead_minutes)`;
recipient checks live in `reminders/recipients.py`, user-id comparison in
`core/user_ids.py`, and mail goes only through `simple_module_core.mail`.

## Plugins

Follow [extensions.md](extensions.md) for registration, worker installation,
budgets, visibility, non-secret settings, missing types and lazy UI. The loader is
`sm_events.calendar.plugins.extensions.load_extensions()`; it owns registration,
as images' loader does.

- A plugin call gets a read-only session of its own (own connection,
  cancellation-shielded cleanup, Postgres `statement_timeout`), a time and item budget and
  validated output. Only an in-memory test engine that cannot supply a second connection
  uses the caller's session inside an always-rolled-back savepoint
  (`calendar/plugins/plugin_isolation.py`); file-backed SQLite and Postgres never do.
- A sibling registers plugins only through `contracts.extensions`; records' optional `events`
  extra registers `records:dates` from `sm_records/events_extensions.py`, which loads
  the integration lazily. Records' imports of `sm_events` are confined to
  `sm_records/integrations/events/`.

The [runner contract](extensions.md#what-the-runner-does-around-your-call) covers session
isolation, including the in-memory test-engine exception above.
