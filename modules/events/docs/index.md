# Events

[Installation, settings, screens and API](../README.md). The
[approved design](../../../docs/superpowers/specs/2026-11-17-events-module-design.md)
sets out the later calendar engine and integrations. [Writing a plugin](extensions.md) covers
sources, event types and UI from another package.

## Access

One calendar policy supplies every caller's rights. `M` is `events.manage`,
`V` is `events.view`, `E` is `events.edit`, and `P` is `events.publish`.
`Pr`, `In` and `Pu` mean private, internal and public calendars. The table
assumes three calendars with the same owner and, for share holders, the same
unexpired share on each. A dash means none. “Edit” is calendar metadata;
“Write” and “Publish” are the event rights: Write creates and edits drafts, and Publish approves, schedules, unpublishes and changes a locked event.

| Principal | Permissions | View | Edit | Delete / share | Write | Publish |
| --- | --- | --- | --- | --- | --- | --- |
| Manager | M | Pr In Pu | Pr In Pu | Pr In Pu | Pr In Pu | — |
| Manager | M P | Pr In Pu | Pr In Pu | Pr In Pu | Pr In Pu | Pr In Pu |
| Owner | V | Pr In Pu | Pr In Pu | Pr In Pu | Pr In Pu | — |
| Owner | V P | Pr In Pu | Pr In Pu | Pr In Pu | Pr In Pu | Pr In Pu |
| Owner who lost V | none | Pu | — | — | — | — |
| View-share holder | V E | Pr In Pu | — | — | In Pu | — |
| View-share holder who lost V | none | Pu | — | — | — | — |
| Edit-share holder | V | Pr In Pu | Pr In Pu | — | Pr In Pu | — |
| Other editor | V E | In Pu | — | — | In Pu | — |
| Other editor | V E P | In Pu | — | — | In Pu | In Pu |
| Other viewer | V | In Pu | — | — | — | — |
| Other user without V | none | Pu | — | — | — | — |
| Anonymous | none | Pu | — | — | — | — |

These are policy rights; HTTP routes add their permission gates. All calendar
API requests need `events.view`; creation also needs `events.edit`. Calendar
pages need `events.view`, and Categories needs both `events.view` and
`events.manage`; category API
writes need both view and manage. The framework sharing API additionally needs
`sharing.share`. No anonymous event API or page ships yet.

Calendar responses carry `owner_name`, a string or `null`. Every viewer of a
calendar sees its owner's display name when the owner is an active member of the
bound organisation with a display name. Anyone else (not a member, inactive,
unknown, or an owner whose only label is an email address) is `null` and shown
as "Unknown user"; no email address or part of one is ever shown outside the
owner/manager-only picker. If the user directory or the membership store
fails, even with a failed SQL query, lists, reads and writes still succeed with
`null` owner names (the lookup runs in a savepoint); the share
picker and an ownership transfer still fail rather than guess (no directory at
all is a 503).

A calendar name and every category name are single line: control characters,
line and paragraph separators and text-direction controls are rejected with a
422. A description keeps line breaks and tabs and rejects other control
characters and text-direction controls. A name with no slug-able characters
falls back to the slug `calendar-2` (`calendar`, `c`, `api`, `feed` and `sitemap` are public
route segments: no calendar or event slug may be one, and derivation skips them) or
`category` (then `-2`, `-3`, ...).

An owner or edit share can write drafts without `events.edit`; that permission
only adds event writing on internal and public calendars. It never grants
editing another owner's calendar metadata. A view share cannot delete, share,
change visibility or edit metadata. Owners and managers alone change
visibility, share, trash and restore; only managers transfer ownership. The
new owner must be an active member of the bound tenant (`owner_not_allowed`
otherwise). An expired share grants nothing. Trashed calendars are excluded
from ordinary reads, including managers' reads. Calendar slugs remain reserved
while in trash, so restore cannot collide.

