# Events PR 4: public pages, public ICS feeds, JSON-LD, sitemap. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An anonymous visitor can browse a tenant's public calendars at `{public_prefix}/` (an upcoming list and a read-only calendar grid), open one public calendar, read an event page (a series occurrence chosen with `?date=`, sub-events listed on the parent), download one event or subscribe to a calendar as `.ics`, and find every published public event through the sitemap and `Event` JSON-LD. Renamed event and calendar slugs redirect. Nothing that is not a published event on a public calendar of the bound tenant reaches this surface.

**Architecture:** One gate. `core/access/public.py` defines the anonymous principal and two selects built on PR 1's `POLICY` and PR 2's `visible_events(…, include_unpublished=False)`; every public read (pages, list, API, feeds, sitemap, redirects, JSON-LD, the 404's suggestions) starts from them and never takes a viewer from the request. `content/public_read.py` holds the slug, redirect, sub-event, alternate and category lookups on top of that gate. `web/endpoints/public/` mirrors news' public package (one router per content locale, fixed paths before the catch-all, mounted and exempted in `on_startup` from the hydrated `public_prefix`), with its own tenant binder, cache policy (records/images' shareable-tenant rule, news' per-viewer `Vary`), head injection and JSON-LD. `feeds/` writes ICS with `icalendar`: it reads event rows with their rules and overrides directly (through the same gate, never through the occurrences read) and emits RRULE + EXDATE + RECURRENCE-ID with TZID and VTIMEZONE. The pages are Inertia screens (`Events/PublicIndex`, `Events/PublicEvent`, `Events/PublicNotFound`); the grid is PR 3's `Calendar` in read-only mode, fed by an anonymous occurrences endpoint.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy async, `icalendar` 7.x (BSD-2-Clause), `zoneinfo`, pytest (SQLite, plus Postgres opt-in through `tests/pg_support.py`), React 19 + Inertia, `@simple-module-py/ui`, PR 3's `Calendar` (FullCalendar 7 MIT packages, lazy chunk), vitest (happy-dom), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`. This plan covers Delivery row 4 and draws on "Anti-goals", "The core idea", "Access", "Tenancy", "Screens and routes", "ICS" and "Settings". Precedent plans: `docs/superpowers/plans/2026-11-17-events-pr2-events.md` (its Rulings define the occurrences read, texts per locale with slugs and redirects, the workflow and all-day storage) and `docs/superpowers/plans/2026-11-17-events-pr3-calendar.md` (the `Calendar` component, Rulings 4–8). The pattern to mirror is news' public side: `modules/news/news/web/endpoints/public/` (every file), `modules/news/news/core/boot.py`, `NewsModule.on_startup`/`register_public_routes`, `modules/news/news/integrations/pagebuilder.py` (`render_not_found`), and its tests `modules/news/tests/web/test_public_*.py`, `test_sitemap.py`. The cache rule to mirror is `modules/images/sm_images/web/serving/cache.py` (`_shared_tenant`) and `modules/records/sm_records/web/endpoints/api/_public_cache.py`.

## Depends on PRs 2 and 3

Before Task 1 the branch is rebased onto the finished `feat/events-pr3-calendar` (which is rebased onto `feat/events-pr2-events`). The implementer of batch A **re-checks every name below against the real code first** and corrects this plan's references in the task text (never by renaming PR 2/3 code) wherever they differ. Stop and report if a *behaviour*, not only a name, differs, in particular if `visible_events(…, include_unpublished=False)` can return anything but published, untrashed events of untrashed public calendars for the anonymous principal.

| Kind | Symbol this plan relies on |
|---|---|
| Access (PR 1) | `sm_events.core.access.POLICY`, `visible_calendars(who, action=ACTION_VIEW) -> Select[Calendar]` (trash excluded), `ACTION_VIEW`; anonymous rule: `user_id is None` → `public` only |
| Access (PR 2) | `sm_events.core.access.events.visible_events(who, *, include_unpublished: bool) -> Select[Event]` (trash excluded, calendar visible) |
| Read (PR 2) | `sm_events.calendar.occurrences.occurrences(db, *, tenant_id, viewer, start, end, filters, default_locale) -> OccurrencePage`; `sm_events.calendar.occurrence.Occurrence` (fields of PR 2 Ruling 14), `OccurrencePage{items, truncated}`; `sm_events.calendar.sources.OccurrenceFilters(calendar_ids, category_ids, types, locale, include_unpublished)`; `InvalidRange` codes `invalid_range`/`range_too_long` |
| Contract (PR 2) | `sm_events.contracts.occurrences.occurrences(session, *, tenant_id, viewer=None, …)`, `sm_events.contracts.mounted(app)` |
| Time (PR 2) | `sm_events.calendar.times`: `Span`, `to_local(span, *, all_day, timezone) -> (str, str)`, `all_day_dates(span, timezone) -> (date, date)`, `localize(naive, tz)` |
| Recurrence (PR 2) | `sm_events.calendar.rrule.parse(text, *, all_day, timezone) -> Rule` (`text`, `freq`, `count`, `until`); `sm_events.calendar.expand.instances(…)`, `is_occurrence(original_start, *, rule, span, all_day, timezone) -> bool` |
| Content (PR 2) | `sm_events.content.richtext.clean(raw) -> str`, `ALLOWED_TAGS`; `sm_events.content.texts.texts_of(db, event_ids) -> {event_id: {locale: EventText}}`, `apply_texts(…)`; `sm_events.content.redirects.record_rename`, `release_slug`; `sm_events.calendar.slugs.free_text_slug`, `free_slug`, `slug_write`, `slugify` |
| Models | `Event` (`uid`, `calendar_id`, `parent_id`, `status`, `cancelled`, `all_day`, `starts_at`, `ends_at`, `timezone`, `rrule`, `recurrence_until`, `attendance_mode`, `venue_name`, `address`, `online_url`, `latitude`, `longitude`, `category_id`, `organiser`, `image`, `registration_url`, `revision`, `published_at`, `publish_at`, `updated_at`, `is_deleted`); `EventText` (`event_id`, `locale`, `slug`, `title`, `summary`, `description`, `seo_title`, `seo_description`, `noindex`; no `updated_at`); `OccurrenceOverride` (`event_id`, `original_start`, `kind`, `starts_at`, `ends_at`, `note`); `Redirect` (`events_redirect`); `Calendar` (`slug`, `name`, `color`, `description`, `visibility`, `default_timezone`, `updated_at`); `Category` (`slug`, `names: dict[str, str]`, `color`); `EventStatus`, `Visibility`, the override kinds (`skipped`/`cancelled`/`moved`), `ATTENDANCE_MODES` |
| Calendars (PR 1) | `sm_events.calendar.calendars.create_calendar`, `update_calendar(db, cal, data)` (the slug rename path), `CALENDAR_SLUG_CONSTRAINT` |
| Settings / tz | `EventsSettings.content_locales` (default first), `default_timezone`; `sm_events.core.timezones.effective(name) -> str` |
| Tenancy | `sm_events.core.tenancy`: `resolve_public`, `note_tenant_source`, `tenant_from_request`, `tenant_scope`, `bind_public`, `mode_of`, `TenancyMode`, `DEFAULT_TENANT`, `tenant_header`, `all_tenants`; `_mode.request_mode`. **Parity-checked: this PR edits none of these files.** |
| Constants | `PACKAGE`, `MODULE_NAME = "Events"`, `ROUTE_PREFIX_API`, `VIEW_PREFIX`, `MAX_RANGE_DAYS`, `MAX_OCCURRENCES`, `SOURCE_EVENTS`, `UID_SUFFIX`, `EDITOR_URL`, `TEXT_SLUG_MAX`, `SLUG_MAX`, `NOT_FOUND_DETAIL` |
| TS (PR 3) | `@simple-module-py/events` / `sm_events/index.ts`: `Calendar`, `CalendarProps` (`fetchOccurrences`, `calendars: CalendarInfo[]`, `categories?: FilterOption[]`, `defaultTimezone`, `initialState?`, `onStateChange?`, `editing?` absent = read-only, `slots?`), `CalendarInfo`, `FilterOption`, `OccurrenceFetcher`, `OccurrenceQuery`, `CalendarState`; `ui/utils/types-events.ts` `Occurrence`, `OccurrencePage`; `ui/calendar/time/*` (`browserTimeZone`, `timeText`, `localTimeText`); `ui/calendar/test-support/FakeGrid.tsx` and the `vi.mock('…/adapter/FullCalendarGrid')` pattern |
| TS (PR 1) | `ui/utils/i18n.ts` (`useT`, `keys`), `ui/page-tests/test-dom.tsx`, `ui/page-tests/support.tsx` (`stubFetch`) |
| Tests | `tests/support/access.py` (`principal`, `seed_calendars` with `P`/`I`/`U`), `tests/support/calendars.py` (`seed_event(db, calendar, **fields)`), `tests/support/app.py`, the `unbound_tenant` marker, `tests/pg_support.py`; e2e `tests/e2e/helpers.ts` (`login`, `moduleCsrfHeader`, `uniqueSlug`) |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**The gate**
1. **The public surface has no viewer** (spec, Access and anti-goal 1). `core/access/public.py` defines `ANONYMOUS = ResourcePrincipal(user_id=None, permissions=frozenset())`, `public_calendars()` (`visible_calendars(ANONYMOUS)`) and `public_events()` (`visible_events(ANONYMOUS, include_unpublished=False)`). Every public read starts from one of these two selects or from the occurrences read called with `viewer=ANONYMOUS` and `include_unpublished=False`. A signed-in visitor, a manager included, gets exactly the anonymous answer; no public handler reads `request.state.user` except to choose cache headers. A test greps `web/endpoints/public/` and `feeds/` for `request.state.user`, `principal_from` and `ResourcePrincipal(` and allows only `_cache.py`.
2. **One answer for "not here".** A draft, in-review or scheduled event, an event of an internal or private calendar, a trashed event, an event of a trashed calendar, another tenant's row, a slug that never existed, a text in another locale, a skipped occurrence and a request that resolved no tenant all give the same 404: same status, same props, `Cache-Control: no-store`, no `ETag`, tenant `Vary` where the tenant is request-specific. `If-None-Match` is evaluated only after the row has passed the gate, so a guessed tag on a hidden URL is a 404, never a 304.
3. **Redirects pass the gate too.** An `events_redirect` or `events_calendar_redirect` hit answers 301 only when its target is publicly visible (and, for an event, has a text in that locale); otherwise the 404 of Ruling 2. A 301 to a draft's current slug would publish the slug.
4. ★ **A sub-event is shown on its own merits.** A published child of a public calendar has its page even when its parent is not public; its page then shows no "Part of" link and no parent title anywhere (page, JSON-LD, ICS `RELATED-TO`). The parent's page lists only its publicly visible children (≤ `SUB_EVENTS_MAX = 200`, by start).
5. ★ **Public category filter** lists only categories used by at least one publicly visible event. `?category=<slug>` naming any other category is the 404.

**Addresses**
6. **Settings** (spec): `public_prefix: str = Field(default="/events", json_schema_extra=_RESTART)`, read in `on_startup` from `app.state.sm_events.settings` and normalised by `core/public_prefix.effective(value) -> str`: leading `/`, no trailing `/`, only `[a-z0-9-/]`, not `/`, not starting with `/api`, `/admin` or `ROUTE_PREFIX_API`/`VIEW_PREFIX`. An invalid stored value logs an error and uses `/events`. Also `public_cache_seconds: int = 300` (runtime; `0` sends `no-store` everywhere) — see Ruling 20.
7. **Per-locale routers, as news** (`news/web/endpoints/public/__init__.py`): the default content locale serves at `{prefix}/…`, every other at `/{locale}{prefix}/…`, one router each, and `/{default}{prefix}/{rest}` 301s to `{prefix}/{rest}`. The sitemap and `/api/occurrences` exist only on the default prefix. Content locales come from events' own `content_locales` setting (restart-only), through `core/locales.py` (`supported()`, `default()`, `is_default()`, `path_prefix(locale)`); create it only if PR 2 has no equivalent.
8. **Route order inside one locale router** (load-bearing, as news' docstring says): `GET|HEAD /sitemap.xml` (default only), `/api/occurrences` (default only), `/calendar.ics`, `/c/{calendar}.ics`, `/c/{calendar}`, `/` (and the exact bare prefix), `/{slug}.ics`, `/{slug}` last.
9. ★ **Reserved slugs.** `RESERVED_SLUGS = ("api", "c", "calendar", "feed", "sitemap")`: an event text slug or a calendar slug equal to one of them is refused with 422 `slug_reserved`, and derivation skips them (`calendar` → `calendar-2`). `calendar` would otherwise lose its `.ics` to the feed, `feed` is PR 5's, the rest keep room. Existing rows: none yet (PR 2 is unreleased), so no data migration.
10. ★ **An occurrence's address is `{prefix}/{slug}?date=YYYY-MM-DD`**, the local date of its `original_start` in the event's timezone (all-day: its first date). Rules are at most daily (PR 2 Ruling 5), so one local date names at most one occurrence. A moved occurrence keeps its original date in the URL and shows its new time with "Rescheduled from …". A cancelled one is 200 with the cancelled banner. A skipped one, a date that is not an occurrence, an unparsable date and `?date=` on a one-off are the 404 of Ruling 2. The bare series URL shows the series (rule summary, next `NEXT_OCCURRENCES = 10` from now, each linking to its `?date=`).
11. **Canonical and hreflang.** Canonical is the absolute URL of what is shown: the bare slug URL, or the `?date=` URL for an occurrence. `hreflang` lists the event's other publicly reachable locales (a text with a slug), plus `x-default` for the default locale's, and nothing on a monolingual site (news' `alternates`). `noindex` on the text gives `<meta name="robots" content="noindex,nofollow">` and keeps the event out of the sitemap.
12. **Language.** An event page exists only in the locales that have a text (spec). Lists, the grid and the 404's suggestions show an event without a text in the visitor's locale in the default locale's text, else its first text by locale, marked `lang` (`<span lang>`), and link to the page in *that* locale.
13. **Calendar slug redirects** (PR 1 ruling deferred them here): a new table `events_calendar_redirect` (`id` big PK, `tenant_id`, `old_slug` str(`SLUG_MAX`), `calendar_id` UUID FK `events_calendar.id` `ON DELETE CASCADE`, indexed, `created_at`; unique `uq_events_calendar_redirect (tenant_id, old_slug)`). `update_calendar` writes one on a slug change; creating or renaming a calendar to a slug deletes any redirect with that `old_slug`, so the holder wins and renaming back removes it (PR 2 Ruling 21's rule for events). `/c/{old}` and `/c/{old}.ics` 301 to the new address, so a subscription survives a rename.

**Pages**
14. ★ **`/events/` shows the upcoming list first**, with a "Calendar" tab (`?view=calendar`) that mounts the read-only grid. The list is server-rendered props (crawlable, works without the FullCalendar chunk); the grid is client-only. The list covers `[now, now + MAX_RANGE_DAYS)`, no past events, `PAGE_SIZE = 20` per page over the capped read (≤ 2,000 items, so at most 100 pages), grouped by month of the event's local start; `?page=` is read leniently (news' `_paging.page_param`), and a page past the end is the 404. Times in lists are the event's own local times with its timezone named when it differs from the calendar's.
15. **`/events/c/{calendar}`** is the same screen narrowed to one public calendar, with its name, description, colour and a Subscribe block (`https` feed URL, a `webcal:` link and a copy button).
16. ★ **A cancelled event's page** stays 200 and indexable, with a banner ("This event has been cancelled") above the title, `eventStatus: EventCancelled`, and the registration button hidden. A cancelled occurrence shows the same banner for that date only.
17. **Event page content:** title, summary, date and time in the event's timezone with a client-side hint in the visitor's timezone when it differs ("Your time: …", PR 3's `localTimeText`), all-day as dates only, the rule summary for a series, place (in person: venue, address, a plain map link only when latitude/longitude exist; online: the link; hybrid: both), organiser text, category, calendar, image (`http`/`https` only, as stored), description, sub-events, registration button (`registration_url`), "Add to calendar" (`{slug}.ics`) and a language switch.
18. ★ **The description is rendered without `dangerouslySetInnerHTML`.** No public page in this repo injects a sanitised HTML body: news and pagebuilder render block documents through Puck and use `dangerouslySetInnerHTML` only for JSON-LD (`news/pages/PublicArticle.tsx:167`, `pagebuilder/pages/PublicPage.tsx:114`). So the server re-cleans the stored HTML (`richtext.clean`, PR 2 Ruling 22: clean at save *and* at render) and converts it to a node tree (`content/richtext_tree.py`), and `ui/public/RichText.tsx` maps each allow-listed tag to a React element and drops anything else to its children. JSON-LD follows the established pattern: `dangerouslySetInnerHTML` with the `</`-escaped string, plus the same tags injected server-side.
19. **Not-found page.** Where pagebuilder is mounted, the site's own 404 through `pagebuilder.contracts.public.render_not_found` (as news, `integrations/pagebuilder.py`), with the tenant the binder resolved (`None` renders no layout). Otherwise events' own `Events/PublicNotFound` page: a message, a link to the index and up to `NOT_FOUND_SUGGESTIONS = 3` next public occurrences, the same for every cause and never derived from the requested slug. Status 404, `no-store`. ★ No site frame (header/footer) around the *other* public pages: pagebuilder exposes none to another module (its contracts give the 404 only), and news' public pages render standalone too (open point 1).

**Caching**
20. ★ **Lifetimes**, all derived from `public_cache_seconds` (default 300): event pages `public, max-age=S, stale-while-revalidate=60`; index, calendar pages and `/api/occurrences` `max-age=min(S, 60)`; feeds and the single-event `.ics` `max-age=S`; sitemap `max-age=S`. `S = 0` sends `no-store` and no `ETag`.
21. **Who may share a cached answer** (records #196, pagebuilder/news #192, images' `_shared_tenant`): `public` only when no tenant was picked by anything request-specific (`not tenant_from_request(request)`), the request-level mode is `SINGLE` and the tenant is `DEFAULT_TENANT`. Otherwise `private` with the same `max-age`, plus the tenant header (`tenant_header(app)`) in `Vary` when there is one. A signed-in visitor's page is `private, no-store` with no `ETag` (news' `SIGNED_IN_CACHE_CONTROL`). Pages also `Vary: X-Inertia, Cookie, Accept-Language`, and every response that names the origin adds `Host` while the origin is guessed (news #355). Errors are `no-store` (records' `error_headers`), through a `PublicErrorRoute` route class on every public router.
22. **Validators.** Pages: a weak ETag over `(event.id, event.revision, calendar.id, calendar.updated_at, the visible children's (id, revision), locale, date, variant, viewer_key)`; the `variant` and `viewer_key` are news' (`_urls.etag_for`, `viewer_key`) so HTML and Inertia JSON never share a tag. Feeds, sitemap and the API: a weak ETag over the response body (deterministic because `DTSTAMP` is `updated_at`, Ruling 27). A 304 carries `ETag`, `Cache-Control` and `Vary`, never a CSP header (news #322).

**ICS**
23. **Library** (spec): `icalendar>=7,<8  # floor: 7.x is the first major checked for RRULE/EXDATE/RECURRENCE-ID/VTIMEZONE round-trip (Task 7)`. `recurring-ical-events` (LGPL) is never added; `scripts/check_rules.py` or a module test fails on it in `uv.lock`'s events dependency closure.
24. **Feeds read rows, not occurrences** (spec). `feeds/select.py` reads `public_events()` masters with their overrides and texts directly. Plugin-source occurrences (spec: plain instances, `UID <source>:<key>`) arrive with PR 6's registry; in PR 4 `SOURCES` holds only the built-in source and nothing is added (open point 3).
25. ★ **Feed window and caps.** A calendar feed holds masters that intersect `[now − 30 days, now + 366 days)` (one-off: `ends_at > lo AND starts_at < hi`; series: `starts_at < hi AND (recurrence_until IS NULL OR recurrence_until > lo)`), ordered by `starts_at`, at most `FEED_MAX_EVENTS = 1000` masters and `FEED_MAX_COMPONENTS = 5000` VEVENTs. A series is always emitted with **all** its overrides (an EXDATE outside the window still hides an instance a client expands); if a series would cross the component cap, it and every later master are dropped, never a series without its EXDATEs. A truncated feed sets `X-Events-Truncated: 1` and logs once per request at INFO. The single-event `.ics` has no window: the whole series and all overrides.
26. **Series encoding.** Master: `DTSTART;TZID=<tz>` and `DTEND;TZID=<tz>` in local wall time (UTC events: `…Z`, no VTIMEZONE), `RRULE` from the stored normalised text (timed `UNTIL` already UTC `Z`; all-day `UNTIL` a `DATE`), `EXDATE;TZID=<tz>` for each `skipped` override (local original start). A `moved` override is a VEVENT with the same `UID`, `RECURRENCE-ID;TZID=<tz>` (local original start), its new `DTSTART`/`DTEND`. A `cancelled` override is a VEVENT with `RECURRENCE-ID`, the original times and `STATUS:CANCELLED`. `event.cancelled` gives `STATUS:CANCELLED` on the master; otherwise `STATUS:CONFIRMED`. All-day events use `VALUE=DATE` for `DTSTART`, `DTEND` (exclusive), `EXDATE` and `RECURRENCE-ID`, with no TZID. One `VTIMEZONE` per distinct timed `TZID` in the file, generated by the library (Task 7 records the exact call).
27. **Properties.** `UID` = `events_event.uid` verbatim; `SEQUENCE` = `revision` (monotone; overrides carry the master's); `DTSTAMP` and `LAST-MODIFIED` = `updated_at` in UTC; `CREATED` = `created_at`; `SUMMARY` and `DESCRIPTION` from the locale's text with Ruling 12's fallback; `DESCRIPTION` is plain text from the re-cleaned HTML (`feeds/plaintext.py`: block tags → line breaks, list items → `- `, links → `text (href)`), then `Organiser: …` and the online link on their own lines; `LOCATION` = venue and address joined by `, ` (online-only: the online URL); `GEO` when both coordinates exist; `URL` = the public event URL; `CATEGORIES` = the category's name in the feed's locale; a public child whose parent is public gets `RELATED-TO;RELTYPE=PARENT:<parent uid>`. No `ORGANIZER` (it needs a `mailto:` address and makes clients treat the event as an invitation), no `ATTENDEE`, no `VALARM`, no `METHOD`. Calendar: `PRODID:-//simple-module//events//EN`, `VERSION:2.0`, `CALSCALE:GREGORIAN`, `X-WR-CALNAME` (calendar name, or the site's events title for `calendar.ics`), `X-WR-TIMEZONE` (the calendar's `default_timezone`, or the settings default), `REFRESH-INTERVAL;VALUE=DURATION:PT1H` and `X-PUBLISHED-TTL:PT1H`. Escaping and line folding are the library's. Components are ordered by `(starts_at, uid, recurrence-id)` so the body is deterministic.
28. **Responses.** `Content-Type: text/calendar; charset=utf-8`. The single event adds `Content-Disposition: attachment; filename="<slug>.ics"`; feeds send none (subscriptions open inline). Feeds exist per locale (`/de/events/calendar.ics` carries German texts with the fallback).

**SEO and limits**
29. **`<head>`** as news (`_head.py`): server-injected `<title>`, description (`seo_description`, else `summary`, else the first 160 characters of the plain-text description), `og:*` (`og:type` `website` for the index/calendar pages, `article` is wrong for an event so event pages use `website` too), canonical, hreflang, robots, the feed autodiscovery link (`type="text/calendar"`) on index and calendar pages, and `<html lang>` rewritten (`set_html_lang`). The same tags through Inertia's `<Head>` for client navigations.
30. **`Event` JSON-LD** on the event page: `@context`, `@type: Event`, `name`, `description`, `startDate`/`endDate` (timed: ISO with the event-timezone offset; all-day: dates, `endDate` the inclusive last day), `eventStatus` (`EventCancelled` for a cancelled event or occurrence; `EventRescheduled` with `previousStartDate` for a moved occurrence; else `EventScheduled`), `eventAttendanceMode` (`Offline`/`Online`/`MixedEventAttendanceMode`), `location` (`Place{name, address: PostalAddress{streetAddress}, geo}`, `VirtualLocation{url}`, both as a list for hybrid), `organizer` (`Organization{name}` from the organiser text), `image`, `url` (canonical), `inLanguage`. ★ The bare page of a series emits a list of one `Event` per next occurrence (≤ `NEXT_OCCURRENCES`); a `?date=` page emits that one. Serialised with `json.dumps` then `</` → `<\/` and `<!--` → `<!--` (news' `_safe_json_ld`) in a `type="application/ld+json"` script. That type is not executable, so it needs no nonce under the 0.0.43 CSP; no executable `<script>` is added by this PR.
31. ★ **Sitemap** at `{prefix}/sitemap.xml` only: the index of every locale, each public calendar page in every locale, then every publicly visible event text with a slug and `noindex` false at its locale's address with `<lastmod>` = the event's `updated_at` date, newest first, at most `SITEMAP_MAX_URLS = 10_000` URLs (under the protocol's 50,000). `?date=` URLs are never listed.
32. **Public occurrences endpoint** `GET {prefix}/api/occurrences?start=&end=&calendar=…&category=…&locale=` (default prefix only): the occurrences read with `viewer=ANONYMOUS`, `include_unpublished=False`, the read's own bounds (366 days, 2,000, `truncated`), `calendar` ids that are not public silently dropped (PR 2 Ruling 15), each item's `url` replaced by its public address (Rulings 10, 12), `editable` false, `event_status` `"published"`. `type` is accepted and ignored. Errors are the `{"detail","code"}` envelope with `no-store`.
33. **Rate limits** for anonymous traffic, added in `on_startup` to the live `app.state.rate_limit_rules` registry (the framework stores the `RateLimitRegistry` there; Task 6 proves the middleware reads it per request, otherwise it registers the default-prefix rules in `register_rate_limits` and files an upstream issue): every `.ics` and `sitemap.xml` under every locale prefix `RateLimitRule("60/minute", key="ip", methods={"GET","HEAD"})` (`FEED_RATE`), `/api/occurrences` `"120/minute"` (`PUBLIC_API_RATE`). Pages ride the host's `rate_limit_public`.
34. **Auth exemption** (news' `exempt_public_routes`): for each locale, `add_prefix(f"{localised}/", methods={"GET","HEAD"})` and `add_exact(localised, methods={"GET","HEAD"})`, and the same for the default-locale alias. Nothing else: a `POST` under the prefix still needs a session.
35. **CSP.** Public pages run under the app's nonce policy: events sets no `Content-Security-Policy` of its own and borrows none (pagebuilder's `public_csp` has no nonce source and would block the Vite entry). FullCalendar's lazy chunk loads through `import()` under `'strict-dynamic'` (PR 3 Ruling 5); the e2e spec fails on any `Content Security Policy` console message.

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, alembic, Playwright or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. At most one Playwright run at a time, and stop its server when done. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr4` on branch `feat/events-pr4-public`, stacked on `feat/events-pr3-calendar` → `feat/events-pr2-events` → `feat/events-pr1-scaffold`. Before Task 1, rebase onto the finished PR 3 branch and run the "Depends on" check. Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points from the worktree root, module tests from the module directory: `cd modules/events && uv run pytest …`.
- Implementers are Claude subagents. Each runs pytest in the foreground, commits its own tasks (one commit per task) and never pushes.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- Names: package `sm_events`, npm `@simple-module-py/events`, locale namespace `events`, table prefix `events_`, pages `Events/PublicIndex`, `Events/PublicEvent`, `Events/PublicNotFound`.
- Version stays `0.0.15` (`uv run python scripts/bump_version.py --check-current`).
- Pins are ranges, never `==`. New dependency: `icalendar>=7,<8` with its `# floor:` comment (Ruling 23). No other Python or npm dependency.
- Settings stay DB-backed with no environment reads; the two new fields (`public_prefix`, `public_cache_seconds`) are added to `EventsSettings`, never to `.env.example`. `public_prefix` is read only from `app.state.sm_events.settings` in `on_startup`.
- Every query on an events table runs with a tenant bound. Core statements carry their own `tenant_id` predicate. `all_tenants()` is not used anywhere in this PR.
- Do not edit `sm_events/core/tenancy/*` (parity family, `scripts/tests/parity_tenancy.py`). Copies of news helpers (`viewer_key`, `etag_for`'s shape, `inject`, `set_html_lang`, `_safe_json_ld`) are written in events, never imported from news; where `scripts/tests/test_helper_parity.py` already has a family for one (`viewer_key`), add events' copy to it.
- Another module is reached only through its `contracts` (pagebuilder: `pagebuilder.contracts.public.render_not_found`), behind a deferred, guarded import in `sm_events/integrations/pagebuilder.py`; `scripts/check_sibling_contracts.py` must pass. Events gains no pagebuilder dependency or extra.
- 300-line cap; keep every `.py`/`.ts`/`.tsx` under 280 lines. The split is fixed in the File structure below.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`); the new bounds (`PAGE_SIZE`, `SUB_EVENTS_MAX`, `NEXT_OCCURRENCES`, `NOT_FOUND_SUGGESTIONS`, `FEED_MAX_EVENTS`, `FEED_MAX_COMPONENTS`, `FEED_DAYS_BACK = 30`, `FEED_DAYS_AHEAD = 366`, `SITEMAP_MAX_URLS`, `FEED_RATE`, `PUBLIC_API_RATE`, `RESERVED_SLUGS`) live there too.
- Only real Inertia pages go under `sm_events/pages/`: `PublicIndex.tsx`, `PublicEvent.tsx`, `PublicNotFound.tsx` in this PR.
- `en.json` and `de.json` keep identical key trees and placeholders (`scripts/check_locales.py`); UI strings go through `t(keys.events.public.…)`.
- Postgres checks use dev-services' Postgres and scratch databases (`smpy_events_check` for alembic, `smpy_events_test` for pytest). Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

The leak list. Each line names the way something could reach the public and the test that pins it; most live in one parametrized table, `tests/web/public/test_leaks.py` (Task 6 builds the harness, later tasks add their surface's rows).

1. **Draft, in-review and scheduled events** on a public calendar: absent from the index list, the calendar page, `/api/occurrences`, `calendar.ics`, `c/{cal}.ics`, the sitemap, the 404 suggestions, the parent's sub-event list; their `/{slug}`, `/{slug}?date=…`, `/{slug}.ics` are the 404. `test_leaks.py::test_hidden_event_absent_everywhere[draft|in_review|scheduled]`.
2. **Published events of internal and private calendars**: the same absences, their calendar's `/c/{slug}` and `/c/{slug}.ics` are the 404, and their category is not in the public filter. `test_leaks.py::test_hidden_event_absent_everywhere[internal|private]`, `test_hidden_calendar_404[internal|private|trashed]`, `test_public_read.py::test_categories_only_from_public_events`.
3. **Trashed rows**: a trashed event, a published event of a trashed public calendar, a trashed child. `test_leaks.py::test_hidden_event_absent_everywhere[trashed|calendar_trashed]`.
4. **Another tenant's rows** (multi mode, `unbound_tenant`): tenant `b`'s public event is absent for tenant `a` on every surface, a request that resolved no tenant gets the 404 without a query, and no answer for a request-specific tenant is `public`. `test_leaks.py::test_other_tenant_absent_everywhere`, `test_public_cache.py::test_request_tenant_never_shareable`.
5. **Existence oracles**: the 404 for a draft slug and for a missing slug have the same status, the same Inertia props (`X-Inertia` request), the same `Cache-Control`/`Vary` and no `ETag`; a guessed `If-None-Match` on a draft URL is a 404; a redirect whose target is a draft or internal is the 404 (not a 301); `?date=` on a draft series is the 404 and on a skipped date too. `test_leaks.py::test_not_found_indistinguishable`, `test_conditional_get_needs_visibility`, `test_redirect_to_hidden_is_404[event|calendar]`, `test_event_page.py::test_date_param_matrix`.
6. **JSON-LD and the head**: no hidden parent title, no draft sibling in `hreflang`, no `</script>` break-out. `test_event_page.py::test_child_of_hidden_parent_names_no_parent`, `test_alternates_only_public_texts`, `test_head.py::test_json_ld_script_break_out`.
7. **The viewer never widens the answer**: a signed-in `events.manage` user gets byte-identical props on every public page and API (only the cache headers differ). `test_leaks.py::test_signed_in_manager_sees_public_only`, plus `test_no_viewer_in_public_code` (the grep of Ruling 1).

Two non-leak failure modes also most likely to bite:

8. **Feed times across DST and all-day**: a weekly 10:00 Europe/Vienna series round-trips through `icalendar` to the same local times either side of 29 March; an all-day event on 29 March is `DTSTART;VALUE=DATE:20260329` / `DTEND;VALUE=DATE:20260330`. `test_ics_roundtrip.py::test_series_round_trip_vienna`, `test_ics_event.py::test_all_day_dates`.
9. **A truncated feed never resurrects skipped occurrences**: with the component cap forcing a cut, no series appears without its EXDATEs. `test_ics_calendar.py::test_cap_drops_whole_series`.

---

## File structure

| File | Responsibility | Target lines |
|---|---|---|
| `core/public_prefix.py` | `effective(value) -> str` | 50 |
| `core/locales.py` (only if PR 2 has none) | `supported`, `default`, `is_default`, `path_prefix` over `content_locales` | 60 |
| `core/access/public.py` | `ANONYMOUS`, `public_calendars()`, `public_events()` | 50 |
| `content/public_read.py` | slug and redirect lookups, children, alternates, categories, all through the gate | 230 |
| `content/calendar_redirects.py` | record, release, resolve calendar redirects | 80 |
| `content/richtext_tree.py` | clean HTML → node tree | 100 |
| `models/calendar_redirect.py` | `CalendarRedirect` | 30 |
| `integrations/pagebuilder.py` | deferred `render_not_found` | 60 |
| `feeds/__init__.py` | docstring | 10 |
| `feeds/plaintext.py` | clean HTML → plain text | 80 |
| `feeds/ics_tz.py` | the VTIMEZONE call, isolated | 50 |
| `feeds/ics_event.py` | one event (+ overrides) → VEVENTs | 230 |
| `feeds/select.py` | the feed read: window, caps, texts, overrides | 170 |
| `feeds/ics_calendar.py` | VCALENDAR assembly, ordering, truncation | 140 |
| `web/endpoints/public/__init__.py` | `public_router(locale)`, `alias_router`, order docstring | 80 |
| `web/endpoints/public/_tenant.py` | `public_tenant` (page binder yielding `None`), `machine_tenant` | 60 |
| `web/endpoints/public/_cache.py` | shareable rule, headers, ETags, 304, `PublicErrorRoute` | 220 |
| `web/endpoints/public/_urls.py` | origin, absolute URLs, path builders, `warn_if_unset` | 160 |
| `web/endpoints/public/_head.py` | head tags, `inject`, `set_html_lang`, `safe_json_ld` | 200 |
| `web/endpoints/public/_jsonld.py` | `Event` JSON-LD | 150 |
| `web/endpoints/public/_not_found.py` | the one 404 | 90 |
| `web/endpoints/public/_listing.py` | upcoming list: read, enrich, month groups, paging | 200 |
| `web/endpoints/public/_index.py` | `/` and `/c/{calendar}` routes | 200 |
| `web/endpoints/public/_occurrence.py` | `?date=` resolution, next occurrences | 150 |
| `web/endpoints/public/_event_props.py` | event page props | 230 |
| `web/endpoints/public/_event.py` | `/{slug}` route | 170 |
| `web/endpoints/public/_api.py` | `/api/occurrences` | 120 |
| `web/endpoints/public/_feeds.py` | `.ics` routes | 200 |
| `web/endpoints/public/_sitemap.py` | sitemap | 150 |
| `core/boot.py` | mount routers, exemptions, rate limits | 150 |
| `web/schemas/public.py` | `PublicListItem`, `PublicEventProps` … (pydantic) | 200 |
| `pages/PublicIndex.tsx`, `PublicEvent.tsx`, `PublicNotFound.tsx` | the three screens | ≤ 200 each |
| `ui/public/*.tsx` | `UpcomingList`, `PublicCalendarGrid`, `CategoryFilter`, `SubscribeBox`, `EventWhen`, `EventPlace`, `RichText`, `SubEvents`, `CancelledBanner`, `LanguageSwitch`, `PublicHead` | ≤ 200 each |
| `ui/public/api-public.ts`, `ui/utils/jsonLd.ts`, `ui/hooks/useDocumentLang.ts` | public fetcher, JSON-LD escape, html lang | ≤ 80 each |

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events suite green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: settings, gate, binding, skeleton, redirects** | 1–6 | settings and constants; the public gate and lookups with the read-level leak table; reserved slugs; calendar redirects with the migration; tenant binder and cache policy; boot wiring (routers, exemptions, rate limits), the 404, the route skeleton and the HTTP leak harness |
| **B: ICS** | 7–11 | `icalendar` round-trip; plain text; VEVENT encoding with VTIMEZONE; the feed read and assembly with caps; the `.ics` routes |
| **C: pages, API, SEO** | 12–19 | head, JSON-LD, html lang; the rich-text tree; `/api/occurrences`; index and calendar pages; the event page; sitemap; the three Inertia screens and their components |
| **D: e2e and docs** | 20–21 | `events-public.spec.ts`, the CSP check; docs, CLAUDE.md, CHANGELOG, branch verification |

---

### Task 1: Settings, constants and the prefix normaliser

**Files:**
- Modify: `sm_events/core/settings/__init__.py` (`public_prefix`, `public_cache_seconds`, Ruling 6), `sm_events/core/constants.py` (the bounds of Global Constraints; `_PAGE_PUBLIC_INDEX = f"{MODULE_NAME}/PublicIndex"`, `_PAGE_PUBLIC_EVENT`, `_PAGE_PUBLIC_NOT_FOUND`; `DEFAULT_PUBLIC_PREFIX = "/events"`; `SLUG_RESERVED_CODE`/`_DETAIL`; `ICS_MEDIA_TYPE = "text/calendar; charset=utf-8"`; `PRODID`), `sm_events/core/errors.py` (`SlugReserved(Invalid)`, 422 `slug_reserved`)
- Create: `sm_events/core/public_prefix.py`; `sm_events/core/locales.py` only if PR 2 has no locale helper (check `grep -rn "def path_prefix\|def supported" modules/events/sm_events` first)
- Test: `tests/core/test_settings.py`, `tests/core/test_public_prefix.py`, `tests/core/test_errors.py`, `tests/core/test_locales.py` (if created)

**Interfaces:**
- `effective(value: str | None) -> str` (Ruling 6); logs `"events: public_prefix %r is not usable, serving at /events"` at ERROR on fallback.
- `locales.path_prefix(locale) -> str`: `""` for the default, `"/de"` otherwise; `supported() -> tuple[str, ...]` from the hydrated `content_locales`, published once at startup with `locales.use(*values)` as news' `core/locales` does.

- [ ] **Step 1: Write the failing tests:**
  - `test_settings.py::test_public_fields`: defaults `"/events"` and `300`; `public_prefix` carries `requires_restart` in its JSON schema, `public_cache_seconds` does not.
  - `test_public_prefix.py::test_effective`: parametrized `("/events", "/events")`, `("/events/", "/events")`, `("events", "/events")`, `("/what-s-on/de", "/what-s-on/de")`, and fallback to `/events` for `"/"`, `""`, `None`, `"/api/x"`, `"/admin/events"`, `"/Events"`, `"/ev ents"`, `"/ev..ts"`, with the ERROR logged (`caplog`).
  - `test_errors.py`: `SlugReserved` is 422 `slug_reserved` with the `{"detail","code"}` body.
- [ ] **Step 2: Run** `~/.claude/bin/wait-for-headroom`, then `cd modules/events && uv run pytest -q tests/core/test_settings.py tests/core/test_public_prefix.py tests/core/test_errors.py`. Expected: FAIL (missing fields and module).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same: PASS. Then `uv run python scripts/check_hardcoded_strings.py` from the root: PASS.
- [ ] **Step 5: Commit** `feat(events): public prefix and cache settings`.

### Task 2: The public gate and its lookups

**Files:**
- Create: `sm_events/core/access/public.py`, `sm_events/content/public_read.py`
- Test: `tests/core/access/test_public_access.py`, `tests/content/test_public_read.py`
- Modify: `tests/support/calendars.py` (add `async seed_public_fixture(db) -> PublicFixture`, a dataclass with: public calendar `pub`, internal `internal`, private `private`, trashed public `gone`; on `pub`: published one-off `one_off`, published weekly series `series` (Europe/Vienna 10:00, 8 weeks from 2026-03-16, overrides: week 3 `moved` +1 h, week 4 `cancelled`, week 5 `skipped`), `draft`, `in_review`, `scheduled` (draft with future `publish_at`), `trashed` event, published parent `conf` with a published child `talk` and a draft child `secret_talk`, a published child `orphan` of a draft parent `draft_parent`, category `public_cat` on `one_off` and `draft_cat` used only by `draft`; on `internal`, `private` and `gone`: one published event each; `de` texts on `one_off` and `series`; each with a unique slug. Every later test uses it.)

**Interfaces:**

```python
# core/access/public.py
ANONYMOUS: ResourcePrincipal
def public_calendars() -> Select          # visible_calendars(ANONYMOUS)
def public_events() -> Select             # visible_events(ANONYMOUS, include_unpublished=False)
# content/public_read.py
async def event_by_slug(db, locale: str, slug: str) -> tuple[Event, EventText] | None
async def resolve_event_redirect(db, locale: str, slug: str) -> str | None   # the target's current slug in locale, only if public (Ruling 3)
async def calendar_by_slug(db, slug: str) -> Calendar | None
async def public_children(db, parent_id: uuid.UUID) -> list[Event]           # by starts_at, <= SUB_EVENTS_MAX
async def public_parent(db, event: Event) -> Event | None                    # None unless the parent is public
async def public_texts(db, event_ids) -> dict[uuid.UUID, dict[str, EventText]]   # texts_of over public ids only
async def public_categories(db) -> list[Category]                             # Ruling 5
async def category_by_slug(db, slug: str) -> Category | None                  # among public_categories
def pick_text(texts: Mapping[str, EventText], locale: str, default: str) -> EventText   # Ruling 12 fallback
```

- [ ] **Step 1: Write the failing tests:**
  - `test_public_access.py::test_anonymous_matches_policy`: `public_calendars()` returns exactly `{pub}`; `public_events()` returns exactly the published events of `pub` (`one_off`, `series`, `conf`, `talk`, `orphan`).
  - `test_public_access.py::test_same_as_contract`: the event ids equal those of `contracts.occurrences.occurrences(viewer=None)` over a 366-day range covering the fixture.
  - `test_public_read.py`:
    - `test_event_by_slug_only_public`: parametrized over every fixture event: a hit only for the five public ones, and only in a locale that has a text (`de` for `one_off`, not for `conf`).
    - `test_event_redirect_through_gate`: a redirect to `one_off` resolves to its current slug; a redirect to `draft` and one to the internal calendar's event resolve to `None`; a redirect in `de` is not seen in `en`.
    - `test_calendar_by_slug`: only `pub`.
    - `test_children`: `public_children(conf) == [talk]`; `public_parent(orphan) is None`; `public_parent(talk) == conf`.
    - `test_categories_only_from_public_events`: `[public_cat]`; `category_by_slug("draft-cat") is None`.
    - `test_pick_text_fallback`: `de` → the `de` text; `de` on an `en`-only event → the `en` text; an event with only `de` and default `en` → the `de` text.
    - `test_other_tenant` (`unbound_tenant`): the same fixture seeded in tenant `b`; under `tenant_scope("a")` every lookup above returns nothing of `b`'s.
- [ ] **Step 2: Run** `uv run pytest -q tests/core/access/test_public_access.py tests/content/test_public_read.py`: FAIL.
- [ ] **Step 3: Implement.** Every function composes `public_events()`/`public_calendars()` with its own `where`; none builds a predicate on `status` or `visibility` itself.
- [ ] **Step 4: Run** it on SQLite and on Postgres (`SM_TEST_DATABASE_URL=…/smpy_events_test`): PASS.
- [ ] **Step 5: Commit** `feat(events): the public gate and its lookups`.

### Task 3: Reserved slugs

**Files:**
- Modify: PR 2's text slug code (`content/texts.py` and `calendar/slugs.py: free_text_slug`) and PR 1's calendar slug code (`calendar/calendars.py`, `calendar/slugs.py: free_slug`) so both refuse an explicit reserved slug with `SlugReserved` and skip reserved ones when deriving
- Test: `tests/calendar/test_reserved_slugs.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_event_text_reserved`: parametrized over `RESERVED_SLUGS`: an explicit text slug gives `SlugReserved`; a title "Calendar" derives `calendar-2`.
  - `test_calendar_reserved`: the same for create and for PATCH of a calendar.
  - `test_api_422`: through the HTTP API, `POST /api/events/calendars` with `slug: "c"` gives 422 `{"detail","code":"slug_reserved"}`.
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_reserved_slugs.py`: FAIL.
- [ ] **Step 3: Implement** one helper `slugs.check_not_reserved(slug: str) -> None` used by both write paths, and `RESERVED_SLUGS` as a skip set inside both `free_*` functions.
- [ ] **Step 4: Run** it plus `tests/calendar/test_slugs.py tests/content/test_texts.py`: PASS.
- [ ] **Step 5: Commit** `feat(events): reserve the public route segments as slugs`.

### Task 4: Calendar slug redirects and their migration

**Files:**
- Create: `sm_events/models/calendar_redirect.py` (Ruling 13), export from `models/__init__.py`
- Create: `sm_events/content/calendar_redirects.py`
- Modify: `calendar/calendars.py` (`create_calendar` releases; `update_calendar` records the old slug and releases the new one, inside the same `slug_write` block)
- Create: `host/migrations/versions/<rev>_events_calendar_redirect.py`
- Test: `tests/models/test_models.py`, `tests/calendar/test_calendar_redirects.py`

**Interfaces:**

```python
async def record_rename(db, *, calendar_id: uuid.UUID, old_slug: str) -> None
async def release_slug(db, slug: str) -> None
async def resolve(db, slug: str) -> str | None   # the target's current slug, only if in public_calendars() (Ruling 3)
```

- [ ] **Step 1: Write the failing tests:**
  - `test_models.py::test_calendar_redirect_unique`: two rows with the same `(tenant_id, old_slug)` raise `IntegrityError`; the same `old_slug` in two tenants is fine.
  - `test_calendar_redirects.py`:
    - `test_rename_records`: renaming `pub` from `a` to `b` gives `resolve("a") == "b"`.
    - `test_chain_collapses`: `a → b → c`: `resolve("a") == "c"` and `resolve("b") == "c"` (each rename re-points, or `resolve` follows at most one hop because rows point at the calendar id, not at a slug).
    - `test_claim_releases`: another calendar created with slug `a` deletes the redirect; `resolve("a") is None`.
    - `test_rename_back_removes`.
    - `test_hidden_target`: after `pub` becomes `internal`, `resolve("a") is None`; trashed likewise.
    - `test_trash_cascade`: none needed (soft delete); a hard delete of the calendar row cascades (Postgres only).
- [ ] **Step 2: Run** `uv run pytest -q tests/models tests/calendar/test_calendar_redirects.py`: FAIL.
- [ ] **Step 3: Check the head and autogenerate.** `uv run python scripts/check_migration_heads.py`: chain off the single head it prints (PR 2's `events_revision.note` revision when this plan was written; if it prints two, stop and report). Autogenerate against a scratch SQLite file as PR 2 Task 7 Step 3 does (`SM_DATABASE_URL=sqlite+aiosqlite:////tmp/events-mig4.db`, `upgrade heads`, `make migration msg="events calendar redirect"`). The revision creates only `events_calendar_redirect` with its unique constraint and index; give it a docstring. Run `upgrade`, `check`, `downgrade -1`, `upgrade`, `check`; delete the file.
- [ ] **Step 4: Postgres.** On `smpy_events_check`: `upgrade heads`, `check`, `downgrade <parent>`, `upgrade heads`, `check`; drop the database. Then the Step 2 tests on SQLite and Postgres (PASS) and `check_migration_heads.py` (one head, the new revision).
- [ ] **Step 5: Commit** `feat(events): calendar slug redirects`.

### Task 5: Tenant binder, cache policy and URLs

**Files:**
- Create: `web/endpoints/public/_tenant.py`, `web/endpoints/public/_cache.py`, `web/endpoints/public/_urls.py`
- Modify: `scripts/tests/test_helper_parity.py` / `parity_families.py` (events' `viewer_key` joins the existing family, if there is one for it)
- Test: `tests/web/public/__init__.py`, `tests/web/public/test_public_cache.py`, `tests/web/public/test_public_urls.py`

**Interfaces:**

```python
# _tenant.py
async def public_tenant(request) -> AsyncIterator[str | None]   # note_tenant_source; resolve_public; None -> yield None unbound; else tenant_scope
# machine routes use sm_events.core.tenancy.bind_public unchanged
# _cache.py
PER_VIEWER_VARY = ("X-Inertia", "Cookie", "Accept-Language")
def shared_tenant(request) -> bool                                # Ruling 21 (images' _shared_tenant)
def signed_in(request) -> bool
def viewer_key(request) -> str                                     # news' copy
def page_etag(*parts: object, variant: str, viewer: str) -> str   # W/"<16 hex>"
def body_etag(body: bytes) -> str                                  # W/"<32 hex>" sha256
def matches(if_none_match: str | None, tag: str) -> bool           # records' weak comparison, "*" included
def apply(response, request, settings, *, kind: Literal["page", "listing", "feed", "sitemap", "api"], etag: str | None) -> Response
def not_modified(request, response_headers) -> Response | None     # 304 carrying ETag, Cache-Control, Vary
def error_headers(request, response) -> Response                   # no-store + tenant Vary for >= 400
class PublicErrorRoute(APIRoute)                                   # applies error_headers to every error, HTTPException included
# _urls.py
def configured_origin(app) -> str        # the host's public_base_url on a single-tenant host, else ""
def public_base_url(request) -> str
def warn_if_unset(app, mode) -> bool     # news' warning, worded for events
def index_path(locale) / calendar_path(slug, locale) / event_path(slug, locale, date: date | None = None)
def event_ics_path(slug, locale) / calendar_ics_path(slug | None, locale) / sitemap_path() / api_path()
def absolute(request, path) -> str
```

- [ ] **Step 1: Write the failing tests** (`test_public_cache.py`, a bare `FastAPI` app with the events tenancy configured as in `tests/core/tenancy/test_tenancy.py`):
  - `test_single_default_is_public`: `Cache-Control` starts `public, max-age=300` for `kind="page"` and `public, max-age=60` for `"listing"`.
  - `test_request_tenant_never_shareable`: parametrized: `request.state.tenant_id = "default"` set upstream, a header tenant in multi mode, a subdomain tenant: always `private`, and the tenant header in `Vary` when the app has one.
  - `test_signed_in_page_is_private_no_store_without_etag`.
  - `test_zero_seconds_is_no_store`: `public_cache_seconds = 0` sends `no-store` and no `ETag` for every kind.
  - `test_vary_per_viewer_and_host`: pages vary on `X-Inertia, Cookie, Accept-Language`; `Host` is added only while no origin is configured.
  - `test_not_modified_keeps_headers`: a matching `If-None-Match` (also `*` and the tag without `W/`) gives 304 with `ETag`, `Cache-Control`, `Vary` and no `Content-Security-Policy`.
  - `test_error_route_no_store`: a route raising `NotFound` and one raising a 422 under `PublicErrorRoute` both carry `no-store`.
  - `test_page_etag_varies`: differs by each part, by `variant` and by `viewer`.
  - `test_urls.py::test_paths`: `event_path("x", "en") == "/events/x"`, `event_path("x", "de", date(2026, 7, 6)) == "/de/events/x?date=2026-07-06"`, `calendar_ics_path(None, "de") == "/de/events/calendar.ics"`, `calendar_ics_path("team", "en") == "/events/c/team.ics"`, with a custom prefix `/whats-on`.
  - `test_urls.py::test_origin`: the host's `public_base_url` on single, the request origin on multi; `warn_if_unset` warns only in production single-tenant mode without one.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public`: FAIL.
- [ ] **Step 3: Implement.** The prefix comes from a module-level value published at startup (`_urls.use(prefix)`), as news' `settings.use`.
- [ ] **Step 4: Run** it (PASS), then `uv run pytest -q scripts/tests/test_helper_parity.py` from the root (PASS).
- [ ] **Step 5: Commit** `feat(events): public tenant binding, cache policy and URLs`.

### Task 6: Boot wiring, the 404, the route skeleton and the HTTP leak harness

**Files:**
- Create: `sm_events/core/boot.py` (`mount_public_routers(app, prefix)`, `exempt_public_routes(app, prefix, languages)`, `register_public_rate_limits(app, prefix, languages)`), `web/endpoints/public/__init__.py` (`public_router(locale)`, `alias_router(prefix)`), `web/endpoints/public/_not_found.py`, `sm_events/integrations/__init__.py`, `sm_events/integrations/pagebuilder.py`
- Create stubs that only answer the 404 for now, replaced in batches B and C: `_index.py`, `_event.py`, `_feeds.py`, `_sitemap.py`, `_api.py` (each route registered with its final path, methods `GET`/`HEAD`, under `PublicErrorRoute`)
- Modify: `sm_events/module.py` (`on_startup`: `public_prefix.effective(settings.public_prefix)` → `_urls.use`, `locales.use`, `warn_if_unset`, mount, exempt, rate limits)
- Modify: `host/tests/test_events_wiring.py` (the public paths)
- Test: `tests/web/public/test_boot.py`, `tests/web/public/test_not_found.py`, `tests/web/public/test_leaks.py` (the harness)

**Interfaces:**
- `not_found(request, inertia, db, *, locale: str, tenant: str | None) -> Response`: pagebuilder's when `integrations.pagebuilder.render_not_found` returns a response; otherwise `inertia.render(_PAGE_PUBLIC_NOT_FOUND, {"locale", "index_url", "suggestions": list[PublicListItem]})` with status 404 and `error_headers`. `suggestions` are the next `NOT_FOUND_SUGGESTIONS` items of the index list (Task 15 fills them; `[]` until then) and empty when `tenant is None` (no query).
- `test_leaks.py` harness: `HIDDEN = ("draft", "in_review", "scheduled", "internal", "private", "trashed", "calendar_trashed")`; `def surfaces(fx, locale) -> list[Surface]` where each `Surface` has a name, a URL and either `kind="page"` (expect the 404 for a hidden event's own URL) or `kind="listing"` (expect the hidden event's title, slug and `uid` absent from the body). Batches B and C add their surfaces to it; Task 6 starts with the event page URL only.

- [ ] **Step 1: Write the failing tests:**
  - `test_boot.py`:
    - `test_routes_per_locale`: with `content_locales=("en","de")` the app has `/events/`, `/events/{slug}`, `/de/events/{slug}`, `/events/sitemap.xml`, `/events/api/occurrences`, and neither `/de/events/sitemap.xml` nor `/de/events/api/occurrences`.
    - `test_fixed_paths_before_catch_all`: `GET /events/calendar.ics` and `/events/sitemap.xml` reach their own handlers (monkeypatched sentinels), never `/{slug}`.
    - `test_custom_prefix_from_db`: a stored `public_prefix="/whats-on"` mounts at `/whats-on/` after lifespan start, and nothing at `/events/`.
    - `test_exemptions_pinned`: an anonymous `GET` and `HEAD` under `/events/`, `/events` and `/de/events/` pass the auth middleware; a `POST /events/x` does not; `/eventsfoo` is not exempt.
    - `test_rate_limit_rules_live`: after startup `app.state.rate_limit_rules.match("GET", "/events/calendar.ics")` is the `FEED_RATE` rule, `"/de/events/x.ics"` too, `"/events/api/occurrences"` is `PUBLIC_API_RATE`, and a request over the limit gets 429 (prove the middleware reads the live registry; if it does not, follow Ruling 33's fallback and say so in the commit).
    - `test_alias_redirect`: `/en/events/x` → 301 `/events/x` with two locales; absent with one.
  - `test_not_found.py`:
    - `test_without_pagebuilder`: renders `Events/PublicNotFound`, 404, `no-store`, no `ETag`.
    - `test_with_pagebuilder_contract`: with `integrations.pagebuilder.render_not_found` monkeypatched to return a sentinel response, that response is returned and called with the bound tenant.
    - `test_no_tenant_no_query` (`unbound_tenant`, multi mode, no tenant resolved): the 404 renders, and a guard on the session raises if any statement is executed.
  - `test_leaks.py::test_hidden_event_absent_everywhere` (parametrized over `HIDDEN` × surfaces): the event page URL of each hidden event is the 404 in both locales.
  - `test_leaks.py::test_not_found_indistinguishable`: `X-Inertia` requests for `draft`'s slug and for `no-such-slug` give equal status, equal `props`, equal `Cache-Control` and `Vary`, no `ETag`.
  - `test_leaks.py::test_no_viewer_in_public_code`: the grep of Ruling 1 over `web/endpoints/public/` and `feeds/`.
  - `test_leaks.py::test_other_tenant_absent_everywhere` (`unbound_tenant`, multi mode, the fixture seeded in tenants `a` and `b` with distinct slugs): every surface requested as tenant `a` holds none of `b`'s slugs, titles or UIDs, and `b`'s event URL is the 404 for `a`. Like the hidden-event test, it iterates `surfaces(...)`, so later tasks extend it by adding surfaces.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public`, then from the root `uv run pytest -q host/tests/test_events_wiring.py`: FAIL.
- [ ] **Step 3: Implement.** Mirror `news/core/boot.py` and `NewsModule.on_startup`. The integration imports `pagebuilder.contracts.public` inside the call and answers `None` when it is absent, not mounted (`getattr(app.state, "pagebuilder", None)` through `pagebuilder.contracts` only; use what news uses) or raises `ImportError`.
- [ ] **Step 4: Run** the same (PASS), then `uv run python scripts/check_sibling_contracts.py`, `check_rules.py` and `check_file_size.py` (PASS).
- [ ] **Step 5: Commit** `feat(events): mount the public routes per locale with their exemptions, limits and 404`.

**End of batch A.** Run `cd modules/events && uv run pytest -q -n 8` (headroom first), `check_file_size.py`, `check_hardcoded_strings.py`, `ruff check modules/events`.

---

### Task 7: `icalendar` and the round-trip test

**Files:**
- Modify: `modules/events/pyproject.toml` (Ruling 23's line), `uv.lock`
- Create: `sm_events/feeds/__init__.py` (docstring: what the package owns; feeds read rows, never the occurrences read), `sm_events/feeds/ics_tz.py`
- Test: `tests/feeds/__init__.py`, `tests/feeds/test_ics_roundtrip.py`, `tests/feeds/test_licences.py`

**Interfaces:** `ics_tz.vtimezone(tzid: str, first: datetime, last: datetime) -> icalendar.Timezone`, wrapping whatever the installed version offers (expected `icalendar.Timezone.from_tzid(tzid, first_date=…, last_date=…)` or `Calendar.add_missing_timezones()`; record the exact call and the version in the module docstring).

- [ ] **Step 1: Write the failing tests:**
  - `test_ics_roundtrip.py::test_series_round_trip_vienna`: build a VCALENDAR with a master `DTSTART;TZID=Europe/Vienna:20260316T100000`, `RRULE:FREQ=WEEKLY;COUNT=8`, `EXDATE;TZID=Europe/Vienna:20260413T100000`, a `RECURRENCE-ID;TZID=Europe/Vienna:20260330T100000` override moved to 11:00, a cancelled `RECURRENCE-ID` for 6 April with `STATUS:CANCELLED`, and `vtimezone("Europe/Vienna", …)`. Serialise with `to_ical()`, parse with `Calendar.from_ical`, and assert: the RRULE is `{"FREQ": ["WEEKLY"], "COUNT": [8]}`; EXDATE and both RECURRENCE-IDs parse back to aware datetimes whose `tzinfo` key is `Europe/Vienna` and whose local times are 10:00; the moved one's DTSTART is 11:00 local; the VTIMEZONE has a `STANDARD` and a `DAYLIGHT` component covering 29 March 2026; the text contains `TZID=Europe/Vienna` on each property.
  - `test_all_day_round_trip`: `DTSTART;VALUE=DATE:20260329`, `DTEND;VALUE=DATE:20260330`, `RRULE:FREQ=WEEKLY;UNTIL=20260426`, `EXDATE;VALUE=DATE:20260405`, `RECURRENCE-ID;VALUE=DATE:20260412`: each parses back to a `date`, not a `datetime`.
  - `test_utc_until_and_escaping`: `UNTIL=20260705T080000Z` survives; a SUMMARY with `,`, `;`, `\n` and 200 characters of `ü` round-trips exactly, and every physical line is ≤ 75 octets.
  - `test_licences.py::test_no_lgpl_recurrence_package`: `recurring-ical-events` is not in `uv.lock`, and `icalendar`'s installed metadata licence mentions BSD.
- [ ] **Step 2: Run** (headroom first) `uv sync --all-packages --all-extras --no-extra anonymize` from the root, then `cd modules/events && uv run pytest -q tests/feeds`: FAIL until `ics_tz.py` exists, then PASS or fail on a library behaviour. **If any assertion about the library fails, stop and report** with the installed version and what it did: the rest of batch B depends on it.
- [ ] **Step 3: Implement** `ics_tz.py`.
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): icalendar dependency with a round-trip check`.

### Task 8: Plain text from the sanitised description

**Files:**
- Create: `sm_events/feeds/plaintext.py`
- Test: `tests/feeds/test_plaintext.py`

**Interfaces:** `to_text(html: str, *, max_chars: int | None = None) -> str` over `richtext.clean(html)` (re-cleaned first); `max_chars` cuts at a word boundary and adds `…` (used for meta and JSON-LD descriptions).

- [ ] **Step 1: Write the failing tests:** `test_blocks_become_lines` (`<p>a</p><p>b</p>` → `"a\n\nb"`), `test_lists` (`<ul><li>x</li><li>y</li></ul>` → `"- x\n- y"`, ordered lists `1. `), `test_links` (`<a href="https://a">site</a>` → `"site (https://a)"`; a link whose text is its href appears once), `test_entities_decoded` (`&amp;` → `&`), `test_br`, `test_script_never_survives` (a raw `<script>` in the stored value is dropped by the re-clean), `test_truncate_word_boundary`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/test_plaintext.py`: FAIL.
- [ ] **Step 3: Implement** with `html.parser.HTMLParser` over the cleaned string.
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): plain-text descriptions for feeds and metadata`.

### Task 9: One event as VEVENTs

**Files:**
- Create: `sm_events/feeds/ics_event.py`
- Test: `tests/feeds/test_ics_event.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FeedEvent:              # what select.py hands over; no ORM objects past this point
    event: Event
    text: EventText            # already picked per Ruling 12
    overrides: Sequence[OccurrenceOverride]
    url: str                   # absolute public URL
    category: str | None       # name in the feed locale
    parent_uid: str | None     # only when the parent is public
def components(item: FeedEvent) -> list[icalendar.Event]   # master first, then overrides by original_start
def tzids(items: Iterable[FeedEvent]) -> set[str]         # timed, non-UTC zones in use
```

- [ ] **Step 1: Write the failing tests** (parse each result back with `icalendar` and assert on values, not on strings):
  - `test_one_off_timed`: DTSTART/DTEND carry `TZID=Europe/Vienna` with local 10:00/11:30; `UID == event.uid`; `SEQUENCE == revision`; `DTSTAMP == LAST-MODIFIED == updated_at` (UTC); `URL`, `SUMMARY`, plain `DESCRIPTION`; `STATUS:CONFIRMED`.
  - `test_all_day_dates`: an all-day event on 2026-03-29 Vienna gives `DTSTART;VALUE=DATE:20260329`, `DTEND;VALUE=DATE:20260330`, no TZID.
  - `test_utc_event_has_no_tzid`.
  - `test_series_with_overrides`: the fixture's `series` gives 3 components: master with `RRULE` equal to the stored text and one `EXDATE` (week 5, local 10:00 Vienna), a moved VEVENT (`RECURRENCE-ID` week 3 10:00 local, DTSTART 11:00 local), a cancelled VEVENT (`RECURRENCE-ID` week 4, `STATUS:CANCELLED`, original times).
  - `test_all_day_series_exdate_is_date`.
  - `test_cancelled_event_status`.
  - `test_location_geo_categories`: venue + address joined; `GEO` only with both coordinates; online-only event's `LOCATION` is its URL; `CATEGORIES` is the given name.
  - `test_description_lines`: organiser and online link appended on their own lines.
  - `test_related_to_only_with_parent_uid`.
  - `test_no_organizer_attendee_alarm`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/test_ics_event.py`: FAIL.
- [ ] **Step 3: Implement.** Local times come from `times.to_local`-equivalent conversion of the stored UTC instants into `ZoneInfo(event.timezone)`; never re-expand the rule here.
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): encode events, series and overrides as VEVENTs`.

### Task 10: The feed read and the calendar file

**Files:**
- Create: `sm_events/feeds/select.py`, `sm_events/feeds/ics_calendar.py`
- Test: `tests/feeds/test_select.py`, `tests/feeds/test_ics_calendar.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FeedRead:
    items: list[FeedEvent]
    truncated: bool
async def feed_events(db, *, calendar_id: uuid.UUID | None, locale: str, default_locale: str,
                      now: datetime, url_for: Callable[[str, str], str]) -> FeedRead
    # public_events() [+ calendar], window and caps of Ruling 25, overrides and texts in one query each,
    # categories and public parents resolved; url_for(slug, locale_of_text) -> absolute URL
async def single_event(db, event: Event, *, locale, default_locale, url_for) -> FeedEvent   # no window
def build(items: Sequence[FeedEvent], *, name: str, timezone: str, first: datetime, last: datetime) -> bytes
    # VCALENDAR (Ruling 27), VTIMEZONEs via ics_tz, components sorted (starts_at, uid, recurrence-id)
```

- [ ] **Step 1: Write the failing tests:**
  - `test_select.py`:
    - `test_only_public_published`: over the fixture, the UIDs are exactly the public events'; no `draft`, `in_review`, `scheduled`, internal, private, trashed or trashed-calendar UID.
    - `test_window`: a one-off that ended 31 days ago and one starting in 367 days are out; an endless series that started two years ago is in; a series whose `recurrence_until` is 31 days ago is out.
    - `test_caps`: 1,001 one-offs give 1,000 items and `truncated`; the components cap of Ruling 25 is tested in `test_ics_calendar`.
    - `test_calendar_filter`: `calendar_id` of an internal calendar gives no items.
    - `test_locale_fallback`: locale `de` uses the `de` text where there is one and the `en` text otherwise, and `url_for` gets the text's own locale.
    - `test_query_count`: at most 5 statements for 50 events (count with an `after_cursor_execute` listener).
    - `test_other_tenant` (`unbound_tenant`).
  - `test_ics_calendar.py`:
    - `test_calendar_properties`: PRODID, VERSION, CALSCALE, X-WR-CALNAME, X-WR-TIMEZONE, REFRESH-INTERVAL, X-PUBLISHED-TTL.
    - `test_one_vtimezone_per_zone`: two Vienna events and one New York event give exactly two VTIMEZONEs; a UTC-only feed has none.
    - `test_deterministic`: building twice gives identical bytes.
    - `test_cap_drops_whole_series`: with `FEED_MAX_COMPONENTS` monkeypatched to 4 and items (one-off, series with 3 overrides, one-off), the output holds the first one-off only (the series would need 4 more), and `truncated` is set by the caller.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/test_select.py tests/feeds/test_ics_calendar.py`: FAIL.
- [ ] **Step 3: Implement.** The component cap is applied in `select.py` while building `items` (it knows each item's component count), so `build` never cuts.
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): the public feed read and calendar files`.

### Task 11: The `.ics` routes

**Files:**
- Modify: `web/endpoints/public/_feeds.py` (replace the stub)
- Modify: `tests/web/public/test_leaks.py` (add the feed surfaces)
- Test: `tests/web/public/test_feeds_http.py`

**Interfaces:** `feed_router(locale) -> APIRouter` with `GET|HEAD /calendar.ics`, `/c/{calendar}.ics`, `/{slug}.ics`, all under `bind_public` (machine routes: a JSON 404 envelope with `no-store`) and `PublicErrorRoute`. `/c/{old}.ics` 301s through `calendar_redirects.resolve` to the new `.ics`; `/{old}.ics` 301s through `resolve_event_redirect`.

- [ ] **Step 1: Write the failing tests:**
  - `test_content_type_and_disposition`: `text/calendar; charset=utf-8`; the single event has `attachment; filename="<slug>.ics"`; feeds have no `Content-Disposition`.
  - `test_calendar_feed_body`: parse the response: the fixture's public UIDs only, RRULE/EXDATE/RECURRENCE-ID present for `series`.
  - `test_single_series_has_all_overrides`: an override 400 days in the past is still in `{slug}.ics`.
  - `test_etag_and_304`: a second request with the ETag is 304 with `ETag`, `Cache-Control` and `Vary`; after an override is added (revision bump) it is 200 with a new tag.
  - `test_cache_kind_feed`: `public, max-age=300` on a single-tenant host.
  - `test_truncated_header`: monkeypatched caps set `X-Events-Truncated: 1`.
  - `test_redirects`: a renamed calendar's old `.ics` → 301 to the new one; a renamed event text slug's old `.ics` → 301.
  - `test_german_feed`: `/de/events/calendar.ics` carries the `de` SUMMARY for `one_off` and the `en` one for `conf`.
  - `test_leaks.py` additions: for each hidden kind, `{slug}.ics` is the 404 and the hidden UID is absent from `calendar.ics` and `c/{pub}.ics`; `c/{internal}.ics` and `c/{gone}.ics` are the 404 (`test_hidden_calendar_404`); `test_redirect_to_hidden_is_404[calendar]` (rename `internal`'s slug, request the old `.ics`).
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_feeds_http.py tests/web/public/test_leaks.py`: FAIL.
- [ ] **Step 3: Implement.** `HEAD` returns the headers of `GET` with no body.
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): public ICS feeds and single-event files`.

**End of batch B.** Run the module suite (`-n 8`), `check_file_size.py`, `check_hardcoded_strings.py`, `ruff check modules/events`.

---

### Task 12: Head, JSON-LD and the document language

**Files:**
- Create: `web/endpoints/public/_head.py` (copies of news' `_tag`, `_alternate_links`, `inject`, `set_html_lang`, `_safe_json_ld` as `safe_json_ld`, plus `event_head(...)` and `listing_head(...)` per Ruling 29), `web/endpoints/public/_jsonld.py`
- Test: `tests/web/public/test_head.py`, `tests/web/public/test_jsonld.py`

**Interfaces:**

```python
def event_json_ld(*, event: Event, text: EventText, url: str, image: str | None, locale: str,
                  occurrences: Sequence[ShownOccurrence]) -> dict | list[dict]
    # one dict for a single occurrence/one-off; a list for a bare series page (Ruling 30)
@dataclass(frozen=True)
class ShownOccurrence:   # produced by _occurrence.py (Task 16)
    start: datetime; end: datetime; all_day: bool; start_date: date | None; end_date: date | None
    status: Literal["scheduled", "cancelled", "rescheduled"]; previous_start: datetime | None
    date_param: date | None
```

- [ ] **Step 1: Write the failing tests:**
  - `test_jsonld.py`: `test_timed_offsets` (`startDate == "2026-07-06T10:00:00+02:00"` for Vienna), `test_all_day_inclusive_end` (`"2026-08-01"`–`"2026-08-03"` for a three-day event), `test_status_cancelled`, `test_status_rescheduled_previous_start`, `test_attendance_modes` (three modes → `https://schema.org/OfflineEventAttendanceMode` etc.), `test_location_shapes` (Place with PostalAddress and geo; VirtualLocation; a list for hybrid), `test_organizer_and_image_optional`, `test_series_list_bounded` (≤ `NEXT_OCCURRENCES`).
  - `test_head.py`: `test_json_ld_script_break_out` (a title `</script><script>alert(1)</script>` gives no second `<script` in the injected head, and the JSON parses back to the same title), `test_html_comment_escaped`, `test_noindex`, `test_canonical_and_hreflang_escaped`, `test_feed_autodiscovery_type_text_calendar`, `test_inject_replaces_shell_title`, `test_set_html_lang_keeps_shell_lang`, `test_no_executable_script` (every `<script` in the head has `type="application/ld+json"`).
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_head.py tests/web/public/test_jsonld.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): head tags and Event JSON-LD for public pages`.

### Task 13: The description as a node tree

**Files:**
- Create: `sm_events/content/richtext_tree.py`
- Test: `tests/content/test_richtext_tree.py`

**Interfaces:** `Node = str | dict` with `{"t": tag, "c": list[Node]}` plus `"href"` on `a`; `to_tree(html: str) -> list[Node]` over `richtext.clean(html)`; tags outside `ALLOWED_TAGS` never appear (the clean already removed them; the tree builder asserts it and unwraps defensively); depth ≤ the sanitiser's cap.

- [ ] **Step 1: Write the failing tests:** `test_simple` (`<p>a <strong>b</strong></p>` → `[{"t":"p","c":["a ",{"t":"strong","c":["b"]}]}]`), `test_link_href_kept_only_safe` (a stored `javascript:` link that predates the sanitiser comes out unwrapped to text), `test_entities_are_text` (`&lt;script&gt;` becomes the text `<script>`, never a node), `test_void_br`, `test_round_trip_every_allowed_tag`, `test_json_serialisable`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_richtext_tree.py`: FAIL.
- [ ] **Step 3: Implement** with `HTMLParser` over the cleaned string.
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): render-safe node tree for descriptions`.

### Task 14: The public occurrences endpoint

**Files:**
- Modify: `web/endpoints/public/_api.py` (replace the stub)
- Create: `web/schemas/public.py` (start it with the API's query parsing; `PublicListItem` etc. arrive in Task 15)
- Modify: `tests/web/public/test_leaks.py` (the API surface)
- Test: `tests/web/public/test_public_api.py`

**Interfaces:** `GET|HEAD {prefix}/api/occurrences` → `OccurrencePage` JSON (Ruling 32). `async def public_page(db, *, tenant, start, end, calendar_ids, category_ids, locale) -> OccurrencePage` in `_api.py` is also used by Task 15 and the 404 suggestions: the read with `ANONYMOUS`, then one `public_texts` query to set each item's `url` (Rulings 10, 12), `editable=False`, `event_status="published"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_shape_and_urls`: items carry public URLs: `one_off` → `/events/<slug>`, a `series` instance → `/events/<slug>?date=<local date of original_start>`, a `de` request for `conf` (no `de` text) → the `en` URL with `lang == "en"`.
  - `test_moved_keeps_original_date`.
  - `test_bounds`: a naive `start` and 367 days give 422 `{"detail","code"}` with `no-store`; `truncated` is serialised.
  - `test_calendar_ids_silently_dropped`: `?calendar=<internal id>` gives `{"items": [], "truncated": false}` with 200, the same as an unknown UUID.
  - `test_signed_in_manager_sees_public_only`: a session with `events.manage` gets the same JSON as anonymous; `Cache-Control` is private for them.
  - `test_cache_and_etag`: `public, max-age=60` on single; a 304 on a repeated tag.
  - `test_leaks.py` addition: the API over a 366-day window holds no hidden event id, slug or title.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_public_api.py tests/web/public/test_leaks.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): anonymous occurrences endpoint for the public calendar`.

### Task 15: Index and calendar pages (server side)

**Files:**
- Modify: `web/endpoints/public/_index.py` (replace the stub), `web/endpoints/public/_not_found.py` (fill `suggestions`)
- Create: `web/endpoints/public/_listing.py`; add `PublicListItem`, `MonthGroup`, `PublicCalendarOut`, `PublicIndexProps` to `web/schemas/public.py`
- Modify: `tests/web/public/test_leaks.py` (index, calendar page, 404 suggestions)
- Test: `tests/web/public/test_index_pages.py`

**Interfaces:**
- `PublicListItem {key, url, title, lang, all_day, start_local, end_local, start_date, end_date, timezone, show_timezone: bool, status, rescheduled: bool, calendar: {slug, name, color}, category: {slug, name, color} | None, venue_name, attendance_mode, summary}`.
- `PublicIndexProps {locale, page, page_count, groups: list[MonthGroup{month: "YYYY-MM", items}], calendars: list[PublicCalendarOut{id, slug, name, color, description, default_timezone, url, feed_url}], calendar: PublicCalendarOut | None, categories: list[{id, slug, name, color}], category: str | None, view: "list" | "calendar", feed_url, default_timezone, api_url, alternates}`.
- `async def upcoming(db, *, locale, default_locale, now, calendar_id: uuid.UUID | None, category_id: uuid.UUID | None) -> list[PublicListItem]` (Ruling 14: one read, enriched with one query for the events' place and category fields).

- [ ] **Step 1: Write the failing tests:**
  - `test_index_props`: groups are by the event's local month in order; `page_count`; only public calendars in `calendars`; `categories == [public_cat]`; `feed_url == "/events/calendar.ics"`.
  - `test_paging`: 45 future occurrences give 3 pages; `?page=0`, `?page=abc` give page 1; `?page=4` and `?page=99999999` are the 404 page.
  - `test_category_filter`: `?category=public-cat` narrows; `?category=draft-cat` and `?category=nope` are the 404.
  - `test_view_param`: `?view=calendar` sets `view`; anything else is `list`.
  - `test_calendar_page`: `/events/c/<pub>` narrows to `pub` with its description and feed URL; `/events/c/<old>` after a rename 301s; `/events/c/<internal>` and `/events/c/<gone>` are the 404 (`test_leaks.py::test_hidden_calendar_404`).
  - `test_head_injected`: the HTML has the listing title, canonical, hreflang (two locales), feed autodiscovery and `<html lang="de">` on `/de/events/`.
  - `test_cache_page_kinds`: anonymous `public, max-age=60` with the per-viewer `Vary`; signed-in `private, no-store`, no `ETag`.
  - `test_fallback_marked`: on `/de/events/`, `conf` appears with `lang == "en"` and its `en` URL.
  - `test_not_found_suggestions`: the 404 page's `suggestions` are the next 3 public items, identical for a draft slug and a missing one.
  - `test_leaks.py` additions: the index (every page), `/events/c/<pub>` and the 404 suggestions hold no hidden event's title, slug or id.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_index_pages.py tests/web/public/test_leaks.py`: FAIL.
- [ ] **Step 3: Implement** `index_router(locale)` with `public_tenant`; a `None` tenant answers `not_found` without a query.
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): public index and calendar pages`.

### Task 16: The event page (server side)

**Files:**
- Modify: `web/endpoints/public/_event.py` (replace the stub)
- Create: `web/endpoints/public/_occurrence.py`, `web/endpoints/public/_event_props.py`; add `PublicEventProps` to `web/schemas/public.py`
- Modify: `tests/web/public/test_leaks.py` (sub-event list, `?date=`, redirects)
- Test: `tests/web/public/test_event_page.py`

**Interfaces:**

```python
def parse_date_param(raw: str | None) -> date | None | Literal["invalid"]
async def shown_occurrence(db, event: Event, day: date) -> ShownOccurrence | None
    # expand.is_occurrence on the local date's instance + the override for it; skipped -> None (Ruling 10)
def next_occurrences(event: Event, overrides, *, now: datetime, limit: int) -> list[ShownOccurrence]
    # expand.instances bounded by now..now+MAX_RANGE_DAYS and limit, skipped dropped
```

- `PublicEventProps {locale, title, summary, description_tree, timezone, all_day, when: ShownOccurrence-as-JSON | None, series: {rule_summary_parts, next: list[{date_param, url, start_local, end_local, status}]} | None, cancelled, place: {mode, venue_name, address, online_url, latitude, longitude}, organiser, image, category, calendar: {slug, name, color, url}, parent: {title, url} | None, sub_events: list[PublicListItem], registration_url, ics_url, canonical_url, alternates, json_ld, index_in_search}`. `rule_summary_parts` is the normalised RRULE text plus `start_local`, so the client summarises it with PR 2's `ui/utils/recurrence.ts` `parseRule`/`summarise`.

- [ ] **Step 1: Write the failing tests:**
  - `test_one_off_page`: 200; props as listed; `ETag` set for anonymous; a repeat with it gives 304; `Content-Language: en`.
  - `test_date_param_matrix`: parametrized over `series`: week 1 date → 200 scheduled; week 3 (moved) → 200 with the new time and `status == "rescheduled"`; week 4 → 200 `cancelled`; week 5 (skipped) → the 404; a Tuesday → the 404; `?date=2026-13-40` → the 404; `?date=` on `one_off` → the 404; `?date=` on `draft`'s slug → the 404.
  - `test_bare_series_page`: `when is None`, `series.next` has ≤ 10 entries from `now` with `?date=` URLs, none for the skipped week; JSON-LD is a list.
  - `test_canonical`: bare URL for the bare page; the `?date=` URL for an occurrence; both absolute.
  - `test_alternates_only_public_texts`: `one_off` in `en`/`de` gives `en`, `de`, `x-default`; a `de` text added to `draft` never appears anywhere.
  - `test_locale_only_where_text`: `/de/events/<conf-slug>` is the 404.
  - `test_slug_redirect`: renaming `one_off`'s `de` slug makes the old `/de/events/<old>` a 301 to the new one, keeping `?date=` when present; `/events/<old de slug>` is the 404 (`test_leaks.py::test_redirect_to_hidden_is_404[event]` with a renamed `draft`).
  - `test_sub_events`: `conf` lists `[talk]` only; `talk` has `parent` set; `test_child_of_hidden_parent_names_no_parent`: `orphan`'s props, head and JSON-LD contain no `draft_parent` title or slug.
  - `test_cancelled_event`: banner flag, registration hidden in props (`registration_url is None`), JSON-LD `EventCancelled`, still indexable.
  - `test_noindex_text`: `index_in_search == False` and the robots meta.
  - `test_description_tree`: a stored `<p onclick=x>Hi <script>bad()</script></p>` gives `[{"t":"p","c":["Hi "]}]`.
  - `test_etag_changes_with_child_and_calendar`: publishing a new child or renaming the calendar changes the page's ETag.
  - `test_leaks.py::test_conditional_get_needs_visibility`: `If-None-Match: *` and a tag captured while `one_off` was public, sent after it was unpublished, give the 404.
  - `test_leaks.py::test_signed_in_manager_sees_public_only`: event, index and calendar page props equal anonymous ones for an `events.manage` session.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_event_page.py tests/web/public/test_leaks.py`: FAIL.
- [ ] **Step 3: Implement.** Order in the handler: tenant → slug lookup (else redirect, else 404) → `?date=` → ETag/304 → props → render → `inject(set_html_lang(...))` → headers.
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): public event pages with occurrences, sub-events and redirects`.

### Task 17: Sitemap

**Files:**
- Modify: `web/endpoints/public/_sitemap.py` (replace the stub)
- Modify: `tests/web/public/test_leaks.py` (the sitemap surface)
- Test: `tests/web/public/test_sitemap.py`

**Interfaces:** `async def sitemap_urls(db, *, base: str) -> list[tuple[str, date | None]]` (Ruling 31), one query for texts joined to `public_events()`.

- [ ] **Step 1: Write the failing tests:** `test_lists_indexes_calendars_events` (both locales' index, `pub`'s page in both, each public text at its locale's URL with `lastmod`), `test_noindex_excluded`, `test_no_date_urls`, `test_bounded` (with `SITEMAP_MAX_URLS` monkeypatched to 5, 5 `<url>` elements, newest first), `test_xml_escaped`, `test_only_default_prefix` (`/de/events/sitemap.xml` is the 404), `test_cache_and_etag`. `test_leaks.py`: no hidden slug in the sitemap.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_sitemap.py tests/web/public/test_leaks.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): sitemap of public events`.

### Task 18: `PublicIndex` and the read-only grid

**Files:**
- Create: `sm_events/pages/PublicIndex.tsx` (layout and data only, < 200 lines)
- Create: `ui/public/UpcomingList.tsx`, `ui/public/PublicCalendarGrid.tsx`, `ui/public/CategoryFilter.tsx`, `ui/public/SubscribeBox.tsx`, `ui/public/PublicHead.tsx` (Inertia `<Head>` mirror of the server tags, JSON-LD through `dangerouslySetInnerHTML` with `ui/utils/jsonLd.ts`'s escape, as news), `ui/public/LanguageSwitch.tsx`, `ui/public/api-public.ts` (`publicFetcher(apiUrl): OccurrenceFetcher`, plain `fetch` with `credentials: "same-origin"`, the `AbortSignal`, `ApiError` on non-2xx), `ui/utils/jsonLd.ts`, `ui/hooks/useDocumentLang.ts` (news' behaviour, written here)
- Modify: `locales/en.json`, `locales/de.json` (`public.*`)
- Test: `ui/page-tests/PublicIndex.test.tsx`, `ui/public/api-public.test.ts`

**Interfaces:** `PublicCalendarGrid` renders PR 3's `Calendar` with `fetchOccurrences={publicFetcher(api_url)}`, `calendars` mapped to `CalendarInfo` (`visibility: "public"`, `can_write_events: false`), `categories` as `FilterOption`s, `defaultTimezone`, `initialState` from the URL (`view`, `date`), `onStateChange` writing `?view=calendar&date=…` with `history.replaceState`, and **no `editing` prop**. An event chip links to `occurrence.url`.

- [ ] **Step 1: Write the failing tests** (`vi.mock` the adapter with PR 3's `FakeGrid`):
  - `renders month groups with localized month names` (`de` → "Juli 2026").
  - `fallback item has lang attribute`.
  - `cancelled and rescheduled markers`.
  - `paging links keep category`.
  - `category filter navigates with ?category=`.
  - `calendar tab mounts the grid read-only`: `fakeGrid.last.editing` is undefined and `selectable`/`editable` options are false.
  - `grid fetcher calls the public API` (`stubFetch`: the URL is `/events/api/occurrences?start=…&end=…&locale=de`, credentials same-origin).
  - `subscribe box shows https and webcal links`.
  - `no admin links rendered` (no `/admin/` in the markup).
  - `api-public.test.ts`: `aborts with the signal`, `throws ApiError on 422`.
- [ ] **Step 2: Run** (headroom first) `npx vitest run modules/events/sm_events/ui/page-tests/PublicIndex.test.tsx modules/events/sm_events/ui/public/api-public.test.ts`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, `npx tsc --noEmit -p modules/events/tsconfig.json`, `npx biome check modules/events`, `uv run python scripts/check_rules.py`, `check_locales.py`, `check_ts_imports.py`: all PASS.
- [ ] **Step 5: Commit** `feat(events): public index screen with the read-only calendar`.

### Task 19: `PublicEvent`, `PublicNotFound` and the rich text

**Files:**
- Create: `sm_events/pages/PublicEvent.tsx`, `sm_events/pages/PublicNotFound.tsx`
- Create: `ui/public/RichText.tsx`, `ui/public/EventWhen.tsx`, `ui/public/EventPlace.tsx`, `ui/public/SubEvents.tsx`, `ui/public/CancelledBanner.tsx`
- Modify: locales (`public.event.*`, `public.not_found.*`)
- Test: `ui/page-tests/PublicEvent.test.tsx`, `ui/public/RichText.test.tsx`, `ui/page-tests/PublicNotFound.test.tsx`

**Interfaces:** `RichText({nodes}: {nodes: Node[]})` with a fixed `Record<AllowedTag, keyof JSX.IntrinsicElements>` map; an `a` gets `rel="nofollow noopener"` and its `href` only when `isSafeHref`-equivalent (`http:`, `https:`, `mailto:`); unknown tags render their children. `EventWhen` shows the event-timezone text and, when `browserTimeZone()` differs and the event is timed, "Your time: …" via PR 3's `localTimeText`-style helpers.

- [ ] **Step 1: Write the failing tests:**
  - `RichText.test.tsx`: `renders allowed tags`, `drops unknown tags to children`, `never renders a script element` (a node `{"t":"script"}` renders its text only), `refuses javascript: href`, `no dangerouslySetInnerHTML` (a source scan of `ui/public/*.tsx` and `pages/Public*.tsx` finds the string only in `PublicHead.tsx`).
  - `PublicEvent.test.tsx`: `shows times in the event timezone`, `shows viewer time hint when the browser zone differs` (stub `Intl.DateTimeFormat().resolvedOptions().timeZone`), `all-day shows dates only and no hint`, `series lists next occurrences with date links`, `cancelled banner hides registration`, `rescheduled shows previous time`, `place modes`, `sub-events list`, `add to calendar links the .ics`, `language switch skips x-default`.
  - `PublicNotFound.test.tsx`: `shows suggestions and an index link`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/PublicEvent.test.tsx modules/events/sm_events/ui/public/RichText.test.tsx modules/events/sm_events/ui/page-tests/PublicNotFound.test.tsx`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, tsc, biome, `check_rules.py`, `check_locales.py`, `check_file_size.py`: all PASS.
- [ ] **Step 5: Commit** `feat(events): public event and not-found screens`.

**End of batch C.** Run the module suite (`-n 8`), `npx vitest run modules/events`, tsc, biome, `basedpyright`, `check_sibling_contracts.py`, `check_file_size.py` (no WARNING under `modules/events`).

---

### Task 20: `events-public.spec.ts` and the CSP check

**Files:**
- Create: `tests/e2e/events-public.spec.ts`
- Modify: `tests/e2e/start-test-server.sh` (set events `content_locales` to `["en","de"]` before boot with `scripts/set_setting.py`, a suite-wide setting; first check that `events.spec.ts` and `events-calendar.spec.ts` still pass with two locales and say so), `tests/e2e/production-csp.spec.ts` (`E2E_BUNDLE=1`: also open `/events/` with the calendar tab and one event page)

**Steps of the spec** (standalone: every slug is `uniqueSlug(...)`, everything seeded through the admin API in `beforeAll` with a logged-in context, then checked in a fresh anonymous `browser.newContext()`):
- Seed: a public calendar, an internal calendar; on the public one a published one-off with an `en` and a `de` text, a published weekly Europe/Vienna series with a moved and a cancelled occurrence and a skipped one, a draft; on the internal one a published event.
- [ ] **Step 1: Write the spec:**
  - `anonymous list shows only public published`: `/events/` lists the one-off and the series, not the draft or the internal event.
  - `calendar tab`: `?view=calendar` shows the grid; the month containing the series shows its chips; the draft's title is not on the page; no console CSP message (the `problems` collector of `events.spec.ts`).
  - `event page`: the one-off's page shows the title, local time, "Add to calendar"; `<script type="application/ld+json">` parses to `@type: Event`.
  - `series occurrence`: the moved occurrence's `?date=` page shows "Rescheduled"; the cancelled one shows the banner.
  - `ics download`: `page.request.get` on `calendar.ics` and the series' `.ics`: the text contains `RRULE:`, `EXDATE;TZID=Europe/Vienna`, `RECURRENCE-ID;TZID=Europe/Vienna`, `STATUS:CANCELLED`, the published UIDs, and not the draft's UID (read from the admin API in `beforeAll`).
  - `german prefix`: `/de/events/<de slug>` shows the German title and `html[lang=de]`; `/de/events/` lists the series with `lang="en"`.
  - `renamed slugs redirect`: rename the one-off's `en` slug and the calendar's slug through the API; the old event URL and the old `/events/c/<old>` land on the new ones (301 followed; assert `response.request().redirectedFrom()`).
  - `draft 404 identical to missing`: the draft's URL and `/events/no-such-<unique>` both answer 404 with the same visible heading and no draft title in the HTML.
  - `signed-in admin sees the same`: in the logged-in context `/events/` still has no draft.
- [ ] **Step 2: Run** (headroom first; one Playwright run at a time) `npx playwright test tests/e2e/events-public.spec.ts` against the e2e server: PASS. Then `E2E_BUNDLE=1 npx playwright test tests/e2e/production-csp.spec.ts`: PASS. Stop the server afterwards.
- [ ] **Step 3: Commit** `test(events): public pages and feeds end to end`.

### Task 21: Docs and branch verification

**Files:**
- Modify: `modules/events/docs/index.md` (status row), create or extend `modules/events/docs/operations.md` (the public prefix and its restart, locale prefixes and the alias redirect, the reserved slugs, caching: the lifetimes of Ruling 20, `public_cache_seconds = 0`, the shareable-tenant rule and why a CDN does not cache anonymous pages until the upstream `Set-Cookie` issue records documents is fixed, feeds: window, caps, `X-Events-Truncated`, refresh hints, rate limits, the CSP note) and `modules/events/docs/public.md` (user guide: what visitors see, the `?date=` address, subscribing from Outlook/Google/Apple, renaming slugs, cancelling vs skipping on the public side, `noindex`)
- Modify: `modules/events/README.md` (Usage: the public route table; status: PR 4 of 10), `CHANGELOG.md` (0.0.16 Added: public pages, ICS feeds, JSON-LD, sitemap, calendar redirects; the `icalendar` dependency), `docs/module-layout.md` (the events row: `feeds/`, `integrations/`)
- Modify: `CLAUDE.md`, the events paragraph only, two sentences: "The public surface (`web/endpoints/public/`, `feeds/`) never takes a viewer: every read starts from `core/access/public.py` (`public_events()`, `public_calendars()`) and answers the same no-store 404 for anything else, a redirect to a hidden target included. Feeds read event rows with their overrides (RRULE, EXDATE, RECURRENCE-ID with TZID) through that gate, never the occurrences read, and never emit a series without its EXDATEs."
- Modify: the spec's "Amendments" (add "Amendments (PR 4)": Rulings 4, 5, 9, 10, 14, 16, 18, 19, 20, 25, 30's series list and 31)

- [ ] **Step 1: Lint set** (headroom first), from the root: `uv run ruff check modules/events scripts host`; `uv run ruff format --check <files touched>`; `uv run basedpyright`; `npx biome check modules/events`; `npx tsc --noEmit -p modules/events/tsconfig.json`; `uv run python scripts/check_metadata.py`, `check_rules.py`, `check_sibling_contracts.py`, `moved_paths.py --check`, `check_ts_imports.py`, `check_readmes.py`, `check_hardcoded_strings.py`, `check_file_size.py` (no WARNING under `modules/events`), `check_locales.py`, `check_migration_heads.py`, `bump_version.py --check-current`. All PASS.
- [ ] **Step 2: Targeted suites, one at a time:** `cd modules/events && uv run pytest -q -n 8` on SQLite; the same on `smpy_events_test`; from the root `uv run pytest -q -n 8 scripts/tests host/tests/test_tenancy_parity.py host/tests/test_events_wiring.py host/tests/test_menu_labels.py host/tests/test_host_boots.py`; `npx vitest run modules/events`. All PASS. Do not run other modules' suites.
- [ ] **Step 3: Fresh-import check** for every new `modules/events/sm_events/**/*.py` (`uv run python -c "import …"`).
- [ ] **Step 4: Commit** `docs(events): public pages, feeds and caching`.
- [ ] **Step 5: Hand over to `/ship`.** Browser QA (anonymous window and signed-in window): the index list and calendar tab in `en` and `de`; a series occurrence that crosses 29 March in "my time" from a non-Vienna browser zone; a moved and a cancelled occurrence; the `.ics` imported into a real client if one is available (else validated with an online-free parser: `icalendar` round-trip of the downloaded file); a renamed calendar's old feed URL; the 404 for a draft; no CSP message in the console; view-source shows the injected head and JSON-LD. Screenshots of the index (list and grid), an event page, a cancelled occurrence and the German index go in the PR.

## Verification checklist (before `/ship`)

- Task 21 Step 1's lint set passes, `basedpyright` included.
- The events pytest passes on SQLite and Postgres; `scripts/tests` and the five host tests pass; `npx vitest run modules/events` passes; `events-public.spec.ts` and the bundle CSP spec pass.
- `alembic check` is clean on SQLite and Postgres after upgrade, downgrade and upgrade; `check_migration_heads.py` reports one head, the calendar-redirect revision.
- No file under `modules/events` is at 280 lines or more.
- `git diff --stat feat/events-pr3-calendar` touches only `modules/events/**`, `host/migrations/versions/<rev>_events_calendar_redirect.py`, `host/tests/test_events_wiring.py`, `scripts/tests/` (the parity family entry), `tests/e2e/events-public.spec.ts`, `tests/e2e/start-test-server.sh`, `tests/e2e/production-csp.spec.ts`, `uv.lock`, `CHANGELOG.md`, `CLAUDE.md`, `docs/module-layout.md`, the spec and this plan.
- The Review Focus tests exist and pass: grep for each test name listed there. `test_leaks.py` covers every surface: event page, `?date=`, `.ics`, both feeds, index, calendar page, API, sitemap, 404 suggestions, redirects.
- Nothing under `sm_events/core/tenancy/` changed (`git diff --stat feat/events-pr3-calendar -- modules/events/sm_events/core/tenancy` is empty).

## Open points

1. **A site frame for the other public pages.** Pagebuilder's contracts give another module its 404 only, so events' index and event pages render standalone, like news' articles. A site wanting its header and footer around them needs a `pagebuilder.contracts.site` addition (layout props for a tenant and locale) and a small frame component exported from `@simple-module-py/pagebuilder`. My recommendation: file it as an issue in this repo when the PR opens, for news and events together.
2. **Shared helpers copied a third time.** `viewer_key`, the head injection, `set_html_lang` and the JSON-LD escape now exist in pagebuilder, news and events. They belong in the framework (`simple_module_hosting`); file an upstream issue in `simple_module_python` with the three copies as the reproduction.
3. **Plugin sources in feeds** (spec: plain instances, 30 days back and 366 ahead, `UID <source>:<key>`) arrive with PR 6's registry; PR 4's feed read has the seam (`feeds/select.py` returns `FeedEvent`s; a plugin item type is added beside it).
4. **CDN caching of anonymous pages** is blocked upstream by the framework's per-request `Set-Cookie` (documented in records' `_public_cache.py`); the headers here help browsers and private caches until it is fixed. Link the existing upstream issue in the docs, or file one if none exists.
5. **A scheduled publish** becomes visible on the next request but a cached page or feed may lag by up to `public_cache_seconds` (the beat emits no bus event, PR 2 open point 2). Acceptable at 300 s; documented.
6. **The ★ rulings** most likely to change: sub-events of a hidden parent (4), the category filter rule (5), reserved slugs (9), the `?date=` address and 404 for skipped dates (10), list-first index and no past events (14), the cancelled page (16), the tree renderer instead of injected HTML (18), no site frame (19), cache lifetimes (20), the feed window and caps (25), the series JSON-LD list (30) and the sitemap bound (31).
