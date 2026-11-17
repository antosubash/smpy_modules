# Events module (`simple_module_events`) — design

Date: 2026-11-17
Status: approved 2026-11-17 (design shown in conversation; issue #400)

## Intent

The maintainer wants a calendar he can build richly on and extend as far as
possible: "I should be able to build a rich calendar and extend it as much as
possible." So this is not a list of dated news items. It is a **calendar
engine** (calendars, timezone-aware and recurring events, month/week/day views,
feeds) with **extension points** that let another module or a host put its own
things on a calendar and change how they look.

No first consuming site was named. Until one is, the module is a publishing and
team-visibility calendar, not a meeting scheduler (see Non-goals).

Success: a host installs the module, creates calendars, enters one-off and
recurring events, sees them in month, week, day and list views in the console
and on the public site, subscribes to them from Outlook or Google, and a second
package adds its own dates and its own event type without touching this one.

## Goals

1. **Calendars**: several per tenant, each `private`, `internal` or `public`,
   shareable with chosen users.
2. **Events** with timezone-aware start and end, all-day and multi-day, place
   (in person, online, hybrid), category, type, a cancelled flag, sub-events,
   and text in several languages.
3. **Recurrence** by iCalendar rules, with skipped, cancelled and moved
   occurrences.
4. **A rich calendar UI**: month, week, day and list views; click to create,
   drag to move and resize; "event time / my time".
5. **Public site**: calendar and list, event pages, ICS files and feeds,
   structured data, sitemap.
6. **Extension points**: occurrence sources, event types with extra fields,
   render slots, bus events.
7. **Feeds and import**: public ICS feeds, private token feeds, `.ics` upload,
   external ICS subscriptions.
8. **Reminders** by email.
9. **Integrations**, all optional: pagebuilder blocks, a newsletter card,
   registration through records.

## Non-goals (v1)

Invitations, RSVP and iTIP mail (a meeting scheduler); rooms and resource
booking; payments and waitlists; a CalDAV server or two-way sync; editing "this
and following" occurrences; event types or custom fields defined by an admin on
a screen (a plugin declares them); a separate agenda/session model (sessions are
sub-events).

## Anti-goals: a failure even if it works

- **An internal or private event reaching the public**: through a page, a feed,
  a pagebuilder block, a newsletter card lookup, the sitemap, structured data
  or a plugin's source.
- **An event shown at the wrong time**: across a timezone, a DST change or an
  all-day boundary.
- **Unbounded recurrence expansion**: one request must never expand a rule
  without a range and a cap.
- **A reminder sent twice**, or sent for a cancelled or skipped occurrence.
- **A feed token that outlives its owner's access.**
- **Non-MIT calendar code** in the bundle (FullCalendar's premium plugins).
- **A subscription URL used to reach an internal address.**
- **Leaking across tenants.**

## Approaches

1. **A standalone module with its own tables (chosen).** Calendar semantics
   (timezones, recurrence, feeds) need typed columns and a range read.
2. **Events as a records type.** Cheap, but records stores JSON documents with
   no notion of recurrence, timezones or feeds, and its list is not a calendar.
3. **Event fields on news articles.** Couples two modules; every news host would
   carry calendar code.

The maintainer picked 1, then asked for recurrence, the rich calendar and the
extension points to be in from the start, and for reminders, per-calendar
access, private feed links, one-off import and viewer timezone to be added.

## The core idea: occurrences from sources

Everything shown on a calendar is an **occurrence**. Occurrences come from
**sources**. The module's own events are the built-in source `events`. Every
view, block, feed and API answers from one read:

```
occurrences(tenant, viewer, start, end, calendars, filters) -> [Occurrence], truncated
```

An `Occurrence` carries: `source`, `key` (stable per source), `calendar_id`,
`start`, `end` (UTC), `all_day`, `timezone`, `title`, `lang`, `color`, `url`,
`status` (`confirmed` | `cancelled`), `type`, `editable`, and for the built-in
source `event_id` and `original_start`.

Bounds, enforced in the read and not by its callers: the range is at most 366
days; at most 2,000 occurrences are returned and `truncated` is set beyond that;
`SECONDLY`, `MINUTELY` and `HOURLY` rules are refused at save.

## Data model

All tables carry `MultiTenantMixin` and sit behind the fail-closed tenancy guard.

| Table | Holds |
| --- | --- |
| `events_calendar` | `slug`, `name`, `color`, `description`, `visibility`, `owner_id`, `default_timezone`, enabled `sources` (JSON list), soft delete |
| `events_event` | `uid` (UUID, the ICS UID), `calendar_id`, `parent_id` (one level), `type`, `status`, `cancelled`, `all_day`, `starts_at`, `ends_at`, `timezone`, `rrule`, `recurrence_until`, `attendance_mode`, `venue_name`, `address`, `online_url`, `latitude`, `longitude`, `category_id`, `organiser`, `image`, `registration_url`, `extra` (JSON), `revision` (int), `publish_at`, `published_at`, soft delete |
| `events_event_text` | per `(event_id, locale)`: `slug`, `title`, `summary`, `description` (allow-listed rich text), SEO fields |
| `events_occurrence_override` | `(event_id, original_start)`: `kind` (`skipped` \| `cancelled` \| `moved`), new `starts_at`/`ends_at`, `note` |
| `events_category` | `slug`, names per locale, `color` |
| `events_revision` | snapshot of an event and its texts per write, actor, action |
| `events_redirect` | `(locale, old_slug) -> event_id` |

Later PRs add `events_feed_token`, `events_follow`, `events_reminder_sent`,
`events_import`, `events_subscription` and `events_external_item`.

Decisions:

- **One event, many texts.** Unlike pages and articles, an event's language is
  not fixed: the schedule belongs to the event, and each language has a text
  row. A sibling-per-language model would let the German and English copies of
  one seminar drift to different times. Slugs are unique per
  `(tenant, locale, slug)` and a rename records a redirect in that locale.
- **No draft copy.** Statuses are `draft`, `in_review` and `published`; an edit
  to a published event is live, because a drag on the calendar has to be.
  History is in `events_revision`. Every write carries `expected_revision`
  (409 `stale`).
- **Times.** `starts_at` and `ends_at` are UTC, `timezone` is an IANA name. An
  all-day event stores local dates at midnight of its timezone and is rendered
  as dates, never shifted for a viewer. A rule recurs on the event's wall clock,
  so a 10:00 weekly seminar stays at 10:00 across DST.
- **Recurrence** is an RFC 5545 `RRULE` string expanded server-side with
  `python-dateutil`, only inside the occurrences read. `recurrence_until` is
  derived at save for the SQL prefilter (`NULL` for an endless rule). The client
  never expands rules.
- **Editing an occurrence** offers "this one" (writes an override) or "all"
  (writes the event). Changing the rule or start of a series deletes overrides
  that no longer match an occurrence, and says so first.
- **Cancelled is not deleted.** A cancelled event or occurrence stays visible,
  marked, and is `STATUS:CANCELLED` in feeds. `skipped` removes one occurrence
  silently.
- **Sub-events.** A conference is an event; its sessions are events with
  `parent_id`, in the same calendar, listed on the parent's page.

## Access

- **Permissions**: `events.view`, `events.edit` (also: create a calendar and
  become its owner), `events.publish`, `events.manage` (every calendar,
  ownership transfer, categories, settings, import, other people's tokens).
- **Calendar visibility**: `private` (owner and shares), `internal` (every
  signed-in member of the tenant with `events.view`), `public` (also anonymous,
  published events only).
- **Shares** use the framework's `sharing` module as images does: resource type
  `events.calendar`, rights view and edit.
- **How shares and permissions combine** (my call, after images' policy):
  `events.manage` bypasses calendar visibility. Otherwise a signed-in user needs
  `events.view` and a way into the calendar (owner, share, or `internal`).
  Someone who can only view sees published events. Someone with an edit right
  on the calendar (owner, edit share, or `events.edit` on an internal or public
  calendar) also sees drafts, writes drafts and submits them for review.
  Publishing, unpublishing and **any change to a published event** (edits are
  live) need `events.publish` as well as that edit right. Sharing, visibility
  and deleting a calendar are the owner's or `events.manage`'s.
- One function decides what a viewer may see (`core/access`). The occurrences
  read, the event read, every feed and every contract go through it. The public
  surface never passes a viewer and gets `public` calendars and `published`
  events only.

## Tenancy

A copy of the fail-closed guard and `bind_admin`/`bind_public` (the parity
family, #335, until #374 moves it upstream). Single-tenant host → `"default"`;
multi → `request.state.tenant_id`; none → 403 `tenant_required` (admin), 404
(public). A public answer for a tenant is never shareable-cached for another.

**One documented exception**, the private feed (below): it binds the tenant of
the token's row.

## The calendar UI

- A `Calendar` component exported from `@simple-module-py/events` (`index.ts`):
  views month, week, day and list; filters by calendar, category and type;
  props for the occurrence fetcher, initial view and date, and render slots.
- **FullCalendar 7, MIT packages only** (checked 2026-11-17: 7.1.5 is npm
  `latest`, v6 is `legacy`): `@fullcalendar/react` (its `/daygrid`,
  `/timegrid`, `/list` and `/interaction` subpaths; React 17–19),
  `@fullcalendar/core` and the required peer `temporal-polyfill`.
  `@fullcalendar/react-scheduler` (AGPL in v7) and any `resource`, `timeline`
  or `scheduler` package are never installed; a test fails on any
  `@fullcalendar/*` dependency outside the allowed list. `@fullcalendar/rrule`
  is not needed: the server expands rules. v7 bundles no CSS, so the component
  imports `skeleton.css` and one theme. FullCalendar is imported only inside
  `ui/calendar/`, so it can be replaced.
- Admin: click or drag-select to create, drag to move, resize to change the
  end, both through the API with `expected_revision`. A recurring occurrence
  asks "this one or all".
- **Grid timezone**: a grid has one timezone at a time, switched by a toggle
  between "calendar time" (the calendar's `default_timezone`; the tenant
  default when several calendars are shown) and "my time" (the browser's).
  v7 handles named zones without a plugin. A drag moves the event in the grid's
  timezone; the event keeps its own `timezone`. Popovers and event pages also
  show the event's own local time when it differs. All-day events ignore the
  toggle.
- Week start and 12/24-hour format follow the console language. Events are
  focusable (`eventInteractive`). FullCalendar documents no keyboard drag or
  resize, so every move and resize is also possible from a "Move" dialog with
  date and time fields.

## Screens and routes

Console, under `/admin/events/`: Calendar (the default), List, the event editor,
Calendars (with sharing and feed links), Categories, Import, Trash, Settings.

API under `/api/events/`, `RequiresCsrf`, JSON errors as `{"detail","code"}`
(the exception: FastAPI's own request-validation 422 keeps its standard list
shape).
`GET /api/events/occurrences` is the read above.

Public, under the `public_prefix` setting (default `/events`, restart-only),
with `/{locale}` prefixes as news has:

| Route | Serves |
| --- | --- |
| `/events/` | calendar and upcoming list over public calendars |
| `/events/c/{calendar}` | one public calendar |
| `/events/{slug}` | event page; `?date=` selects an occurrence of a series |
| `/events/{slug}.ics` | one event |
| `/events/calendar.ics`, `/events/c/{calendar}.ics` | public feeds |
| `/events/feed/{token}.ics` | private feed |
| `/events/sitemap.xml` | published events of public calendars |

The event page carries `Event` JSON-LD (`eventStatus`, `eventAttendanceMode`,
`location`). A calendar view shows an event without a text in the viewer's
language in the default language, marked with `lang`; an event **page** exists
only in languages that have a text. Scripts carry the CSP nonce.

## ICS

Read and written with the `icalendar` package (7.x, BSD-2-Clause).
`recurring-ical-events` is LGPL and is not used. The first task of the feeds PR
is a round-trip test of `RRULE`, `EXDATE`, `RECURRENCE-ID` and `VTIMEZONE`.

- **Feeds do not use the occurrences read for this module's own events.** They
  read events with their rules and overrides directly (through the same access
  function) and emit a series as `RRULE` plus `EXDATE` and `RECURRENCE-ID`,
  with `TZID`. Occurrences from **plugin sources** enabled on the calendar are
  added as plain instances for a window of 30 days back and 366 days ahead,
  with `UID` `<source>:<key>`. External subscriptions are never re-exported.
- **UID.** `events_event.uid` is text, unique per `(tenant, calendar, uid)`. A
  new event gets `<uuid4>@simple-module-events` once; an imported event keeps
  the UID it came with. Feeds emit it verbatim, so it never depends on the
  host name. The same UID in two calendars is two events.

- **Private feed tokens.** A token is 32 random bytes shown once; only its
  SHA-256 is stored, so it does not depend on `SM_SECRET_KEY` (#366). It belongs
  to one user and one calendar. The feed looks the hash up in one narrow
  `all_tenants()` read, binds that row's tenant, and serves what that user may
  see **now**. Unknown, revoked, or a user who lost access: the same 404. A
  token can be revoked by its owner or by `events.manage`.
- **Upload.** An `.ics` file (5 MB cap) is parsed in a background task into a
  staged import with counts; applying it writes events into a chosen calendar
  as drafts or published. A UID already present in that calendar updates that
  event. What is
  dropped (alarms, attendees, unsupported rules) is reported.
- **Subscriptions.** A calendar can subscribe to an ICS URL as a read-only
  source: fetched by a beat task with `ETag`, cached in
  `events_external_item`, the URL checked as ai checks a base URL (public
  addresses only, re-checked on redirect).

## Extension points

A package with a `simple_module` entry point ships **`events_extensions.py`**
with `def register(registry)`. It is loaded in the web process (`on_startup`)
and in a worker (first registry read), then the registry is frozen, as in
images.

- **Sources.** `registry.add_source(Source)`: an id, a label key and
  `async occurrences(ctx, start, end) -> list[Occurrence]`. `ctx` names the
  tenant and the viewer; the source pins the tenant itself and returns only what
  that viewer may see. A source is read-only on the calendar and each occurrence
  links to its own screen. An admin enables a source per calendar. A source that
  raises or exceeds its time budget is skipped for that read and reported in the
  response, never a 500.
- **Event types.** `registry.add_type(EventType)`: an id, a label key and a
  pydantic model that validates `extra`. On a host without the plugin the event
  keeps its type and `extra` untouched and renders as a plain event.
- **Frontend.** A sibling package ships `events-extensions.ts`, globbed by this
  module as pagebuilder globs `pagebuilder-blocks.ts`: `registerEventType({id,
  EditorSection, Detail, Chip})` and toolbar slots.
- **Bus events** in `sm_events.contracts.events`: `EventPublished`,
  `EventRescheduled`, `EventCancelled`, `EventDeleted`, published after commit.
- **Contracts** for siblings: `contracts.occurrences` (the read),
  `contracts.cards` (published events of public calendars, for newsletter),
  `contracts.mounted(app)`.

The in-repo proof is a source that puts a records date field on a calendar.

## Reminders

- A signed-in user can **follow** an event ("Remind me"), with a lead time; a
  calendar has default lead times.
- A beat task finds due reminders and sends through `simple_module_core.mail`
  (the durable outbox when the host has one, as records' notifications do).
- **At most once** (my call): `events_reminder_sent` is unique on `(event,
  occurrence start, recipient, lead)` and is claimed and committed before the
  send. A crash between the claim and the send loses that reminder; it is never
  retried, because a duplicate is the anti-goal and a late reminder is useless.
  Records' notifications make the opposite trade and can duplicate. Claims
  that never reached `sent` are counted on the Settings screen. A cancelled or
  skipped occurrence is not reminded; a rescheduled one is reminded at its new
  time.
- No mail transport, or no `public_base_url`: nothing is sent and the control is
  hidden. When the notifications module (#401) exists, delivery moves to it.

## Integrations (optional extras)

- **pagebuilder**: `Calendar` and `UpcomingEvents` blocks
  (`pagebuilder-blocks.ts`), public calendars only.
- **newsletter**: an event card through `sm_events.contracts.cards`; newsletter's
  `content/integrations/` gains `events.py`. The lookup returns only published
  events of public calendars. A card is a snapshot taken at insert, as article
  and page cards are: making the event private later does not recall a campaign
  that already holds it.
- **records**: registration with a capacity limit and a closing date, a
  confirmation mail with the `.ics` attached, reminders to registrants and "my
  registrations". It needs a new records contract; that PR starts with its own
  short design note. Until then an event has only `registration_url`.
- **search (#399)** and **ai (#392)** later.

## Settings

DB-backed (`DbBackedSettings`), no environment variables: `public_prefix`
(restart), `content_locales` (restart), `default_timezone`,
`reminders_enabled`, `default_reminder_minutes`, `import_max_bytes`,
`subscription_refresh_minutes`. Console strings in `en.json` and `de.json`, keys
derived from `en.json` as in news.

## Background work

All through `background_tasks` (`tasks.py`, `task_config.py`); no in-process
loop: `events.publish_due`, `events.reminders`, `events.run_import`,
`events.refresh_subscriptions`. Each enumerates tenants in one narrow
`all_tenants()` read and works under `tenant_context`. Eager hosts run them
inline.

## Layout

`modules/events/sm_events/`: `module.py`, `models/`, `tasks.py`,
`task_config.py`, `pages/`, `locales/`, `index.ts`, `contracts/`; areas `core/`
(constants, settings, tenancy, access), `web/`, `calendar/` (occurrences,
recurrence, sources, registry), `content/` (events, texts, slugs, revisions,
workflow), `feeds/` (ics, tokens, import, subscriptions), `reminders/`, `ui/`.
Migrations are in `host/migrations/versions/`, the first with
`branch_labels = ("events",)`.

## Delivery

| PR | Delivers |
| --- | --- |
| 1 | Scaffold, tenancy, settings, calendars with visibility and sharing, the Calendars screen, host migration, docs |
| 2 | Events and texts, recurrence and overrides, the occurrences read, workflow, API, list and editor screens |
| 3 | The `Calendar` component and the console calendar: views, create, drag, resize, grid timezone |
| 4 | Public pages (with calendar slug redirects), public ICS, JSON-LD, sitemap, e2e spec |
| 5 | Private feed tokens and `.ics` upload |
| 6 | The extension registry, plugin guide, the records date-field source |
| 7 | Pagebuilder blocks and the newsletter card |
| 8 | Reminders |
| 9 | Registration through records |
| 10 | External ICS subscriptions |

Each PR goes through `/ship`. The framework bump (#405) lands first. PR 1
creates every table of PRs 1 and 2 in one labelled revision.

## Left to the builder

File names inside each area; index choices beyond `(tenant_id, calendar_id,
starts_at)` and the recurrence prefilter; the rich-text allow-list (start from
newsletter's); the FullCalendar major; e2e data seeding.

## Open

- Which site uses this first. If staff will schedule meetings with it,
  invitations and RSVP move from Non-goals into a later PR.

## Amendments (PR 1)

The approved PR 1 rulings refine the scope above: `events.edit` creates a
calendar owned by the caller. Owners and share holders still need
`events.view`; without it the policy grants public view only. Visibility is
stored as VARCHAR with Python constants, not a database enum. Calendar
metadata uses last-write-wins forms without `expected_revision`; event writes
retain that guard from PR 2. Categories (API and screen) ship in PR 1.
`events.manage` alone authorises ownership transfer, to an active member of
the bound tenant; the HTTP calendar API also requires `events.view`.

Later PR 1 rulings: calendar responses carry `owner_name`, a string or `null`;
only an active member of the bound organisation with a display name is named,
anyone else (an owner whose only label is an address included) is `null` and
shown as "Unknown user", and no address is shown outside the owner/manager
picker. A failing user directory leaves the names `null` instead of failing the
list. Calendar and category names are single line (control characters, line and
paragraph separators and direction controls are a 422); descriptions keep line
breaks and tabs. A name with no slug-able characters falls back to the slug
`calendar` or `category`, with `-2`, `-3` ... on a clash.