The picker is a search, not a directory listing: with a directory installed,
fewer than three trimmed characters returns no candidates. It excludes inactive
users, the calendar's owner and other tenants' members. The route is rate-limited per signed-in
user. A user whose display label contains an at-sign (any variant: @, U+FE6B,
U+FF20) is never matched by name, only by the exact full address, and is shown
masked otherwise. Any other user matches by display-name text or the exact full
address; partial email matches alone return nobody. It scans at most 100
directory matches and returns at most 20 candidates. Email addresses, including
address-bearing display labels, remain masked unless the trimmed query equals
the full address. Names, addresses and the query are compared NFC-normalised
and case-insensitively, so a query typed with decomposed accents matches; a
directory provider that does not return a user for such a query is outside the
module's control. The UI displays that response verbatim.

## Events and texts

An event belongs to one calendar and has a type (`event`), a status
(`draft`, `in_review`, `published`) and a text per content locale
(`content_locales`, the first is the default and always required). A text has a
title, a slug unique per tenant and locale, a summary, a rich-text description
and search fields. An absent slug is derived from the title. Renaming a slug
records a redirect in that locale only; claiming a slug removes a redirect to it.
`calendar_id`, `parent_id` and `type` cannot change after creation. A sub-event
has a parent in the same calendar (one level only); a series cannot have
sub-events and a sub-event cannot repeat.

The description is rich text. The server cleans it when it is saved
(`content/richtext.py`, an allow-list of `p br strong em u s a ul ol li blockquote
h2 h3`, links only `http`, `https` or `mailto`) and returns the cleaned HTML.
The editor never trusts input either: HTML it loads, pastes or emits goes
through its own copy of the allow-list (`ui/utils/richtext.ts`), and a read-only
description is shown in a sandboxed frame. Nothing outside the allow-list is
ever inserted as markup.

## Times and all-day

The API takes the event's local wall clock plus an IANA `timezone`, never UTC:
`times: {all_day, timezone, start, end}` with `YYYY-MM-DDTHH:MM` for a timed
event and `YYYY-MM-DD` for an all-day one, whose `end` is the inclusive last
day. Responses carry the UTC `starts_at` and `ends_at` and the same local form
(`start_local`, `end_local`). A time in a daylight-saving gap is refused
(`invalid_local_time`); a time that occurs twice uses its first occurrence. An
all-day event is stored from local midnight of its first day to local midnight
after its last. A timed event lasts up to 366 days, a recurring event or a moved
occurrence up to 31.

