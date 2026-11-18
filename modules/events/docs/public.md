# Public pages, feeds and SEO

What an anonymous visitor sees under the public prefix (default `/events`, the `public_prefix`
setting). A **public** calendar's **published** events are on this surface and nothing else: not a
draft, an event in review or a scheduled one, not an event of an internal or private calendar, not a
trashed event or calendar, not another organisation's. A signed-in visitor, a manager included,
gets exactly the anonymous answer.

## Addresses

| Address | Serves |
| --- | --- |
| `/events/` | The upcoming list (20 to a page, grouped by month) with a **Calendar** tab (`?view=calendar`): a read-only month, week, day and list grid |
| `/events/c/{calendar}` | One public calendar, with its description and a subscribe box |
| `/events/{slug}` | An event page. `?date=2026-07-06` selects one occurrence of a series |
| `/events/{slug}.ics` | One event (its whole series and every override) for "Add to calendar" |
| `/events/calendar.ics`, `/events/c/{calendar}.ics` | Subscription feeds |
| `/events/sitemap.xml` | Every public, indexable event, in every language |
| `/events/api/occurrences` | What the grid reads (default language only) |

The default content language is served at the bare prefix, every other under its tag
(`/de/events/...`). `/en/events/x` (the default language's redundant prefix) redirects to
`/events/x`. An event page exists **only in the languages that have a text**; the lists show an
event without a text in the visitor's language in the default one, marked with `lang`, and link to
that language's page.

`calendar`, `c`, `api`, `feed` and `sitemap` are reserved: no calendar or event can have them as a
slug (a 422 `slug_reserved`; derived slugs skip them).

## Occurrences

An occurrence's address is `{slug}?date=YYYY-MM-DD`, the local date of its original start in the
event's timezone. A **moved** occurrence keeps its original date in the address and shows its new
time with "Rescheduled from ...". A **cancelled** one is shown with a banner (cancelled is not
deleted, and stays indexable). A **skipped** one, a date that is not an occurrence and a malformed
date are the 404, as is `?date=` on a one-off.

## One 404

A slug that never existed, a draft, an internal calendar's event, a trashed row, another
organisation's row, a text in another language, a skipped date and a request that resolved no
organisation all answer the **same** 404 (same status, body, `Cache-Control: no-store`, no `ETag`),
so it cannot be used to find out what exists. Where pagebuilder is mounted it is the site's own 404;
otherwise events' own page with the next three events.

## Renamed slugs

Renaming an event's slug in a language, or a calendar's slug, records a redirect: the old address
answers `301` to the new one (the `.ics` too, so a subscription survives). A redirect is followed
only when its target is public now; otherwise it is the 404, never a 301 that would publish a draft's
address. A slug someone claims later wins over an old redirect.

## Subscribing

Every list page has a **Subscribe** box: the `https` feed address, a `webcal:` link that opens
Outlook, Apple Calendar and most phones, and a copy button. For Google Calendar choose *Other
calendars > From URL* and paste the `https` address. The feed refreshes hourly
(`REFRESH-INTERVAL`, `X-PUBLISHED-TTL`).

A feed holds the events that meet *30 days back to 366 days ahead*, at most 1,000 events and 5,000
components. A series is emitted as `RRULE` plus `EXDATE` (skipped), and one component per moved or
cancelled occurrence (`RECURRENCE-ID`, `STATUS:CANCELLED`), in the event's own time zone with a
`VTIMEZONE`, so it stays at 10:00 across a daylight-saving change. A series whose overrides would not
fit is left out of a calendar feed whole, never emitted without its `EXDATE`s, and the response
carries `X-Events-Truncated: 1`. The single-event file has no window.

## Search engines

Each event page carries `<title>`, description, canonical (the `?date=` address for an occurrence),
`hreflang` for the languages it exists in plus `x-default`, Open Graph tags and `Event` JSON-LD
(`eventStatus` including cancelled and rescheduled, `eventAttendanceMode`, `location`, `organizer`).
A series' bare page lists its next ten occurrences in JSON-LD. Tick **No index** on a text to add
`noindex,nofollow` and leave it out of the sitemap. The sitemap never lists `?date=` addresses.
