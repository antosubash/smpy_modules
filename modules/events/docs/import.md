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
| Components, nesting, time zones | 20,000, 3 deep, 100 | `IMPORT_MAX_COMPONENTS`, `IMPORT_MAX_DEPTH`, `IMPORT_MAX_TIMEZONES` |
| Lines, line length | 1,000,000, 65,536 | `IMPORT_MAX_LINES`, `IMPORT_MAX_LINE` |
| Properties per event, parameters per property | 500, 20 | `IMPORT_MAX_PROPERTIES`, `IMPORT_MAX_PARAMS` |
| Bytes per event | 262,144 | `IMPORT_MAX_EVENT_BYTES` |
| `EXDATE` values / overrides per series | 1,000 / 730 | `IMPORT_MAX_EXDATES`, `IMPORT_MAX_OVERRIDES` |
| Instances expanded to match an exception | 3,000 | `IMPORT_EXPAND_CAP` |
| Parse time, parse attempts | 20 s, 3 | `IMPORT_PARSE_SECONDS`, `IMPORT_PARSE_ATTEMPTS` |
| Unfinished imports per user / per tenant | 5 / 25 | `IMPORT_ACTIVE_MAX`, `IMPORT_ACTIVE_TENANT_MAX` |
| Kept for | 24 hours | `IMPORT_TTL` |

Over a limit the whole file is refused with a readable reason (`too_many_events`, `ics_invalid`,
`too_complex`); one event over a limit is skipped and the rest import.

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

In a real Celery worker (`events.run_import`) there is no app, so **no** account, membership or
permission check runs per slice. It relies on the grants stored at apply time (the importer's
permissions then) and per-item checks against the database: the calendar's share and owner, trash
and published-lock. A role, membership or account removed mid-import therefore applies only from the
next import; the worker finishes the import with the stored grants (at most 24 h, the import's
lifetime). `importer_gone` and the per-slice narrowing exist in `runner._Slice.narrow` and work only
when a caller passes an `importer` (`launch.importer_check`, which uses the offline principal); the
inline (eager) path in `launch.launch` does not pass one today, so that path is not narrowed either.
Only the person who uploaded an import can see, apply or discard it.