A refusal that belongs to one input carries its dotted request path as `field`
beside `detail` and `code`: `times.start` or `times.end` for `invalid_local_time`
(an override's own are `start` and `end`), `times.end` for `end_before_start` and
`duration_too_long`, `publish_at_local` for an approve time in a gap,
`texts.<locale>.slug` for `slug_taken` and `texts.<locale>.description` for
`description_too_long`. Every other refusal keeps exactly `detail` and `code`.
The console shows the message at that input; the list's date filters are the
console user's days in their own time zone, sent as instants, and a new event
starts on today's date on its calendar's clock.

## Recurrence

The rule is an RRULE string, stored normalised. Allowed: `FREQ` of `DAILY`,
`WEEKLY`, `MONTHLY` or `YEARLY` (sub-daily rules are `rrule_frequency_refused`),
`INTERVAL` 1 to 99, `COUNT` 1 to 730 or `UNTIL` (not both), and the parts
`BYDAY`, `BYMONTHDAY`, `BYMONTH`, `BYSETPOS` and `WKST`. `BYHOUR`, `BYMINUTE`,
`BYSECOND`, `BYWEEKNO`, `BYYEARDAY` and anything else are `invalid_rrule`. The start
must be the first occurrence of its rule (`start_not_in_rule`). Occurrences
keep their wall-clock time across daylight-saving changes; an instance in a gap
moves forward by the gap. Expansion is lazy and always bounded by an `until`:
never expand a rule without one. The editor covers daily, weekly (weekdays),
monthly (day of month, or the nth or last weekday) and yearly, ending never,
after N times or on a date. Any other stored rule (including an interval or count
outside those limits) is shown read-only as text and sent back unchanged unless
the user edits it as text or replaces it with a repeat from the form.

## Overrides

One override exists per (event, original start). `skipped` removes the
occurrence, `cancelled` keeps it marked cancelled, `moved` changes only the start
and end (on the event's clock). An override needs a recurring event
(`not_recurring`) and a real occurrence (`not_an_occurrence`). Changing a series'
rule, start, timezone or all-day flag first runs `POST /recurrence/preview`: if
overrides would no longer match, the save needs `drop_orphaned_overrides`
(409 `overrides_orphaned` otherwise), and the editor asks for that confirmation.

## The occurrences read

`GET /occurrences` and `sm_events.contracts.occurrences` answer every range
question within fixed bounds: a range of at most 366 days (`range_too_long`,
`invalid_range`), at most 2,000 items, sorted by (start, end, source, key), with
`truncated` set when there are more. Series are expanded lazily and merged, so
the work does not depend on how many instances the range holds. An occurrence
key is the event id, plus the original start for a series instance (a moved
one keeps its original key). A viewer without write rights never receives a
draft, an event in review or a scheduled one.

## The calendar

`/admin/events/` (`events.view`) draws the occurrences read as month, week,
day and list. The toolbar has Today, Previous, Next, the range title and the
view switcher; the sidebar filters by calendar (the legend: swatch, name and
visibility in words), category and, once a second type exists, type. The state
is mirrored in the query string (`view`, `date`, `tz`, repeated `calendar`,
`category`, `type`) and read back on load; "every calendar" is the default and
is not written. The grid fetches the visible range plus seven days on each
side (never more than 366 days), keeps the last eight answers, and a navigation
that stays inside a fetched range makes no request. A new fetch aborts the one
in flight. A truncated answer (2,000 items) shows a persistent notice.

**State is never colour alone.** A draft has a dashed border and the word
"Draft", an event in review a dotted border and "In review", a cancelled
occurrence a struck-through title and "Cancelled" (in month cells the word is
there for screen readers). An occurrence the viewer may not change on a
calendar they can write to shows a lock whose name gives the reason.

**Create.** Click a slot (a 60-minute event) or drag-select in the time grid,
or click or select days in the month and all-day row (an all-day event). The
quick-create dialog takes the title, the calendar (writable ones only), all-day,
and start and end in that calendar's zone; **Create** saves a draft, **More
options** opens the editor prefilled.

**Move and resize.** Drag an event to another slot or day, or drag its lower
edge to change its end. The grid shows the drop at once; the write runs in the
background (the event is `aria-busy` and cannot be dragged meanwhile), and any
refusal puts it back. A drag between the all-day row and the time grid is
refused: change all-day in the editor. Cancelled occurrences, cancelled events
and occurrences the viewer may not edit (a published event without
`events.publish`, a calendar they only view) cannot be dragged, and the detail
popover says why.

**Keyboard.** Events are focusable; Enter or Space opens the detail popover,
Escape closes it and returns focus to the event. **Move…** in the popover opens
the Move dialog (start, end, and for a series "Only this occurrence" or "All
occurrences"), which is the keyboard path for move and resize and goes through
the same write as a drag. Dialogs trap focus and give it back to the event.

**The grid time zone.** "Calendar time" is the zone of the one calendar shown,
or the tenant's default when several are; "My time" is the browser's. The
toggle shows both zone names, and says so when they are the same. All-day
occurrences are dates and ignore the toggle. FullCalendar reports instants in
the grid's zone; `ui/calendar/time/zones.ts` (Temporal) converts them into the
**event's** own wall clock (`YYYY-MM-DDTHH:MM`), which is what the API takes,
never UTC and never the grid's zone. A move keeps the duration, a resize
changes only the end. A drop on the second occurrence of a repeated autumn hour
is refused client-side (`repeated_local_time`), because the server reads a wall
clock as the first.

**What a drag does to a series.** The grid asks "Only this occurrence" or "All
occurrences". One writes a `moved` override for that occurrence (a second
write replaces it). All shifts the master's start and end by the wall-clock
difference; the rule text is never rewritten, so moving a `BYDAY` series to
another weekday is a 422 `start_not_in_rule` ("open the editor"), and a shift
that orphans overrides asks for the confirmation the editor asks for.

"All occurrences" leaves an occurrence that has its own exception where the
exception put it: only the master moves. A change another session made to a field
the drag does not write (a venue, say) does not make the drag stale; the write
sends the fetched revision and keeps that field. The browser console logs the
expected 409 and 422 answers as "Failed to load resource" lines; they are the
network's report, not a script error.

**A click near a clock jump.** On the day the clocks jump forward (02:00 to 03:00
in Vienna) the grid still draws the slots in the skipped hour, and FullCalendar
moves a click there forward, so the callback cannot say which slot was meant.
Quick create therefore follows one rule: when the proposed start, on the
calendar's clock, lies in the window after a jump (from where it ends up to one
jump's length later: 03:00 to 03:59 in Vienna, 02:30 to 02:59 for Lord Howe's
half-hour jump), it says "On this day the clock jumps from 02:00 to 03:00
(Europe/Vienna). Check the start time." The note is true for a click on the
skipped slots and on the real ones alike. A drag or resize onto a skipped hour is
refused (`invalid_local_time`), because there the intended wall time is rebuilt
from the old position and the delta.

An occurrence carries no revision, so a write first reads the event and stops as
stale, sending nothing, if what the grid showed no longer matches; otherwise it
sends the fetched revision.

| Answer | What the user sees |
| --- | --- |
| 200 / 201 | "Moved" or "Resized"; the range is refetched |
| stale (client or 409 `stale`) | "This event changed since it was loaded…"; the grid refreshes |
| 409 `overrides_orphaned` | the orphaned-overrides confirm; confirming resends with `drop_orphaned_overrides` |
| 403 `publish_required` / `forbidden` | the server's message |
| 404 | "This event no longer exists" |
| 422 `start_not_in_rule` | the weekday message, with a link to the editor |
| other 422, network, 5xx | the error text |

## Embedding `Calendar`

`import { Calendar } from '@simple-module-py/events'`. Props (types are
exported alongside): `fetchOccurrences(query, signal)` (aware-UTC half-open
range, calendar, category and type filters, locale), `calendars`
(`id`, `name`, `color`, `visibility`, `default_timezone`, `can_write_events`),
`categories`, `types` (the filter shows with two or more), `defaultTimezone`,
`initialState` (read once), `onStateChange`, `refreshToken` (bump to refetch),
`editing` and `slots`. No FullCalendar type appears in the props.

`editing` is a callback surface: `canCreate`, `onCreate(slot)`, `onChange(change)`
(resolve `true` to keep the optimistic position, `false` to revert), `onMove`
and `pendingKeys`. Leave it out and the calendar is read-only (the public
site). `slots` are `EventChip`, `Detail`, `ToolbarStart` and `ToolbarEnd`; the
first two receive `Default`, so a slot can wrap or fall back for occurrences it
does not know. The grid is a lazy chunk (`React.lazy`): a consumer that never
renders one pays for the shell only, and the console's Calendars and Events
screens never request it.

## FullCalendar

The grid is FullCalendar 7 (`@fullcalendar/react` `^7.1.5`, as every module ranges its
third-party packages; `package-lock.json` holds the resolved version), MIT packages only: the allow-list
is `@fullcalendar/react`, `@fullcalendar/core` and `@full-ui/headless-calendar`,
and `boundaries.test.ts` fails on any other `@fullcalendar/*` or `@full-ui/*`
package, on a name containing `scheduler`, `resource`, `timeline` or `premium`,
and on an allow-listed lockfile entry that is not MIT. It also fails on any
import of `@fullcalendar/` outside `sm_events/ui/calendar/adapter/`. The
adapter loads the day-grid, time-grid, list and **interaction** plugins (without
interaction nothing can be dragged, resized or selected) and the `classic`
theme, whose variables `adapter/calendar.css` maps onto the console's tokens, so
light and dark follow it. Replacing the library means rewriting `adapter/` to the
`GridProps`/`GridHandle` contract in `ui/calendar/types.ts`. Production CSP
needs nothing special: the library uses no `eval` and inserts no script.

## Workflow

Every transition is a `POST` with `expected_revision`; a state it cannot leave is
409 `invalid_transition`.

| Action | From | To | Needs |
| --- | --- | --- | --- |
| `submit` | draft | in review | write |
| `withdraw` | in review | draft | write |
| `approve` (optional `publish_at_local`) | draft, in review | published, or scheduled for a future time | write and publish |
| `reject` (`note` required) | in review | draft | write and publish |
| `unschedule` | scheduled | same status, no time | write and publish |
| `unpublish` | published | draft | write and publish |

*Scheduled* is a draft or event in review with `publish_at`. A published or
scheduled event is **locked**: changing, trashing, restoring or overriding it
needs write and publish (403 `publish_required` otherwise). A caller who cannot
see an event gets 404. The editor mirrors that rule (`workflowActions`): an
action is offered only when the caller can write the event and, for every action
but submit and withdraw, also publish. It shows a read-only reason instead of a
form for a locked event.

## Revisions and conflicts

Every write, the beat's included, increments `revision` and records a revision
with its action, actor (`null` for the beat) and, for a rejection or dropped
overrides, a note. The newest 100 are kept. History is read-only. Its rows carry
`actor_name`, resolved in one batch with the owner-name rules above (an actor who
is not a named member is `null`), and `system: true` for the beat's rows, which
have no actor at all; the console shows the name, else "Unknown user", else
"System". A write's first
statement is a compare-and-set on `expected_revision`: a stale one is 409
`stale` and writes nothing. The editor then loads the newer event, shows the
fields that differ and offers "Load their version" or "Save mine over theirs",
an explicit click that resends with the new revision. It never retries by itself.

## Bus events

`sm_events.contracts.events` has nine events, for events that are or were published, and only
for a write that commits: `EventPublished`, `EventRescheduled` (a time, timezone, all-day or
rule change, or a moved occurrence), `EventCancelled`, `EventDeleted`, `EventUnpublished`
(unpublish, or a cancelled schedule), `EventReinstated`, `OccurrenceSkipped`, `EventRestored` and
`EventUpdated` (the names of the fields that changed). A write a specific event covers emits only
that one. Each is published in process after the commit and, when the host has the `background_tasks`
outbox and the event has durable handlers, also written to the outbox in the writer's own
transaction and delivered at least once by a worker (retries, backoff and a dead-letter state are
the framework's). There is no ordering between two events of one `event_id`; re-read the event.
The scheduled publish announces `EventPublished` through the worker's bus, so it reaches durable
subscribers; in-process subscribers see web-process changes only. See
[extensions.md](extensions.md#bus-events).

## Extensions

Another package can put its own dates on a calendar (a source), add an event type with its own
data (`extra`) and contribute UI, from `events_extensions.py` and `events-extensions.ts`. An admin
enables a source per calendar in the **Sources** dialog. [extensions.md](extensions.md) is the guide;
records ships `records:dates` as its optional `events` extra.

## Scheduled publishing (needs beat)

`events.publish_due` runs every 60 seconds on the `events` queue (`expires`
55 s) and publishes up to 200 due events per tenant, each tenant under its own
session. It does not re-check the scheduler's right: the `scheduled` revision
records who scheduled it. A host without Celery beat never publishes on a
schedule. `make worker` serves the `events` queue.

## Tenancy

Every table carries `MultiTenantMixin`. `sm_events.core.tenancy` copies
newsletter's fail-closed guard and is included in the helper parity checks.
An unbound ORM statement raises `TenantUnbound`; deliberate cross-tenant reads
use `all_tenants`, and Core/text statements still pin `tenant_id` explicitly.

Every admin router binds `bind_admin` before opening a session. Single-tenant
hosts bind `default` when nothing upstream resolved a tenant; multi-tenant
hosts use the framework's `request.state.tenant_id` and refuse a missing one
with 403 `tenant_required`. An already resolved tenant always wins. A module
never chooses a user's `tenant_id` or reads a tenant header itself.

The framework sharing router does not bind events' tenant on a single-tenant
host. The registered `events.calendar` loader uses request-context middleware
to apply the same resolver and pin the tenant in the lookup without binding
the context. Its execution option bypasses only events' unbound-query guard. It
never turns a foreign calendar UUID into a readable resource. The sharing
policy requires `events.view` even if a caller still owns or holds a share on
a private calendar.

## Data model

One host migration creates seven tables; visibility, statuses and kinds are
VARCHAR values checked with Python constants, not database enums. Every
unique tenant index leads with `tenant_id`. Calendars, events and categories
have UUID primary keys; the remaining tables have big-int keys.

| Table | Behavior starts |
| --- | --- |
| `events_calendar` | PR 1: ownership, metadata, visibility, sharing, soft deletion |
| `events_category` | PR 1: names by content locale, immutable slug, optional colour |
| `events_event` | PR 2: schedule, workflow, recurrence, location and event metadata |
| `events_event_text` | PR 2: locale-specific text and slug |
| `events_occurrence_override` | PR 2: skipped, cancelled or moved occurrences |
| `events_revision` | PR 2: event snapshots |
| `events_redirect` | PR 2: locale-scoped event slug redirects |

The demo host's revision `b8e1d0783868` follows `541bfbe29a28` and creates all
seven tables; `f3c0b2daeaf2` follows it and adds the nullable
`events_revision.note` (a reject note, or the overrides a series change
dropped). Migrations belong to the host. The `events` branch label is a
named target in a shared history, not a way to roll back this module alone.
Calendar metadata is
last-write-wins; event writes use `expected_revision`.

## Status

PR 4 adds the public surface: pages, ICS feeds, JSON-LD and a sitemap, with calendar slug
redirects (see [Public pages](public.md) and [Operating](operations.md)); private feed links are in [Private feed links](feeds.md). PR 3 adds the calendar: the `Calendar` component and the console grid at
`/admin/events/`. PR 2 adds events: texts, recurrence and overrides, the
occurrences read, the workflow, scheduled publishing, the API, and the Events list and editor. PR 1
provided calendars, categories, settings, the tenancy and access policy and all
seven tables. Browser QA and the shipping pipeline follow branch verification.
Later delivery remains:

| PR | Delivers |
| --- | --- |
| 2 | Events and texts, recurrence and overrides, occurrences read, workflow, API, list and editor |
| 3 | Calendar component and console grid: views, create, drag, resize, timezone |
| 4 (this release) | Public pages, calendar slug redirects, public ICS, JSON-LD and sitemap |
| 5 | Private feed tokens and `.ics` upload |
| 6 | Extension registry, plugin guide and records date-field source |
| 7 (this release) | Pagebuilder blocks and newsletter card |
| 8 | Reminders |
| 9 | Registration through records |
| 10 | External ICS subscriptions |

## Feeds and import

[Private feed links](feeds.md) and [Importing an .ics file](import.md).

## Blocks and cards

[Pagebuilder blocks and the card contract](blocks.md): the `UpcomingEvents` and `EventsCalendar` blocks,
their anonymous routes and bounds, and `sm_events.contracts.cards` for newsletter.
