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

## Images

The public pages allow images from their own origin only (`img-src 'self'`), so an event's image is
emitted (page, JSON-LD, `og:image`, lists, blocks, the card contract) only when it is a path on the site
(`/media/...`) or an address on the site's own origin; an off-site address is simply not emitted. The
editor accepts a path or an address, and refuses a *new* off-site value with `image_off_site`
(`422`, `field: image`); an image already stored is kept as it is.

## Occurrences

An occurrence's address is `{slug}?date=YYYY-MM-DD`, the local date of its original start in the
event's timezone. A **moved** occurrence keeps its original date in the address and shows its new
time with "Rescheduled from ...". A **cancelled** one is shown with a banner (cancelled is not
deleted, and stays indexable). A **skipped** one, a date that is not an occurrence and a malformed
date are the 404, as is `?date=` on a one-off.

## What the public JSON names

No event's id appears in a page's props or in `/api/occurrences`: `event_id` and `original_start`
are null and an item's `key` is `<slug>` (a one-off) or `<slug>:<stamp>` (an instance of a series).
The id of a *public* calendar or category does appear (`calendar_id`, the filter lists): the grid
passes them back as `?calendar=` and `?category=`, and they name only rows the public may see.

## Query parameters

On the pages, `?category=<slug>` that names an unknown, hidden or malformed category is the module
404 (the plan's Ruling 5: "`?category=<slug>` naming any other category is the 404"); the page has
no `?calendar=` (a calendar is the path, `/c/<slug>`), so it is ignored like any other unknown
parameter. On `/api/occurrences`, `calendar` and `category` ids that are not public or not known
match nothing and answer 200 with no items, the same either way (Ruling 32: "`calendar` ids that are
not public silently dropped"); a missing or malformed parameter (`start`, `end`, an id that is not a
UUID) is `422 {"detail", "code": "invalid_query"}`, never an HTML page.

## Left as they are

Sub-events also appear as ordinary items in the lists, next to their parent. A moved date keeps its
original date in its address (`?date=` is the date it was scheduled for) and shows the new time.

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
Matching server metadata and `PublicHead` tags share Inertia keys (`data-inertia` and `head-key`), so hydration keeps one copy; the client replaces `<title>` separately. A keyed server tag must also be rendered by the client or hydration removes it. The endpoint resolves the head values once, writes them and sends them as the page's `head` prop, which `PublicHead` renders without recomputing.
An event with no summary, description or SEO text gets a generated one-line description (date and
time, place, calendar) in the page's language. An event that exists in a single language still
names it, with `x-default`. A series' bare page lists its next ten occurrences in JSON-LD. Tick **No index** on a text to add
`noindex,nofollow` and leave it out of the sitemap. The sitemap never lists `?date=` addresses.
