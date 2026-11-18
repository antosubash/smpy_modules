# simple_module_events

Owned calendars with private, internal or public visibility, calendar sharing,
multilingual categories, and events for SimpleModule hosts. Events have texts in
each content language, one-off, all-day and recurring schedules, overrides for
single occurrences, a review and publishing workflow, and a bounded occurrences
read, a console calendar, and (from PR 4) a public site: pages, ICS feeds, JSON-LD and a
sitemap. This is **PR 4 of 10**. See the [guide](docs/index.md), [public pages](docs/public.md), [operating](docs/operations.md) and the
[approved design](../../docs/superpowers/specs/2026-11-17-events-module-design.md).

## Install

Add `simple_module_events` to the consuming host's dependencies:

```bash
pip install simple_module_events
```

The framework's `settings`, `sharing` and `background_tasks` modules must also be
installed (`background_tasks` runs scheduled publishing). The
module is discovered through its `simple_module` entry point. In this repo,
the workspace dependency and host wiring are already present:

```bash
make install
make migrate
```

For a different host, autogenerate and inspect its own migration:

```bash
make migration msg="add events"
```

Set `branch_labels = ("events",)` on its first events revision, inspect that
it creates the seven `events_*` tables without dropping existing data, then
run `make migrate`. Migrations belong to the host, never to this wheel. The
label is a named target in the host's shared history; downgrading
`events@base` does not remove only events' tables.

## Usage

Open `/admin/events/calendars` to create a calendar, edit its metadata, change
visibility, share it, or move it to Trash and restore it. Calendar slugs may
be renamed in this release. Creation needs `events.edit` and makes the caller
the owner. Only `events.manage` holders see **Transfer ownership**; they pick
an active member of the current tenant. The user picker searches after three
characters and shows the server's masked email; an exact address search may
return that address in full.

Open `/admin/events/categories` with `events.view` and `events.manage` to enter category names in each configured
content language. The first language is required. Categories have an optional
colour and a slug fixed at creation. Deletion leaves events uncategorised.

`/admin/events/` (`events.view`) is the calendar: month, week, day and list
views over every calendar the caller can read, with a filter per calendar and
category, a toggle between the calendar's time zone and the browser's, and
live state in the URL (`?view=week&date=2026-03-25&tz=mine&calendar=<id>`). A
caller who may write events can click or drag-select a slot to create a draft,
drag an event to another time or day, drag its edge to change the end, or open
it and choose **Move…**, the keyboard path for both. A drag moves one
occurrence of a series or the whole series (a prompt asks) and never rewrites
the repeat rule. See the guide's [The calendar](docs/index.md#the-calendar).

