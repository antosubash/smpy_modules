# Events

[Installation, settings, screens and API](../README.md). The
[approved design](../../../docs/superpowers/specs/2026-11-17-events-module-design.md)
sets out the later calendar engine and integrations.

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
`sharing.share`. No anonymous event API or page ships in PR 1.

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
falls back to the slug `calendar` or `category` (then `-2`, `-3`, ...).

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
after N times or on a date; any other stored rule is a raw text field the server
validates.

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
see an event gets 404. The editor offers only the actions the API's flags
allow, and shows a read-only reason instead of a form for a locked event.

## Revisions and conflicts

Every write, the beat's included, increments `revision` and records a revision
with its action, actor (`null` for the beat) and, for a rejection or dropped
overrides, a note. The newest 100 are kept. History is read-only. A write's first
statement is a compare-and-set on `expected_revision`: a stale one is 409
`stale` and writes nothing. The editor then loads the newer event, shows the
fields that differ and offers "Load their version" or "Save mine over theirs",
an explicit click that resends with the new revision. It never retries by itself.

## Bus events

`sm_events.contracts.events`: `EventPublished`, `EventRescheduled` (a time,
timezone, all-day or rule change of a published event, or a moved occurrence),
`EventCancelled` and `EventDeleted`, for events that are or were published, and
only after the write commits. Reinstating, unpublishing and skipping emit
nothing yet. A scheduled publish runs in a worker with no in-process bus, so it
emits nothing either.

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
seven tables. Migrations belong to the host. The `events` branch label is a
named target in a shared history, not a way to roll back this module alone.
Calendar metadata is
last-write-wins; event writes use `expected_revision`.

## Status

PR 2 adds events: texts, recurrence and overrides, the occurrences read, the
workflow, scheduled publishing, the API, and the Events list and editor. PR 1
provided calendars, categories, settings, the tenancy and access policy and all
seven tables. Browser QA and the shipping pipeline follow branch verification.
Later delivery remains:

| PR | Delivers |
| --- | --- |
| 2 (this release) | Events and texts, recurrence and overrides, occurrences read, workflow, API, list and editor |
| 3 | Calendar component and console grid: views, create, drag, resize, timezone |
| 4 | Public pages, calendar slug redirects, public ICS, JSON-LD and sitemap |
| 5 | Private feed tokens and `.ics` upload |
| 6 | Extension registry, plugin guide and records date-field source |
| 7 | Pagebuilder blocks and newsletter card |
| 8 | Reminders |
| 9 | Registration through records |
| 10 | External ICS subscriptions |
