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
“Write” and “Publish” describe the event rights PR 2 will consume.

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

The demo host's revision `b8e1d0783868` follows `c7a41e9d2b60` and creates all
seven tables. Migrations belong to the host. The `events` branch label is a
named target in a shared history, not a way to roll back this module alone.
No background task or public contract ships in PR 1. Calendar metadata is
last-write-wins; event writes will use `expected_revision` from PR 2.

## Status

PR 1 provides the Calendars and Categories screens and API, settings, the
tenancy/access policy and all seven tables. Browser QA and the shipping
pipeline follow branch verification. Later delivery remains:

| PR | Delivers |
| --- | --- |
| 2 | Events and texts, recurrence and overrides, occurrences read, workflow, API, list and editor |
| 3 | Calendar component and console grid: views, create, drag, resize, timezone |
| 4 | Public pages, calendar slug redirects, public ICS, JSON-LD and sitemap |
| 5 | Private feed tokens and `.ics` upload |
| 6 | Extension registry, plugin guide and records date-field source |
| 7 | Pagebuilder blocks and newsletter card |
| 8 | Reminders |
| 9 | Registration through records |
| 10 | External ICS subscriptions |
