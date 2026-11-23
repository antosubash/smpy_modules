# Events PR 7: pagebuilder blocks and the newsletter event card. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A site author drops an "Upcoming events" list and a read-only events calendar onto a pagebuilder page, and an anonymous visitor sees only published events of public calendars there. A newsletter writer inserts an "Event card" into a campaign: it is a snapshot of a published public event (its next occurrence for a series), rendered in the email with the date in the event's timezone, a link to the event page and an "Add to calendar" link to its `.ics`.

**Architecture:** Events gains one sibling contract, `sm_events.contracts.cards`, built on PR 4's public gate (`core/access/public.py`) and the PR 2 occurrences read (which gains an `event_ids` filter), so a card sees exactly what the public event page sees. Newsletter reads it only from `content/integrations/events.py`, a guarded deferred import that mirrors `news.py`; the email side is a new `EventCard` block with its own props model, snapshot and refresh through the existing `cards.py` dispatch, and a renderer file of its own. The pagebuilder blocks live in events (`sm_events/pagebuilder-blocks.ts`, globbed only by pagebuilder), fetch client-side as `NewsFeed` does, from three anonymous, fixed-path routes under `/api/events/public/` that reuse PR 4's handlers, binder and cache policy. The calendar block is a `lazyBlock`, so FullCalendar's chunk loads only on a page that renders it.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy async, Babel (dates in the campaign's language), `zoneinfo`, pytest (SQLite, plus Postgres opt-in through each module's `tests/pg_support.py`), React 19, Puck (`@puckeditor/core` ^0.24), `@simple-module-py/pagebuilder` (`registerPuckBlocks`, `lazyBlock`), PR 3's `Calendar`, vitest (happy-dom), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`, Delivery row 7. It draws on "Integrations (optional extras)" (blocks over public calendars only; the card is a snapshot taken at insert; the lookup returns only published events of public calendars; a later privacy change does not recall a campaign), the anti-goals ("an internal or private event reaching the public: through … a pagebuilder block, a newsletter card lookup", "an event shown at the wrong time", "leaking across tenants") and "The calendar UI". Precedent plans: `2026-11-17-events-pr2-events.md` (structure; contracts, occurrences read, texts per locale), `-pr3-calendar.md` (Rulings 4–8: lazy adapter, `CalendarProps`), `-pr4-public.md` (Rulings 1, 2, 10, 12, 13, 20–22, 32–35: the gate, `?date=` addresses, calendar redirects, cache policy, the public occurrences endpoint, CSP), `-pr6-extensions.md` (Ruling 27: slots; plugin sources). The code precedents are news' blocks (`modules/news/news/pagebuilder-blocks.ts`, `ui/components/NewsFeed.tsx`, `NewsStats.tsx`, the `pagebuilder` extra and `peerDependenciesMeta`), images' `ImageGallery` (`modules/images/sm_images/ui/components/block/ImageGalleryBlock.tsx` and `ui/page-tests/pagebuilder-blocks.test.ts`), records' `RecordsListRender.tsx` (`puck.isEditing`), pagebuilder's `lazyBlock` (`modules/pagebuilder/pagebuilder/ui/components/lazyBlock.tsx`) and newsletter's card system (`modules/newsletter/sm_newsletter/content/integrations/`, `content/cards.py`, `content/blocks.py`, `content/render/`, `web/endpoints/cards_api.py`, `web/schemas/cards.py`, `ui/components/editor/{CardPicker.tsx,blocks/cards.tsx,puckConfig.tsx}`, and `tests/content/test_{integrations,cards,render_golden}.py`). The card contract's shape follows `modules/news/news/contracts/articles.py`.

## Depends on PRs 2–6

Before Task 1 the branch is rebased onto the finished `feat/events-pr6-extensions`. The batch A implementer **re-checks every name below against the real code first** and corrects this plan's references in the task text (never by renaming earlier PRs' code). Stop and report if a *behaviour*, not only a name, differs, in particular if `public_events()` can return anything but published, untrashed events of untrashed public calendars of the bound tenant, or if the occurrences read called with the anonymous principal can return a draft.

| Kind | Symbol this plan relies on |
|---|---|
| Gate (PR 4) | `sm_events.core.access.public`: `ANONYMOUS`, `public_calendars() -> Select[Calendar]`, `public_events() -> Select[Event]` |
| Read (PR 2) | `sm_events.calendar.occurrences.occurrences(db, *, tenant_id, viewer, start, end, filters, default_locale) -> OccurrencePage`; `sm_events.calendar.occurrence.Occurrence` (`event_id`, `original_start`, `start`, `end`, `all_day`, `start_date`, `end_date`, `timezone`, `title`, `lang`, `status`, `url`), `OccurrenceFilters(calendar_ids, category_ids, types, locale, include_unpublished)`; `sm_events.calendar.sources.EventsSource` (where the built-in SQL is), `sort_key` |
| Plugin sources (PR 6) | the place in the occurrences read where registered sources are merged (`calendar/plugin_runner.py`), and `OccurrencePage.sources` |
| Contracts (PR 2) | `sm_events.contracts.mounted(app)`, `sm_events/contracts/occurrences.py` (the file shape to copy), root `pyproject.toml` `[tool.pyright] include` already lists `modules/events/sm_events/contracts` |
| Public side (PR 4) | `web/endpoints/public/_api.py` `public_page(db, *, tenant, start, end, calendar_ids, category_ids, locale) -> OccurrencePage`; `_listing.upcoming(db, *, locale, default_locale, now, calendar_id, category_id) -> list[PublicListItem]`; `web/schemas/public.py` `PublicListItem`, `PublicCalendarOut`; `content/public_read.py` (category lookup "used by a public event"); `content/calendar_redirects.py` (resolve an old slug); `_cache.apply(…, kind="api", etag=…)`, `body_etag`, `PublicErrorRoute`; `_urls.event_path(slug, locale, date=None)`, `event_ics_path(slug, locale)`; `core/locales.py` `default()`/`supported()`; `core/boot.py` (auth exemption with `add_prefix`, `PUBLIC_API_RATE` rule registration); `machine_tenant`/`bind_public` |
| Time (PR 2) | `sm_events.calendar.times.all_day_dates`, `Span` |
| Models | `Event` (`id` UUID, `calendar_id`, `status`, `cancelled`, `starts_at`, `ends_at`, `rrule`, `recurrence_until`, `attendance_mode`, `venue_name`, `address`, `image`, `timezone`, `all_day`, `is_deleted`), `EventText` (`event_id`, `locale`, `slug`, `title`, `summary`), `Calendar` (`slug`, `name`, `color`, `default_timezone`, `visibility`); `ATTENDANCE_MODES = ("in_person", "online", "hybrid")` |
| Tenancy | `sm_events.core.tenancy.tenant_scope` (raises `ValueError` for an invalid id, `TenantIsolationError` for a different bound one). **Parity-checked: this PR edits no tenancy file in events or newsletter.** |
| TS (PR 3) | `@simple-module-py/events` (`sm_events/index.ts`): `Calendar`, `CalendarProps`, `CalendarInfo`, `FilterOption`, `CalendarView`; the lazy adapter; `ui/calendar/test-support/FakeGrid.tsx` and its `vi.mock('…/adapter/FullCalendarGrid')` pattern; the bundle check of PR 3 Task 15 |
| TS (PR 4) | `ui/public/api-public.ts` `publicFetcher(apiUrl): OccurrenceFetcher` |
| TS (PR 1) | `ui/utils/i18n.ts` (`keys`, `translate`, `Translate`, `useT`), `ui/page-tests/test-dom.tsx`, `support.tsx` (`stubFetch`) |
| Tests | events `tests/support/access.py` (`seed_calendars`, `P`/`I`/`U`), `tests/support/calendars.py` (`seed_event`), the `unbound_tenant` marker, `tests/web/public/test_leaks.py` (the parametrized leak harness); e2e `tests/e2e/helpers.ts` (`login`, `moduleCsrfHeader`, `uniqueSlug`) and PR 4's events seeding helpers |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**The card contract (`sm_events.contracts.cards`)**
1. **Surface.** `__all__ = ["MAX_EVENT_SEARCH_LIMIT", "EventCard", "get_event_card", "mounted", "search_events"]`. `mounted` is `sm_events.contracts.mounted`, re-exported so a caller imports one module (news' `contracts.articles` shape). The functions take no `app`: the public prefix and the default content locale come from PR 4's startup-published `_urls` and `core/locales`. If PR 4 made either read the app instead, all three functions take `app` as their first positional parameter (pagebuilder's `contracts.cards` shape), and Task 4 passes it.
2. **Raw fields, no formatted date.** The card carries the instants, the timezone and the all-day dates. The consumer formats them, because only it knows its language (newsletter: the campaign's). A formatted string from events would fix the language and the format in the wrong module.
3. **Who is found** (spec): only rows of PR 4's `public_events()` (published, not trashed, on an untrashed `public` calendar), with the tenant pinned twice: `with tenant_scope(tenant_id)` and `col(Event.tenant_id) == tenant_id` (and the same on `EventText` and `Calendar` in any join). An invalid `tenant_id` raises `ValueError` before any SQL. A strict session with nothing bound (`MissingTenantError`) answers `[]`/`None`. A non-`UUID` `event_id` and a non-`str` pattern raise `ValueError` (caller bugs). A draft, in-review, scheduled, trashed, internal, private or other-tenant event is `None` and never a search hit.
4. ★ **Which occurrence a card shows.** A one-off: itself, whatever its date. A series: its **next** occurrence, the first item of the occurrences read with `viewer=ANONYMOUS`, `include_unpublished=False`, `event_ids={id}` over `[now, now + MAX_RANGE_DAYS)` whose `end > now` (in progress counts). So skipped occurrences never appear, a moved one appears at its new time, and a cancelled one is `cancelled=True`, exactly as on the public page. A series with nothing in that window is `None` (not cardable, and not a hit). There is **no `occurrence` parameter** in v1: newsletter would never pass one, and it would be a second code path. The card names its occurrence by `occurrence_start` (the `original_start`), and its `path` is PR 4's `?date=` address (Ruling 10 there).
5. **Text and locale.** The text in `locale`, else the default content locale's, else the first by locale (PR 4 Ruling 12). `EventCard.locale` says which, and `path`/`ics_path` are in that locale.
6. **`EventCard`** (pydantic, frozen): `id: UUID`, `title`, `summary` (`""` when none), `starts_at`/`ends_at` (aware UTC, the occurrence's), `all_day`, `start_date`/`end_date` (`date | None`, all-day only, end exclusive), `timezone`, `occurrence_start: datetime | None` (series only), `attendance_mode`, `venue_name`, `address` (`""` when none), `image_url` (`event.image` as stored, `""` when none), `path`, `ics_path` (both site-relative), `locale`, `cancelled` (the event's flag or the occurrence's `status == "cancelled"`).
7. **Search.** `search_events(session, *, tenant_id, pattern, locale=None, limit=20, upcoming_only=True)`. `pattern` is a `LIKE` pattern with `\` as the escape; the caller owns escaping (news). It matches any of the event's text titles. `limit` must be an `int` (not `bool`) in `1..MAX_EVENT_SEARCH_LIMIT = 50`, else `ValueError`. Candidates: at most `CARD_SEARCH_SCAN = 50` gate rows that match, with `upcoming_only` prefiltering in SQL (one-off `ends_at > now`; series `recurrence_until IS NULL OR recurrence_until > now`), ordered by `starts_at, id`. Each candidate becomes a card by Ruling 4 (a series with nothing upcoming drops out). The result is sorted by `(starts_at, id)`, upcoming before past, and past one-offs (only with `upcoming_only=False`) newest first, then cut to `limit`. A writer narrows a long list by typing more; the scan bound is in the docs.
8. **`OccurrenceFilters.event_ids`** (new, `frozenset[UUID] | None = None`): the built-in source adds `Event.id IN (…)` to both its one-off and its series SQL. While it is set, plugin sources are not called (they have no event ids). This is the only change to PR 2/6 code in batch A.

**Newsletter**
9. **The `events` extra and its floor.** `events = ["simple_module_events>=0.0.16,<0.1"]` with the comment `# floor: 0.0.16 — the first events release, with contracts.cards`, plus `simple_module_events = { workspace = true }` in `[tool.uv.sources]`. The repo is at `0.0.15` and events has never been released, so the floor is the next lockstep version: `check_rules.py` accepts it with the comment, and `check_sibling_contracts.py` checks `sm_events.contracts.cards` and its names against the working tree (a floor one patch past the newest tag). The consequence is that newsletter 0.0.16 is installable with `[events]` only if events 0.0.16 is published in the same release, so Task 4 checks that the release workflow builds `modules/events` (PR 1 should have added it). A newsletter installed without the extra keeps working: the card is hidden.
10. **Babel is a direct dependency:** `babel>=2.12,<3` (newsletter imports it; today it arrives only through `simple_module_core`).
11. **`content/integrations/events.py`** is a copy of `news.py`'s guard: `_CONTRACT = "sm_events.contracts.cards"`, `importlib.import_module` in `_contract()` (never `from sm_events.contracts import cards`), `available(app)`, `_require(app)` raising `IntegrationUnavailable`, `search(…)` and `card(…)`. `capabilities(app)` gains `"events"`. It stays the only newsletter package that imports `sm_events` (a new guard test).
12. ★ **An event card is its own block, `EventCard`, with its own props model** (`EventCardProps`), not `CardProps`: its source id is a UUID string, and it carries times, place and the `.ics` link that article and page cards do not. Like the other cards, the block is always *defined*. A stored card renders from its snapshot without the module, and only the palette hides it (`hidden` category).
13. **Routes** (all under the existing `cards_api` router: `bind_admin`, `newsletter.edit`):
    - `GET /api/newsletter/cards/events?q=&locale=` → `list[EventHitOut]`, through `search(…, upcoming_only=True)`: a newsletter promotes what is coming.
    - `POST /cards/snapshot` takes a body discriminated on `kind`: `{kind: "article"|"page", source_id: int}` as today, or `{kind: "event", source_id: UUID}`. It answers `CardSnapshot | EventCardSnapshot`.
    - `POST /campaigns/{id}/cards/refresh` is unchanged and dispatches on the block's type.
    - Without the module: 409 `integration_unavailable` on search, snapshot and refresh of an event card. An unknown or hidden event: 404 on snapshot, 409 `card_source_gone` on refresh with the snapshot kept (existing codes).
    - The campaign list-access re-check is untouched: refresh still goes through `require_campaign` with the caller's roles.
14. ★ **Refresh rolls a series card forward.** It re-reads the card with Ruling 4, so a series card whose occurrence has passed moves to the next one. A one-off keeps its date. A series with nothing upcoming, or an event that is no longer public, gives 409 `card_source_gone` and keeps the snapshot. The editor shows "This date has passed. Refresh to show the next one" when the snapshot's `ends_at` is in the past.
15. **Rendering.** All of it is in a new `content/render/event_card.py`. `html._inner` and `text.block` dispatch `"EventCard"` to it.
    - **When** is formatted in the event's `timezone`, in the render's language `ctx.locale`. That is the host default language, the same as the footer's (newsletter R12): a campaign has no language of its own. It uses Babel `format_date(d, "full", locale)` and `format_time(t, "short", locale)`, and an unknown locale falls back to `en`.
      - Timed, same local day: `"{date}, {start}–{end} {zone}"`.
      - Timed, several days: `"{date}, {start} {zone} – {date}, {end} {zone}"`.
      - All-day: `"{date}"`, or `"{first} – {last}"` with the inclusive last day.
    - ★ **The zone** is the tzdata abbreviation, `aware_local.tzname()`, for example `CEST` or `EDT`. Where start and end differ (across DST), each time gets its own. It is not translated: Babel's short names are missing for most zones in English (`+0200`), and an email must name the zone the same way for every reader.
    - **HTML**, inside the existing `CELL`: the image (linked), a "Cancelled" badge when cancelled, the title (linked), the when-line, the place line, the excerpt, then the links "Read more" (event page) and, unless cancelled, "Add to calendar" (the `.ics`).
      - The place line: `venue_name, address` for `in_person`, `"Online"` for `online`, and both joined with ` · ` for `hybrid`.
      - Every href is made absolute with `url(ctx.content_base, …)`, the campaign tenant's public origin. Every value goes through `inert()`.
    - **Text part:** the lines `"{Cancelled}: {title}"` or `title`, then the when-line, the place line, the excerpt, the absolute event URL, and `"{Add to calendar}: {absolute ics}"` (omitted when cancelled). Empty lines are dropped.
    - New `newsletter.email.*` strings: `add_to_calendar`, `cancelled` and `online`, carried on `FooterCopy`. The `.ics` link is PR 4's single-event file, which holds the whole series.
16. **The snapshot rule, in the docs** (spec): a card is what the event said when it was inserted or last refreshed. Making the event private, cancelling it or trashing it later does not change a draft until Refresh, and never changes a campaign that has been scheduled (freeze uses the render snapshot).

**Pagebuilder blocks (shipped in events)**
17. **Packaging.** `sm_events/pagebuilder-blocks.ts` registers the blocks through `registerPuckBlocks`, each in its own `try`/`catch` (news' guard and comment). `@simple-module-py/pagebuilder` (`"*"`) is an optional peer in `peerDependenciesMeta`, with `@puckeditor/core` (`^0.24.0`) as a peer, as images has them. Python gains the extra `pagebuilder = ["simple_module_pagebuilder>=0.0.16,<0.1"]` with `# floor: 0.0.16 — events imports no pagebuilder Python; its pagebuilder-blocks.ts imports registerPuckBlocks and lazyBlock from the @simple-module-py/pagebuilder entry point (index.ts), first released in 0.0.16` (images' wording). This amends PR 4's "events gains no pagebuilder extra", which concerned Python imports. Only `pagebuilder-blocks.ts` and `ui/blocks/**` may import `@simple-module-py/pagebuilder`, and `index.ts` never imports `ui/blocks/`.
18. ★ **The blocks read three anonymous, fixed-path routes under `/api/events/public/`**, not `{public_prefix}/api/occurrences`. A block on a pagebuilder page cannot learn events' configurable prefix, and `/api/events` is a constant (`ROUTE_PREFIX_API`), like images' `/api/images/public/stats`. Each is a thin wrapper over a PR 4 function: the same gate, PR 4's machine binder (none resolved → 404), `PublicErrorRoute`, `_cache.apply(kind="api")` with a body ETag, a GET/HEAD auth exemption for the `/api/events/public/` prefix, and the `PUBLIC_API_RATE` rule. They sit on their own router, not under the `RequiresCsrf`/`bind_admin` API router.
    - `GET|HEAD /api/events/public/calendars?calendar=<slug>…&locale=` → `{calendars: [{id, slug, name, color, default_timezone}], categories: [{id, slug, name, color}], default_timezone}`. No `calendar`: every public calendar. With slugs: those that resolve, each through PR 4's calendar redirects; any other is dropped silently. Categories are those used by a public event (PR 4 Ruling 5), names in `locale`.
    - `GET|HEAD /api/events/public/upcoming?calendar=<slug>…&category=<slug>&count=&locale=` → `{items: PublicListItem[]}` over `[now, now + MAX_RANGE_DAYS)`, at most `count` (1–`UPCOMING_BLOCK_MAX = 20`, else 422).
    - `GET|HEAD /api/events/public/occurrences?…`: PR 4's `/api/occurrences`, the same parameters (calendar *ids*) and answer.
    - The data is fetched client-side, as `NewsFeed` and `RecordsList` do: pagebuilder renders a page's blocks in the browser, and a block's data has its own short cache, so it never goes stale inside the page's ETag.
19. **Calendars and the category are referenced by slug** (lead's rule), resolved on every request, so a renamed calendar keeps working through PR 4's redirects.
    - An empty calendar selection means every public calendar.
    - A non-empty selection that resolves to nothing means **nothing**, never a fallback to all.
    - A category slug that is not a public category means nothing (`items: []`), never unfiltered.
    - A chosen calendar that became internal, private or trashed is dropped without a trace: no error and no name. The editor sees only a count ("1 chosen calendar is not public or no longer exists", `puck.isEditing`). The stored slugs are in the page JSON that visitors receive. They were public when chosen, and a slug is not a name; this is documented.
    - `PublicListItem` gains `image: str | None` (http/https as stored). PR 4's `upcoming()` takes `calendar_ids: Sequence[UUID] | None` instead of `calendar_id`, and its own callers pass `[id]` or `None`.
20. ★ **The pickers read the anonymous calendars route, not the console list.** It lists exactly what a block can render, needs no `events.view` (a page editor may not have it), and cannot leak. The lead's "console route" would have been `GET /api/events/calendars`, filtered client-side as images does.
21. **`UpcomingEvents`** (palette label "Upcoming events"). Props:
    - `heading` (≤ 200 characters, default "Upcoming events");
    - `calendars: {slug: string}[]` (an array field, ≤ `BLOCK_CALENDARS_MAX = 10`, rows chosen from a select);
    - `category` (slug or `""`);
    - `count` (1–20, default 5, clamped on `load` and at render as `NewsFeed` does);
    - `layout: 'list' | 'cards'`;
    - `showImages` (default true; `cards` only).

    Each item shows the date and time (the event's local time; all-day as dates; `lang` marked for a fallback text, PR 4 Ruling 12), the title linked to the item's `url`, the place and, in cards, the summary and image. Cancelled and rescheduled items are marked as on PR 4's index. The language is the page's (a copy of news' `useContentLocale`, never a block field), passed as `locale`. While loading, or when empty, or when the fetch fails, the block renders `<></>` (NewsFeed). In the editor an empty result shows an "editor only" hint.
22. **`EventsCalendar`** (palette label "Events calendar"). Props:
    - `calendars` (as above);
    - `defaultView: 'month' | 'week' | 'day' | 'list'` (default month);
    - `height: 'compact' | 'medium' | 'tall'` (min-heights 480, 640 and 800 px; no free number).

    It renders PR 3's `Calendar` **read-only** (no `editing`): `calendars` mapped to `CalendarInfo` (`visibility: 'public'`, `can_write_events: false`), the public categories as its filter, `defaultTimezone` from the route, and `fetchOccurrences={publicFetcher('/api/events/public/occurrences')}` limited to the resolved ids. It registers through `lazyBlock(() => import('./ui/blocks/EventsCalendarRender'))` with a skeleton fallback of the chosen height. So neither the block's render code nor `Calendar` is in the eagerly imported registration graph, and PR 3's lazy adapter keeps FullCalendar out of everything but the grid's own chunk. It uses PR 6's `buildSlots('public')`, so plugin types render their public chips.
23. **Labels.** The blocks are module-scope constants, so their static labels are catalogue keys, resolved by pagebuilder's `localizeConfig` (news' floor comment). Fields built in `resolveFields` (the calendar and category selects, filled once the route answers) run after that, so events resolves them itself with `ui/blocks/localizeFields.ts`. That resolver translates every `label`, every `options[].label`, and recurses into `arrayFields` and `objectFields`, which pagebuilder's resolver also does. Keys live under `events.blocks.*` in both `en.json` and `de.json`.
24. **Page-only:** no `layout: true` (news: a list in the header or footer would repeat on every page). Palette group `{ key: 'events', title: keys.events.blocks.palette_group }`.
25. **The Puck canvas shows live data:** the same render and the same anonymous routes as the public page (NewsFeed, RecordsList), so an author sees what a visitor will see. Only the "editor only" hints read `puck.isEditing`.
26. **Bundles and restores.** Blocks store slugs, and pagebuilder's bundle carries page JSON as it is. Restored on another host, a block shows that host's public calendars with those slugs, if any, and otherwise nothing (with the editor hint). No bundle section is added.
27. **CSP.** `/p/{slug}` responses carry pagebuilder's `public_csp` (`script-src 'self'`, `connect-src 'self'`, `style-src 'self' 'unsafe-inline'`), which allows a same-origin `import()` chunk, same-origin `fetch` and FullCalendar's inline styles. Events sets no CSP of its own (PR 4 Ruling 35). The e2e spec fails on any `Content Security Policy` console message on a page holding both blocks.

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, vite build, Playwright, alembic or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. At most one Playwright run at a time, and stop its server when it is done. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr7` on branch `feat/events-pr7-integrations`, which is stacked on `feat/events-pr6-extensions` → PR 5 → PR 4 → PR 3 → PR 2 → PR 1. Before Task 1, rebase onto the finished PR 6 branch and run the "Depends on" check. Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points and `npx` from the worktree root, and module tests from the module directory (`cd modules/events && uv run pytest …`, `cd modules/newsletter && uv run pytest …`).
- Implementers are Claude subagents. Each runs pytest in the foreground, commits its own tasks (one commit per task) and never pushes.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- Names: package `sm_events`, npm `@simple-module-py/events`, locale namespaces `events` and `newsletter`, block types `UpcomingEvents`, `EventsCalendar` and `EventCard`, card kind `"event"`, the public block API prefix `/api/events/public`.
- Version stays `0.0.15` (`uv run python scripts/bump_version.py --check-current`).
- Pins are ranges, never `==`. New requirements:
  - newsletter: `events` extra `simple_module_events>=0.0.16,<0.1` (Ruling 9's floor comment), and the dependency `babel>=2.12,<3`;
  - events: the `pagebuilder` extra of Ruling 17;
  - npm (events): peers `@simple-module-py/pagebuilder` (optional) and `@puckeditor/core`.

  Nothing else.
- Settings stay DB-backed with no environment reads. This PR adds no settings field.
- Every query on an events table runs with a tenant bound and pinned. Core statements carry their own `tenant_id` predicate. `all_tenants()` is not used in this PR.
- Do not edit any `core/tenancy/*` file in events or newsletter (parity families).
- Modules reach each other only through `contracts`, behind guarded deferred imports: newsletter → `sm_events.contracts.cards` from `content/integrations/events.py` only. `scripts/check_sibling_contracts.py` and `scripts/check_ts_imports.py` must pass. Newsletter's frontend never imports `@simple-module-py/events`.
- 300-line cap; keep every `.py`/`.ts`/`.tsx` under 280 lines. The files near it, and where each splits:
  - `newsletter/content/blocks.py` (213 today) stays ≤ 255;
  - `CardPicker.tsx` (237) moves `CardHits` to `CardHits.tsx` before it grows;
  - `render/html.py` (187) gets only the dispatch line;
  - `CampaignEditor.tsx` (241) gets at most 3 lines.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`). The new bounds live there: `MAX_EVENT_SEARCH_LIMIT`, `CARD_SEARCH_SCAN`, `UPCOMING_BLOCK_MAX`, `UPCOMING_BLOCK_DEFAULT`, `BLOCK_CALENDARS_MAX` and `PUBLIC_BLOCKS_API = f"{ROUTE_PREFIX_API}/public"`.
- Nothing new goes under any `pages/` folder (`check_rules.py`): block code lives in `sm_events/ui/blocks/`, and newsletter's in `ui/components/editor/`.
- `en.json` and `de.json` keep identical key trees and placeholders, in both modules (`scripts/check_locales.py`).
- Postgres checks use dev-services' Postgres and scratch databases (`smpy_events_test` and `smpy_newsletter_test` for pytest). Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **Private data reaching the public through a card or a block.** These must never reach a search hit, a card, a refresh, any `/api/events/public/*` answer or a rendered block, in any of `id`, `title`, `slug`, calendar `name` or category `name`:
   - a draft, in-review or scheduled event;
   - a published event of an internal or private calendar;
   - a trashed event, or an event of a trashed calendar;
   - a skipped occurrence.

   Pinned by `test_cards_contract.py::test_hidden_events_never_carded[draft|in_review|scheduled|internal|private|trashed|calendar_trashed]` and by new rows in PR 4's `test_leaks.py` (`test_hidden_event_absent_everywhere` over the three block routes). Also by `test_public_blocks_api.py::test_calendar_turned_internal_vanishes_without_name`, and in the browser by `events-blocks.spec.ts`'s "calendar made internal" step.
2. **Tenant pinning in the contract.** Named tenant `b` while nothing is bound returns only `b`'s events. Naming `b` while `a` is bound raises `TenantIsolationError`. An invalid id raises `ValueError` with no SQL run, and a strict session with nothing bound returns `[]`/`None`. Pinned by `test_cards_contract.py::test_tenant_pinned_when_unbound` (`unbound_tenant`), `test_other_bound_tenant_refused`, `test_invalid_tenant_no_sql` (an event listener counts statements) and `test_strict_session_unbound_is_empty`.
3. **Cache poisoning across tenants on the block routes.** An answer for a tenant picked by header, subdomain or upstream state is never `public`, and it carries the tenant header in `Vary`. Two tenants with the same query get different bodies and different ETags. A guessed `If-None-Match` for a hidden calendar's slug gets 200 `{"calendars": []}`, never a 304 that reveals a tag. Pinned by `test_public_blocks_api.py::test_request_tenant_never_shareable`, `test_two_tenants_two_etags` and `test_etag_only_over_visible_body`.
4. **Sibling floors, boundaries and a missing sibling at import time.**
   - Python: `sm_newsletter.module`, `cards_api` and `content.cards` import with `sys.modules["sm_events"] = None` (`test_integrations.py::test_newsletter_imports_without_events`). A blocked contract import gives `available() is False` and 409 on every event route (`test_event_routes_unavailable`). `check_sibling_contracts.py` passes, and `check_rules.py` accepts both new floors. `test_packaging.py` pins the extras.
   - TS: `@simple-module-py/pagebuilder` is imported only by `pagebuilder-blocks.ts` and `ui/blocks/**`, and `index.ts` never reaches `ui/blocks/` (`ui/blocks/boundary.test.ts`). Newsletter defines `EventCard` with `events: false` and hides it from the palette (`puckConfig.test.ts`).
5. **FullCalendar in a public bundle.** No eager import chain from `pagebuilder-blocks.ts` reaches `Calendar` or `@fullcalendar/*` (`boundary.test.ts::registration graph is lazy for the calendar`). A production build puts `@fullcalendar` only in a lazy chunk, not in the entry or the blocks' chunk (PR 3 Task 15's manifest check, rerun in Task 12). The e2e spec loads `/p/<slug>` holding only `UpcomingEvents` and asserts no request for the grid chunk.
6. **Wrong time in an email.** A 10:00 Europe/Vienna event renders `10:00 CEST` in July and `10:00 CET` in January. An all-day event on 29 March (a 23-hour day) renders as that one date. A multi-day all-day event shows its inclusive last day. A timed event crossing the DST change names both zones. Pinned by `test_event_card_render.py::test_when_*` with exact strings in `en` and `de`.

---

## File structure

| File | Responsibility | Target lines |
|---|---|---|
| events `calendar/occurrence.py`, `calendar/sources.py`, the plugin merge | `event_ids` filter | +15 |
| events `content/cards.py` | `EventCard` assembly: gate rows → card (Rulings 4–6) | 200 |
| events `contracts/cards.py` | the contract surface, tenant pinning, limits | 130 |
| events `web/endpoints/public/_blocks_api.py` | the three `/api/events/public/*` routes | 170 |
| events `pagebuilder-blocks.ts` | guarded registrations | 60 |
| events `ui/blocks/api-blocks.ts` | typed fetchers for the block routes | 70 |
| events `ui/blocks/localizeFields.ts` | key → text over fields, recursive | 60 |
| events `ui/blocks/usePageLocale.ts` | the page's language (news' hook, rewritten) | 40 |
| events `ui/blocks/calendarField.ts` | shared `calendars` array field and select loading | 90 |
| events `ui/blocks/UpcomingEventsBlock.tsx` / `UpcomingEventsRender.tsx` | config / render | 120 / 200 |
| events `ui/blocks/EventsCalendarBlock.tsx` / `EventsCalendarRender.tsx` | config (lazy) / render | 90 / 120 |
| newsletter `content/integrations/events.py` | guarded contract access | 100 |
| newsletter `content/integrations/hits.py` | `+ EventHit` | +35 |
| newsletter `content/event_snapshot.py` | `EventHit` → `EventCardProps` dict | 80 |
| newsletter `content/render/event_card.py` | when-line, HTML, text | 200 |
| newsletter `ui/components/editor/blocks/eventCard.tsx` | canvas view of the snapshot | 140 |
| newsletter `ui/utils/eventWhen.ts` | the editor's when-line (`Intl`) | 60 |
| newsletter `ui/components/editor/CardHits.tsx` | hit list, extracted, event when-line | 80 |

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events and newsletter suites green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: the cards contract** | 1–3 | constants and the `event_ids` filter; card assembly; `contracts.cards` |
| **B: the newsletter event card** | 4–8 | the extra and the guarded integration; the block, snapshot and refresh; routes; rendering and goldens; the editor |
| **C: pagebuilder blocks, e2e, docs** | 9–14 | the public block routes; TS foundations; `UpcomingEvents`; `EventsCalendar` and registration; e2e; docs and verification |

---

### Task 1: Constants and the `event_ids` filter

**Files:**
- Modify: `modules/events/sm_events/core/constants.py` (the bounds of Global Constraints: `MAX_EVENT_SEARCH_LIMIT = 50`, `CARD_SEARCH_SCAN = 50`, `UPCOMING_BLOCK_MAX = 20`, `UPCOMING_BLOCK_DEFAULT = 5`, `BLOCK_CALENDARS_MAX = 10`, `PUBLIC_BLOCKS_API`)
- Modify: `sm_events/calendar/occurrence.py` (`OccurrenceFilters.event_ids`), `sm_events/calendar/sources.py` (the built-in source's SQL), the PR 6 plugin merge (skip plugin sources while `event_ids` is set)
- Test: `tests/calendar/test_occurrences.py` (add)

**Interfaces:** produces `OccurrenceFilters(event_ids: frozenset[uuid.UUID] | None = None)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_event_ids_filter`: three published events (a one-off, a weekly series, another one-off); `event_ids={series.id}` returns only the series' instances; an empty `frozenset()` returns nothing.
  - `test_event_ids_skips_plugin_sources`: with a fake registered source enabled on the calendar (PR 6's test registry helper), `event_ids` set gives no plugin items and no `sources` status entry for it.
  - `test_event_ids_keeps_overrides`: a skipped instance is absent and a moved one is at its new time.
- [ ] **Step 2: Run** (headroom first) `cd modules/events && uv run pytest -q tests/calendar/test_occurrences.py`: FAIL.
- [ ] **Step 3: Implement.** `col(Event.id).in_(ids)` in both the one-off and the series select. No change to ordering, caps or truncation.
- [ ] **Step 4: Run** it (PASS), then `uv run python scripts/check_hardcoded_strings.py` from the root (PASS).
- [ ] **Step 5: Commit** `feat(events): an event_ids filter on the occurrences read`.

### Task 2: Card assembly

**Files:**
- Create: `sm_events/content/cards.py`
- Test: `tests/content/test_cards.py`

**Interfaces:**

```python
class EventCard(BaseModel): ...          # Ruling 6, frozen; defined here, re-exported by the contract
async def card_for(db, event: Event, texts: dict[str, EventText], *, locale: str | None,
                   default_locale: str, now: datetime) -> EventCard | None   # Rulings 4-6
async def cards_for(db, rows: Sequence[Event], *, tenant_id: str, locale: str | None,
                    now: datetime) -> list[EventCard]   # one texts query, then card_for per row
```

`card_for` calls the occurrences read with `viewer=ANONYMOUS`, `start=now`, `end=now + MAX_RANGE_DAYS`, `OccurrenceFilters(event_ids={event.id}, include_unpublished=False)`, and takes the first item with `end > now`. A one-off outside that window still gets a card, built from its own row (`starts_at`/`ends_at`, PR 2's `all_day_dates` for an all-day one). `path` is `_urls.event_path(text.slug, text.locale, date)`, where `date` is the local date of `original_start` for a series instance and `None` for a one-off. `ics_path` is `_urls.event_ics_path(…)`.

- [ ] **Step 1: Write the failing tests** (rows through `seed_event`, `now` fixed at 2026-07-01T08:00Z):
  - `test_one_off_card_fields`: every Ruling 6 field. `path == "/events/<slug>"`, `ics_path == "/events/<slug>.ics"`, `occurrence_start is None`, `summary == ""` when there is none.
  - `test_past_one_off_still_carded`: an event that ended yesterday keeps its own times.
  - `test_series_next_occurrence`: a weekly Wednesday 10:00 Vienna series started in May gives `starts_at == 2026-07-01T08:00Z` (in progress at `now` counts), `occurrence_start` equal to it, and `path == "/events/<slug>?date=2026-07-01"`.
  - `test_series_skips_and_moves`: with the next instance skipped, the card is the one after it; with it moved, the card has the new times and the original date in `path`.
  - `test_cancelled`: the event flag and a `cancelled` override each give `cancelled=True`.
  - `test_ended_series_is_none`: a `COUNT=2` series that ended in June gives `None`.
  - `test_all_day_dates`: an all-day event on 2026-03-29 in Vienna gives `start_date == 2026-03-29` and `end_date == 2026-03-30`.
  - `test_text_fallback`: `locale="de"` without a `de` text gives the `en` text, `locale == "en"` and the `en` path. With a `de` text, `path` starts `/de/events/`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_cards.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): event cards for published public events`.

### Task 3: `contracts.cards`

**Files:**
- Create: `sm_events/contracts/cards.py`
- Test: `tests/contracts/test_cards_contract.py`

**Interfaces:**

```python
MAX_EVENT_SEARCH_LIMIT: int                     # from constants
async def search_events(session: AsyncSession, *, tenant_id: str, pattern: str,
                        locale: str | None = None, limit: int = 20,
                        upcoming_only: bool = True) -> list[EventCard]       # Ruling 7
async def get_event_card(session: AsyncSession, *, tenant_id: str, event_id: uuid.UUID,
                         locale: str | None = None) -> EventCard | None      # Rulings 3-4
def mounted(app: Any) -> bool                   # re-export
```

Both functions run inside `with tenant_scope(tenant_id):`, start from `public_events()`, add `col(Event.tenant_id) == tenant_id`, catch `MissingTenantError`, and pass `now = utcnow()` (events' clock) to `cards_for`. In this file, SQLModel columns go through `sqlmodel.col()`.

- [ ] **Step 1: Write the failing tests:**
  - `test_hidden_events_never_carded[...]` (Review Focus 1): for each hidden kind, `get_event_card` is `None` and a search on its exact title returns `[]`. A published public twin with the same title is found.
  - `test_search_matches_any_locale_title_and_escapes`: a `de`-only title matches. The caller-escaped pattern `like_contains_pattern("50%")` matches `"50% off"` only, and not `"500 off"`.
  - `test_upcoming_only`: a past one-off is excluded by default, and included with `upcoming_only=False` after the upcoming ones, newest first.
  - `test_order_and_limit`: hits are by next start, cut to `limit`.
  - `test_limits`: `limit` of `0`, `51`, `True` and `"5"` raise `ValueError`.
  - `test_bad_event_id`: `event_id="x"` raises `ValueError`, and an unknown UUID gives `None`.
  - `test_tenant_pinned_when_unbound` (`unbound_tenant`); `test_other_bound_tenant_refused`; `test_invalid_tenant_no_sql` (`tenant_id="bad tenant!"` raises `ValueError`, and a `before_cursor_execute` listener counts 0 statements); `test_strict_session_unbound_is_empty`.
  - `test_mounted` and `test_contract_surface` (`__all__`, Ruling 1).
- [ ] **Step 2: Run** `uv run pytest -q tests/contracts/test_cards_contract.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and on Postgres (`smpy_events_test`): PASS. From the root: `uv run basedpyright` (0 errors) and `uv run python scripts/check_sibling_contracts.py` (PASS).
- [ ] **Step 5: Commit** `feat(events): the cards contract for newsletter`.

### Task 4: The `events` extra and the guarded integration

**Files:**
- Modify: `modules/newsletter/pyproject.toml` (the extra with its floor comment, `babel>=2.12,<3`, `[tool.uv.sources] simple_module_events`), `uv.lock`
- Create: `sm_newsletter/content/integrations/events.py`
- Modify: `content/integrations/__init__.py` (`capabilities` gains `"events"`, and the docstring names events), `content/integrations/hits.py` (`EventHit`)
- Modify: `tests/pg_support.py` `_extra_metadata` (events' `Base.metadata`, under the same `ImportError` guard as news)
- Create: `tests/support/events_seed.py` (rows written straight to events' tables under `sm_events.core.tenancy.tenant_scope`; a test-only import, as `news_seed.py` is)
- Test: `tests/core/test_packaging.py`, `tests/content/test_integrations.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class EventHit:            # hits.py
    kind: Literal["event"]; source_id: str  # canonical UUID text
    title: str; excerpt: str; image_url: str; url: str; ics_url: str; locale: str
    starts_at: datetime; ends_at: datetime; all_day: bool
    start_date: date | None; end_date: date | None; timezone: str
    attendance_mode: str; place: str  # "venue, address" or ""
    cancelled: bool
# events.py
def available(app) -> bool
async def search(app, session, *, tenant_id: str, q: str, locale: str | None) -> list[EventHit]
async def card(app, session, *, tenant_id: str, source_id: str) -> EventHit | None
    # an unparsable UUID -> None without asking the contract
```

- [ ] **Step 1: Write the failing tests:**
  - `test_packaging.py::test_extras_and_floors`: adds `extras["events"] == ["simple_module_events>=0.0.16,<0.1"]` and `"babel>=2.12,<3" in dependencies`.
  - `test_integrations.py`:
    - `test_unavailable_when_not_mounted` and `test_unavailable_when_import_blocked` extended to events (`sys.modules["sm_events.contracts.cards"] = None`);
    - `test_capabilities_dict` with three keys;
    - `test_event_card_maps_the_contract` (a monkeypatched `get_event_card` returning an `EventCard`: the hit is renamed field by field, and `source_id="nope"` gives `None` with no call);
    - `test_event_search_passes_escaped_pattern_and_upcoming`;
    - `test_newsletter_imports_without_events`: in a subprocess with `sys.modules["sm_events"] = None` set before import, `import sm_newsletter.module, sm_newsletter.web.endpoints.cards_api, sm_newsletter.content.cards` succeeds;
    - `test_only_integrations_import_sm_events`: no `.py` under `sm_newsletter/` outside `content/integrations/` mentions `sm_events`.
- [ ] **Step 2: Run** (headroom first) `cd modules/newsletter && uv run pytest -q tests/core/test_packaging.py tests/content/test_integrations.py`: FAIL.
- [ ] **Step 3: Implement.** Then run `uv sync --all-packages --all-extras --no-extra anonymize` from the root (headroom first). Check that `.github/workflows/release.yml` builds every `modules/*` (or names events). If it does not, add events there and say so in the commit.
- [ ] **Step 4: Run** the tests (PASS), then from the root `uv run python scripts/check_rules.py` and `check_sibling_contracts.py` (both PASS).
- [ ] **Step 5: Commit** `feat(newsletter): optional events integration through sm_events.contracts.cards`.

### Task 5: The `EventCard` block, snapshot and refresh

**Files:**
- Modify: `sm_newsletter/content/blocks.py` (`"EventCard"` in `BLOCK_TYPES`, `EventCardProps`, `EventCardBlock` in the union)
- Create: `sm_newsletter/content/event_snapshot.py`
- Modify: `sm_newsletter/content/cards.py` (`_SOURCES["event"] = events`, `_KIND_OF_BLOCK["EventCard"] = "event"`, snapshot/refresh dispatch, `source_id: int | str`)
- Test: `tests/content/test_blocks.py`, `tests/content/test_event_cards.py`

**Interfaces:**

```python
class EventCardProps(_Props):
    source_id: Annotated[str, Field(pattern=UUID_RE)]
    title: ≤300 = ""; excerpt: ≤1000 = ""; image_url: ImageUrl = ""; url: Link; ics_url: Link
    locale: ≤16 = ""; starts_at: AwareDatetime; ends_at: AwareDatetime; all_day: bool = False
    start_date: date | None = None; end_date: date | None = None
    timezone: str   # a known IANA name (zoneinfo), ≤64
    attendance_mode: Literal["in_person", "online", "hybrid"] = "in_person"
    place: ≤500 = ""; cancelled: bool = False; snapshot_at: AwareDatetime
    # model validator: ends_at > starts_at; all_day iff both dates set and start_date < end_date
def event_snapshot_props(hit: EventHit, *, block_id: str, now: datetime) -> dict[str, Any]
    # clipped like snapshot_props; a url or ics_url the body refuses -> CardSourceGone; a refused image dropped
```

- [ ] **Step 1: Write the failing tests:**
  - `test_blocks.py`:
    - `test_event_card_props_valid`;
    - `test_event_card_props_refused`, parametrized over a non-UUID `source_id`, `ends_at <= starts_at`, `all_day` without dates, an unknown timezone, a `javascript:` `ics_url`, a naive `starts_at` and an extra key: each is `InvalidBody` naming the path only.
  - `test_event_cards.py` (events rows through `events_seed`, `APP` with `sm_events` mounted):
    - `test_snapshot_event_from_contract`: the props validate, and `url`/`ics_url` are site-relative.
    - `test_snapshot_hidden_event_404` (draft, internal).
    - `test_refresh_rolls_series_forward`: freeze the clock past the snapshotted occurrence; after refresh the card has the next date and the block keeps its id.
    - `test_refresh_one_off_keeps_date`.
    - `test_refresh_gone_keeps_snapshot`: the event is made internal; refresh gives `CardSourceGone`, and the stored body and revision are unchanged.
    - `test_refresh_unavailable`: with events not mounted, refreshing an `EventCard` raises `IntegrationUnavailable`, and an `ArticleCard` in the same body still refreshes.
    - `test_snapshot_survives_privacy_change`: a draft holding an event card still parses and renders after the event is trashed (spec snapshot rule).
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_blocks.py tests/content/test_event_cards.py tests/content/test_cards.py`: FAIL.
- [ ] **Step 3: Implement.** `refresh_block` asserts `isinstance(block.props, (CardProps, EventCardProps))`.
- [ ] **Step 4: Run** them: PASS, with the existing card tests unchanged.
- [ ] **Step 5: Commit** `feat(newsletter): the event card block, snapshot and refresh`.

### Task 6: Event card routes

**Files:**
- Modify: `sm_newsletter/web/schemas/cards.py` (`EventHitOut`, `EventSnapshotRequest`, `SnapshotRequest` as an `Annotated[… | …, Field(discriminator="kind")]`, `EventCardSnapshot`)
- Modify: `sm_newsletter/web/endpoints/cards_api.py` (`GET /cards/events`, and snapshot dispatch)
- Test: `tests/web/test_cards_api.py` (add to it)

**Interfaces:** `GET /api/newsletter/cards/events?q=&locale=` → `list[EventHitOut]`; `POST /api/newsletter/cards/snapshot` → `CardSnapshot | EventCardSnapshot` (Ruling 13).

- [ ] **Step 1: Write the failing tests:**
  - `test_search_events_route`: a published public upcoming event is found; a draft, an internal one and a past one are not.
  - `test_snapshot_event_route`: `{kind: "event", source_id: "<uuid>"}` gives 200 with `EventCardSnapshot` fields. `{kind: "event", source_id: 7}` and `{kind: "article", source_id: "<uuid>"}` give 422.
  - `test_event_routes_unavailable` (Review Focus 4): with the contract import blocked, search, snapshot and refresh of an event card give 409 `integration_unavailable`, while article routes keep working.
  - `test_needs_edit_permission`: 403 without `newsletter.edit`.
  - `test_multi_tenant_search_pins_bound_tenant`: tenant `b`'s event is never a hit for `a`.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_cards_api.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): search and snapshot routes for event cards`.

### Task 7: Rendering and goldens

**Files:**
- Create: `sm_newsletter/content/render/event_card.py`
- Modify: `content/render/html.py` and `text.py` (dispatch), `render/types.py` (`FooterCopy.add_to_calendar`, `.cancelled`, `.online`, with English defaults), `render/styles.py` (`CARD_META`, `CARD_BADGE`), `content/context.py` (`_KEYS`), `locales/en.json`/`de.json` (`email.add_to_calendar` "Add to calendar"/"Zum Kalender hinzufügen", `email.cancelled` "Cancelled"/"Abgesagt", `email.online` "Online"/"Online")
- Modify: `tests/content/test_render_golden.py` (one timed `EventCard` in `KITCHEN_SINK`; a new `event_cards` case in `de` with a timed, an all-day multi-day, a cancelled and an online card), `tests/content/golden/*` (regenerated)
- Test: `tests/content/test_event_card_render.py`

**Interfaces:**

```python
def when(p: EventCardProps, locale: str) -> str      # Ruling 15
def html(p: EventCardProps, ctx: RenderContext) -> str
def text(p: EventCardProps, ctx: RenderContext) -> str
```

- [ ] **Step 1: Write the failing tests** (`test_event_card_render.py`):
  - `test_when_timed_same_day`: en `"Wednesday, July 1, 2026, 10:00 AM–11:30 AM CEST"`, de `"Mittwoch, 1. Juli 2026, 10:00–11:30 CEST"`.
  - `test_when_winter_zone`: a January event gives `CET`.
  - `test_when_multi_day_timed`: `"…, 6:00 PM CEST – Thursday, July 2, 2026, 9:00 AM CEST"`.
  - `test_when_all_day_short_day`: 29 March in Vienna gives `"Sunday, March 29, 2026"`.
  - `test_when_all_day_range_inclusive`: 1–3 August gives `"Saturday, August 1, 2026 – Monday, August 3, 2026"`.
  - `test_when_across_dst`: 2026-10-25 01:30–03:30 Vienna gives `"…, 1:30 AM CEST–3:30 AM CET"`.
  - `test_when_unknown_locale_falls_back_to_en`.
  - `test_html_links_absolute_and_inert`: the hrefs start with `ctx.content_base`, the `.ics` link is present, and a title holding `{{first_name}}` and `<b>` comes out escaped with no `{{`.
  - `test_cancelled_badge_no_calendar_link`: the badge is there and the `.ics` link is not; the text part starts `"Cancelled: "`.
  - `test_place_lines`: in person `"Hall 1, Main St 2"`, online `"Online"`, hybrid `"Hall 1, Main St 2 · Online"`.
  - `test_text_part_lines`: the exact line list.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_event_card_render.py tests/content/test_render_golden.py`: FAIL.
- [ ] **Step 3: Implement.** Then regenerate with `NEWSLETTER_UPDATE_GOLDEN=1 uv run pytest -q tests/content/test_render_golden.py` and review the diff. Only the new card rows and the new `event_cards.*` files may change.
- [ ] **Step 4: Run** both files again without the variable (PASS), plus `tests/content/test_render.py` and `tests/content/test_context.py` (PASS).
- [ ] **Step 5: Commit** `feat(newsletter): render event cards in the HTML and text parts`.

### Task 8: The editor's Event card

**Files:**
- Modify: `ui/utils/types.ts` (`'EventCard'` in the block union; `CardKind` gains `'event'`; `EventCardHit`, `EventCardSnapshot`; `source_id: number | string` on hits), `ui/utils/api.ts` (`snapshot(kind, source_id: number | string)`)
- Create: `ui/components/editor/CardHits.tsx` (moved out of `CardPicker.tsx`; an event hit shows its when-line and a "Cancelled" marker), `ui/utils/eventWhen.ts`, `ui/components/editor/blocks/eventCard.tsx`
- Modify: `ui/components/editor/CardPicker.tsx` (`CARD_TYPE.event = 'EventCard'`, the search placeholder per kind, and the "date has passed" hint of Ruling 14), `puckConfig.tsx` (`Capabilities.events`, `EventCard` in `cards`/`hidden`), `ui/utils/bodyDraft.ts` (`isComplete` for `EventCard`: a non-empty `source_id` string and `url`), `pages/CampaignEditor.tsx` (pass `events`), `locales/en.json`/`de.json` (`blocks.event_card.label` "Event card"/"Veranstaltungskarte", `editor.card.event`, `editor.card.search_event`, `editor.card.date_passed`)
- Test: `puckConfig.test.ts`, `CardPicker.test.ts`, `ui/components/editor/blocks/eventCard.test.tsx`, `ui/utils/eventWhen.test.ts`, `ui/utils/bodyDraft.test.ts`, `tests/web/test_views.py` (the `capabilities` prop gains `events`)

**Interfaces:** `eventCardBlock(available: boolean): ComponentConfig<EventCardSnapshotProps>` (one `source_id` field, the shared `cardField('event', available)`); `formatEventWhen(p, locale): string` (`Intl.DateTimeFormat` with `timeZone: p.timezone`, `timeZoneName: 'short'`, all-day as dates). The canvas is only a preview, so it need not match the server's string byte for byte.

- [ ] **Step 1: Write the failing tests:**
  - `puckConfig.test.ts`: `ALL` gains `EventCard` (nine blocks, always defined, for all eight capability combinations), and `EventCard` is in `cards` when `events` is set and in `hidden` otherwise.
  - `CardPicker.test.ts`: `applySnapshot(puck, id, 'event', snap)` replaces an `EventCard` and refuses an `ArticleCard`.
  - `eventCard.test.tsx`: an empty card shows the empty note; a snapshot shows its title, the when-line in `Europe/Vienna` with the zone, the place, and "Cancelled" when cancelled; with `available=false` the picker is disabled with the integration note.
  - `eventWhen.test.ts`: timed, all-day and multi-day, in `de`.
  - `bodyDraft`: an `EventCard` with `source_id: ''` is incomplete.
- [ ] **Step 2: Run** (headroom first) `npx vitest run modules/newsletter/sm_newsletter/ui/components/editor modules/newsletter/sm_newsletter/ui/utils`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, `npx tsc --noEmit -p modules/newsletter/tsconfig.json`, `npx biome check modules/newsletter`, `uv run python scripts/check_locales.py` and `check_file_size.py` (no WARNING on a touched file): all PASS. Also run `cd modules/newsletter && uv run pytest -q tests/web/test_views.py`: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): the Event card in the campaign editor`.

### Task 9: The public block routes

**Files:**
- Create: `sm_events/web/endpoints/public/_blocks_api.py`
- Modify: `web/endpoints/public/_listing.py` (`upcoming(…, calendar_ids: Sequence[uuid.UUID] | None, …)` and its callers), `web/schemas/public.py` (`PublicListItem.image`, `BlockCalendarsOut`, `UpcomingOut`), `core/boot.py` (mount the router, the GET/HEAD auth exemption for `PUBLIC_BLOCKS_API + "/"`, and the `PUBLIC_API_RATE` rule on that prefix)
- Modify: `tests/web/public/test_leaks.py` (the three routes as surfaces), `host/tests/test_events_wiring.py` (an anonymous `GET /api/events/public/calendars` on the real host app gives 200, not 401 or a redirect)
- Test: `tests/web/public/test_public_blocks_api.py`

**Interfaces:** Ruling 18. `async def resolve_calendars(db, slugs: Sequence[str]) -> list[Calendar]` resolves each slug through the public gate, then through calendar redirects. It lives in `_blocks_api.py` unless PR 4's `content/public_read.py` already has it.

- [ ] **Step 1: Write the failing tests:**
  - `test_calendars_all_and_by_slug`: without `calendar`, every public calendar; with `?calendar=pub&calendar=int&calendar=nope`, `[pub]` only; an old slug after a rename resolves to the calendar's current slug.
  - `test_calendar_turned_internal_vanishes_without_name` (Review Focus 1): the body holds neither its slug nor its name.
  - `test_categories_only_public`.
  - `test_upcoming_count_and_bounds`: `count=3` gives 3 items by start; `count=0`, `21` and `"x"` give 422 `{"detail","code"}` with `no-store`.
  - `test_upcoming_selection_rules` (Ruling 19): no `calendar` means every public calendar; calendars that resolve to nothing give `[]`; an unknown category gives `[]`, not unfiltered.
  - `test_upcoming_items`: `image`, a fallback `lang`, a cancelled marker, and the `?date=` url for a series instance.
  - `test_occurrences_alias_matches_pr4`: the same JSON as `{prefix}/api/occurrences` for the same query.
  - `test_anonymous_and_no_csrf`: GET and HEAD without a session give 200; a POST gives 405.
  - `test_signed_in_manager_sees_public_only`: the same body, with private cache headers.
  - `test_request_tenant_never_shareable`, `test_two_tenants_two_etags`, `test_etag_only_over_visible_body` (Review Focus 3, with PR 4's multi-tenant app helper).
  - `test_no_tenant_404`: multi mode with no tenant resolved gives 404 without a query.
- [ ] **Step 2: Run** `cd modules/events && uv run pytest -q tests/web/public/test_public_blocks_api.py tests/web/public/test_leaks.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them on SQLite and Postgres, the rest of `tests/web/public` (PR 4's index tests still pass with `calendar_ids`), and from the root `uv run pytest -q host/tests/test_events_wiring.py`: PASS.
- [ ] **Step 5: Commit** `feat(events): anonymous routes for the pagebuilder blocks`.

### Task 10: Block foundations: packaging, fetchers, labels, locale, boundary

**Files:**
- Modify: `modules/events/package.json` (peers and `peerDependenciesMeta`, Ruling 17), `modules/events/pyproject.toml` (the `pagebuilder` extra with its floor comment; `simple_module_pagebuilder = { workspace = true }` in `[tool.uv.sources]`), `package-lock.json`, `uv.lock`
- Create: `sm_events/ui/blocks/api-blocks.ts` (`fetchBlockCalendars(slugs, locale, signal)`, `fetchUpcoming({slugs, category, count, locale}, signal)`, with plain `fetch`, `credentials: 'same-origin'` and `ApiError` on non-2xx), `ui/blocks/localizeFields.ts`, `ui/blocks/usePageLocale.ts`, `ui/blocks/calendarField.ts` (`calendarsField(tr, options)` builds the `array` field with an `arrayFields.slug` select, `max: BLOCK_CALENDARS_MAX`; `loadCalendarOptions(signal)` turns the anonymous route into `{label: name, value: slug}`, and is empty on any failure), `ui/blocks/limits.ts` (`clampCount`, the bounds mirrored from constants)
- Modify: `locales/en.json`/`de.json` (`blocks.*`: `palette_group`, `upcoming.*`, `calendar.*`, `fields.*`, `editor_hint.*`)
- Test: `ui/blocks/localizeFields.test.ts`, `ui/blocks/api-blocks.test.ts`, `ui/blocks/boundary.test.ts`, `tests/core/test_packaging.py` (events; create it after newsletter's if absent)

**Interfaces:** `localizeFields<F>(fields: F, tr: Translate): F`, a pure deep copy.

- [ ] **Step 1: Write the failing tests:**
  - `localizeFields.test.ts`: it translates `label`, `options[].label`, `arrayFields.*.label` and `objectFields.*.label` nested two levels; leaves `value`s and non-label strings untouched; and leaves the input unmutated.
  - `api-blocks.test.ts` (`stubFetch`): URLs are `/api/events/public/calendars?calendar=a&calendar=b&locale=de` and `/api/events/public/upcoming?…&count=5`; aborts with the signal; throws `ApiError` on 404.
  - `boundary.test.ts`:
    - only `pagebuilder-blocks.ts` and `ui/blocks/**` import `@simple-module-py/pagebuilder`;
    - `index.ts`'s static import graph (followed by a small regex walker over relative imports) never reaches `ui/blocks/`;
    - `registration graph is lazy for the calendar`: the static graph from `pagebuilder-blocks.ts` reaches neither `ui/calendar/` nor `@fullcalendar/`, and `import()` expressions are not followed.
  - `test_packaging.py`: `extras["pagebuilder"] == ["simple_module_pagebuilder>=0.0.16,<0.1"]` and no `==` pins.
- [ ] **Step 2: Run** (headroom first) `npx vitest run modules/events/sm_events/ui/blocks` and `cd modules/events && uv run pytest -q tests/core/test_packaging.py`: FAIL.
- [ ] **Step 3: Implement.** Run `npm install` and `uv sync --all-packages --all-extras --no-extra anonymize` from the root (headroom first).
- [ ] **Step 4: Run** the tests, then `npx tsc --noEmit -p modules/events/tsconfig.json`, `uv run python scripts/check_rules.py`, `check_ts_imports.py` and `check_locales.py`: all PASS.
- [ ] **Step 5: Commit** `feat(events): foundations for the pagebuilder blocks`.

### Task 11: `UpcomingEvents`

**Files:**
- Create: `ui/blocks/UpcomingEventsBlock.tsx` (the `ComponentConfig`: key labels, `defaultProps`, `resolveFields` with the module-level `AbortController` (images' `picker` pattern) and `localizeFields`, `resolveData` clamping `count` and capping `calendars` on `load`), `ui/blocks/UpcomingEventsRender.tsx`
- Test: `ui/blocks/UpcomingEvents.test.tsx`

**Interfaces:** `UpcomingEventsProps` (Ruling 21); `UpcomingEventsRender(props & { puck?: { isEditing: boolean } })`.

- [ ] **Step 1: Write the failing tests** (`stubFetch`, the page props carry `locale: 'de'`):
  - `fetches with the page locale and stored slugs`.
  - `renders a list`: heading, a date and time in `de`, title links to `item.url`, a `lang` attribute on a fallback title.
  - `renders cards with images only when showImages`.
  - `marks cancelled and rescheduled`.
  - `renders nothing while loading, when empty and on a failed fetch` (an empty fragment).
  - `editor hint`: with `puck.isEditing` and an empty answer, the "no upcoming public events" hint shows; with two stored slugs and one resolved (the calendars route), "1 chosen calendar is not public or no longer exists", with no slug or name. A visitor sees neither.
  - `clamps a stored count of 4.5 and 99`.
  - `resolveFields builds translated selects from the anonymous route`, and an empty select on failure.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/blocks/UpcomingEvents.test.tsx`: FAIL.
- [ ] **Step 3: Implement.** Items render their own text; the block never uses `dangerouslySetInnerHTML`.
- [ ] **Step 4: Run** it, then `npx tsc --noEmit -p modules/events/tsconfig.json` and `npx biome check modules/events`: PASS.
- [ ] **Step 5: Commit** `feat(events): the UpcomingEvents block`.

### Task 12: `EventsCalendar` and the registration

**Files:**
- Create: `ui/blocks/EventsCalendarBlock.tsx` (`lazyBlock(() => import('./EventsCalendarRender').then((m) => m.EventsCalendarRender), config, fallback)`), `ui/blocks/EventsCalendarRender.tsx`
- Create: `sm_events/pagebuilder-blocks.ts` (two guarded `registerPuckBlocks` calls, group `events`, no `layout`, news' header comment adapted)
- Check (no new file): PR 3 Task 15's manifest check (`host/static/dist/.vite/manifest.json`), applied again: neither the entry chunk's static `imports` nor the chunk holding `pagebuilder-blocks` reaches the chunk containing FullCalendar
- Test: `ui/blocks/EventsCalendar.test.tsx`, `ui/page-tests/pagebuilder-blocks.test.ts`

- [ ] **Step 1: Write the failing tests:**
  - `EventsCalendar.test.tsx` (`vi.mock` the adapter with `FakeGrid`):
    - `read-only grid`: `fakeGrid.last.editing` is undefined;
    - `calendars mapped to CalendarInfo` (`visibility: 'public'`, `can_write_events: false`) from the resolved ones only;
    - `default view and height`;
    - `fetcher hits /api/events/public/occurrences with resolved ids`;
    - `renders nothing when a non-empty selection resolves to nothing` (plus the editor hint while editing);
    - `fallback has the chosen height`.
  - `pagebuilder-blocks.test.ts` (images' pattern): both names are registered in `{key: 'events', title: 'events.blocks.palette_group'}` with `layout` falsy; a second import that re-registers does not throw out of the module (the guard).
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/blocks modules/events/sm_events/ui/page-tests/pagebuilder-blocks.test.ts`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, tsc, biome, then (headroom first) `npm run build` and the manifest check above: FullCalendar is only in a dynamically imported chunk. All PASS.
- [ ] **Step 5: Commit** `feat(events): the EventsCalendar block and pagebuilder registration`.

### Task 13: E2E

**Files:**
- Create: `tests/e2e/events-blocks.spec.ts`
- Modify: PR 4's events e2e helpers (if PR 4 made none, create `tests/e2e/events-helpers.ts` with `seedCalendar(page, {visibility})`, `seedEvent(page, calendarId, {texts, start, publish})` and `setCalendarVisibility`, all through the events API)
- Modify: `tests/e2e/start-test-server.sh` only if events' `content_locales` is not already `["en","de"]` there
- Modify: `tests/e2e/newsletter.spec.ts` (one step), `tests/e2e/newsletter-campaign.ts` (`eventCard(page, id, eventId)`, mirroring `articleCard`)

**The spec** stands alone (unique slugs, its own data):
- Seed calendars: public `Pub`, internal `Int`.
- Seed events:
  - `A`, published on `Pub` in 7 days, with `en` and `de` texts;
  - `B`, a draft on `Pub`;
  - `C`, published on `Int`;
  - `S`, a weekly published series on `Pub`.
- Create and publish two pagebuilder pages:
  - an `en` page with `UpcomingEvents` (`calendars: []`, `layout: 'cards'`) and `EventsCalendar` (`calendars: [{slug: Pub}]`);
  - a `de` page with `UpcomingEvents`.

**Steps:**
1. **An anonymous visitor** (a fresh `browser.newContext()`) on `/p/<en>`:
   - sees `A`'s English title and `S`'s next date;
   - does not see `B`, `C` or `Int`;
   - the grid shows `A`'s chip;
   - no `Content Security Policy` console message.
2. **`/de/p/<de>`** shows `A`'s German title and a German month name.
3. **Lazy grid:** `/p/<page with only UpcomingEvents>` requests no chunk whose name contains `FullCalendar`/`fullcalendar`.
4. **Calendar made internal:** set `Pub` to internal and reload as the visitor. Both blocks render nothing, and the page text contains no `Pub` name.
5. **Editor:** signed in, open the en page in the pagebuilder editor. The palette shows "Upcoming events" and "Events calendar" under "Events", and the calendar picker lists `Pub` (when public) and never `Int`.

**The newsletter step**, in the opt-in `E2E (newsletter)` job:
- seed a published public event;
- the editor palette shows "Event card" under cards;
- `eventCard()` sets a body holding the snapshot;
- the preview frame shows the title and an "Add to calendar" link whose `href` is absolute and ends in `.ics`.

Rendering detail is the module goldens' job. This step proves the host wires the capability and the route end to end.

- [ ] **Step 1: Write the spec and the step.**
- [ ] **Step 2: Run** (headroom first, one Playwright run at a time) `npx playwright test tests/e2e/events-blocks.spec.ts`, then `E2E_NEWSLETTER=1 npx playwright test tests/e2e/newsletter.spec.ts` against a non-bundle development host (as that job runs). Both PASS. Stop the servers.
- [ ] **Step 3: Commit** `test(e2e): events blocks on a public page and the newsletter event card`.

### Task 14: Docs and branch verification

**Files:**
- Modify: `modules/events/docs/index.md`. Add a section "Pagebuilder blocks" covering both blocks, their props, the slug rule and its empty/unresolved cases, the anonymous routes and their caching, the lazy calendar, the canvas, and bundles and restores. Add a section "Card contract (`contracts.cards`)" covering what is found, which occurrence, the fields, the search order and scan bound, and the tenant pinning.
- Modify: `modules/newsletter/docs/content.md`: `EventCard` in the block table; in Cards, the event kind, its routes, the when-line format and its language, the zone abbreviation, cancelled, the `.ics` link, Refresh rolling forward, and the snapshot rule of Ruling 16.
- Modify: `modules/pagebuilder/docs/user-guide.md` only if it lists other modules' blocks. It did not on 2026-11-18, so it stays as it is unless that changed.
- Modify: `modules/events/README.md` (the blocks and the `pagebuilder` extra), `modules/newsletter/README.md` (the `events` extra), `CHANGELOG.md` (0.0.16 Added: the events blocks, the event card, `contracts.cards`).
- Modify: `CLAUDE.md`:
  - in the newsletter paragraph, "Card and media lookups go through `news.contracts.articles`, `pagebuilder.contracts.cards` and `sm_events.contracts.cards` only";
  - in the events paragraph, one sentence: "`contracts.cards` and the blocks' `/api/events/public/*` routes start from the public gate (published events of public calendars), the contract pins the named tenant twice, and the blocks reference calendars by slug, rendering nothing for one that is no longer public."
- Modify: the spec's Amendments (add "Amendments (PR 7)" listing Rulings 4, 12, 14, 15's zone abbreviation, 17's extra, 18 and 20).

- [ ] **Step 1: Lint set** (headroom first), from the root:
  - `uv run ruff check modules/events modules/newsletter scripts host`
  - `uv run ruff format --check <files touched>`
  - `uv run basedpyright`
  - `npx biome check modules/events modules/newsletter`
  - `npx tsc --noEmit -p modules/events/tsconfig.json` and `-p modules/newsletter/tsconfig.json`
  - `uv run python scripts/check_metadata.py`, `check_rules.py`, `check_sibling_contracts.py`, `moved_paths.py --check`, `check_ts_imports.py`, `check_readmes.py`, `check_hardcoded_strings.py`, `check_file_size.py` (no WARNING under the touched files), `check_locales.py`, `check_migration_heads.py` and `bump_version.py --check-current`

  All pass.
- [ ] **Step 2: Targeted suites, one at a time:**
  1. `cd modules/events && uv run pytest -q -n 8` on SQLite, then on `smpy_events_test`.
  2. `cd modules/newsletter && uv run pytest -q -n 8` on SQLite, then on `smpy_newsletter_test`.
  3. From the root: `uv run pytest -q -n 8 scripts/tests host/tests/test_events_wiring.py host/tests/test_host_boots.py`.
  4. `npx vitest run modules/events modules/newsletter`.

  All pass. Drop the scratch databases.
- [ ] **Step 3: Fresh-import check** for every touched `modules/events/sm_events/**/*.py` and `modules/newsletter/sm_newsletter/**/*.py`.
- [ ] **Step 4: Commit** `docs(events,newsletter): pagebuilder blocks, the cards contract and the event card`.
- [ ] **Step 5: Hand over to `/ship`.** Browser QA:
  - add both blocks to a page in the editor and choose calendars and a category;
  - publish, and view it signed out in English and German;
  - make a chosen calendar internal and see the editor hint;
  - insert an Event card into a campaign, refresh it, and view the preview, in light and German console;
  - as a visitor, check the grid navigates and links to event pages.

  Screenshots of the palette, both blocks on the public page, the editor hint, the Event card in the editor and the email preview go in the PR.

## Verification checklist (before `/ship`)

- Task 14 Step 1's lint set passes, including `basedpyright`, `check_sibling_contracts.py` and `check_ts_imports.py`.
- The events and newsletter pytest suites pass on SQLite and Postgres; `scripts/tests` and the host tests pass; vitest passes for both modules.
- The goldens changed only by the event card rows and the new `event_cards.*` files.
- The production build has `@fullcalendar` only in the lazy grid chunk.
- No file touched is at 280 lines or more.
- `git diff --stat feat/events-pr6-extensions` touches only `modules/events/**`, `modules/newsletter/**`, `host/tests/test_events_wiring.py`, `tests/e2e/events-blocks.spec.ts`, `tests/e2e/newsletter.spec.ts`, `tests/e2e/newsletter-campaign.ts`, events e2e helpers, `tests/e2e/start-test-server.sh` (only if needed), `.github/workflows/release.yml` (only if Task 4 found events missing), `package-lock.json`, `uv.lock`, `CHANGELOG.md`, `CLAUDE.md`, the spec and this plan. There are no migrations.
- Every Review Focus test exists and passes: grep for each name listed there.

## Open points

1. **No pinned occurrence (★ Ruling 4).** A writer cannot card "the 3 March session" of a series, only the next one. If editors ask for it, add `occurrence_start` to the snapshot request and an `occurrence` parameter to `get_event_card` (validated with PR 2's `is_occurrence`). File it as an issue when the PR opens.
2. **Blocks keep an old slug after a calendar rename.** Redirects make it work. A `resolveData` on `load` could rewrite the stored slug to the current one, but that changes page content just by opening the editor. This is a follow-up issue, not this PR.
3. **The zone abbreviation is not translated** (★ Ruling 15). German readers see `CEST`, not `MESZ`. Babel's CLDR names are complete in German but missing in English. Revisit if a site asks.
4. **Search scans 50 candidates** (Ruling 7). A tenant with hundreds of matching series could miss one in the picker until the writer types more. That is acceptable for a picker, and it is documented.
5. **Block data lags the page.** A block's answer is cached up to `min(public_cache_seconds, 60)` s, separately from the page, and a scheduled publish has PR 2's beat lag on top. Documented.
6. **Prefix discovery for sibling blocks.** Pagebuilder gives a block no way to learn another module's public routes, which is why Ruling 18 adds fixed-path aliases. If a third module needs this, a small `pagebuilder.contracts.site` addition (or framework support) would be better. Note it in the PR; no issue yet.
7. **The ★ rulings** most likely to change: no `occurrence` parameter and a series card being the next occurrence (4), `EventCard` as its own block (12), Refresh rolling forward (14), the untranslated zone abbreviation (15), the fixed-path public block routes (18) and the anonymous route feeding the pickers (20).