Open `/admin/events/list` (`events.view`) for the Events list: filter by
calendar, status (draft, in review, published, scheduled), category, date range
and title, page through the results, and move an event to Trash or restore it.
**New event** opens the editor on a calendar the caller may write in. The editor
(`/admin/events/edit/{id}`) has the texts per content language with a rich-text
description, times on the event's own clock (timezone and all-day), place,
category, sub-events, the repeat rule with a preview of the next occurrences and
skip, cancel and move for single ones, the workflow bar (submit, withdraw,
approve now or later, reject with a note, cancel a schedule, unpublish) and the
revision history. A save that meets a newer revision shows what changed and asks
whether to load theirs or save yours over it. A published or scheduled event is
read-only for a caller without `events.publish`, with the reason on screen.
Scheduled publishing needs the Celery beat (see the guide's
[Scheduled publishing](docs/index.md#scheduled-publishing-needs-beat)).

### API

All paths below start with `/api/events`. Writes use the framework's session
CSRF token (`X-CSRF-Token`); module errors use `{"detail","code"}`. FastAPI
request-validation errors retain their ordinary 422 shape. Unknown or
inaccessible calendars return the same 404. Calendars use last-write-wins
metadata forms and have no `expected_revision`; every event write quotes it
(409 `stale`).

| Method and path | Action / permission |
| --- | --- |
| `GET /calendars?trashed=false` | List readable calendars; `events.view` |
| `POST /calendars` | Create; `events.view` and `events.edit` |
| `GET /calendars/{id}` | Read through the calendar policy; `events.view` |
| `PATCH /calendars/{id}` | Edit metadata; owner, edit share or manager |
| `PUT /calendars/{id}/visibility` | Set private/internal/public; owner or manager |
| `PUT /calendars/{id}/owner` | Transfer with `{owner_id}`; manager, active tenant member only |
| `DELETE /calendars/{id}` | Move to trash; owner or manager |
| `POST /calendars/{id}/restore` | Restore; owner or manager |
| `GET /calendars/{id}/share-candidates?q=…` | Find active members; owner or manager, three characters minimum |
| `GET /categories` | List; `events.view` |
| `POST /categories` | Create; `events.view` and `events.manage` |
| `PATCH /categories/{id}` | Replace names or colour; `events.view` and `events.manage` |
| `DELETE /categories/{id}` | Delete; `events.view` and `events.manage` |
| `GET /events` | List with `calendar`, `status`, `category`, `from`, `to`, `q`, `trashed`, `locale`, `page`, `page_size`; `events.view` |
| `POST /events` | Create with `calendar_id`, `times`, `texts`; write right on the calendar |
| `GET /events/{id}` | Read with texts, overrides, sub-events and the caller's rights; `events.view` |
| `PATCH /events/{id}` | Edit with `expected_revision`; write right, plus `events.publish` when the event is published or scheduled |
| `DELETE /events/{id}?expected_revision=` | Move to trash; same right as PATCH |
| `POST /events/{id}/restore` | Restore with `expected_revision`; same right |
| `POST /events/{id}/{submit,withdraw,approve,reject,unschedule,unpublish}` | Workflow, each with `expected_revision` (see the guide's table) |
| `GET /events/{id}/revisions`, `/revisions/{number}` | History, newest first; write right |
| `POST /events/{id}/overrides` | Skip, cancel or move one occurrence; `DELETE /events/{id}/overrides/{override_id}?expected_revision=` restores it |
| `POST /recurrence/preview` | The next occurrences of a schedule and the overrides it would orphan |
| `GET /occurrences?start=&end=` | The bounded read for a range (at most 366 days, 2,000 items) |

Calendar responses carry `owner_name` (a string or `null`). An owner is named
only when they are an active member of the bound organisation with a display
name; anyone else, including an owner whose only label is an email address, is
`null` and shown as "Unknown user". No address or part of one is shown outside
the owner/manager-only picker. If the user directory or the membership store fails
(a failed query included), lists, reads and writes still succeed with `null`
owner names; the share picker and an ownership transfer still fail
rather than guess (no directory at all is a 503).

A calendar name and every category name are single line: control characters,
line and paragraph separators and text-direction controls are rejected with a
422. A description keeps line breaks and tabs and rejects other control
characters and text-direction controls. A name with no slug-able characters
gets the slug `calendar-2` (`calendar` is a public route segment, so no calendar
takes it) or `category` (then `-2`, `-3`, ...).

Every calendar API route also needs `events.view`. Grants, lists and revokes
use the framework's `/api/sharing/shares` with
`resource_type="events.calendar"`, the calendar UUID as `resource_id`, a user
`subject_id` and role `view` or `edit`. The framework additionally requires
`sharing.share`. The picker requires the owner or a manager; an edit share does
not admit it. Calendar and category lists return at most 500 rows each.

### Settings

Configure **Events** on the Settings screen or with
`scripts/set_setting.py`. Both fields are SYSTEM-scope and DB-backed; no
`SM_EVENTS_*` environment variables are read.

| Field | Default | Applies |
| --- | --- | --- |
| `default_timezone` | `UTC` | New calendars; unknown stored names fall back to UTC with a warning |
| `content_locales` | `["en"]` | The languages of category names, event texts and event slugs; restart required |

### Permissions and access

`events.view` admits console readers; owners and share holders also need it.
`private` calendars are readable by their owner and shares; `internal` and
`public` calendars are readable by signed-in members with `events.view`.
Only owners, edit shares and managers edit calendar metadata. Only owners
and managers change visibility, share, trash or restore a calendar.
`events.manage` bypasses calendar visibility within the bound tenant and
manages categories and ownership. `events.publish`, combined with write access to the
calendar, approves, schedules and unpublishes events and is needed to change
an event that is published or scheduled. See the guide's [access table](docs/index.md#access).

No anonymous page or API ships yet. A public calendar's visibility prepares it
for later public, published-event reads; it exposes no anonymous screen today.

## Extensions

A second package can add dates to a calendar (a source such as records' `records:dates`), add an event type
with its own validated `extra`, and contribute chips, details, editor and settings sections and toolbar
items. An admin turns a source on per calendar (Calendars, **Sources**). A plugin call runs on its own
database connection with a time budget and validated, bounded output, and a failing source is reported in the
calendar instead of failing it. See [the plugin guide](docs/extensions.md). Events publishes nine bus
events, also durably through the `background_tasks` outbox. Status: PR 6 of 10 (extensions).

## Public pages

Anonymous visitors get a public calendar's published events under `public_prefix` (default
`/events`, restart-only), with `/{locale}` prefixes:

| Route | Serves |
| --- | --- |
| `/events/` | Upcoming list and a read-only calendar tab |
| `/events/c/{calendar}` | One public calendar |
| `/events/{slug}` (`?date=`) | An event, or one occurrence of a series |
| `/events/{slug}.ics`, `/events/calendar.ics`, `/events/c/{calendar}.ics` | Event file and subscription feeds |
| `/events/sitemap.xml` | Every public, indexable event |

Everything else (drafts, internal and private calendars, trash, other tenants) answers one
identical 404. See [Public pages](docs/public.md).
