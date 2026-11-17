# Events PR 3: the `Calendar` component and the console calendar. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reusable `Calendar` React component (month, week, day and list views, filters, render slots) exported from `@simple-module-py/events`, and the console calendar at `/admin/events/` built on it: create by click or drag-select, drag to move, resize to change the end, "this one or all" for series, a "calendar time / my time" grid timezone, and a keyboard path ("Move" dialog) for every move and resize.

**Architecture:** Everything lives in `sm_events/ui/calendar/`. FullCalendar 7 (MIT packages only) is wrapped by one adapter folder, `adapter/`, which is the only code that imports it and which is loaded lazily, so FullCalendar and its CSS sit in their own chunk. Around it: pure time and range maths on `temporal-polyfill` (`time/`), a range-keyed, abortable occurrence cache (`data/`), the generic shell (toolbar, filters, status, popover, default chip, slots) and the console-only write layer (`console/`: quick-create, move dialog, scope prompt, the write orchestration). The write orchestration turns a grid change into PR 2's API calls (`PATCH` for the event or series, `POST …/overrides` for "this one") with `expected_revision`, and turns every failure into a revert and a message.

**Tech Stack:** React 19 + Inertia, `@simple-module-py/ui` (Radix popover, dialog, toggle group, checkbox), `@fullcalendar/react@^7.1.5` (bundling `/daygrid`, `/timegrid`, `/list`, `/interaction`, `/locales/*`, `/themes/*`), `temporal-polyfill@^1.0.8`, vitest (node and happy-dom, the PR 1 harness `ui/page-tests/test-dom.tsx`), Playwright. On the Python side, only a view, the menu and constants change.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`. This plan covers Delivery row 3 and draws on "The calendar UI", "Screens and routes", the anti-goals ("an event shown at the wrong time", "non-MIT calendar code") and the PR 1 amendments. The API it consumes is PR 2's: `docs/superpowers/plans/2026-11-17-events-pr2-events.md`, Rulings 1, 2, 10–14, 16, 19, 27 and Task 15's route table. Read both, `docs/module-layout.md`, `modules/events/docs/index.md`, and the PR 1/PR 2 frontend under `modules/events/sm_events/pages` and `sm_events/ui` before starting.

## Depends on PR 2

Before Task 1 the branch is rebased onto the finished `feat/events-pr2-events`. The implementer of batch A **re-checks every name below against the real code first** and corrects this plan's references (in the task text, not by renaming PR 2 code) wherever they differ. Already known: the plan calls the editor URL `EVENT_EDIT_URL`, but the code has `EDITOR_URL` (`core/constants.py`). Stop and report if a behaviour, not just a name, differs.

| Kind | PR 2 symbol this plan relies on |
|---|---|
| Endpoint | `GET /api/events/occurrences?start=&end=&calendar=…&category=…&type=…&locale=&include_unpublished=` → `OccurrencePage` (aware ISO `start`/`end`, repeatable filters, 422 `invalid_range`/`range_too_long` past 366 days) |
| Endpoint | `GET /api/events/events/{id}` → `EventOut` (`revision`, `all_day`, `timezone`, `start_local`, `end_local`, `rrule`, `overrides[]` with `original_start`/`kind`/`starts_at`/`ends_at`, `locked`, `can_write`, `can_publish`, `calendar_id`) |
| Endpoint | `POST /api/events/events` (`EventCreate`: `calendar_id`, `times: {all_day, timezone, start, end}`, `texts: {<default locale>: {title}}`) → 201 `EventOut` |
| Endpoint | `PATCH /api/events/events/{id}` (`expected_revision`, `times`, `drop_orphaned_overrides`) → 409 `stale` / `overrides_orphaned`, 403 `publish_required`, 422 `start_not_in_rule` / `invalid_local_time` / `end_before_start` / `duration_too_long` |
| Endpoint | `POST /api/events/events/{id}/overrides` (`OverrideIn`: `expected_revision`, `original_start` aware UTC, `kind: "moved"`, `start`, `end` local wall clock in the event's timezone) |
| Endpoint | `POST /api/events/recurrence/preview` (`PreviewOut.orphaned`), used to list what a series shift drops |
| View | `/admin/events/edit/new?calendar=<id>` and `/admin/events/edit/{id}`; the view helper that builds `calendars: [{id, name, color, can_write_events}]` and `categories` for the Events list (`web/endpoints/views.py`) |
| Constants | `EDITOR_URL`, `EVENTS_URL`, `_PAGE_EVENTS`, `_PAGE_EVENT_EDITOR`, `MENU_*_EVENTS` (`order=395`), every error code of PR 2 Ruling 27 |
| TS types | `ui/utils/types-events.ts`: `Occurrence` (incl. `start_date`, `end_date`, `event_status`, `editable`, `key`, `original_start`, `event_id`, `status`, `lang`, `url`), `OccurrencePage`, `EventOut`, `OverrideOut`, `PreviewOut`, `TimesIn` (the `times` body); `Visibility` from PR 1's `ui/utils/types.ts` |
| TS client | `ui/utils/api-events.ts`: `listOccurrences`, `getEvent`, `createEvent`, `updateEvent`, `setOverride`, `previewRecurrence`; `ui/utils/api.ts`: `ApiError`, `errorText` (with PR 2's codes), `isGone` |
| TS UI | the orphaned-overrides confirm in the editor (PR 2 Task 21, under `ui/components/editor/`); if it is inline in a hook or the page, extract it to `ui/components/editor/OrphansConfirm.tsx` unchanged in Task 8 |
| TS hooks | PR 1's `useRequestScope`, `useFormErrors`, `field-errors`, `isolate` (`withName`, `Name`), `ConfirmDialog`, `useT`/`keys` (`useT().locale`) |
| Tests | `ui/page-tests/test-dom.tsx` (the mount harness), `ui/page-tests/support.tsx` (`stubFetch`), `tests/support/calendars.seed_event` (Python) |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**Library and shipping**
1. **Dependencies** (spec: FullCalendar 7, MIT only). `modules/events/package.json` `dependencies`: `"@fullcalendar/react": "^7.1.5"`, `"temporal-polyfill": "^1.0.8"` (FullCalendar's peer, and our time maths use it too). `@fullcalendar/core` and `@full-ui/headless-calendar` (MIT, a dependency of `@fullcalendar/react@7.1.5` that the lead's facts did not name; checked on npm 2026-11-17) come in transitively. The allow-list is exactly `@fullcalendar/react`, `@fullcalendar/core`, `@full-ui/headless-calendar`. A test fails on any other `@fullcalendar/*` or `@full-ui/*` package in `modules/events/package.json` or anywhere in `package-lock.json`, on any name containing `scheduler`, `resource`, `timeline` or `premium`, and on any allow-listed lockfile entry whose `license` is not `MIT`. `@fullcalendar/rrule` is not installed (spec).
2. ★ **Only `ui/calendar/adapter/` imports FullCalendar.** The spec says `ui/calendar/`; the adapter folder is stricter and is the whole of what a replacement rewrites. A vitest test scans `modules/events/sm_events/**/*.{ts,tsx,css}` for `@fullcalendar/` and fails outside `ui/calendar/adapter/`. `import type` counts too.
3. ★ **One theme, mapped onto the console's tokens.** The adapter imports `@fullcalendar/react/skeleton.css`, the `classic` theme (its JS plugin plus `themes/classic/theme.css`) and our `adapter/calendar.css`, which sets the theme's CSS variables from `@simple-module-py/ui`'s tokens (`--background`, `--foreground`, `--border`, `--primary`, `--muted`), so light and dark follow the console. CSS imported from the adapter module goes into the adapter's chunk: no line in `host/client_app/styles.css`, exactly as images imports `maplibre-gl/dist/maplibre-gl.css` from `MapCanvas.tsx`. A wheel-installed host gets it the same way. Tailwind classes in `ui/calendar/**` are already scanned by the host's `@source "../../modules/*/*/**/*.{ts,tsx}"` and by `modules.generated.css` for wheels.
4. ★ **Code split at the adapter.** Pages are already per-page chunks (`import.meta.glob` without `eager` in `host/client_app/pages.ts`). `Calendar` is a thin shell, and the grid is `React.lazy(() => import('./adapter/FullCalendarGrid'))` behind `Suspense` with a skeleton. So FullCalendar does not reach the entry chunk, nor the chunk of any later importer of `@simple-module-py/events` that does not render a grid (PR 7's blocks). Task 15 checks the build.
5. **CSP.** Production is `script-src 'self' 'nonce-…' 'strict-dynamic'` with no `unsafe-eval`, and `style-src 'self' 'unsafe-inline'` (framework `simple_module_hosting/_security_headers.py`). So FullCalendar must not call `eval`/`new Function` and must not insert `<script>`. Inline styles and `<style>` elements are allowed. Task 1 greps the installed packages for `new Function`, `eval(` and `createElement('script')`. In the browser, `tests/e2e/production-csp.spec.ts` (`E2E_BUNDLE=1` only) also opens `/admin/events/`, and `events-calendar.spec.ts` fails on any `Content Security Policy` console message, as `events.spec.ts` does.

**Component**
6. ★ **Public props** (`ui/calendar/types.ts`, re-exported from `index.ts`):

   ```ts
   export type CalendarView = 'month' | 'week' | 'day' | 'list';
   export type CalendarInfo = { id: string; name: string; color: string; visibility: Visibility;
     default_timezone: string; can_write_events: boolean };
   export type FilterOption = { id: string; label: string; color?: string | null };
   export type OccurrenceQuery = { start: string; end: string; calendars: string[]; categories: string[];
     types: string[]; locale: string };                        // aware ISO UTC, half-open
   export type OccurrenceFetcher = (q: OccurrenceQuery, signal: AbortSignal) => Promise<OccurrencePage>;
   export type CalendarState = { view: CalendarView; date: string; tzMode: TzMode;
     calendars: string[]; categories: string[]; types: string[] };   // date = YYYY-MM-DD in the grid tz
   export type CalendarProps = {
     fetchOccurrences: OccurrenceFetcher;
     calendars: CalendarInfo[];
     categories?: FilterOption[];
     types?: FilterOption[];                 // the type filter shows only with 2+ types
     defaultTimezone: string;                // the tenant's, for "calendar time" over several calendars
     initialState?: Partial<CalendarState>;
     onStateChange?: (state: CalendarState) => void;
     editing?: CalendarEditing;              // absent: read-only (the public site, PR 4)
     slots?: CalendarSlots;
     refreshToken?: number;                  // bump to invalidate the cache and refetch
   };
   ```

   `Calendar` owns its state, reads `initialState` once and reports every change through `onStateChange`. The props never expose a FullCalendar type.
7. ★ **Slots** (spec: render slots; PR 6's registry plugs in through them):

   ```ts
   export type EventChipProps = { occurrence: Occurrence; view: CalendarView; timeText: string;
     Default: ComponentType<EventChipProps> };
   export type DetailProps = { occurrence: Occurrence; gridTimeZone: string; close: () => void;
     actions: ReactNode; Default: ComponentType<DetailProps> };
   export type ToolbarSlotProps = { state: CalendarState; range: { start: string; end: string } | null };
   export type CalendarSlots = { EventChip?: ComponentType<EventChipProps>;
     Detail?: ComponentType<DetailProps>; ToolbarStart?: ComponentType<ToolbarSlotProps>;
     ToolbarEnd?: ComponentType<ToolbarSlotProps> };
   ```

   A slot receives `Default` so it can wrap or fall back per occurrence: PR 6 builds one `slots` object whose `EventChip` dispatches on `occurrence.type` and renders `Default` for unknown types. `CalendarProps` does not change for that.
8. **Editing is a callback surface**, not API knowledge. `CalendarEditing = { canCreate: boolean; onCreate: (slot: CreateSlot) => void; onChange: (change: OccurrenceChange) => Promise<boolean>; onMove: (occurrence: Occurrence) => void; pendingKeys: ReadonlySet<string> }`. `CreateSlot = { allDay: boolean; start: string; end: string }` (instants for timed, dates with an exclusive end for all-day). `OccurrenceChange = { occurrence: Occurrence; kind: 'move' | 'resize'; start: string; end: string; allDay: boolean }`, in the same encoding. `onChange` resolves `true` to keep the grid's optimistic position and `false` to revert. The console implements it (`console/`), and the public site passes nothing.

**Views, state and fetching**
9. **Views** map to `dayGridMonth`, `timeGridWeek`, `timeGridDay` and `listMonth`. The toolbar is ours (`headerToolbar: false`): today, previous, next, the title from FullCalendar's `datesSet` (`view.title`), and a view switcher. `fixedWeekCount: false`, `nowIndicator: true`, `dayMaxEvents: true` (a "+N more" link), `slotDuration` 30 min, `scrollTime` 08:00.
10. **The console mirrors the state in the URL** (`?view=week&date=2026-03-30&tz=mine&calendar=<id>&category=<id>`) with `history.replaceState`, and reads it back on load. Defaults: month, today, calendar time, every calendar shown, no category filter.
11. ★ **Range fetching.** The fetch range is the visible range padded by `RANGE_MARGIN_DAYS = 7` on each side, and is never longer than `MAX_RANGE_DAYS = 366` (an assertion; the longest view is six weeks). Filters go to the server (`calendar`, `category`, `type`), so truncation stays honest. The cache holds `CACHE_ENTRIES = 8` pages, LRU, keyed by `(start, end, calendars, categories, types, locale)`. A navigation whose visible range lies inside a cached padded range with the same filters reuses it without a request. Each new fetch aborts the one in flight (`useRequestScope`), and a late answer is dropped. Any write, or a bump of `refreshToken`, clears the cache and refetches the current range. The console passes `include_unpublished` as the API default (true).

**Timezone** (spec: grid timezone)
12. ★ **Grid timezone.** "Calendar time" is the `default_timezone` of the one calendar shown when exactly one is, else `defaultTimezone` (the tenant's). "My time" is `Intl.DateTimeFormat().resolvedOptions().timeZone`. The default is calendar time. The toggle shows the zone name (`Europe/Vienna`). When both are the same zone, it stays visible and says so ("Your time is the same"). FullCalendar gets `timeZone: <grid zone>` (named zones need no plugin in v7). All-day occurrences are passed as `start_date`/`end_date` strings with `allDay: true`, which FullCalendar does not shift, so they ignore the toggle (spec).
13. ★ **Grid change → event-local wall clock.** FullCalendar reports instants. A write converts them with Temporal into the **event's** timezone, as `YYYY-MM-DDTHH:MM` (`:SS` only when non-zero), because PR 2's API takes local wall clock in the event's timezone (PR 2 Ruling 1). A move keeps the exact duration (new end = new start + old end − old start, as instants). A resize changes only the end. An all-day move adds FullCalendar's day delta to `start_date`, and the API's inclusive `end` is `end_date − 1 day` plus the same delta. A drag between the all-day row and the time grid is refused (`eventAllow`): changing all-day goes through the Move dialog or the editor. When the new instant maps to the **second** occurrence of a repeated local hour in the event's zone (autumn fold), the server would read the wall clock as the first (PR 2 Ruling 4, `fold=0`), an hour off. So the write is refused client-side with `repeated_local_time` ("That time happens twice in Europe/Vienna on that day; choose another time"), and the grid reverts.
14. ★ **"All" on a series shifts the master on the event's wall clock.** shift = (new instance start, local in the event's zone) − (old instance start, local), as a `PlainDateTime` difference, added to the master's `start_local`/`end_local`. A resize applied to all sets the master's end so its duration equals the instance's new exact duration. The rule text is never rewritten. A day change on a `BYDAY` rule therefore gets 422 `start_not_in_rule`, which reverts and says "Moving the whole series to another weekday changes its rule; open the editor", with a link to the editor. A master landing in a DST gap gets `invalid_local_time` and reverts with PR 2's message.
15. ★ **Where `expected_revision` comes from.** An occurrence carries no revision. So a write first `GET`s the event. If what the grid showed no longer matches it (for a one-off: its `start`/`end`; for an instance: the master's times, `rrule`, and any override at that `original_start`), the write stops as **stale** without sending anything. Otherwise it sends with the fetched `revision`. This is one extra request per drag, and it keeps "stale" meaning "changed since you looked". Open point 1 proposes adding `revision` to `Occurrence`.

**Writes and states** (spec: create, drag, resize, "this one or all")
16. **Which write.** A one-off: `PATCH` `times`. A series instance: a prompt with "Only this occurrence" (`POST …/overrides`, `kind: "moved"`, `original_start` from the occurrence, `start`/`end` local; a second write replaces an existing moved override, PR 2 Ruling 10) or "All occurrences" (`PATCH` per Ruling 14). Cancelling the prompt reverts. Cancelled occurrences, cancelled events and occurrences with `editable: false` are not draggable or resizable (`startEditable`/`durationEditable` false). Drafts and in-review events are draggable when `editable`.
17. **Outcomes** (each failure reverts the grid first, then refetches the range):

    | Answer | What the user sees |
    |---|---|
    | 200/201 | success toast "Moved"; the range is refetched |
    | client stale (Ruling 15) or 409 `stale` | toast "This event changed since it was loaded. The calendar has been refreshed; try again." |
    | 409 `overrides_orphaned` | PR 2's orphaned-overrides confirm, listing them (from `previewRecurrence`); confirm resends with `drop_orphaned_overrides: true`, cancel reverts |
    | 403 `publish_required` / `forbidden` | toast with `errorText` ("Only a publisher can change a published event") |
    | 404 | toast "This event no longer exists" |
    | 422 `start_not_in_rule` | Ruling 14's message with an "Open editor" action |
    | other 422, network, 5xx | `errorText` |

18. **Optimistic move.** FullCalendar shows the drop at once. While its write runs, the occurrence's key is in `pendingKeys`: it renders `aria-busy`, at reduced opacity, and is not draggable. On `false` the adapter calls FullCalendar's `revert()`.
19. **Create.** Drag-select in the time grid gives a timed range. A click in the time grid gives a 60-minute event (`DEFAULT_CREATE_MINUTES = 60`). A click or drag-select in the day grid gives all-day dates. `canCreate` is true when any shown calendar has `can_write_events`. The quick-create dialog has the title (stored as the default content locale's text, `content_locales[0]`), the calendar (writable calendars only; the one shown, if exactly one is, else the first), an all-day switch, and start and end fields **in the chosen calendar's timezone** (its name is shown beside them). Changing the calendar re-expresses the same instants in the new zone. "Create" sends `POST /api/events/events` (status draft) and refetches. "More options" navigates to `EDITOR_URL/new?calendar=<id>&all_day=<0|1>&start=<local>&end=<local>&title=<text>`, and Task 10 makes PR 2's editor prefill from those parameters.
20. **Drafts, review and cancelled are visible without colour** (spec). Draft: a dashed border and the text "Draft". In review: a dotted border and "In review". Cancelled: the title struck through and "Cancelled". Not editable on a calendar the viewer writes to: a lock icon whose accessible name gives the reason. In month cells the status word is visually hidden but present for screen readers, and the border style carries it visually. In week, day and list views it is visible text.
21. **The detail popover.** It shows the title (with a `lang` badge when the text fell back to another language), the time in the grid timezone, and the event's own local time with its zone when they differ (spec), plus the calendar (name and swatch), the status, and actions. "Open in editor" appears when `url` is set. "Move…" appears when `editable`. When not editable on a writable calendar it shows the reason ("Published: only a publisher can change it" when `event_status === 'published'`, else "You can view this calendar only"). For an all-day occurrence the dates are shown as dates, never with a time.
22. **Locale** (spec): FullCalendar's locale follows `useT().locale`: `de` loads `@fullcalendar/react/locales/de` (Monday week start, 24-hour), and anything else uses the built-in `en` (Sunday, 12-hour). Every string of ours goes through `t(keys.events.calendar.*)`. Our dates go through `Intl.DateTimeFormat(locale, { timeZone })`.
23. **Accessibility** (spec: focusable events, and a Move dialog because FullCalendar has no keyboard drag). `eventInteractive: true`. Enter or Space on a focused event opens the popover: FullCalendar's `eventClick` when it fires on Enter (Task 1 confirms), otherwise a `keydown` handler on our chip. Closing the popover returns focus to that event element. The Move dialog has start date and time, end date and time (dates only for all-day) and, for an instance, "Only this occurrence / All occurrences". It sends through the same `onChange` path, so it gets the same outcomes. The toolbar buttons and the view switcher (a toggle group with `aria-pressed`) carry names. Filters are labelled checkboxes. The grid region has `aria-label` set to the title and `aria-busy` while loading.
24. **States.** Loading: a `role="status"` line and `aria-busy`. Error: a `role="alert"` with `errorText` and a "Retry" button. Empty (no items, not loading): "Nothing in this range" (FullCalendar's `noEventsContent` in the list view). Truncated: a persistent notice "Showing the first 2,000 items in this range. Narrow the filters or switch to a shorter view."
25. **Console screen.** `GET /admin/events/` (`events.view`) renders the new page `events/Calendar` with `{**view_props, "calendars": [{id, name, color, visibility, default_timezone, can_write_events}], "categories", "default_timezone", "content_locales", "editor_url"}` and replaces PR 1's 303. A new menu entry "Calendar" (`events.view`, `order=390`, icon `calendar-range`) comes first in the Events group, before "Events" (395) and "Calendars" (400).

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, biome, build, playwright or `npm install`/`uv sync` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. At most one test suite and one dev server at a time; stop servers as soon as a step is done. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr3` on branch `feat/events-pr3-calendar`. Before Task 1, rebase onto the finished `feat/events-pr2-events` and re-check "Depends on PR 2". Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points and `npx` from the worktree root, and module pytest from the module directory (`cd modules/events && uv run pytest …`).
- Implementers are Claude subagents. Each one commits its own tasks, one commit per task, and never pushes.
- Never run `ruff format` or `biome format` repo-wide. Format only the files touched. Never commit `.env*`.
- Names: package `sm_events`, npm `@simple-module-py/events`, locale namespace `events` (new keys under `calendar.*` and `menu.calendar`), API prefix `/api/events`, view prefix `/admin/events`, page `events/Calendar`.
- Version stays `0.0.15` (`uv run python scripts/bump_version.py --check-current`).
- npm dependency ranges are carets (`^7.1.5`, `^1.0.8`), never exact. Only the Ruling 1 packages are added. `npm install` runs at the root (workspaces), and `package-lock.json` is committed with it.
- The frontend imports other modules only as `@simple-module-py/<module>` (`scripts/check_ts_imports.py`). Nothing in this PR imports another module.
- 300-line cap. Keep every `.py`/`.ts`/`.tsx` under 280 lines. The File Structure below gives each file a budget.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`).
- Only real Inertia pages go under `sm_events/pages/`: `Calendar.tsx` in this PR.
- `en.json` and `de.json` keep identical key trees and placeholders (`scripts/check_locales.py`). UI strings go through `t(keys.events.…)`.
- Tests that need the DOM declare `// @vitest-environment happy-dom` and use PR 1's `test-dom.tsx` harness. There is no `@testing-library` here: do not add one.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## What is and is not unit-tested

FullCalendar's rendering, hit-testing and pointer drags do not work in happy-dom (no layout), so **the adapter's `FullCalendarGrid.tsx` is not mounted in vitest**. Everything it does is pushed into pure functions that are: `adapter/mapping.ts` (occurrence → event input, FullCalendar's drop/resize arguments → `OccurrenceChange`, `eventAllow`), `adapter/options.ts` (locale, views, time zone, editability), `time/*`, `data/*` and `console/writes.ts`. The shell (`Calendar.tsx`) and the console layer are mounted in happy-dom with `vi.mock('../adapter/FullCalendarGrid')` replaced by `test-support/FakeGrid.tsx`, which implements the same props and handle and lets a test fire `onRangeChange`, `onEventOpen`, `onSelect` and `onChange`. What only a browser shows (drag gestures, week start on screen, focus inside FullCalendar, CSS, CSP) is in the e2e spec (Task 14).

## File Structure

All under `modules/events/sm_events/ui/calendar/` unless the path says otherwise. Budgets are line targets.

| File | Responsibility | ≤ |
|---|---|---|
| `types.ts` | the public types of Rulings 6–8 | 120 |
| `Calendar.tsx` | the shell: state, fetch hook, toolbar, filters, status, lazy grid, popover, slots | 220 |
| `Toolbar.tsx` | today, prev, next, title, view switcher, timezone toggle, toolbar slots | 150 |
| `Filters.tsx` | calendar checkboxes with swatch and visibility label (the legend), category and type filters | 180 |
| `StatusBar.tsx` | loading, error with retry, empty, truncated | 80 |
| `EventChip.tsx` | the default chip: time, title, status word, border style, lock, pending | 120 |
| `DetailPopover.tsx` | the default detail and the popover frame with focus return | 200 |
| `TimezoneToggle.tsx` | calendar time / my time | 80 |
| `adapter/FullCalendarGrid.tsx` | the only FullCalendar mount; the `GridHandle`; callbacks into the shell | 220 |
| `adapter/options.ts` | static options, views, locale choice, time zone | 120 |
| `adapter/mapping.ts` | occurrence ↔ FullCalendar event input and change arguments (type imports only) | 160 |
| `adapter/calendar.css` | skeleton and theme imports, token mapping, status styles | 120 |
| `time/zones.ts` | Temporal conversions, repeated-hour check, wall-clock shift, browser zone, grid zone | 160 |
| `time/range.ts` | padded range, the 366-day clamp, range key, containment | 80 |
| `time/format.ts` | popover and chip time text in a zone and locale | 100 |
| `data/cache.ts` | the LRU range cache (pure) | 90 |
| `data/useOccurrences.ts` | fetch per range with abort, cache and refresh | 140 |
| `console/writes.ts` | pure: a change plus the fetched event → the request to send, or a refusal | 220 |
| `console/useCalendarWrites.ts` | orchestration: get, stale check, prompt, send, outcomes | 240 |
| `console/ScopePrompt.tsx` | "Only this occurrence / All occurrences" | 100 |
| `console/QuickCreateDialog.tsx` | quick create and "More options" | 230 |
| `console/MoveDialog.tsx` | move and resize by keyboard | 220 |
| `console/ConsoleCalendar.tsx` | `Calendar` plus the console's editing and dialogs | 200 |
| `test-support/FakeGrid.tsx` | the mocked grid (no `.test.` in the name, so vitest skips it) | 120 |
| `../../pages/Calendar.tsx` | the Inertia page: props, URL state, `ConsoleCalendar` | 120 |
| `../../index.ts` | `export { Calendar }` and the public types | 30 |

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves `npx vitest run modules/events`, `tsc` and the events pytest green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: dependency, adapter, range fetch, read-only views** | 1–6 | verified FullCalendar install with allow-list and boundary tests; time and range maths; the cache and fetch hook; the adapter; the shell with toolbar, filters, states, popover and slots; the console page in read-only form |
| **B: create, move, resize, overrides, timezone** | 7–12 | the change → request maths; the write orchestration with its prompts and outcomes; drag and resize wiring; quick create and the editor prefill; the Move dialog; the timezone toggle |
| **C: accessibility, e2e, docs** | 13–15 | keyboard and focus behaviour; `events-calendar.spec.ts` and the CSP check; docs, bundle check and branch verification |

---

### Task 1: Install FullCalendar, verify its surface, and guard the dependency

**Files:**
- Modify: `modules/events/package.json` (`dependencies`, Ruling 1), `package-lock.json`
- Create: `sm_events/ui/calendar/boundaries.test.ts`
- Modify: this plan (corrections from Step 2, in the same commit)

- [ ] **Step 1: Write the failing test** `boundaries.test.ts` (node environment):
  - `allow-lists FullCalendar packages in the module manifest`: every key of `dependencies`, `devDependencies` and `peerDependencies` in `modules/events/package.json` that starts with `@fullcalendar/` or `@full-ui/` is in `ALLOWED = ['@fullcalendar/react', '@fullcalendar/core', '@full-ui/headless-calendar']`, and `@fullcalendar/react` is present.
  - `allow-lists every FullCalendar package in the lockfile`: for every key of `package-lock.json`'s `packages` whose last `node_modules/` segment starts with `@fullcalendar/` or `@full-ui/`, the package name is in `ALLOWED` and its `license === 'MIT'`.
  - `refuses premium names anywhere`: no lockfile package name and no manifest dependency of `modules/events` matches `/scheduler|resource|timeline|premium/` under those scopes. Also assert the test itself catches a synthetic manifest with `@fullcalendar/react-scheduler`, by calling the checker function on a literal object.
  - `imports FullCalendar only from the adapter`: walk `modules/events/sm_events` (skipping `node_modules`) and assert that every `.ts`, `.tsx` or `.css` file containing the string `@fullcalendar/` (in an import, a type import or a CSS `@import`) is under `ui/calendar/adapter/`. The test file itself is excluded by path.
- [ ] **Step 2: Run** `~/.claude/bin/wait-for-headroom`, then `npx vitest run modules/events/sm_events/ui/calendar/boundaries.test.ts`. Expected: the first test fails (no dependency yet).
- [ ] **Step 3: Install and verify.** From the root (headroom first): `npm install --workspace modules/events @fullcalendar/react@^7.1.5 temporal-polyfill@^1.0.8`. Then read, without guessing, and write the answers into this plan's Rulings 1, 3, 5, 9, 22 and 23 and into Task 4's interfaces wherever they differ:
  - `node_modules/@fullcalendar/react/package.json` `exports`. Expected as of 2026-11-17: `.`, `./daygrid`, `./timegrid`, `./list`, `./interaction`, `./multimonth`, `./locales/*`, `./locales-all`, `./skeleton.css`, `./themes/{classic,forma,pulse,breezy,monarch}` (JS) with `theme.css`, and palettes.
  - `index.d.ts`: the default or named export of the component, the ref type with `getApi()`, and the prop names for `timeZone`, `locale`, `eventInteractive`, `headerToolbar`, `editable`, `selectable`, `eventAllow`, `eventDrop`/`eventResize` (and whether their argument still has `revert()` and `delta`), `datesSet`, `eventContent`, `dateClick`, `select`, `noEventsContent`, and what type `event.start` is (a `Date`, or a Temporal value).
  - `themes/classic/index.d.ts`: how a theme is applied (a plugin in `plugins`, or CSS only), and the CSS variables `theme.css` reads.
  - `README.md` and the types: does `eventClick` fire on Enter for an interactive event?
  - Peers: `npm ls temporal-polyfill @fullcalendar/core @full-ui/headless-calendar` shows one copy of each.
  - CSP: `grep -rlE "new Function|\beval\(|createElement\(['\"]script" node_modules/@fullcalendar node_modules/@full-ui node_modules/temporal-polyfill` finds nothing in shipped JS (a comment-only match is fine; say so). Also note whether core inserts a `<style>` element at runtime.
- [ ] **Step 4: Run** the test: passes. Then `npx tsc --noEmit -p modules/events/tsconfig.json` (passes; nothing imports FullCalendar yet).
- [ ] **Step 5: Commit** `build(events): FullCalendar 7 (MIT packages only) with an allow-list test` (`modules/events/package.json`, `package-lock.json`, `boundaries.test.ts`, this plan).

### Task 2: Time and range maths

**Files:**
- Create: `ui/calendar/time/zones.ts`, `ui/calendar/time/range.ts`, `ui/calendar/time/format.ts`
- Constants (frontend-only, so not in `core/constants.py`): `RANGE_MARGIN_DAYS = 7`, `MAX_RANGE_DAYS = 366` and `DEFAULT_CREATE_MINUTES = 60` in `time/range.ts`; `CACHE_ENTRIES = 8` in `data/cache.ts` (Task 3).
- Test: `ui/calendar/time/zones.test.ts`, `ui/calendar/time/range.test.ts`, `ui/calendar/time/format.test.ts`

**Interfaces:**

```ts
// zones.ts — Temporal from 'temporal-polyfill'
export type TzMode = 'calendar' | 'mine';
export const browserTimeZone: () => string;
export function gridTimeZone(mode: TzMode, shown: CalendarInfo[], tenantDefault: string, mine?: string): string;
export function toLocal(instantIso: string, timeZone: string): string;      // 'YYYY-MM-DDTHH:MM' (+':SS' if non-zero)
export function toInstant(local: string, timeZone: string): string;          // earlier on a fold, later on a gap (= server); ISO 'Z'
export function isRepeatedSecond(instantIso: string, timeZone: string): boolean; // instant is the 2nd of a repeated wall time
export function shiftLocal(local: string, from: string, to: string): string;  // local + (to - from), PlainDateTime maths
export function addDays(date: string, days: number): string;                 // 'YYYY-MM-DD'
// range.ts
export type Range = { start: string; end: string };                         // ISO 'Z', half-open
export function paddedRange(visible: Range, margin?: number): Range;         // clamps to MAX_RANGE_DAYS around the visible middle
export function contains(outer: Range, inner: Range): boolean;
export function rangeKey(q: OccurrenceQuery): string;                       // stable: sorted filter ids
// format.ts
export function timeText(o: Occurrence, timeZone: string, locale: string): string;   // all-day → dates only
export function localTimeText(o: Occurrence, locale: string): string | null;         // in o.timezone; null when it is the grid zone's text
```

- [ ] **Step 1: Write the failing tests:**
  - `zones.test.ts`:
    - `toLocal across the EU change`: `toLocal('2026-03-30T09:00:00Z', 'Europe/Vienna') === '2026-03-30T11:00'` and `toLocal('2026-03-23T09:00:00Z', 'Europe/Vienna') === '2026-03-23T10:00'`.
    - `toLocal keeps non-zero seconds`: `'…T09:00:30Z'` → `'…T10:00:30'` (winter date).
    - `toInstant round-trips outside gaps and folds` (a seeded loop of 300 instants over `Europe/Vienna`, `America/New_York`, `Australia/Lord_Howe`, `Pacific/Apia`, `Asia/Kolkata`): `toInstant(toLocal(i, z), z) === i`, except where `isRepeatedSecond(i, z)`.
    - `isRepeatedSecond on the Vienna fold`: `'2026-10-25T01:30:00Z'` (02:30 CET, the second) is true, `'2026-10-25T00:30:00Z'` (02:30 CEST, the first) is false, and `'2026-07-01T08:00:00Z'` is false.
    - `toInstant on a gap matches the server`: `toInstant('2026-03-29T02:30', 'Europe/Vienna') === '2026-03-29T01:30:00Z'`.
    - `shiftLocal adds a wall-clock difference`: `shiftLocal('2026-03-02T10:00', '2026-03-23T10:00', '2026-03-30T11:00') === '2026-03-09T11:00'`.
    - `gridTimeZone`: one calendar shown gives its zone; two give the tenant default; `mine` gives the injected browser zone.
    - `addDays crosses month ends`: `addDays('2026-01-31', 1) === '2026-02-01'`.
  - `range.test.ts`:
    - `pads by seven days`: `[2026-03-01, 2026-04-12)` → `[2026-02-22, 2026-04-19)`.
    - `never exceeds 366 days`: a 360-day visible range padded stays ≤ 366 days and still contains the visible range.
    - `contains`, including equal edges.
    - `rangeKey ignores filter order`: `calendars: ['b','a']` and `['a','b']` give the same key.
  - `format.test.ts`:
    - `all-day text is dates only and ignores the zone`: an occurrence with `start_date: '2026-03-29'`, `end_date: '2026-03-30'` gives the same text for `Europe/Vienna` and `Pacific/Kiritimati`, with no time in it.
    - `timed text in the grid zone`: 09:00Z in `America/New_York` (en) contains `5:00` (EDT, 2026-03-23).
    - `localTimeText is null when zones agree` and contains `10:00` and `Europe/Vienna` when the grid is New York (de).
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/calendar/time`: fails.
- [ ] **Step 3: Implement.** Use `Temporal.Instant`, `toZonedDateTimeISO`, `Temporal.PlainDateTime` and `toZonedDateTime(tz, { disambiguation: 'earlier' })` in `toInstant` for folds; for a gap, `'later'`, so it matches `zoneinfo`'s shift forward (PR 2 Ruling 4). Detect a gap by comparing a round trip: the round trip differs from the input in a gap. `isRepeatedSecond(i, z)` is true when `toInstant(toLocal(i, z), z) !== i`, and the local time is not in a gap.
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): calendar time and range maths on Temporal`.

### Task 3: The occurrence cache and fetch hook

**Files:**
- Create: `ui/calendar/data/cache.ts`, `ui/calendar/data/useOccurrences.ts`
- Test: `ui/calendar/data/cache.test.ts`, `ui/page-tests/useOccurrences.test.tsx` (happy-dom)

**Interfaces:**

```ts
// cache.ts
export class RangeCache {
  constructor(limit = CACHE_ENTRIES /* 8 */);
  find(visible: Range, filtersKey: string): OccurrencePage | undefined;  // an entry whose range contains `visible`; touches LRU
  put(range: Range, filtersKey: string, page: OccurrencePage): void;
  clear(): void;
}
export function filtersKey(q: Omit<OccurrenceQuery, 'start' | 'end'>): string;
// useOccurrences.ts
export function useOccurrences(args: { fetcher: OccurrenceFetcher; visible: Range | null;
  filters: Omit<OccurrenceQuery, 'start' | 'end'>; refreshToken: number }): {
  items: Occurrence[]; truncated: boolean; loading: boolean; error: unknown | null;
  retry: () => void; invalidate: () => void };
```

The items returned are filtered to the visible range only by FullCalendar, so the hook returns the cached page's items as they are.

- [ ] **Step 1: Write the failing tests:**
  - `cache.test.ts`:
    - `hit inside a padded range`.
    - `miss on different filters`.
    - `evicts least recently used past 8`.
    - `clear empties`.
  - `useOccurrences.test.tsx` (a fetcher spy returning controllable promises):
    - `fetches the padded range once per navigation inside it`: two visible ranges inside one padded range give one fetch, with `start`/`end` equal to `paddedRange(first)`.
    - `aborts the previous request`: the first call's `signal.aborted` becomes true when the visible range moves outside.
    - `drops a late answer`: resolve the second request, then the first; the items are the second's.
    - `truncated is passed through`.
    - `error then retry`: a rejected fetch sets `error`, `retry()` refetches, and success clears it.
    - `refreshToken bump clears the cache and refetches the same range`.
    - `invalidate after a write refetches even when cached`.
    - `no fetch while visible is null`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/calendar/data modules/events/sm_events/ui/page-tests/useOccurrences.test.tsx`: fails.
- [ ] **Step 3: Implement** on `useRequestScope` (PR 1): begin one scoped request per fetch, and ignore completions whose `alive()` is false.
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): range-keyed occurrence cache with abortable fetches`.

### Task 4: The FullCalendar adapter

**Files:**
- Create: `ui/calendar/adapter/FullCalendarGrid.tsx`, `adapter/options.ts`, `adapter/mapping.ts`, `adapter/calendar.css`
- Create: `ui/calendar/types.ts` (Rulings 6–8, plus `GridHandle` and `GridProps` below, which are internal and not re-exported)
- Test: `ui/calendar/adapter/mapping.test.ts`, `ui/calendar/adapter/options.test.ts`

**Interfaces:**

```ts
export type GridHandle = { today(): void; prev(): void; next(): void; setView(v: CalendarView): void;
  gotoDate(date: string): void; focusEvent(key: string): void };
export type GridProps = {
  view: CalendarView; date: string; timeZone: string; locale: string;
  items: Occurrence[]; editing?: CalendarEditing; renderChip: (o: Occurrence, timeText: string) => ReactNode;
  onRangeChange: (r: { visible: Range; title: string; view: CalendarView; date: string }) => void;
  onEventOpen: (o: Occurrence, element: HTMLElement) => void;
  ariaLabel: string;
};
// mapping.ts (only `import type` from FullCalendar)
export function toEventInput(o: Occurrence, editing: CalendarEditing | undefined): EventInputLike;
  // id = key; all-day → start_date/end_date strings, allDay true; timed → ISO instants;
  // startEditable/durationEditable = Boolean(editing) && o.editable && o.status !== 'cancelled' && !pending;
  // extendedProps.occurrence = o; classNames per Ruling 20 (sm-ev-draft | sm-ev-review | sm-ev-cancelled)
export function toChange(kind: 'move' | 'resize', o: Occurrence, ev: { start: Date | null; end: Date | null;
  allDay: boolean; startStr: string; endStr: string }): OccurrenceChange;
export function allowDrop(o: Occurrence, dropAllDay: boolean): boolean;   // false when all-day would change
export const VIEW_NAMES: Record<CalendarView, string>;  // dayGridMonth, timeGridWeek, timeGridDay, listMonth
// options.ts
export function localeFor(code: string | undefined): LocaleInput | 'en';  // 'de' → the de locale object
export function baseOptions(): Record<string, unknown>;                   // Ruling 9 (headerToolbar false, …)
```

`FullCalendarGrid` forwards a ref to `GridHandle` through `getApi()`, renders chips through `eventContent` → `renderChip`, sets `eventInteractive: true`, calls `onRangeChange` from `datesSet`, and calls `onEventOpen` from `eventClick`. Selection, drop and resize are wired in Task 9; until then `editable` and `selectable` are false. `calendar.css` holds the imports from Ruling 3, the token mapping (also under `.dark`), and the three status styles: a dashed or dotted 2px border, and `text-decoration: line-through` on the title.

- [ ] **Step 1: Write the failing tests:**
  - `mapping.test.ts`:
    - `all-day uses dates and no zone`: `toEventInput` of an all-day occurrence gives `start: '2026-03-29'`, `end: '2026-03-30'` and `allDay: true`, independent of any zone.
    - `timed uses instants`.
    - `editable only when editing, editable, not cancelled and not pending`: a parametrized truth table.
    - `status classes`: draft, in_review and cancelled each get their class; published confirmed gets none.
    - `toChange keeps the occurrence and encodes timed as instants and all-day as dates`.
    - `allowDrop refuses all-day changes`.
  - `options.test.ts`:
    - `de locale data starts the week on Monday`: `localeFor('de')` has `week.dow === 1` (or the property name Task 1 found).
    - `en falls back to built-in`: `localeFor('en') === 'en'`, `localeFor(undefined) === 'en'`.
    - `base options turn the toolbar off and events interactive`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/calendar/adapter`: fails.
- [ ] **Step 3: Implement.** The grid itself is not mounted in vitest (see "What is and is not unit-tested"). Check it by `npx tsc --noEmit -p modules/events/tsconfig.json`.
- [ ] **Step 4: Run** the tests and `tsc`: both pass. Rerun `boundaries.test.ts`: passes (all FullCalendar imports are in `adapter/`).
- [ ] **Step 5: Commit** `feat(events): FullCalendar adapter behind a replaceable boundary`.

### Task 5: The `Calendar` shell: toolbar, filters, states, chip, popover, slots

**Files:**
- Create: `ui/calendar/Calendar.tsx`, `Toolbar.tsx`, `Filters.tsx`, `StatusBar.tsx`, `EventChip.tsx`, `DetailPopover.tsx`, `test-support/FakeGrid.tsx`
- Modify: `sm_events/index.ts` (`export { Calendar } from './ui/calendar/Calendar'` and `export type { CalendarProps, CalendarView, CalendarState, CalendarInfo, CalendarSlots, EventChipProps, DetailProps, ToolbarSlotProps, OccurrenceFetcher, OccurrenceQuery, FilterOption } from './ui/calendar/types'`; `Occurrence` and `OccurrencePage` re-exported from `ui/utils/types-events`), the module doc comment
- Modify: `locales/en.json`, `de.json` (`calendar.toolbar.*`, `calendar.views.*`, `calendar.filters.*`, `calendar.legend.*` (visibility words), `calendar.status.*` (`draft`, `in_review`, `cancelled`, `loading`, `empty`, `truncated`, `retry`), `calendar.detail.*` (`open_editor`, `move`, `your_time`, `event_time`, `read_only`, `needs_publish`, `lang_fallback`))
- Test: `ui/page-tests/Calendar.test.tsx`, `ui/page-tests/CalendarSlots.test.tsx` (happy-dom, `vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/test-support/FakeGrid'))`)

**Interfaces:** `Calendar(props: CalendarProps)` as in Ruling 6. `FakeGrid` records its last props in `fakeGrid.last` and exposes `fakeGrid.emitRange(visible, title)`, `fakeGrid.open(key)`, and in batch B `select(slot)` and `change(change)`, which returns the `onChange` promise. The popover frame is Radix `Popover` with a `PopoverAnchor virtualRef` to the clicked element. `onCloseAutoFocus` prevents the default and focuses that element (Ruling 23).

- [ ] **Step 1: Write the failing tests:**
  - `Calendar.test.tsx`:
    - `toolbar buttons call the grid handle`: today, previous and next each call the matching `GridHandle` method once, and each has an accessible name.
    - `view switcher sets the view and reports state`: clicking "Week" makes `fakeGrid.last.view === 'week'`, the button `aria-pressed="true"`, and `onStateChange` receives `view: 'week'`.
    - `title comes from the grid`: after `emitRange(…, 'March 2026')` the heading shows it.
    - `calendar filter is server-side`: unchecking one of two calendars refetches with `calendars: [other]`.
    - `legend names visibility in words`: each calendar row shows its name and "Private"/"Internal"/"Public" as text.
    - `type filter hidden with one type`.
    - `loading, error with retry, empty and truncated states`: four cases, each with its role (`status`/`alert`) and text, and Retry refetches.
    - `chip shows the status in words`: draft, in-review and cancelled items render "Draft"/"In review"/"Cancelled" in the chip's text content.
    - `detail popover shows grid time and the event's own time when different`: grid `America/New_York`, event `Europe/Vienna`: both lines are present; with a Vienna grid only one.
    - `all-day detail shows dates only`.
    - `read-only reason`: a published, non-editable occurrence on a writable calendar shows "Published: only a publisher can change it", and on a view-only calendar "You can view this calendar only". Neither shows "Move…".
    - `lang badge on fallback title`: `lang: 'en'` while the console is `de`.
    - `no editing prop: no create, no move`: `fakeGrid.last.editing === undefined` and there is no "Move…".
  - `CalendarSlots.test.tsx`:
    - `EventChip slot replaces the chip and can fall back to Default`: a slot that renders `<Default …/>` for `type !== 'x'` and a custom node for `'x'`.
    - `Detail slot gets actions`.
    - `toolbar slots render at both ends with the state`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/Calendar.test.tsx modules/events/sm_events/ui/page-tests/CalendarSlots.test.tsx`: fails.
- [ ] **Step 3: Implement.** `Calendar.tsx` loads the grid with `lazy()` and `Suspense` (the fallback is a `Skeleton` of the grid's height), and computes the grid zone through `gridTimeZone` (calendar mode only until Task 12).
- [ ] **Step 4: Run** the tests, `tsc`, `npx biome check modules/events` and `uv run python scripts/check_locales.py`: all pass.
- [ ] **Step 5: Commit** `feat(events): the Calendar component with filters, states, popover and slots`.

### Task 6: The console calendar screen (read-only)

**Files:**
- Modify: `sm_events/core/constants.py` (`_PAGE_CALENDAR = f"{MODULE_NAME}/Calendar"`, `CALENDAR_URL = f"{VIEW_PREFIX}/"`, `MENU_LABEL_CALENDAR = "Calendar"`, `MENU_LABEL_KEY_CALENDAR = "events.menu.calendar"`, `MENU_ICON_CALENDAR = "calendar-range"`)
- Modify: `web/endpoints/views.py` (`GET /` renders the page; Ruling 25), `web/endpoints/menu.py` (the entry, `order=390`), `locales/*.json` (`menu.calendar`, `calendar.title`, `calendar.subtitle`)
- Create: `sm_events/pages/Calendar.tsx`, `ui/calendar/console/ConsoleCalendar.tsx` (without editing yet), `ui/calendar/console/urlState.ts` (`readState(search: string): Partial<CalendarState>`, `writeState(state): string`)
- Modify: `host/tests/test_menu_labels.py` (item count +1 from what PR 2 left), `host/tests/test_events_wiring.py` (`/admin/events/` is now a page, not a redirect)
- Test: `tests/web/test_views.py` (Python), `ui/calendar/console/urlState.test.ts`, `ui/page-tests/CalendarPage.test.tsx`

**Interfaces:** the page props of Ruling 25. `ConsoleCalendar({calendars, categories, defaultTimezone, contentLocales, editorUrl})` renders `Calendar` with `fetchOccurrences = (q, signal) => listOccurrences({...q}, signal)` (extend PR 2's `listOccurrences` with an optional `signal` if it has none) and `types = [{id: 'event', label: t(…)}]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_views.py`:
    - `test_root_renders_calendar_page`: 200, component `events/Calendar`, and the props carry `calendars` with `visibility` and `default_timezone` only for calendars the viewer sees.
    - `test_root_needs_view`: without `events.view` gives 403 (as the other views do).
    - `test_menu_calendar_first`: the Events group's items in order are Calendar, Events, Calendars, Event categories.
    - Replace PR 1's `test_root_redirects…` (and PR 2's `test_root_still_redirects_to_calendars`).
  - `urlState.test.ts`:
    - `round-trips every field`.
    - `ignores unknown views and malformed dates`.
  - `CalendarPage.test.tsx`:
    - `reads view and date from the URL on load`.
    - `writes state with replaceState`.
    - `passes the console locale to the fetcher`.
- [ ] **Step 2: Run** `cd modules/events && uv run pytest -q tests/web/test_views.py`, then from the root `uv run pytest -q host/tests/test_events_wiring.py host/tests/test_menu_labels.py` and `npx vitest run modules/events/sm_events/ui/calendar/console modules/events/sm_events/ui/page-tests/CalendarPage.test.tsx`: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same (pass), plus `check_hardcoded_strings.py`, `check_rules.py` (the new page has `export default`) and `check_locales.py`.
- [ ] **Step 5: Commit** `feat(events): the console calendar at /admin/events/`.

**End of batch A.** Run (headroom first) `npx vitest run modules/events`, `npx tsc --noEmit -p modules/events/tsconfig.json`, `npx biome check modules/events`, `cd modules/events && uv run pytest -q -n 8`, `uv run python scripts/check_file_size.py` (no WARNING under `modules/events`) and `scripts/check_ts_imports.py`. Then open the page once in the dev stack (the `running-the-stack` skill), check that month, week, day and list render seeded events, and stop the stack.

---

### Task 7: A grid change → the request to send

**Files:**
- Create: `ui/calendar/console/writes.ts` (pure)
- Test: `ui/calendar/console/writes.test.ts`

**Interfaces:**

```ts
export type Scope = 'one' | 'all';
export type Plan =
  | { kind: 'patch'; eventId: string; body: { expected_revision: number; times: TimesIn; drop_orphaned_overrides?: true } }
  | { kind: 'override'; eventId: string; body: { expected_revision: number; original_start: string; kind: 'moved'; start: string; end: string } }
  | { kind: 'refuse'; code: 'stale' | 'repeated_local_time' };
export function isSeries(o: Occurrence): boolean;                    // original_start !== null
export function isStale(o: Occurrence, event: EventOut): boolean;    // Ruling 15
export function planChange(change: OccurrenceChange, event: EventOut, scope: Scope): Plan;  // Rulings 13, 14, 16
```

- [ ] **Step 1: Write the failing tests** (fixtures: a Vienna one-off; a weekly Monday 10:00 Vienna series starting 2026-03-02; an all-day Vienna one-off):
  - `one-off move in a New York grid writes Vienna wall clock`: the occurrence on 2026-03-23 10:00–11:00 Vienna, moved to `2026-03-30T09:00:00Z`, gives `times: {all_day: false, timezone: 'Europe/Vienna', start: '2026-03-30T11:00', end: '2026-03-30T12:00'}` and `expected_revision` from the event.
  - `move keeps the exact duration across the change`: a 2-hour event moved over 29 March still spans 2 hours in instants.
  - `resize changes only the end`.
  - `all-day move by delta with an inclusive end`: `2026-08-01`–`2026-08-04` (exclusive) moved by +2 days gives `start: '2026-08-03'`, `end: '2026-08-05'`.
  - `instance this one is a moved override`: `original_start` is the occurrence's, and `start`/`end` are Vienna local.
  - `instance all shifts the master on the event's wall clock`: the 2026-03-23 instance moved to `2026-03-30T09:00:00Z` (11:00 CEST) gives the master `start: '2026-03-09T11:00'` (`shiftLocal`, Ruling 14).
  - `instance all resize sets the master's duration`.
  - `repeated hour is refused`: a move to `2026-10-25T01:30:00Z` on a Vienna event gives `{kind: 'refuse', code: 'repeated_local_time'}`; `00:30Z` is allowed and gives `02:30`.
  - `isStale`: false when the fetched event matches; true when the one-off's start differs, when the master's `rrule` differs, and when a moved override now exists at the instance's `original_start` with times different from the occurrence's.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/calendar/console/writes.test.ts`: fails.
- [ ] **Step 3: Implement** on `time/zones.ts` only.
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): grid changes become wall-clock writes in the event's timezone`.

### Task 8: The write orchestration, the scope prompt and the orphans confirm

**Files:**
- Create: `ui/calendar/console/useCalendarWrites.ts`, `ui/calendar/console/ScopePrompt.tsx`
- Modify (only if needed): extract PR 2's orphaned-overrides confirm to `ui/components/editor/OrphansConfirm.tsx` without changing its behaviour, and use it from the editor and from here
- Modify: `ui/utils/api.ts` (`errorText` gains `repeated_local_time` and a calendar-specific `stale` text via a `context` argument, or a separate `calendarErrorText` in `console/`; pick whichever keeps `api.ts` under 140 lines), `locales/*.json` (`calendar.writes.*`, `calendar.scope.*`)
- Test: `ui/page-tests/CalendarWrites.test.tsx` (happy-dom, `stubFetch`)

**Interfaces:**

```ts
export function useCalendarWrites(args: { invalidate: () => void; editorUrl: string }): {
  onChange: (change: OccurrenceChange) => Promise<boolean>;  // the CalendarEditing.onChange
  pendingKeys: ReadonlySet<string>;
  dialogs: ReactNode;                                        // the ScopePrompt and OrphansConfirm when open
};
```

Flow: put the key into `pendingKeys` → `getEvent(event_id)` → `isStale` (refuse, Ruling 17) → series? ask `ScopePrompt` (cancel → `false`) → `planChange` → send → on 409 `overrides_orphaned`, `previewRecurrence` for the list and `OrphansConfirm` (confirm → resend with `drop_orphaned_overrides: true`) → a toast per Ruling 17 → `invalidate()` → remove from `pendingKeys` → resolve `true` only on success.

- [ ] **Step 1: Write the failing tests:**
  - `one-off move sends one GET and one PATCH with the fetched revision`.
  - `series asks this one or all; cancel sends nothing and reverts`.
  - `this one posts an override`.
  - `all patches the master`.
  - `client stale sends no write and refreshes`: the GET returns different times, so there is no PATCH, it resolves `false`, `invalidate` is called, and the toast text is the stale one.
  - `409 stale reverts and refreshes`.
  - `409 overrides_orphaned confirms then resends with the flag`, and `cancel at the orphans confirm reverts`.
  - `403 publish_required reverts with the reason`.
  - `422 start_not_in_rule offers the editor`: the toast action's href is `${editorUrl}/${event_id}`.
  - `pending key is set during the write and cleared after`.
  - `network failure reverts with the offline text`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/CalendarWrites.test.tsx`: fails.
- [ ] **Step 3: Implement.** Toasts use `sonner` (a peer already). The prompts are Radix dialogs that return focus to the event element on close.
- [ ] **Step 4: Run** it, plus PR 2's editor tests if `OrphansConfirm` was extracted (`npx vitest run modules/events/sm_events/ui/page-tests/RecurrenceEditor.test.tsx`): pass.
- [ ] **Step 5: Commit** `feat(events): calendar writes with this-one-or-all, stale and orphan handling`.

### Task 9: Drag and resize in the grid

**Files:**
- Modify: `ui/calendar/adapter/FullCalendarGrid.tsx` (`editable`/`selectable` from `editing`, `eventAllow` → `allowDrop`, `eventDrop`/`eventResize` → `toChange` → `editing.onChange`, `revert()` on `false`), `ui/calendar/Calendar.tsx` (passes `editing` through), `ui/calendar/console/ConsoleCalendar.tsx` (wires `useCalendarWrites`)
- Modify: `ui/calendar/test-support/FakeGrid.tsx` (`change(change)` returns the promise)
- Test: `ui/page-tests/CalendarDrag.test.tsx`

- [ ] **Step 1: Write the failing tests** (FakeGrid plus `stubFetch`):
  - `a change from the grid reaches the write flow and resolves true on success`.
  - `a refused write resolves false` (the adapter's revert path).
  - `pending occurrence is not editable`: while the write runs, `fakeGrid.last.items` mapped through `toEventInput` has `startEditable: false` for that key, and the chip has `aria-busy="true"`.
  - `read-only calendar passes no editing`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/CalendarDrag.test.tsx`: fails.
- [ ] **Step 3: Implement.** In the adapter, `eventDrop` and `eventResize` call `editing.onChange(toChange(…))` and `info.revert()` when it resolves `false`. The real gesture is covered by the e2e "drag in week view" test (Task 14).
- [ ] **Step 4: Run** it, `tsc` and `boundaries.test.ts`: pass.
- [ ] **Step 5: Commit** `feat(events): drag to move and resize to change the end`.

### Task 10: Quick create and the editor prefill

**Files:**
- Create: `ui/calendar/console/QuickCreateDialog.tsx`
- Modify: `adapter/FullCalendarGrid.tsx` (`select` and `dateClick` → `editing.onCreate(CreateSlot)`, with the 60-minute default from Ruling 19), `console/ConsoleCalendar.tsx`
- Modify (PR 2 code): `web/endpoints/views.py` editor-new route (pass the query `start`, `end`, `all_day`, `title` through as `prefill: {start, end, all_day, title} | null`, each validated: `start`/`end` must match `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`, the title is a single line ≤ 300 characters; anything invalid is dropped, never a 422), `pages/EventEditor.tsx` or `ui/hooks/useEvent.ts` (start a new form from `prefill`)
- Modify: `locales/*.json` (`calendar.create.*`)
- Test: `ui/page-tests/QuickCreate.test.tsx`, `tests/web/test_views.py` (`test_editor_prefill_passed_and_validated`), and one case in PR 2's `EventEditor.test.tsx` (`prefill fills times and title`)

**Interfaces:** `QuickCreateDialog({slot: CreateSlot | null, calendars: CalendarInfo[] /* writable only */, preferred: string | null, defaultLocale: string, editorUrl: string, onCreated: () => void, onClose: () => void})`.

- [ ] **Step 1: Write the failing tests:**
  - `QuickCreate.test.tsx`:
    - `timed slot prefills local times in the calendar's zone`: slot `2026-07-01T08:00:00Z`–`09:00Z` with a Vienna calendar shows `10:00`–`11:00` and the label `Europe/Vienna`.
    - `changing the calendar re-expresses the same instants`: switching to a `America/New_York` calendar shows `04:00`–`05:00`.
    - `all-day slot shows dates with an inclusive end`: `2026-08-01`–`2026-08-04` (exclusive) shows the end `2026-08-03`.
    - `create posts the default-locale text and times`: the body has `texts: {en: {title}}`, `calendar_id` and `times`; then `onCreated` runs.
    - `title is required` (no request).
    - `server field error lands on the field` (PR 1's `useFormErrors`, `loc` `texts.en.title`).
    - `More options links to the editor with the prefill`: the href equals `/admin/events/edit/new?calendar=<id>&all_day=0&start=2026-07-01T10%3A00&end=2026-07-01T11%3A00&title=<encoded>`.
    - `only writable calendars are offered`.
  - `test_editor_prefill_passed_and_validated`: valid values are passed, and `start=garbage` or a two-line title is dropped.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/QuickCreate.test.tsx modules/events/sm_events/ui/page-tests/EventEditor.test.tsx` and `cd modules/events && uv run pytest -q tests/web/test_views.py`: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same: pass.
- [ ] **Step 5: Commit** `feat(events): click or select to create, with a prefilled editor`.

### Task 11: The Move dialog

**Files:**
- Create: `ui/calendar/console/MoveDialog.tsx`
- Modify: `console/ConsoleCalendar.tsx` (`editing.onMove` opens it from the popover's "Move…"), `locales/*.json` (`calendar.move.*`)
- Test: `ui/page-tests/MoveDialog.test.tsx`

**Interfaces:** `MoveDialog({occurrence: Occurrence | null, onSubmit: (change: OccurrenceChange, scope?: Scope) => Promise<boolean>, onClose})`. The fields are in the **event's** timezone (`toLocal(o.start, o.timezone)`), with the zone named. On submit it converts back with `toInstant` and calls the same write flow as a drag (`useCalendarWrites` gains `submit(change, scope)`, which skips the prompt because the dialog chose the scope). All-day shows date fields only. A series shows the scope radio, defaulting to "Only this occurrence". Changing all-day is not offered here (the editor does it).

- [ ] **Step 1: Write the failing tests:**
  - `prefills event-local times and names the zone`.
  - `end before start is refused locally` (no request; the message is linked with `aria-describedby`).
  - `submit sends the same request as a drag`: moving a Vienna one-off to `2026-03-30 11:00` produces the same PATCH body as Task 7's first case.
  - `series shows scope and all patches the master`.
  - `a refused write keeps the dialog open with the message`.
  - `focus goes to the first field on open and back to the event on close`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/MoveDialog.test.tsx`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): a Move dialog for every move and resize`.

### Task 12: The grid timezone toggle

**Files:**
- Create: `ui/calendar/TimezoneToggle.tsx`
- Modify: `Toolbar.tsx` (mount it), `Calendar.tsx` (`tzMode` in state; `gridTimeZone(mode, shown, defaultTimezone)`), `console/urlState.ts` (`tz=mine`), `locales/*.json` (`calendar.tz.*`)
- Test: `ui/page-tests/TimezoneToggle.test.tsx`

- [ ] **Step 1: Write the failing tests** (the browser zone injected through `browserTimeZone` mocked with `vi.spyOn`, set to `America/New_York`):
  - `calendar time with one calendar uses its zone`: `fakeGrid.last.timeZone === 'Europe/Vienna'`.
  - `calendar time with several calendars uses the tenant default`.
  - `my time uses the browser zone and survives a reload`: `tz=mine` in the URL.
  - `toggle names both zones`: the buttons' text contains `Europe/Vienna` and `America/New_York`, and `aria-pressed` marks the active one.
  - `same zone is said`: with the browser in Vienna it shows "Your time is the same".
  - `all-day items are unaffected`: `toEventInput` of an all-day item is identical in both modes.
  - `popover shows the event's own time in my time`.
  - `a drag in my time still writes the event's zone`: through FakeGrid, a change in a New York grid on a Vienna event sends Vienna wall clock (Task 7's numbers).
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/TimezoneToggle.test.tsx`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it, and the whole `npx vitest run modules/events`: pass.
- [ ] **Step 5: Commit** `feat(events): calendar time and my time for the grid`.

**End of batch B.** Run the batch A end checks again, plus `uv run python scripts/check_hardcoded_strings.py`.

---

### Task 13: Keyboard and focus

**Files:**
- Modify: `EventChip.tsx` (Enter/Space opens the popover when Task 1 found that `eventClick` does not fire on Enter; otherwise nothing), `adapter/FullCalendarGrid.tsx` (`GridHandle.focusEvent(key)`: focus the element whose event id is `key`, used after a popover, dialog or write closes), `DetailPopover.tsx`, `Toolbar.tsx`, `Filters.tsx` (names, roles, `aria-controls` from the view switcher to the grid region)
- Test: `ui/page-tests/CalendarA11y.test.tsx`

- [ ] **Step 1: Write the failing tests:**
  - `every control has an accessible name`: every `button`, `input` and `[role=radio]` in the toolbar, filters, popover and dialogs has a non-empty `aria-label` or text, checked by a helper that walks the mounted tree.
  - `Enter on a chip opens the popover` (only if the chip handles it, per Task 1).
  - `closing the popover with Escape focuses the event again` (`GridHandle.focusEvent` called with the key).
  - `after a successful Move the event is focused again`.
  - `view switcher is a pressed-state group operable with Tab and Enter`.
  - `the grid region is labelled with the title and busy while loading`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/CalendarA11y.test.tsx`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): keyboard access and focus return on the calendar`.

### Task 14: The e2e spec and the CSP check

**Files:**
- Create: `tests/e2e/events-calendar.spec.ts`
- Modify: `tests/e2e/events.spec.ts` (the sidebar test: `/admin/events/` now shows the Calendar heading, and the sidebar lists Calendar first), `tests/e2e/production-csp.spec.ts` (also open `/admin/events/` and wait for the grid)

The spec stands alone (CLAUDE.md, e2e sharding). It seeds through the API with `moduleCsrfHeader`: one calendar per test in `Europe/Vienna` with a unique name, a one-off and a weekly series in the current week (dates computed in the test, never fixed), and nothing it does not create. It keeps `events.spec.ts`'s `pageerror` and `Content Security Policy` listeners and the empty-problems `afterEach`. Locate by role and name. `page.clock` is not used, because FullCalendar's now-indicator does not need it.

- [ ] **Step 1: Write the tests:**
  - `views switch and an event shows in month and week`: open `/admin/events/?calendar=<id>`, see the one-off by title in month, switch to Week (the URL gains `view=week`), see it again, and switch to Day and List.
  - `create by click`: in week view, click an empty slot, fill the title in the quick-create dialog, press Create; the chip appears and the API lists the event as a draft.
  - `move through the Move dialog`: focus the event with the keyboard (Tab until it is focused, then Enter), choose Move…, change the start to the next day at 14:00, and save; the API's `start_local` is that time in Vienna.
  - `drag in week view`: drag the one-off with `page.mouse` (down on the chip, a stepped move one day column to the right, up); the API shows the new day and the same time.
  - `this one or all`: drag a series instance and choose "Only this occurrence"; the event's `overrides` has one `moved` entry, and the other instances are unchanged.
  - `timezone toggle`: with the browser context's `timezoneId: 'America/New_York'` (`test.use`), "My time" shows the 10:00 Vienna event at 04:00 or 05:00 depending on the date (computed with `Intl` in the test), and "Calendar time" shows 10:00.
  - `German week start`: set the `locale` cookie to `de` (as `events.spec.ts` does), open the month view, and the first column header is "Mo." (FullCalendar's German abbreviation; take the exact string from the de locale file and assert on it); reset the cookie to `en` at the end.
  - `a published event is not draggable for a writer without publish`: skipped when the e2e users do not include one; say so in the test's `test.skip` reason. A unit test (Task 5's `read-only reason`) covers the message either way.
- [ ] **Step 2: Run** (headroom first; one suite at a time) `npx playwright test tests/e2e/events-calendar.spec.ts tests/e2e/events.spec.ts` against the dev-server e2e host. Expected: all pass. A failing drag is fixed in the spec's gesture (more `steps`, waiting for `.sm-ev-*` to settle), not by loosening the assertion.
- [ ] **Step 3: Run** the bundle check once: `make e2e-bundle` is a full suite, so instead build (`npm run build`) and run `E2E_BUNDLE=1 npx playwright test tests/e2e/production-csp.spec.ts tests/e2e/events-calendar.spec.ts`. Expected: no CSP violations.
- [ ] **Step 4: Stop** every server the run started (`/usr/bin/ps` to check).
- [ ] **Step 5: Commit** `test(events): e2e for the console calendar, and the calendar under the production CSP`.

### Task 15: Docs, bundle check and branch verification

**Files:**
- Modify: `modules/events/README.md` (Usage: the calendar screen, and the `Calendar` component's props for a host or sibling; status: PR 3 of 10)
- Modify: `modules/events/docs/index.md`. Add a section "The calendar" covering views, filters, create, drag, resize, "this one or all", the grid timezone and the write conversion (Rulings 12–14), the Move dialog and the keyboard, and the outcomes table (Ruling 17). Add a section "Embedding `Calendar`" covering props, slots, the read-only mode and the lazy chunk. Add "FullCalendar" covering the allow-list, the adapter boundary and how to replace it.
- Modify: `CHANGELOG.md` (0.0.16 Added: the calendar component and console calendar; the FullCalendar 7 dependency)
- Modify: `CLAUDE.md`, the events paragraph only, adding:
  - FullCalendar is imported only in `ui/calendar/adapter/`, and only MIT packages on the allow-list (`boundaries.test.ts`);
  - calendar writes convert to the event's timezone wall clock, never UTC;
  - `/admin/events/` is the calendar.
- Modify: the spec's "Amendments", adding "Amendments (PR 3)" listing Rulings 2, 4, 11, 12, 13 (repeated hour), 14 and 15.

- [ ] **Step 1: Bundle check.** `npm run build` (headroom first), then in `host/static/dist/.vite/manifest.json`: the entry `main.tsx` chunk's `imports` do not reach a chunk that contains FullCalendar. Find that chunk by grepping the built JS for a string from `@fullcalendar/core` that survives minification (note in this step which one Task 1 found, for example a CSS custom property name from `skeleton.css` in the CSS asset). It must be reachable only through `dynamicImports`. Record the calendar chunk's gzip size in the PR description (`gzip -c <file> | wc -c`).
- [ ] **Step 2: Lint set** (headroom first), from the root:
  - `uv run ruff check modules/events host scripts`
  - `uv run ruff format --check <files touched>`
  - `npx biome check modules/events tests/e2e/events-calendar.spec.ts`
  - `npx tsc --noEmit -p modules/events/tsconfig.json`
  - `uv run python scripts/check_rules.py`, `check_ts_imports.py`, `check_readmes.py`, `check_hardcoded_strings.py`, `check_file_size.py` (no WARNING under `modules/events`), `check_locales.py`, `moved_paths.py --check` and `bump_version.py --check-current`

  All pass.
- [ ] **Step 3: Targeted suites, one at a time:**
  1. `npx vitest run modules/events`.
  2. `cd modules/events && uv run pytest -q -n 8 tests/web`.
  3. From the root: `uv run pytest -q host/tests/test_events_wiring.py host/tests/test_menu_labels.py host/tests/test_host_boots.py`.

  All pass. Do not run other modules' suites.
- [ ] **Step 4: Commit** `docs(events): the calendar, embedding it, and the FullCalendar boundary`.
- [ ] **Step 5: Hand over to `/ship`.** Browser QA:
  - month, week, day and list on seeded data;
  - create by click and by drag-select, and "More options" into a prefilled editor;
  - drag and resize a one-off, and drag a series instance with both scopes;
  - a series shift that orphans overrides (the confirm);
  - a stale drag from two tabs;
  - a writer without publish on a published event (lock and reason);
  - "my time" with the browser in another zone, across 29 March;
  - the German console (Monday start, 24-hour);
  - keyboard only: Tab to an event, Enter, Move…, save;
  - dark mode;
  - the truncated notice (seed more than 2,000 occurrences with an endless daily series in many calendars, or a test hook).

  Screenshots of the month and week views, the popover, quick create, the Move dialog, the scope prompt and the timezone toggle go in the PR.

## Review Focus

1. **"My time" with an event in another zone across a DST change.** A Vienna 10:00 event viewed in a New York grid in the weeks between the US change (8 March) and the EU change (29 March) shows at 05:00, and an hour later outside them. A drag must write Vienna wall clock, never New York's and never UTC. Covered by Task 2 (`toLocal across the EU change`), Task 7 (`one-off move in a New York grid writes Vienna wall clock`) and Task 12 (`a drag in my time still writes the event's zone`).
2. **The repeated autumn hour.** A drop on the second 02:30 in Vienna must not silently land an hour earlier. Covered by Task 2 (`isRepeatedSecond on the Vienna fold`) and Task 7 (`repeated hour is refused`).
3. **A drag on data that changed since it was loaded.** Another tab moved the event or changed the rule: the drag must not overwrite it with a fresh revision. Covered by Task 7 (`isStale`) and Task 8 (`client stale sends no write and refreshes`, `409 stale reverts and refreshes`).
4. **Fast navigation.** Clicking "next" five times quickly must show the last range's events, not an earlier answer that arrived late, and must not leave five requests running. Covered by Task 3 (`aborts the previous request`, `drops a late answer`).
5. **All-day events on far-off browser zones.** An all-day event on 29 March stays on 29 March in "my time" with the browser at `Pacific/Kiritimati` (+14) or `Pacific/Pago_Pago` (−11). Covered by Task 2 (`all-day text is dates only and ignores the zone`), Task 4 (`all-day uses dates and no zone`) and Task 12 (`all-day items are unaffected`).

## Verification checklist (before `/ship`)

- Task 15's lint set and targeted suites pass; the e2e spec passes in dev and under `E2E_BUNDLE=1` with no CSP message.
- `boundaries.test.ts` passes: only allow-listed MIT FullCalendar packages, imported only in `ui/calendar/adapter/`.
- The build check shows FullCalendar only in a dynamically imported chunk.
- No file under `modules/events` is at 280 lines or more.
- `git diff --stat feat/events-pr2-events` touches only `modules/events/**`, `package-lock.json`, `host/tests/test_events_wiring.py`, `host/tests/test_menu_labels.py`, `tests/e2e/events-calendar.spec.ts`, `tests/e2e/events.spec.ts`, `tests/e2e/production-csp.spec.ts`, `CHANGELOG.md`, `CLAUDE.md`, the spec and this plan.
- The Review Focus tests exist and pass: grep for each test name listed there.

## Open points

1. **`revision` on `Occurrence`.** Ruling 15's extra `GET` per drag and its client-side stale comparison exist only because an occurrence carries no revision. Adding `revision: int | None` to PR 2's `Occurrence` (built-in source only) would remove both. It is a small change to the read and its tests. I recommend it as a follow-up issue, not a PR 2 change now, because PR 2 is in implementation.
2. **Changing all-day by drag** is refused (Ruling 13) and is not offered in the Move dialog. The editor does it. Say if the grid should allow it, with a default duration.
3. **"All" for a weekday change on a `BYDAY` rule** is refused by the server (`start_not_in_rule`, Ruling 14). Rewriting `BYDAY` client-side would make the drag work, but it would put rule editing in the grid. My recommendation is to keep it refused.
4. **List view range.** `listMonth` matches the month view. If the PR 2 Events list makes it redundant, the list view could become `listWeek` or an agenda of the next 30 days.
5. **Keyboard drag.** FullCalendar documents none. If a later v7 release adds it, the Move dialog stays as the documented path.
6. **The ★ rulings** most likely to change are: the adapter-only import boundary (2), the classic theme (3), the lazy split (4), the public props (6) and slots (7), server-side filters and the cache sizes (11), the grid-zone choice for several calendars (12), refusing the repeated hour (13), shifting "all" on the event's wall clock (14) and the GET-before-write stale check (15).
