# Importing an .ics file

`Events > Import events` (`/admin/events/import`) takes a calendar file, shows a preview, and
imports it into one calendar. It needs `events.view` and `events.manage`, and write rights on the
chosen calendar. Everything is created as a **draft**; "Import and publish" is offered only with
`events.publish`, and a published event is updated only by someone who may publish.

## Limits

| Limit | Value | Constant |
| --- | --- | --- |
| File size (setting, default / floor / ceiling) | 5 MiB / 64 KiB / 20 MiB | `IMPORT_DEFAULT_BYTES`, `IMPORT_MIN_BYTES`, `IMPORT_BODY_CEILING` |
| Events per file | 5,000 | `IMPORT_MAX_EVENTS` |
| Components / nesting / time zones | 20,000 / 3 deep / 100 | `IMPORT_MAX_COMPONENTS`, `IMPORT_MAX_DEPTH`, `IMPORT_MAX_TIMEZONES` |
| Lines / line length | 1,000,000 / 65,536 | `IMPORT_MAX_LINES`, `IMPORT_MAX_LINE` |
| Properties per event / parameters per property | 500 / 20 | `IMPORT_MAX_PROPERTIES`, `IMPORT_MAX_PARAMS` |
| Bytes per event | 262,144 | `IMPORT_MAX_EVENT_BYTES` |
| Attendees counted per event | 200 | `IMPORT_MAX_ATTENDEES` |
| Description characters | 20,000 | `IMPORT_DESCRIPTION_MAX` |
| `EXDATE` values / overrides per series | 1,000 / 730 | `IMPORT_MAX_EXDATES`, `IMPORT_MAX_OVERRIDES` |
| Instances expanded to match an exception | 3,000 | `IMPORT_EXPAND_CAP` |
| Parse time / parse attempts | 20 s / 3 | `IMPORT_PARSE_SECONDS`, `IMPORT_PARSE_ATTEMPTS` |
| Unfinished imports per user / per tenant | 5 / 25 | `IMPORT_ACTIVE_MAX`, `IMPORT_ACTIVE_TENANT_MAX` |
| Kept for | 24 hours | `IMPORT_TTL` |
| Rights captured at apply stay valid for | 1 hour | `IMPORT_GRANTS_TTL` |

**A limit over one event skips that event** and the rest import: more than 500 properties
(`too_many_properties`), more than 20 parameters on a property (`too_many_parameters`), more than
262,144 bytes (`event_too_large`), more than 200 attendees (`too_many_attendees`) or more than
1,000 `EXDATE` values (`too_many_overrides`). The preview names the event by its place in the file
(`#17`) and its title when it had one before the limit tripped; the rest of such an event is counted
and discarded unread, so skipping is as cheap as scanning. **A limit over the whole file fails the
import** with the limit's own code: `file_too_large`, `too_many_lines`, `line_too_long`,
`too_many_events`, `too_many_components`, `too_many_timezones`, `too_deep`, and
`component_too_large` (a time zone or other non-event component with more than 500 properties).
`ics_invalid` is only a file that is not a well-formed calendar (this includes a NUL or other control
character in it), and `too_complex` only a parse that ran out of its time budget or attempts.

The upload itself is stored in the database (`events_import.source`), not in a directory: up to
20 MiB a row and at most 25 unfinished imports per tenant, but only an import that has not been
parsed yet holds it, so the worst case is 25 x 20 MiB = 500 MiB per tenant (125 MiB at the 5 MiB
default). It is cleared the moment the file is staged, or when the import fails, and the row itself
is deleted after 24 hours.

## How a file is read

`feeds/importing/scan.py` is the only parser of an upload: one bounded pass over bytes (unfolded
before decoding, so a fold inside a character is fine). No library parses an upload. `VTIMEZONE`
and `VALARM` are counted and dropped unread, so a file cannot make the server evaluate them.

## What is and is not imported

Imported: title, description (plain text, links kept if `http(s)` without credentials), place,
start and end, all-day, `STATUS:CANCELLED`, one `RRULE`, `EXDATE`, and `RECURRENCE-ID` children
that move or cancel one occurrence. Not imported: organisers, attendees and alarms (counted and
shown as "Not imported"; **attendee addresses are never stored**), attachments, other `X-`
properties, `RANGE=THISANDFUTURE`.

- **Time zones.** An IANA name or a Windows name (through icalendar's table) is read; any other
  `TZID` skips the event (`unknown_timezone`). A floating time is read in the calendar's zone
  (`floating_time`). A repeating event written in UTC **stays UTC** (`kept_utc`), so its
  clock time follows UTC, not the calendar's zone, across clock changes.
- **Recurrence.** Daily, weekly, monthly and yearly rules PR 2's editor accepts. Anything else
  skips the event (`unsupported_rule`). A bad `EXDATE` value is noted (`exdate_ignored`); the
  good ones still apply; a date-valued one on a timed series skips that day's occurrence.
- **Private items.** `CLASS:PRIVATE` or `CONFIDENTIAL` is imported as a draft and **never**
  written into a published event (`private_kept`, `kept_draft_private`).

## Idempotency

An event is identified by its `UID` in the calendar. Importing the same file again creates
nothing; an event that changed in the file is updated, one that did not is `unchanged`. An event
edited in the console since the import is not overwritten (`changed_since_preview`). The highest
`SEQUENCE` wins among duplicates.

## Rights are re-checked

On a host that runs tasks inline (eager), every slice asks the user directory who the importer is
now (`launch.importer_check`, the offline principal): a deactivated or removed importer ends the
import as `importer_gone`, and lost permissions narrow what the remaining items may do. A real
Celery worker (`events.run_import`) has no app, so it cannot ask. It relies on the rights captured
when the import was applied, which are valid for one hour (`IMPORT_GRANTS_TTL`; stored as
`rights_until`): a slice that starts later writes nothing and ends the import `rights_expired`
(upload again). Within the hour it also checks, per item, the calendar's share and owner, trash and
the published lock. A framework gap (no way to resolve a user's permissions outside a request) is why
the worker cannot do more. One hour is above the slowest measured run: about 0.2 s an item on
SQLite, so 5,000 items take about 17 minutes.
Only the person who uploaded an import can see, apply or discard it.
