# simple_module_events

Owned calendars with private, internal or public visibility, calendar sharing
and multilingual categories for SimpleModule hosts. This is **PR 1 of 10**:
the calendar and category API and console screens are available. Events,
recurrence, calendar grids, public pages and ICS feeds arrive in later PRs.
The seven event tables are already created for PRs 1 and 2. See the
[guide](docs/index.md) and the [approved design](../../docs/superpowers/specs/2026-11-17-events-module-design.md).

## Install

Add `simple_module_events` to the consuming host's dependencies:

```bash
pip install simple_module_events
```

The framework's `settings` and `sharing` modules must also be installed. The
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
`/admin/events/` redirects to Calendars until the calendar grid arrives.

### API

All paths below start with `/api/events`. Writes use the framework's session
CSRF token (`X-CSRF-Token`); module errors use `{"detail","code"}`. FastAPI
request-validation errors retain their ordinary 422 shape. Unknown or
inaccessible calendars return the same 404. Calendars use last-write-wins
metadata forms and have no `expected_revision`.

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

Calendar responses carry `owner_name` (a string or `null`). An owner is named
only when they are an active member of the bound organisation with a display
name; anyone else, including an owner whose only label is an email address, is
`null` and shown as "Unknown user". No address or part of one is shown outside
the owner/manager-only picker. If the user directory fails, lists still load,
with `null` owner names; the share picker and an ownership transfer still fail
rather than guess (no directory at all is a 503).

A calendar name and every category name are single line: control characters,
line and paragraph separators and text-direction controls are rejected with a
422. A description keeps line breaks and tabs and rejects other control
characters and text-direction controls. A name with no slug-able characters
gets the slug `calendar` or `category` (then `-2`, `-3`, ...).

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
| `content_locales` | `["en"]` | Category names; restart required |

### Permissions and access

`events.view` admits console readers; owners and share holders also need it.
`private` calendars are readable by their owner and shares; `internal` and
`public` calendars are readable by signed-in members with `events.view`.
Only owners, edit shares and managers edit calendar metadata. Only owners
and managers change visibility, share, trash or restore a calendar.
`events.manage` bypasses calendar visibility within the bound tenant and
manages categories and ownership. `events.publish` is reserved for event
publishing in PR 2, combined with calendar write access; published event
changes will be live. See the guide's [access table](docs/index.md#access).

There are no public routes in PR 1. A public calendar's visibility prepares it
for later public, published-event reads; it exposes no anonymous screen today.
