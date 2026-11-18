# Events PR 6: the extension registry, the plugin guide and the records date-field source. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second package can put its own dates on a calendar and add its own event type without touching events. It ships `events_extensions.py` (sources, types) and `events-extensions.ts` (chips, details, editor sections, settings sections, toolbar items). Events loads both, isolates every plugin call (time budget, item cap, validation, a savepoint), and reports per-source status instead of failing. Records proves it in-repo with an optional `events` extra: the source `records:dates` shows records with a date or datetime field on any calendar where an owner enables it, filtered by records' own access rules.

**Architecture:** On the Python side, the plugin-facing types live in `calendar/extension_types.py` and are re-exported from `sm_events.contracts.extensions`, the only import path a plugin uses. `calendar/registry.py` is a process-global, lock-guarded store that freezes after `calendar/extensions.load_extensions()` has registered the built-ins (the `events` source and the `event` type) and every installed package's `events_extensions`. That load runs in `on_startup` in the web process and on the first registry read in a worker, as in images. `calendar/plugin_runner.py` calls each enabled `(calendar, source)` pair inside a savepoint with an `asyncio.timeout`, and `calendar/plugin_validate.py` turns a plugin's `SourceOccurrence`s into PR 2 `Occurrence`s or rejects the whole answer. The occurrences read merges these with the built-in stream under PR 2's ordering and cap, and the answer carries `sources: [SourceStatus]`. Event types validate `extra` on create and update, an event of an uninstalled type keeps its bytes, and the public page only ever receives a type's declared `public_fields`. Bus events gain the missing transitions and are also published durably through the outbox, which closes PR 2's worker gap. On the frontend, `ui/extensions/` holds a registry, a **lazy** guarded glob of `../../../../*/*/events-extensions.ts`, an error boundary and `buildSlots(surface)`, and these feed PR 3's `CalendarSlots`, PR 2's editor, PR 4's public event page and PR 1's Calendars screen. Records ships `contracts/dated.py`, which is records' own access-checked range read, plus `integrations/events/` (the source and its settings), a thin `events_extensions.py`, and `events-extensions.ts` with a settings section.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy async, pydantic v2, `importlib.metadata` entry points, `asyncio.timeout`, the framework's `EventBus` (`publish`, `publish_durable`, `durable_transport`) and `background_tasks.outbox.worker.worker_bus`, pytest (SQLite, plus opt-in Postgres through `tests/pg_support.py`), React 19 + Inertia, Vite `import.meta.glob` (lazy), `React.lazy`/`Suspense`, vitest (happy-dom), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`, Delivery row 6. It draws on "The core idea: occurrences from sources", "Extension points", "Access", the anti-goals (anything private reaching the public, "leaking across tenants", "unbounded expansion") and the Amendments. Precedent plans: PR 2 (`2026-11-17-events-pr2-events.md`, Rulings 12–15, 23 and 25, open points 2 and 3), PR 3 (Rulings 6 and 7, the slots), PR 4 (Rulings 1, 24, 25 and 32) and PR 5 (Rulings 5, 7 and 29). Precedent code: `modules/images/sm_images/pipeline/{extensions,registry}.py`, `modules/images/docs/writing-a-plugin.md`, `modules/images/sm_images/ui/components/results/{plugins,registry}.ts`, `modules/pagebuilder/pagebuilder/puck-blocks.ts`, `host/client_app/blocks.ts`, `modules/records/sm_records/contracts/newsletter.py` (a records contract that pins its tenant) and `modules/records/sm_records/records/services/_access.py` (`role_blocked`, `caller_access`).

## Depends on PRs 2–5

Before Task 1, rebase the branch onto the finished `feat/events-pr5-feeds` (which sits on PR 4 → PR 3 → PR 2 → PR 1). The implementer of each batch **first re-checks every symbol below against the real code** and corrects this plan's references in the task text, never by renaming earlier PRs' code. The one exception is the internal `SourceContext` rename in Task 3. Stop and report if a *behaviour* differs, not just a name, and in particular if the occurrences read does any database work after it starts yielding, or if `visible_calendars(ANONYMOUS)` can return a non-public calendar.

| Kind | Symbol this plan relies on |
|---|---|
| Read (PR 2) | `sm_events.calendar.occurrences.occurrences(db, *, tenant_id, viewer, start, end, filters, default_locale) -> OccurrencePage` and its `_merge`; `calendar/occurrence.py` `Occurrence` (frozen; `source, key, calendar_id, start, end, all_day, timezone, start_date, end_date, title, lang, color, url, status, type, editable, event_id, original_start, event_status`), `OccurrencePage{items, truncated}`, `OccurrenceFilters{calendar_ids, category_ids, types, locale, include_unpublished}`; `calendar/sources.py` `SourceContext` (internal), `Source` (internal async-iterator protocol), `EventsSource`, `EVENTS_SOURCE`, `SOURCES`, `TRUNCATED`, `sort_key` |
| Times (PR 2) | `calendar/times.py` `localize`, `all_day_dates`, `Span`; `core/timezones.is_known`, `effective` |
| Access | `core/access` `POLICY`, `visible_calendars(who)`, `calendar_rights`; `core/access/events.visible_events`, `load_event`, `event_rights`; PR 4 `core/access/public.ANONYMOUS`, `public_calendars()`; PR 5 `core/access/offline.feed_principal(app, db, *, user_id, tenant_id)` and the directory lookup it makes with `with_roles=True` |
| Writes (PR 2) | `content/events_write.create_event`, `update_event`; `web/schemas/events_in.EventCreate` (`type: str = DEFAULT_EVENT_TYPE`), `EventPatch` (whose `model_validator` refuses `type`, `calendar_id` and `parent_id`); `UnknownType`, `ImmutableField`; `content/revisions.snapshot` (keeps `extra`) |
| Bus (PR 2) | `sm_events.contracts.events` (`EventPublished`, `EventRescheduled`, `EventCancelled`, `EventDeleted`); `content/bus.py` `attach`, `emit`, `commit`, `rollback`; `web/endpoints/deps.event_db`; `content/publish_due.publish_due_async`; `core/worker.py` |
| API / views | `web/endpoints/occurrences_api.py` (`GET /api/events/occurrences`), `web/endpoints/events_api.py`, `web/services/events_out.py` (`EventOut`), `web/endpoints/calendars_api.py`, `web/schemas/calendars.CalendarOut.sources: list[Any]`, `web/endpoints/views.py` (the console `Calendar` page props, PR 3 Ruling 25; the editor props, PR 2 Task 18) |
| Public (PR 4) | `web/endpoints/public/_api.py` (`/api/occurrences`), `_listing.py`, `_event_props.py`, `_feeds.py`, `_urls.absolute(request, path)`; `feeds/select.feed_events(db, *, calendar_id, locale, default_locale, now, url_for, events=None) -> FeedRead`, `FeedEvent`; `feeds/ics_calendar.build(items, *, name, timezone, first, last) -> bytes`; `FEED_DAYS_BACK = 30`, `FEED_DAYS_AHEAD = 366`, `FEED_MAX_COMPONENTS`; `tests/web/public/test_leaks.py` (the parametrized leak table) |
| Private feed (PR 5) | `web/endpoints/public/_private_feed.py` (the route, `_deny`), `feeds/tokens/resolve.resolve -> FeedAccess` (`row`, `who`, `calendar`) |
| Worker (PR 2) | `core/worker.py` (the copied newsletter runtime), `tasks.py`, `task_config.py` |
| Constants | `PACKAGE`, `MODULE_NAME`, `SOURCE_EVENTS = "events"`, `DEFAULT_EVENT_TYPE`, `MAX_OCCURRENCES`, `MAX_RANGE_DAYS`, `EDITOR_URL`, `UNKNOWN_TYPE_CODE`, `IMMUTABLE_FIELD_CODE` |
| TS (PR 3) | `ui/calendar/types.ts` `CalendarSlots`, `EventChipProps` (`Default`), `DetailProps` (`Default`, `actions`), `ToolbarSlotProps`; `ui/calendar/StatusBar.tsx`; `ui/calendar/Filters.tsx`; `ui/calendar/console/ConsoleCalendar.tsx`; `index.ts` exports |
| TS (PR 2/4/1) | `ui/components/editor/EventForm.tsx`, `ui/hooks/useEvent.ts`, `pages/EventEditor.tsx`; `pages/PublicEvent.tsx`, `ui/public/PublicCalendarGrid.tsx`; `pages/Calendars.tsx`, `ui/components/calendars/CalendarRow.tsx`; `ui/utils/api.ts` `ApiError`, `send`, `fieldsOf`; `ui/utils/i18n.ts` `keys`, `translate`, `useT`; `ui/utils/types-events.ts` `Occurrence`, `OccurrencePage`, `EventOut` |
| Tests | `tests/support/app.py`, `tests/support/access.py` (`principal`, `seed_calendars` → `P`, `I`, `U`), `tests/support/calendars.seed_event`, the `unbound_tenant` marker, `tests/pg_support.py`; `ui/page-tests/test-dom.tsx`, `support.tsx` (`stubFetch`), `ui/calendar/test-support/FakeGrid.tsx`; e2e `tests/e2e/helpers.ts` (`login`, `moduleCsrfHeader`, `uniqueSlug`) |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**Registry and loading**
1. **Discovery, as images does it** (spec). A package with a `simple_module` entry point ships `<package>/events_extensions.py` with `def register(registry) -> None`. `calendar/extensions.load_extensions()` first runs the built-in loaders (the `events` source and the `event` type), then goes through each entry point sorted by package name: it probes `<pkg>.events_extensions` with `find_spec`, imports it and calls `register(Registrar(namespace=<entry-point name>))`. Then it freezes the registry. A second call does nothing. A failure resets the registry and propagates, so a broken plugin fails the boot, exactly as images does. Only a missing `events_extensions` submodule, or an entry-point package that cannot be imported at all, is skipped (images' `_find`, copied rather than imported). The web process calls it in events' `on_startup`. A worker calls it on its first registry read: every public getter runs `ensure_loaded()`. After the freeze, `add_source` and `add_type` raise `RegistryFrozenError`.
2. ★ **Ids are namespaced by the entry-point name.** Plugin ids match `^[a-z][a-z0-9_]*:[a-z][a-z0-9_-]{0,47}$`, and the part before `:` must equal the entry-point name the `Registrar` was built for. Records' entry point is `records`, so its source is `records:dates`. Breaking either rule raises `InvalidExtensionId`. The built-ins `events` (source) and `event` (type) carry no colon and are registered only through `register_builtin_*`. A duplicate id raises `DuplicateExtension`. Namespacing by entry-point name makes a collision between two installed packages impossible, rather than leaving it to depend on load order.
3. **Registration validates the object once**, so a malformed plugin fails at boot rather than on a read (images' `_check_protocol`). The checks:
   - a `Source` has a string `id` and `label_key`, `public: bool`, an optional `color` (`#rrggbb`) and `icon` (`[a-z0-9-]{1,40}`), `settings_model` (`None` or a pydantic `BaseModel` subclass), a coroutine function `occurrences`, and optionally a coroutine function `check_settings`;
   - an `EventType` (a frozen dataclass) has an `id`, a `label_key` and an `extra_model` whose `model_config["extra"] == "forbid"`, and every name in `public_fields` is a field of that model.
4. **Install identically in the web image and in every worker image** (images' rule, documented). Today only the web process reads sources. A worker never re-validates `extra` (Ruling 21), so a worker without a plugin's types loses nothing. The rule is still documented, because PR 8 (reminders) will render occurrences in a worker.

**Sources: shape and context**
5. ★ **Plugins return `SourceOccurrence`, not PR 2's `Occurrence`.** `SourceOccurrence` (pydantic, `extra="forbid"`, frozen) has:
   - `key` (1–200, `[A-Za-z0-9:._@-]`);
   - `title` (1–300, plain text);
   - `start` and `end` (aware datetimes), **or** `all_day: True` with `start_date` and `end_date` (`date`, end exclusive);
   - `timezone` (IANA name; defaults to the calendar's);
   - `url`;
   - `color` (`#rrggbb`);
   - `status` (`confirmed` | `cancelled`);
   - `lang`;
   - `updated_at` (for the ICS `DTSTAMP`).

   It has no `source`, `calendar_id`, `editable`, `type`, `event_id` or `event_status`. The read fills those in: `source` is the source's id, `calendar_id` is the calendar being read, `editable=False`, `type=DEFAULT_EVENT_TYPE`, and the rest are `None`. So a plugin cannot claim another source's id or another calendar, cannot be dragged, and does not have to know the internal model. The internal async-iterator protocol stays PR 2's and is used by the built-in only.
6. **`SourceContext`** (frozen dataclass) carries:
   - `tenant_id`;
   - `viewer: SourceViewer | None`, where `SourceViewer` holds `user_id`, `roles: tuple[str, ...]`, `permissions: frozenset[str]` and `role_map: Mapping[str, Any] | None`; it is `None` on every public surface;
   - `calendar: SourceCalendar` (`id`, `slug`, `name`, `visibility`, `default_timezone`, `color`);
   - `settings` (the validated settings-model instance, or `None`);
   - `locale` and `default_locale`;
   - `limit: int`;
   - `db: AsyncSession`.

   Roles are carried because records narrows by role (`allowed_roles`), and the framework's `ResourcePrincipal` has none. The console builds the viewer with `source_viewer_from(request)` (roles from `request.state.user.roles`, permissions from the resolved set, `role_map` from `app.state.sm.permissions.role_map`). The private feed builds it with `feed_viewer(app, db, *, user_id, tenant_id)` (Task 7), which reuses PR 5's directory lookup.
7. ★ **The database handle is the caller's session inside a savepoint.** Each plugin call runs in `async with db.begin_nested()` after a `db.flush()`. A failing statement then rolls back only that savepoint, and on Postgres the request's transaction is not aborted (the bug PR 1's owner-name lookup hit). After the call, the runner checks that the session's outer transaction object is unchanged and that `db.new`, `db.dirty` and `db.deleted` are empty. If not, the plugin wrote or committed: the savepoint is rolled back, the answer is dropped, status `failed` with code `wrote`, and an error is logged. A separate session per call was considered. It would let calls run concurrently, but the in-memory SQLite test engine shares one connection, and the savepoint keeps "a plugin reads in the request's snapshot and tenant". Calls therefore run **sequentially**. The isolation guards against plugin *bugs*, not malice: a plugin is code the operator installed, and the guide says so.
8. ★ **Budget.**
   - Each call gets `SOURCE_TIMEOUT_SECONDS = 2.0` (`asyncio.timeout`).
   - All plugin calls of one read share `SOURCE_PHASE_SECONDS = 5.0`. A call starts only if at least 0.25 s of the phase is left, and its timeout is `min(2.0, remaining)`. Pairs that cannot start get `skipped` with code `budget`.
   - At most `SOURCE_CALLS_MAX = 16` `(calendar, source)` pairs are called per read, ordered by calendar name and then source id. The rest get `skipped` with code `too_many_calls`.
   - Each call may return at most `ctx.limit = SOURCE_CALL_MAX_ITEMS = 500` items. Beyond that, the earliest 500 (by `sort_key`) are kept, the status is `truncated` and the page is `truncated`.

   On a timeout the savepoint is rolled back. asyncpg cancels the statement on the server. aiosqlite finishes its statement in its thread, and the rollback queues behind it, which is slow but correct. If that rollback raises, no further plugin calls are made in this read (the rest get `skipped`, code `session`), and the built-in source still runs. The guide adds that a plugin which swallows `CancelledError` or blocks the loop with synchronous work cannot be pre-empted.
9. **Validation** (`plugin_validate.py`). Any single invalid item rejects that call's **whole** answer, with status `failed` and code `invalid_item`, because a partly valid answer comes from a broken source and is the one most likely to leak. The checks:
   - It is a `SourceOccurrence`.
   - A timed item has aware `start < end`, normalised to UTC. An all-day item has dates with `start_date < end_date`, converted to the UTC instants of local midnight in `timezone` through `times.localize`, with `start_date`/`end_date` kept.
   - The span is at most `MAX_EVENT_DAYS` (366).
   - `timezone` is known.
   - The title is stripped and its control characters removed. If it is still non-empty, it is kept as text: `<` and `>` are allowed, because every renderer escapes them, and a test proves it.
   - `url` is `None`, a same-origin path (starts with `/`, not `//`, no `\`, no control or whitespace characters, ≤ 2000), or an absolute `http`/`https` URL (≤ 2000). `javascript:`, `data:` and anything else is invalid.
   - `key` is unique within the call (otherwise code `duplicate_key`).

   An item that does not intersect `[start, end)` is **dropped**, not an error, because a source may over-fetch at the edges. A call that raises gets `failed` with code `raised`. It is logged with `logger.exception` naming the source id and calendar id, never an item's content.
10. **Merging.** Plugin answers become one sorted stream that joins PR 2's built-in stream in `_merge`, under PR 2 Ruling 13's `(start, end, source, key)` order and the 2,000 cap. When the same `(source, calendar_id, key)` appears twice, only the first is kept. No share of the cap is reserved for the built-in source: items are cut by time, so a busy plugin can only push later items out.
11. ★ **Status report.** `OccurrencePage` gains `sources: list[SourceStatus] = []`, where `SourceStatus` is `{id, calendar_id, status, code: str | None}` and `status` is one of `ok`, `truncated`, `failed`, `timeout`, `skipped` or `not_installed`. Only plugin pairs appear: the built-in source never does. `not_installed` marks an entry stored on a calendar whose id is not registered on this host. `failed` also covers stored settings that no longer validate against the source's model (code `invalid_settings`; the source is not called). The console API returns `sources`. The public `/api/occurrences` and every public page omit it (they log it instead), so a public answer that may be cached does not vary with a plugin's health.

**Which sources run where**
12. **Per-calendar enabling** (spec: "An admin enables a source per calendar").
    - Entries are `events_calendar.sources = [{"id": str, "settings": dict}]`, at most `CALENDAR_SOURCES_MAX = 8`, and each id at most once per calendar. A plugin that needs several configurations takes a list in its settings model, as records does with `mappings`.
    - The built-in `events` is always on and is never listed. Writing it gives 422 `builtin_source`.
    - ★ **There is no data migration.** PR 1's column is already JSON and events is unreleased. A tolerant reader (`calendar/source_entries.read(raw) -> list[SourceEntry]`) maps a plain string `"x"` to `{"id": "x", "settings": {}}` and drops (and logs) anything else that is malformed. Writes always store objects.
    - **Writing** is `PUT /api/events/calendars/{id}/sources {sources: [{id, settings}]}`. It needs the visibility right, which is the owner's or `events.manage`'s (PR 1), because enabling a source changes what the calendar's audience sees. Otherwise the answer is 404 or 403.
    - Each registered entry's `settings` is validated with `settings_model.model_validate` and stored as `model_dump(mode="json")`. A source without a model must get `{}`. Errors are a 422 in FastAPI's list shape with `loc ["body", "sources", i, "settings", …]`.
    - Then the optional `async check_settings(sctx: SettingsContext, settings) -> None` runs in a savepoint with the same timeout. `SettingsContext` holds `tenant_id`, `viewer` (the admin), `calendar` and `db`. It raises `SourceSettingsError(loc: tuple[str | int, ...], message: str)`, which becomes that 422. A timeout or another exception gives 503 `source_unavailable`.
    - An entry whose id is **not registered** is accepted only if it equals a stored entry byte for byte (it is kept as is: "not installed"). Otherwise it gets 422 `unknown_source`.
    - `CalendarOut.sources` becomes `list[CalendarSourceOut{id, settings, installed: bool, label_key: str | None}]`.
13. ★ **The public surface calls only `public = True` sources**, and only on calendars that `visible_calendars(ANONYMOUS)` returns, with `viewer=None`. The default is `public = False`, and such a source is never called for an anonymous read, a public feed, a public page or the public API. A public source must return only data that is public in its own module, which for records means published records of `is_public` types. A signed-in read calls every enabled source on the calendars that viewer can see. A signed-in caller that passes no `source_viewer` (a sibling going through `contracts.occurrences` without one) gets every plugin pair `skipped` with code `no_viewer`, which fails safe.
14. **Filters.** `OccurrenceFilters` gains `sources: frozenset[str] | None = None` (`None` means every applicable source; `SOURCE_EVENTS` names the built-in). `GET /api/events/occurrences` takes repeatable `source=` values. `types` keeps filtering the built-in stream only. A plugin item's `type` is always `DEFAULT_EVENT_TYPE`, and the frontend dispatches its chip on `source` first (Ruling 27).
15. ★ **On the public site, plugin occurrences appear in the grid (`/api/occurrences`) and the feeds only**, never in the server-rendered upcoming list, the sitemap, JSON-LD or the 404 suggestions. Those are about this module's event pages, and PR 4's listing passes `sources={SOURCE_EVENTS}`. This narrows public exposure to the two surfaces that already show "things on a calendar" (open point 1).
16. **Feeds** (spec: plain instances, 30 days back and 366 ahead, `UID <source>:<key>`).
    - The feed calls the plugin runner directly, not the occurrences read. Its window is 396 days, over the read's 366, so sources must accept any window up to `SOURCE_WINDOW_MAX_DAYS = 400`.
    - The public `calendar.ics` and `c/{cal}.ics` feeds call public sources with `viewer=None`. The private feed (PR 5) calls every enabled source with `feed_viewer(...)` for the token's owner. When the viewer cannot be built, the plugin pairs are skipped and the feed is still served.
    - Each item becomes one `VEVENT`:
      - `UID:<source>:<key>`, `SUMMARY`, `STATUS`;
      - `DTSTART`/`DTEND` in UTC (timed) or `VALUE=DATE` (all-day);
      - `URL`, absolute through PR 4's `_urls.absolute` for a path;
      - `DTSTAMP` = `updated_at`, else `start`, so the body stays deterministic for PR 4's ETag;
      - `SEQUENCE:0`.
    - Plugin VEVENTs count against `FEED_MAX_COMPONENTS` after this module's own events, so a cut drops plugin items first.

**Amendments (decided during implementation)**
- **14a. A category filter narrows.** When `OccurrenceFilters.category_ids` is set, plugin sources are not called and add no items or statuses (their items have no category), on the console read, the public read and both APIs alike; with no category filter they appear as before. Same principle as `types`.
- **16a. A plugin item's ICS UID is `<source id>:<calendar id>:<key>`**, passed through the same single-line sanitiser and the `UID_MAX` cap as native UIDs, so one source on two calendars gives two distinct items. A repeat inside one source and calendar answer is already refused (`duplicate_key`); a repeated UID in the file keeps the first. `SourceOccurrence.updated_at` reaches `DTSTAMP` through `PluginOccurrence` (excluded from every response).
- **12a. Source settings are never secret.** They are stored in the clear and shown only to those who can manage the calendar; registration refuses a `settings_model` with a `SecretStr`/`SecretBytes` or sealed-secret field.

**Event types**
17. **`EventType`** (spec: an id, a label key and a pydantic model that validates `extra`). It is a frozen dataclass with:
    - `id`;
    - `label_key`;
    - `extra_model: type[BaseModel]`;
    - `public_fields: frozenset[str] = frozenset()`;
    - `icon: str | None`.

    Defaults are the model's field defaults, and the JSON schema is `extra_model.model_json_schema()`. The built-in `event` type's model is `NoExtra` (no fields, `extra="forbid"`). `GET /api/events/types` (`events.view`) lists `[{id, label_key, icon, builtin, public_fields, json_schema, defaults}]`, sorted with built-in first, then by id.
18. **Create** takes `type` (a registered id; otherwise 422 `unknown_type`) and `extra: dict = {}`. `extra` is validated with `extra_model.model_validate(extra)` and stored as `model_dump(mode="json")`. Its serialised JSON may be at most `EXTRA_MAX_BYTES = 16_384` (otherwise 422 `extra_too_large`). Validation errors become a `RequestValidationError` with `loc ["body", "extra", *err.loc]` and the error's `msg`, so the editor maps `extra.<path>` to the plugin's section.
19. ★ **The type is immutable** (PR 2 Ruling 23 stands: `type` in a PATCH gives 422 `immutable_field`). Changing a type reinterprets `extra`. A conversion is a new event, and refusing it removes a re-validation path nobody has asked for.
20. **Update.** A PATCH that sends `extra` replaces it whole, validated against the event's type. A PATCH without `extra` leaves the stored JSON byte for byte unchanged (PR 2 already does this, and a test pins it).
21. ★ **An event whose type is not installed** keeps `type` and `extra` byte for byte. Its `extra` is never re-validated, never rewritten by any path (update, override, workflow, trash and restore, the worker's `publish_due`, the import, the revision snapshot), and never editable: a PATCH with `extra` gets 422 `type_not_installed`. The event renders as a plain event. `EventOut` gains `type_installed: bool` and `type_label_key: str | None`, and the editor shows a notice and hides the section. Every other field stays editable.
22. ★ **Public extra.** Public pages receive `public_extra = {k: extra[k] for k in public_fields if k in extra}`, and only when the type is installed (otherwise `{}`). `extra` itself never reaches a public prop, the public API, ICS or JSON-LD. A plugin's `PublicDetail` can therefore show only what its type declared public, whatever it renders.

**Bus events**
23. ★ **The final list in `sm_events.contracts.events`.** PR 2's four stay. Five are added (PR 2 open point 3), each carrying `tenant_id, event_id, calendar_id, uid` first:
    - `EventUnpublished(was_scheduled: bool)` on `unpublish` and `unschedule`;
    - `EventReinstated(original_start: datetime | None)` when a published event's `cancelled` flag is cleared, or a `cancelled` override on it is cleared or replaced by another kind;
    - `OccurrenceSkipped(original_start: datetime)` for a `skipped` override on a published event;
    - `EventRestored()` when a published event is restored from the trash;
    - `EventUpdated(changed: tuple[str, ...])` for any other write to a published event, where `changed` is the sorted top-level names (`texts`, `venue_name`, `category_id`, `extra`, …).

    A write covered by a specific event emits only that one. They are emitted only for events that are, or were, published, as in PR 2 Ruling 25.
24. ★ **Durable delivery closes PR 2 open point 2. No upstream issue is needed.**
    - `content/bus.emit` still publishes in process after commit.
    - When the session's bus has a `durable_transport` and the event type has durable handlers (`bus.durable.handler_names`), it also calls `await bus.publish_durable(event, db)` in the same transaction, as `modules/records/sm_records/public_submissions/mail_runner.py:_durable` decides.
    - `events.publish_due` attaches `background_tasks.outbox.worker.worker_bus()` to each tenant's session, so a scheduled publish reaches **durable** subscribers. In-process subscribers see web-process changes only.
    - The import keeps emitting nothing (PR 5 Ruling 29: 5,000 rows for one upload would flood every subscriber).
    - Every class is a plain `@dataclass` that passes `simple_module_core.durable_events.check_serializable`.
    - The guide tells subscribers: use `bus.subscribe_durable(Type, handler, name="<stable>")` in `register_event_handlers` before any `if app is None: return` to see everything, and `bus.subscribe` for the web process only.

**Frontend**
25. ★ **Registrations are lazy.** `events-extensions.ts` statically imports only `@simple-module-py/events` and type-only imports, and passes loaders:
    - `registerEventType({id, Chip?, Detail?, EditorSection?, PublicDetail?})`;
    - `registerSource({id, Chip?, Detail?, SettingsSection?, PublicDetail?})`;
    - `registerToolbarItem({id, placement: 'start' | 'end', surfaces: ('console' | 'public')[], Component})`.

    Each component is `() => Promise<{default: ComponentType<P>}>`. Events wraps every loader in `React.lazy` inside a `PluginBoundary` (an error boundary that renders the `Default`, or nothing) and `Suspense`. This keeps console code out of the public chunk: the public page fetches only `PublicDetail`. A repo test scans every `modules/*/*/events-extensions.ts` for any other static import. An id registered twice throws.
26. **Loading is a lazy, guarded glob.** `ui/extensions/load.ts` runs `import.meta.glob('../../../../*/*/events-extensions.ts')` without `eager`. Four levels up from `sm_events/ui/extensions/` is `modules/` in the workspace and the Python lib directory in a wheel install, so `*/*` is `<dist>/<package>` in both (pagebuilder's comment, one level deeper). `loadEventExtensions(): Promise<void>` runs once, with `Promise.allSettled` over the loaders. A file that throws on import is logged with `console.error` naming its path, and the rest load. An eager glob would let one plugin's top-level throw take down the bundle, and would create an import cycle with `index.ts`. `useEventExtensions(): boolean` reports readiness. Until it is ready, defaults render.
27. **Slots.** `buildSlots(surface: 'console' | 'public'): CalendarSlots` builds:
    - `EventChip`, which dispatches on `occurrence.source` (a registered source's `Chip`), then on `occurrence.type` (a registered type's `Chip`), else `Default`;
    - `Detail`, dispatched the same way (`PublicDetail` on the public surface, where a missing one means `Default`);
    - `ToolbarStart` and `ToolbarEnd`, which render that placement's items for the surface in id order.

    PR 3's `CalendarProps` stays unchanged. ★ **Plugin components may render on the public page and grid** only through `PublicDetail` and public-surface toolbar items. They get `{occurrence | event fields, publicExtra, locale}` and never console props. The guide says they must not call console APIs (an anonymous visitor gets a 401) and must not inject scripts (the page runs under the nonce CSP).
28. **The editor.**
    - On create, a type picker appears when more than one type is registered. The type is shown read-only afterwards (Ruling 19).
    - A registered `EditorSection` gets `{extra, onChange, errors: Record<string, string>, readOnly, locale, eventId: string | null}`. `errors` is keyed by the path under `extra` (`speaker.name`), with the server's message. `ApiError` gains `messages: Record<string, string>` from the 422's `msg`, and `readOnly` is the editor's locked flag.
    - Saving sends `extra` only when a section exists and changed it.
    - An uninstalled type shows the notice of Ruling 21.
    - Label keys are resolved **at render** through `translateKey(key)` (a runtime `t` with a cast, falling back to the id when the catalogue has no such key). This is the `localizeConfig` lesson in CLAUDE.md: a registration is a module-scope constant.
29. **The Calendars screen** gains a "Sources" action on a row, for the owner or `events.manage` (from `can_change_visibility`). It opens `SourcesDialog`:
    - The dialog lists every registered source from `GET /api/events/sources` with its label, a "public" badge and an enable switch.
    - An enabled source shows its plugin's `SettingsSection` (`{settings, onChange, errors, calendar}`), or, without one, a JSON textarea validated by the server.
    - A stored entry that is not installed is listed as "Not installed", kept unless removed.
    - Save sends `PUT …/sources`.

    The console calendar's `StatusBar` shows one line per non-`ok` status ("Deadlines could not be loaded (timed out)"), and its filters gain a "Sources" group when any source is enabled on a shown calendar. The page props gain `sources: [{id, label_key, color}]`.
30. **Types for plugins.** `index.ts` exports `registerEventType`, `registerSource`, `registerToolbarItem` and the types `EventTypeRegistration`, `SourceRegistration`, `ToolbarItemRegistration`, `EditorSectionProps`, `SourceSettingsProps`, `PublicDetailProps`, `LazyComponent`, `SourceStatus`, plus PR 3's chip and detail props. A plugin never deep-imports (`scripts/check_ts_imports.py`).

**The records source** (spec: "a source that puts a records date field on a calendar")
31. **The dependency direction.** Records depends on events, and events never on records.
    - Records gains the extra `events = ["simple_module_events>=0.0.16,<0.1"]`, with the comment `# floor: 0.0.16: sm_events.contracts.extensions (the plugin registry) first ships in 0.0.16`. The newest tag is `v0.0.15`, so `check_sibling_contracts.py` checks the floor against the working tree.
    - Records' `package.json` gains `@simple-module-py/events` as an optional peer.
    - `sm_records/events_extensions.py` has only `register()`, which imports `sm_records.integrations.events.source` inside the function body. That integration package is the only records code that imports `sm_events`, and only `sm_events.contracts.*`. A records test pins that importing `sm_records.events_extensions` leaves `sm_events` out of `sys.modules`.
    - Records' tests for it run under `pytest.importorskip("sm_events")`.
    - An events test fails on any `sm_records` (or other sibling) string anywhere in `sm_events/`.
32. ★ **A records contract for the read, `sm_records.contracts.dated`.** The source goes through it rather than through records' internals, so the access rule has one owner and is tested where records' rules live. It provides:
    - `dated_records(session, *, tenant_id, type_key, field, end_field=None, lo, hi, caller: DatedCaller | None, locale: str | None, limit: int) -> DatedPage`, which reads published, untrashed records whose `field` lies in `[lo, hi)`, ascending by `field`, at most `limit` (1–`MAX_DATED_BATCH = 1000`), with `truncated` set;
    - `dated_types(session, *, tenant_id, caller) -> list[DatedTypeInfo]` for the settings check.

    The contract binds records' `tenant_scope(tenant_id)` itself and pins `tenant_id` in every query (the newsletter contract's rule).

    **Access:**
    - `caller=None` (anonymous) reads only an `is_public` type.
    - A `DatedCaller(roles, permissions, role_map)` needs `records.view` (`grants`) and must not be `role_blocked(rtype, caller_access(...))`, with records' per-type grant and wildcard rule.
    - A type the caller may not read, an unknown type or an unknown field gives an **empty** page, so nothing can be probed through it.
    - A field that is not an indexed `date`/`datetime` field, or that is being reindexed, raises `DatedQueryError(reason)`.
    - Drafts are never returned to anyone ★ (a calendar is a published view; a draft belongs in records' own screens).
    - On a `translatable` type, only `locale` is returned; otherwise every row.
33. **Source `records:dates`** (`public = True`, `label_key = "records.events.source.label"`, `icon = "database"`).
    - **Settings:** `RecordDatesSettings{mappings: list[RecordDateMapping]}` with 1–5 entries. Each `RecordDateMapping` has `type_key`, `field`, `end_field: str | None`, `duration_minutes: int = 60` (1–1440) and `color: str | None`.
    - **`check_settings`** uses `dated_types` with the admin as caller. It requires the type to exist and be readable, `field` and `end_field` to be indexed fields of the same kind (`date` or `datetime`), and `end_field != field`. Errors carry `loc ("mappings", i, "type_key" | "field" | "end_field")`.
    - **Reading.** For each mapping, the source looks back `RECORDS_SOURCE_LOOKBACK_DAYS = 31` so multi-day records that started earlier show up. A `datetime` field reads `[start − 31 d, end)`. A `date` field reads the local dates of the window in the calendar's timezone, minus 31 days.
    - **Items:**
      - `key = f"{type_key}:{uuid}:{field}"`;
      - `title` = `display_title`, else the type's `label`;
      - `url` = `/admin/records/{type_key}/{uuid}` for a signed-in viewer, `None` for anonymous (records has no public record page);
      - a `date` field gives an all-day item, with `end_date` = (end value or start value) + 1 day;
      - a `datetime` field gives a timed item, ending at the end value or at start + `duration_minutes`; an end before the start falls back to the duration;
      - `timezone` is the calendar's and `color` the mapping's.
    - **Limit:** it requests `ctx.limit + 1` in total across mappings, and the runner marks a call over its limit `truncated`.
    - The frontend `events-extensions.ts` registers `SettingsSection` (type, field and end-field pickers from records' own `/api/records/types`, filtered to indexed date and datetime fields) and a console `Detail` that adds "Open record".

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, biome, alembic, build, Playwright or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. At most one Playwright run at a time; stop its server when done. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr6` on branch `feat/events-pr6-extensions`, stacked on `feat/events-pr5-feeds` → PR 4 → PR 3 → PR 2 → PR 1. Before Task 1, rebase onto the finished PR 5 branch and run the "Depends on" check. Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points and `npx` from the worktree root, and module pytest from the module directory (`cd modules/events && uv run pytest …`, `cd modules/records && uv run pytest …`).
- Implementers are Claude subagents. Each runs pytest in the foreground, commits its own tasks (one commit per task) and never pushes.
- Never run `ruff format` or `biome format` repo-wide. Format only the files touched, and run `uv run ruff check <paths>`. Never commit `.env*`.
- Names: package `sm_events`, npm `@simple-module-py/events`, locale namespace `events` (new keys under `extensions.*`, `sources.*`, `types.*`), API prefix `/api/events`, plugin file names `events_extensions.py` and `events-extensions.ts`, entry-point group `simple_module`, records source id `records:dates`.
- The version stays `0.0.15` (`uv run python scripts/bump_version.py --check-current`).
- Pins are ranges, never `==`. Add no new third-party Python or npm dependency. The only new requirement is records' `events` extra (Ruling 31), with its `# floor:` comment.
- Settings stay DB-backed with no environment reads, and this PR adds no settings field.
- Every query on an events or records table runs with a tenant bound, and Core statements carry their own `tenant_id` predicate. Do not edit either module's `core/tenancy/*` (the parity family).
- Events imports no sibling module. Records imports only `sm_events.contracts.*`, and only from `sm_records/integrations/events/`. `scripts/check_sibling_contracts.py` and `scripts/check_ts_imports.py` must pass.
- Root `pyproject.toml` `[tool.pyright] include` gains `modules/records/sm_records/contracts` (if it is not already listed) and `modules/records/sm_records/integrations/events`. In those files, SQLModel columns go through `sqlmodel.col()`, and a suppression is `# pyright: ignore[rule]` with its reason.
- 300-line cap. Keep every `.py`/`.ts`/`.tsx` under 280 lines. The File Structure gives each file a budget.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`). The bounds of Rulings 8, 9, 12, 16 and 18 live there too.
- Only real Inertia pages go under `*/pages/`. This PR adds none.
- `en.json` and `de.json` keep identical key trees in both modules (`scripts/check_locales.py`).
- Tests that need the DOM declare `// @vitest-environment happy-dom` and use PR 1's `test-dom.tsx`. Do not add `@testing-library`.
- Postgres checks use dev-services' Postgres and the scratch databases `smpy_events_test` and `smpy_records_test`. Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **A plugin source leaking to the public.** A `public = False` source on a public calendar must never be called for an anonymous read: not by the public API, the grid, pages, `calendar.ics` or `c/{cal}.ics`. A public source on an internal or private calendar must never be called for anonymous either. The records source with `viewer=None` must return nothing from a non-public type and no drafts. Pinned by Task 7 (`test_leaks.py::test_private_source_never_public[api|calendar_ics|cal_ics|index_list|sitemap]`, `test_public_source_on_internal_calendar_absent`) and Task 16 (`test_anonymous_needs_public_type`, `test_drafts_never_returned`).
2. **A failing or slow source taking the request down, or aborting its transaction.** A source that raises, sleeps for 10 s, issues a bad SQL statement on Postgres, writes a row, or commits must leave the read at 200, with the built-in events intact and the right status. After a bad statement on Postgres, the built-in events must still be read in the same transaction. Pinned by Task 5 (`test_raises_is_failed`, `test_timeout_cancels`, `test_bad_sql_keeps_transaction[pg]`, `test_write_is_rolled_back`, `test_commit_detected`) and Task 6 (`test_api_200_with_failing_source`).
3. **Registry freeze and web/worker skew.** Registering after the freeze raises. A worker reading the registry first loads exactly what the web process loads. A worker without a plugin publishes a scheduled event of that plugin's type with its `extra` unchanged. Pinned by Task 2 (`test_frozen_after_load`, `test_worker_first_read_loads`) and Task 10 (`test_publish_due_keeps_unknown_extra`).
4. **The `extra` of an uninstalled type lost on save.** Every write path (PATCH without `extra`, an override, each workflow action, trash and restore, `publish_due`, the revision snapshot) must keep the stored bytes, and a PATCH with `extra` must be refused. Pinned by Task 9 (`test_uninstalled_type_bytes_survive_every_path`).
5. **The frontend glob in a published package.** The glob must match a workspace sibling and a wheel-installed sibling, a throwing plugin file must not stop the others, and no plugin file may statically import console code. Pinned by Task 12 (`load.test.ts`: `glob pattern resolves in workspace and site-packages layouts`, `a throwing plugin does not stop the others`) and `plugin-files.test.ts`.
6. **The records↔events dependency direction.** Events must contain no `sm_records`. Importing `sm_records.events_extensions` must not import `sm_events`. Records reaches events only through contracts. Pinned by Task 3 (`test_no_sibling_imports`), Task 17 (`test_events_extensions_imports_lazily`) and `check_sibling_contracts.py`.

---

## File Structure

Events (`modules/events/sm_events/`):

| File | Responsibility | ≤ |
|---|---|---|
| `calendar/extension_types.py` | `SourceOccurrence`, `SourceViewer`, `SourceCalendar`, `SourceContext`, `SettingsContext`, `Source` (Protocol), `EventType`, `NoExtra`, `SourceSettingsError`, `SourceStatus` | 220 |
| `calendar/registry.py` | the store, `add_*`/`register_builtin_*`, freeze, reset, getters with `ensure_loaded` | 220 |
| `calendar/extensions.py` | `load_extensions`, `Registrar`, discovery | 160 |
| `calendar/source_entries.py` | tolerant reader, `SourceEntry`, settings validation and `check_settings` | 200 |
| `calendar/plugin_validate.py` | `SourceOccurrence` → `Occurrence`, URL and title rules | 200 |
| `calendar/plugin_runner.py` | savepoint, timeout, phase budget, statuses | 240 |
| `calendar/plugin_scope.py` | which `(calendar, entry)` pairs a read calls | 150 |
| `calendar/sources.py` | PR 2's built-in source; internal `SourceContext` renamed `ReadContext`, `SOURCES` removed | (PR 2) |
| `contracts/extensions.py` | re-exports for plugins | 60 |
| `contracts/events.py` | the nine bus events | 200 |
| `content/types.py` | `validate_extra`, `public_extra`, `type_info` | 150 |
| `content/bus.py` | adds the durable publish | (PR 2) |
| `web/endpoints/extensions_api.py` | `GET /sources`, `GET /types`, `PUT /calendars/{id}/sources` | 180 |
| `web/schemas/extensions.py` | `SourceOut`, `TypeOut`, `CalendarSourceIn/Out`, `SourcesIn` | 120 |
| `web/services/source_viewer.py` | `source_viewer_from(request)` | 60 |
| `feeds/plugin_items.py` | plugin items → VEVENTs | 150 |
| `ui/extensions/types.ts` | the registration and prop types | 140 |
| `ui/extensions/registry.ts` | maps, `register*`, getters, `clearExtensions` | 140 |
| `ui/extensions/load.ts` | the lazy glob, `loadEventExtensions`, `useEventExtensions` | 90 |
| `ui/extensions/PluginBoundary.tsx` | error boundary plus Suspense around a lazy component | 80 |
| `ui/extensions/slots.tsx` | `buildSlots(surface)` | 160 |
| `ui/extensions/translateKey.ts` | runtime label lookup with fallback | 40 |
| `ui/components/editor/TypeSection.tsx` | type picker, section mount, not-installed notice | 180 |
| `ui/components/calendars/SourcesDialog.tsx` | the Sources dialog | 240 |
| `ui/components/calendars/JsonSettings.tsx` | fallback settings editor | 100 |
| `ui/public/PluginDetail.tsx` | public detail mount | 80 |
| `docs/writing-a-plugin.md` | the guide | — |

Records (`modules/records/sm_records/`):

| File | Responsibility | ≤ |
|---|---|---|
| `contracts/dated.py` | `dated_records`, `dated_types`, `DatedCaller`, `DatedHit`, `DatedPage`, `DatedTypeInfo`, `DatedQueryError`, `MAX_DATED_BATCH` | 240 |
| `events_extensions.py` | `register(registry)`, lazy | 30 |
| `integrations/__init__.py`, `integrations/events/__init__.py` | docstrings | 15 |
| `integrations/events/settings.py` | `RecordDatesSettings`, `RecordDateMapping`, `check_settings` | 140 |
| `integrations/events/source.py` | `RecordDatesSource` | 200 |
| `events-extensions.ts` | `registerSource({id: 'records:dates', …})` | 40 |
| `ui/events/RecordDatesSettings.tsx`, `ui/events/RecordDateDetail.tsx` | settings section and detail | 240 / 80 |

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events suite (and, from batch D, the records suite) green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: registry, loading, isolation, per-calendar sources** | 1–7 | plugin types and contract; the registry with freeze and the loader; built-ins through the API; source entries and their API; the runner with budget and validation; the read's scope and status report; public, feeds and private feed |
| **B: event types and `extra`, bus events** | 8–11 | the type registry surface and API; `extra` on create and update, immutability, the uninstalled-type guarantee; public extra; the final bus events and durable delivery |
| **C: frontend extension API and slots** | 12–15 | the TS registry, the lazy glob and boundary, exports; calendar slots, status and source filter; editor sections and the type picker; public detail and the Sources dialog |
| **D: the records source, e2e, plugin guide, docs** | 16–20 | `contracts.dated`; `records:dates` and its extra; the records frontend; the host e2e; the guide, README, CHANGELOG, layout, CLAUDE.md, spec amendments, verification |

---

### Task 1: Plugin-facing types, constants, errors and `contracts.extensions`

**Files:**
- Create: `sm_events/calendar/extension_types.py`, `sm_events/contracts/extensions.py`
- Modify: `sm_events/core/constants.py`, `sm_events/core/errors.py`
- Test: `tests/calendar/test_extension_types.py`, `tests/core/test_errors.py`

**Interfaces:**
- Produces (in `extension_types.py`, re-exported verbatim by `contracts/extensions.py` with that `__all__`):

```python
class SourceOccurrence(BaseModel):   # frozen, extra="forbid"; fields of Ruling 5
@dataclass(frozen=True)
class SourceViewer: user_id: str; roles: tuple[str, ...]; permissions: frozenset[str]; role_map: Mapping[str, Any] | None
@dataclass(frozen=True)
class SourceCalendar: id: uuid.UUID; slug: str; name: str; visibility: str; default_timezone: str; color: str
@dataclass(frozen=True)
class SourceContext: tenant_id: str; viewer: SourceViewer | None; calendar: SourceCalendar; settings: BaseModel | None
                     locale: str; default_locale: str; limit: int; db: AsyncSession
@dataclass(frozen=True)
class SettingsContext: tenant_id: str; viewer: SourceViewer; calendar: SourceCalendar; db: AsyncSession
class Source(Protocol):
    id: str; label_key: str; public: bool; color: str | None; icon: str | None; settings_model: type[BaseModel] | None
    async def occurrences(self, ctx: SourceContext, start: datetime, end: datetime) -> Sequence[SourceOccurrence]: ...
    # optional: async def check_settings(self, sctx: SettingsContext, settings: BaseModel) -> None
@dataclass(frozen=True)
class EventType: id: str; label_key: str; extra_model: type[BaseModel]; public_fields: frozenset[str] = frozenset(); icon: str | None = None
class NoExtra(BaseModel): model_config = ConfigDict(extra="forbid")
class SourceSettingsError(Exception): def __init__(self, loc: tuple[str | int, ...], message: str)
class SourceStatus(BaseModel): id: str; calendar_id: uuid.UUID; status: Literal["ok","truncated","failed","timeout","skipped","not_installed"]; code: str | None = None
```

- Constants: `SOURCE_TIMEOUT_SECONDS = 2.0`, `SOURCE_PHASE_SECONDS = 5.0`, `SOURCE_MIN_SLICE_SECONDS = 0.25`, `SOURCE_CALLS_MAX = 16`, `SOURCE_CALL_MAX_ITEMS = 500`, `SOURCE_WINDOW_MAX_DAYS = 400`, `CALENDAR_SOURCES_MAX = 8`, `SOURCE_KEY_MAX = 200`, `SOURCE_TITLE_MAX = 300`, `SOURCE_URL_MAX = 2000`, `EXTRA_MAX_BYTES = 16_384`, `EXTENSIONS_MODULE = "events_extensions"`, `ENTRY_POINT_GROUP = "simple_module"`, `PLUGIN_ID_PATTERN`, `BUILTIN_TYPE = DEFAULT_EVENT_TYPE`. Also a `*_CODE`/`*_DETAIL` pair for each of: 422 `unknown_source`, `builtin_source`, `duplicate_source`, `too_many_sources`, `extra_too_large`, `type_not_installed`; 503 `source_unavailable`.
- `errors.py`: `UnknownSource`, `BuiltinSource`, `DuplicateSource`, `TooManySources`, `ExtraTooLarge`, `TypeNotInstalled` (each a subclass of `Invalid`) and `SourceUnavailable` (503).

- [ ] **Step 1: Write the failing tests.**
  - `test_source_occurrence_forbids_extra_fields`: `source=` and `calendar_id=` raise `ValidationError`.
  - `test_source_occurrence_timed_or_all_day`: the schema accepts both shapes (the *checks* belong to Task 5).
  - `test_contract_surface`: `sm_events.contracts.extensions.__all__` equals the sorted names above plus `"Registrar"` (from Task 2) and `"RegistryFrozenError"`, and every name is the same object as in `calendar`.
  - `test_errors.py::test_extension_codes`: parametrized over each new class, checking status, code and the `{"detail","code"}` body.
- [ ] **Step 2: Run** (headroom first) `cd modules/events && uv run pytest -q tests/calendar/test_extension_types.py tests/core/test_errors.py`. Expected: ImportError.
- [ ] **Step 3: Implement.** `contracts/extensions.py` imports `Registrar` and `RegistryFrozenError` from Task 2's modules. Write those names in Task 2 and keep this test `xfail(strict=True)` until then: Task 2 removes the mark.
- [ ] **Step 4: Run** the tests (they pass, apart from the strict xfail), then `uv run python scripts/check_hardcoded_strings.py` (passes).
- [ ] **Step 5: Commit** `feat(events): plugin-facing source and type types`.

### Task 2: The registry, the loader and the freeze

**Files:**
- Create: `sm_events/calendar/registry.py`, `sm_events/calendar/extensions.py`
- Test: `tests/calendar/test_registry.py`, `tests/calendar/test_extensions_loader.py`, `tests/fixtures/acme_events/__init__.py`, `tests/fixtures/acme_events/events_extensions.py` (a fake plugin package: source `acme:talks`, type `acme:talk`)

**Interfaces:**

```python
# registry.py
class RegistryFrozenError(RuntimeError): ...
class DuplicateExtension(ValueError): ...
class InvalidExtensionId(ValueError): ...
class InvalidExtension(TypeError): ...
def add_source(source: Source, *, namespace: str) -> None      # Rulings 2, 3
def add_type(etype: EventType, *, namespace: str) -> None
def register_builtin_source(source: Any) -> None               # id must be SOURCE_EVENTS
def register_builtin_type(etype: EventType) -> None            # id must be DEFAULT_EVENT_TYPE
def get_source(source_id: str) -> Source | None                # all getters call ensure_loaded()
def plugin_sources() -> dict[str, Source]                      # excludes the built-in
def builtin_source() -> Any
def get_type(type_id: str) -> EventType | None
def all_types() -> dict[str, EventType]
def is_frozen() -> bool
def freeze() -> None
def reset_registry() -> None                                   # tests and a failed load only
def ensure_loaded() -> None                                    # calls extensions.load_extensions() lazily (import inside)
# extensions.py
class Registrar:
    def __init__(self, namespace: str) -> None
    def add_source(self, source: Source) -> None
    def add_type(self, etype: EventType) -> None
def load_extensions() -> None                                  # Ruling 1
```

- [ ] **Step 1: Write the failing tests** (an autouse fixture calls `reset_registry()` before and after each test):
  - `test_registry.py`:
    - `test_add_and_get`;
    - `test_duplicate_refused`;
    - `test_namespace_must_match` (`records` registering `acme:x` raises `InvalidExtensionId`);
    - `test_id_pattern` (parametrized over `"x"`, `"acme:"`, `"Acme:x"`, `"acme:x y"` and 49 characters after the colon);
    - `test_builtin_ids_reserved` (`add_source` with id `events` raises);
    - `test_protocol_checked`: a missing `occurrences`, a sync `occurrences`, `public="yes"`, a bad colour, `settings_model=dict`, and an `extra_model` without `extra="forbid"`, each raise `InvalidExtension`;
    - `test_public_fields_must_be_model_fields`;
    - `test_frozen_after_load`: after `load_extensions()`, `add_source` raises `RegistryFrozenError`.
  - `test_extensions_loader.py` (entry points monkeypatched as in `modules/images/tests/pipeline/test_extensions.py`, with `tests/fixtures` on `sys.path`):
    - `test_finds_fixture_plugin`;
    - `test_idempotent`;
    - `test_builtins_registered_first`;
    - `test_registrar_exposes_only_registration` (no `freeze` or `reset` attribute);
    - `test_failed_load_resets_so_retry_is_clean`;
    - `test_plugin_package_import_error_is_not_swallowed`;
    - `test_absent_extensions_module_skipped`;
    - `test_absent_parent_package_is_skipped_with_a_warning`;
    - `test_worker_first_read_loads`: in a fresh state, `get_type("acme:talk")` with no prior `load_extensions()` returns the type and the registry is frozen.
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_registry.py tests/calendar/test_extensions_loader.py tests/calendar/test_extension_types.py`. Expected: fail.
- [ ] **Step 3: Implement.** The store is a module-level dict guarded by a `threading.RLock`, as images' is. `ensure_loaded` returns at once when the registry is frozen. Copy images' `_find`; never import it. Remove Task 1's `xfail`.
- [ ] **Step 4: Run** the tests: they pass.
- [ ] **Step 5: Commit** `feat(events): the extension registry and its loader`.

### Task 3: Built-ins through the registry, startup and worker loading, no sibling imports

**Files:**
- Modify: `sm_events/calendar/sources.py`: rename the internal `SourceContext` to `ReadContext` (and every PR 2 use of it); delete `SOURCES`; add `def register_builtins() -> None` (`register_builtin_source(EVENTS_SOURCE)`, `register_builtin_type(EventType(id=DEFAULT_EVENT_TYPE, label_key="events.types.event", extra_model=NoExtra))`). Also give `EventsSource` the plugin attributes `label_key`, `public = True`, `color = None`, `icon = "calendar"` and `settings_model = None`.
- Modify: `sm_events/calendar/extensions.py` (`_BUILTIN_LOADERS = [register_builtins]`), `sm_events/calendar/occurrences.py` (use `registry.builtin_source()`), `sm_events/module.py` (`on_startup`: `load_extensions()`), `sm_events/core/worker.py` (the runtime's first use calls `registry.ensure_loaded()`), `locales/en.json`/`de.json` (`types.event`)
- Test: `tests/calendar/test_builtins.py`, `tests/core/test_module_boot.py`, `tests/core/test_layout.py` (new or extended)

- [ ] **Step 1: Write the failing tests:**
  - `test_builtins.py`:
    - `test_builtins_registered`: `builtin_source() is EVENTS_SOURCE` and `get_type("event").extra_model is NoExtra`;
    - `test_builtin_not_in_plugin_sources`;
    - `test_read_unchanged`: PR 2's `test_one_off_and_series_merge_sorted` assertion run again through the registry, giving the same items.
  - `test_module_boot.py::test_startup_freezes_registry`: `is_frozen()` is true after `events_app` starts.
  - `test_layout.py::test_no_sibling_imports`: no `.py` under `sm_events/` has an import statement (`^\s*(from|import)\s+(sm_records|sm_images|sm_newsletter|sm_billing|sm_ai|news|pagebuilder)\b`) or an `import_module`/`find_spec` string naming one of those packages, except PR 4's `integrations/pagebuilder.py`. No `.ts`/`.tsx` imports `@simple-module-py/(records|images|news|newsletter|billing|ai|pagebuilder)`.
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_builtins.py tests/core/test_module_boot.py tests/core/test_layout.py tests/calendar/test_occurrences.py`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same, plus the whole `tests/calendar` directory: all pass.
- [ ] **Step 5: Commit** `refactor(events): the built-in source and type register through the registry`.

### Task 4: Per-calendar source entries, settings validation and their API

**Files:**
- Create: `sm_events/calendar/source_entries.py`, `sm_events/web/schemas/extensions.py`, `sm_events/web/endpoints/extensions_api.py`, `sm_events/web/services/source_viewer.py`
- Modify: `web/endpoints/__init__.py` (include the router), `web/schemas/calendars.py` (`CalendarOut.sources: list[CalendarSourceOut]`), the calendar-out builder in `web/endpoints/calendars_api.py`
- Test: `tests/calendar/test_source_entries.py`, `tests/web/test_extensions_api.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class SourceEntry: id: str; settings: dict[str, Any]
def read(raw: Any) -> list[SourceEntry]                         # Ruling 12's tolerant reader
def settings_of(source: Source, entry: SourceEntry) -> BaseModel | None   # raises pydantic ValidationError
async def write_entries(db, who: ResourcePrincipal, viewer: SourceViewer, calendar: Calendar,
                        incoming: Sequence[CalendarSourceIn]) -> list[SourceEntry]
    # BuiltinSource, DuplicateSource, TooManySources, UnknownSource; RequestValidationError for settings;
    # check_settings in a savepoint with SOURCE_TIMEOUT_SECONDS -> SourceSettingsError -> 422, other -> SourceUnavailable
def source_viewer_from(request: Request) -> SourceViewer | None   # None for an anonymous request
```

| Method and path | Needs | Success | Errors |
|---|---|---|---|
| `GET /api/events/sources` | `events.view` | 200 `[SourceOut{id, label_key, color, icon, public, has_settings, settings_schema}]` sorted by id | none |
| `GET /api/events/types` | `events.view` | 200 `[TypeOut]` (Ruling 17, filled in Task 8) | none |
| `PUT /api/events/calendars/{id}/sources` | `events.view` plus the visibility right | 200 `CalendarOut` | 403, 404, 422, 503 |

- [ ] **Step 1: Write the failing tests:**
  - `test_source_entries.py`:
    - `test_reads_legacy_strings`;
    - `test_drops_malformed_and_logs`;
    - `test_settings_validated_and_dumped` (a `datetime` setting is stored as an ISO string);
    - `test_source_without_model_needs_empty`;
    - `test_unknown_kept_only_if_unchanged`;
    - `test_builtin_refused`;
    - `test_duplicate_and_max`;
    - `test_check_settings_error_loc` (loc `["body","sources",0,"settings","mappings",0,"field"]`);
    - `test_check_settings_timeout_is_503`;
    - `test_check_settings_bad_sql_keeps_transaction`, which on Postgres runs a `SELECT * FROM nope` and then an update to the calendar in the same request that succeeds.
  - `test_extensions_api.py`:
    - `test_list_sources_excludes_builtin`;
    - `test_put_needs_visibility_right`: `SE` gets 403, `V` on `P` gets 404, and `O` gets 200;
    - `test_put_round_trip_and_calendar_out` (with `installed` and `label_key`);
    - `test_not_installed_entry_shown`;
    - `test_put_needs_csrf`;
    - `test_tenant_isolation` (`unbound_tenant`, multi mode).
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_source_entries.py tests/web/test_extensions_api.py`. Expected: fail.
- [ ] **Step 3: Implement.** The `RequestValidationError` errors are built as FastAPI's, so PR 1's 422 handler renders them unchanged.
- [ ] **Step 4: Run** the tests on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): enable sources per calendar with validated settings`.

### Task 5: The plugin runner: savepoint, timeout, budget, validation

**Files:**
- Create: `sm_events/calendar/plugin_validate.py`, `sm_events/calendar/plugin_runner.py`
- Test: `tests/calendar/test_plugin_validate.py`, `tests/calendar/test_plugin_runner.py`, `tests/support/sources.py` (spy and fake sources: `ok`, `raises`, `sleeps(s)`, `bad_sql`, `writes`, `commits`, `floods(n)`, `invalid(item)`, `swallows_cancel`)

**Interfaces:**

```python
def to_occurrences(items: Sequence[Any], *, source_id: str, calendar: SourceCalendar, start: datetime,
                   end: datetime, default_lang: str) -> list[Occurrence]      # raises InvalidPluginItem(code)
@dataclass(frozen=True)
class Call: calendar: SourceCalendar; entry: SourceEntry; source: Source | None   # None = not installed
@dataclass(frozen=True)
class RunResult: items: list[Occurrence]; statuses: list[SourceStatus]; truncated: bool
async def run_sources(db, calls: Sequence[Call], *, tenant_id: str, viewer: SourceViewer | None,
                      start: datetime, end: datetime, locale: str, default_locale: str,
                      clock: Callable[[], float] = time.monotonic) -> RunResult
    # Rulings 7-9; items sorted by sort_key, deduplicated on (source, calendar_id, key)
```

- [ ] **Step 1: Write the failing tests:**
  - `test_plugin_validate.py`:
    - `test_timed_normalised_to_utc`;
    - `test_all_day_dates_to_local_midnight` (Vienna 2026-03-29 gives `starts_at` 2026-03-28T23:00Z);
    - `test_naive_refused`;
    - `test_start_not_before_end`;
    - `test_span_cap`;
    - `test_unknown_timezone`;
    - `test_url_rules`: parametrized over `/admin/x` (kept), `https://a/x` (kept), `//evil`, `/\evil`, `javascript:alert(1)`, `data:x`, `ftp://a`, a 2001-character URL and `/a b` (each rejected);
    - `test_title_kept_as_text`: `<script>x</script>` is kept verbatim, control characters are stripped, and a title that is empty after stripping is invalid;
    - `test_outside_window_dropped`;
    - `test_duplicate_key_invalid`;
    - `test_fields_filled`: `source`, `calendar_id`, `editable False`, `type "event"`, `event_id None`.
  - `test_plugin_runner.py`:
    - `test_ok`;
    - `test_raises_is_failed`;
    - `test_invalid_item_drops_whole_answer`;
    - `test_timeout_cancels`: `sleeps(10)` returns within 2.5 s with status `timeout`;
    - `test_phase_budget_skips_rest`: with a fake clock and three slow sources, the third is `skipped`/`budget`;
    - `test_calls_capped` (17 calls, so the last is `skipped`/`too_many_calls`);
    - `test_flood_truncated`: 600 items give the first 500 by time, `truncated` and `status truncated`;
    - `test_write_is_rolled_back`: `writes` inserts a `Category` and gets `failed`/`wrote`, and the row does not exist after a commit of the outer session;
    - `test_commit_detected`: `commits` gets `failed`/`wrote`, with an error logged;
    - `test_bad_sql_keeps_transaction[pg]`: on Postgres, `bad_sql` gets `failed`/`raised`, and a following `select(Event)` in the same session succeeds;
    - `test_not_installed_status`;
    - `test_invalid_settings_not_called` (the spy records no call);
    - `test_context_carries_calendar_settings_viewer_limit`;
    - `test_dedupe_across_calendars_keeps_both` (the same key on two calendars is two items).
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_plugin_validate.py tests/calendar/test_plugin_runner.py`. Expected: fail.
- [ ] **Step 3: Implement.** `SourceContext.settings` comes from `settings_of`, whose `ValidationError` gives `failed`/`invalid_settings`. A call runs as `await db.flush()`, then `outer = db.get_transaction()`, then `async with asyncio.timeout(t): async with db.begin_nested() as sp: items = await source.occurrences(ctx, start, end); ... ; await sp.rollback()`. Always roll back the savepoint, because a read needs no release. Then compare `db.get_transaction() is outer` and the identity sets.
- [ ] **Step 4: Run** the tests on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): isolated, bounded plugin source calls`.

### Task 6: Plugin sources in the occurrences read, the API and the contract

**Files:**
- Create: `sm_events/calendar/plugin_scope.py`
- Modify: `calendar/occurrence.py` (`OccurrencePage.sources: list[SourceStatus] = []`; `OccurrenceFilters.sources: frozenset[str] | None = None`), `calendar/occurrences.py` (new keyword `source_viewer: SourceViewer | None = None`; the plugin phase runs before the merge; Rulings 10, 11 and 13), `web/endpoints/occurrences_api.py` (`source=` repeatable; `source_viewer_from(request)`), `contracts/occurrences.py` (passes `source_viewer` through; `SourceStatus` re-exported), `web/endpoints/views.py` (console Calendar props `sources: [{id, label_key, color}]` for sources enabled on the shown calendars)
- Test: `tests/calendar/test_plugin_scope.py`, `tests/calendar/test_occurrences_plugins.py`, `tests/web/test_occurrences_api.py`, `tests/contracts/test_occurrences_contract.py`

**Interfaces:**

```python
async def plugin_calls(db, viewer: ResourcePrincipal, source_viewer: SourceViewer | None,
                       filters: OccurrenceFilters) -> tuple[list[Call], list[SourceStatus]]
    # calendars: visible_calendars(viewer) ∩ filters.calendar_ids; entries via source_entries.read;
    # anonymous (viewer.user_id is None): public sources only; signed in without source_viewer: skipped/no_viewer;
    # filters.sources narrows; order by (calendar.name, entry.id)
```

- [ ] **Step 1: Write the failing tests:**
  - `test_plugin_scope.py`:
    - `test_only_visible_calendars`: a source enabled on `P` is not called for `V`;
    - `test_anonymous_public_sources_on_public_calendars_only`;
    - `test_signed_in_without_viewer_skipped`;
    - `test_sources_filter`;
    - `test_invisible_calendar_in_filter_dropped_silently`.
  - `test_occurrences_plugins.py`:
    - `test_merged_in_order`;
    - `test_cap_counts_plugin_items`: 1,900 built-in items plus 200 plugin items give 2,000 and `truncated`;
    - `test_statuses_reported`;
    - `test_builtin_never_in_statuses`;
    - `test_types_filter_ignores_plugins`;
    - `test_sources_events_only_excludes_plugins`;
    - `test_failing_source_keeps_builtin`.
  - `test_occurrences_api.py`:
    - `test_api_200_with_failing_source` (body has `sources[0].status == "failed"` and the built-in items);
    - `test_source_param`.
  - `test_occurrences_contract.py::test_contract_without_viewer_skips_plugins`.
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_plugin_scope.py tests/calendar/test_occurrences_plugins.py tests/web/test_occurrences_api.py tests/contracts`. Expected: fail.
- [ ] **Step 3: Implement.** The source registry is read through `registry.plugin_sources()`.
- [ ] **Step 4: Run** the tests on SQLite and Postgres, plus PR 2's `tests/calendar/test_occurrences*.py`: all pass.
- [ ] **Step 5: Commit** `feat(events): plugin sources in the occurrences read with a status report`.

### Task 7: Public surface, public feeds and the private feed

**Files:**
- Create: `sm_events/feeds/plugin_items.py`
- Modify: `core/access/offline.py` (add `async def feed_viewer(app, db, *, user_id, tenant_id) -> SourceViewer | None`, sharing `feed_principal`'s directory lookup and returning its roles), `web/endpoints/public/_api.py` (public sources; `sources` omitted from the body and logged at INFO when not `ok`), `web/endpoints/public/_listing.py` (`filters.sources={SOURCE_EVENTS}`), `web/endpoints/public/_feeds.py` and `_private_feed.py` (plugin items over `[now − FEED_DAYS_BACK, now + FEED_DAYS_AHEAD)` through `run_sources`), `feeds/ics_calendar.py` (accepts plugin VEVENTs after the event components, under `FEED_MAX_COMPONENTS`)
- Test: `tests/feeds/test_plugin_items.py`, `tests/web/public/test_leaks.py` (new rows), `tests/web/public/test_private_feed.py` (new cases)

**Interfaces:**

```python
def plugin_vevents(items: Sequence[Occurrence], *, absolute: Callable[[str], str]) -> list[icalendar.Event]   # Ruling 16
```

- [ ] **Step 1: Write the failing tests:**
  - `test_plugin_items.py`:
    - `test_uid_and_dates` (timed in UTC `Z`; all-day `VALUE=DATE`, exclusive end);
    - `test_url_absolute_for_path`;
    - `test_dtstamp_deterministic` (`updated_at`, else start; two builds are byte-identical);
    - `test_title_escaped` (a `;`/`,`/newline title round-trips through `icalendar`).
  - `test_leaks.py`:
    - `test_private_source_never_public[api|calendar_ics|cal_ics|index_list|sitemap]`: a spy `public=False` source enabled on public `U` is never called, and its titles are absent;
    - `test_public_source_on_internal_calendar_absent`;
    - `test_public_source_called_with_no_viewer` (the spy saw `viewer is None`);
    - `test_public_api_has_no_sources_field`;
    - `test_plugin_items_not_in_listing_or_sitemap`.
  - `test_private_feed.py`:
    - `test_private_feed_calls_sources_with_owner_viewer` (roles from the directory);
    - `test_private_feed_viewer_missing_skips_plugins_still_200`;
    - `test_component_cap_drops_plugin_items_first`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/test_plugin_items.py tests/web/public/test_leaks.py tests/web/public/test_private_feed.py`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests on SQLite and Postgres, plus the rest of `tests/web/public`: all pass.
- [ ] **Step 5: Commit** `feat(events): plugin sources on the public grid and in feeds`.

**End of batch A.** Run (headroom first) `cd modules/events && uv run pytest -q -n 8`, then from the root `uv run python scripts/check_file_size.py` (no WARNING under `modules/events`), `check_hardcoded_strings.py`, `check_sibling_contracts.py`, `uv run basedpyright` and `uv run ruff check modules/events`.

---

### Task 8: Types on the API and in the console props

**Files:**
- Create: `sm_events/content/types.py`
- Modify: `web/endpoints/extensions_api.py` (`GET /types`), `web/endpoints/views.py` (editor and calendar props gain `types: [{id, label_key, icon}]`; PR 3's console passes them as the `types` filter options)
- Test: `tests/content/test_types.py`, `tests/web/test_extensions_api.py`

**Interfaces:**

```python
def type_info(etype: EventType) -> TypeOut                     # json_schema, defaults (model_construct().model_dump(mode="json") of defaulted fields)
def validate_extra(type_id: str, extra: Mapping[str, Any]) -> dict[str, Any]
    # UnknownType; ExtraTooLarge (json.dumps(separators=(",",":")) > EXTRA_MAX_BYTES, checked before and after);
    # pydantic errors -> RequestValidationError([{"loc": ("body","extra",*e["loc"]), "msg": e["msg"], "type": e["type"]}])
def public_extra(type_id: str, extra: Mapping[str, Any]) -> dict[str, Any]   # Ruling 22
```

- [ ] **Step 1: Write the failing tests:**
  - `test_types.py`:
    - `test_builtin_accepts_only_empty`;
    - `test_plugin_extra_validated_and_dumped` (with the fixture's `acme:talk {speaker: str, room: str | None = None, level: Literal[...]}`);
    - `test_error_locs_under_extra` (`["body","extra","speaker"]`);
    - `test_size_cap`;
    - `test_public_extra_filters_and_unknown_type_empty`.
  - `test_extensions_api.py`:
    - `test_list_types_builtin_first`;
    - `test_type_schema_and_defaults`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_types.py tests/web/test_extensions_api.py`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests: they pass.
- [ ] **Step 5: Commit** `feat(events): event types API and extra validation`.

### Task 9: `extra` on create and update, an immutable type, uninstalled types kept

**Files:**
- Modify: `web/schemas/events_in.py` (`EventCreate.extra: dict[str, Any] = {}`, `EventPatch.extra: dict[str, Any] | None`), `content/events_write.py` (`create_event` checks `get_type` and calls `validate_extra`; `update_event`: `extra` present on an installed type → `validate_extra`, on an uninstalled one → `TypeNotInstalled`, absent → untouched), `web/services/events_out.py` (`type_installed`, `type_label_key`)
- Test: `tests/content/test_events_extra.py`, `tests/web/test_events_api.py` (new cases)

- [ ] **Step 1: Write the failing tests:**
  - `test_events_extra.py`:
    - `test_create_with_plugin_type`;
    - `test_create_unknown_type_422`;
    - `test_patch_replaces_extra_validated`;
    - `test_patch_type_immutable`;
    - `test_uninstalled_type_bytes_survive_every_path`: seed a row directly with `type="gone:thing"` and `extra` set to raw JSON containing key order `{"b":1,"a":[1,2]}`. Then run a PATCH of the venue, an override set and clear, `submit`, `approve`, `unpublish`, `trash`, `restore` and a revision snapshot, and after each assert `json.dumps(row.extra)` is unchanged and `type == "gone:thing"`. On Postgres, also compare `extra::text` read through Core.
    - `test_uninstalled_patch_with_extra_refused` (422 `type_not_installed`, revision unchanged).
  - `test_events_api.py`:
    - `test_extra_422_shape` (FastAPI's list shape with `loc` starting `["body","extra"]`);
    - `test_event_out_type_flags`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_events_extra.py tests/web/test_events_api.py`. Expected: fail.
- [ ] **Step 3: Implement.** On Postgres the column is JSON: confirm whether PR 1's `json_col` is `JSON` or `JSONB`. JSONB normalises key order, so if it is JSONB, the byte test compares `json.loads` equality and the docs say "unchanged value" instead. Report which it is in the commit body.
- [ ] **Step 4: Run** the tests on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): typed extra on events; uninstalled types are preserved`.

### Task 10: Public extra and worker skew

**Files:**
- Modify: `web/endpoints/public/_event_props.py` (`type`, `public_extra`), `web/schemas/public.py` (the page props)
- Test: `tests/web/public/test_event_page.py` (new cases), `tests/content/test_publish_due.py` (new case)

- [ ] **Step 1: Write the failing tests:**
  - `test_public_props_only_public_fields`: `acme:talk` with `public_fields={"speaker"}` and `extra={"speaker":"A","room":"secret"}`; the props and the Inertia JSON contain `"speaker"` and not `"secret"`.
  - `test_ics_and_jsonld_never_carry_extra`: `secret` is absent from `{slug}.ics` and from the JSON-LD.
  - `test_uninstalled_type_public_extra_empty`.
  - `test_publish_due_keeps_unknown_extra`: with the registry reset to built-ins only (no fixture plugin, standing in for a worker image without the plugin), a scheduled `acme:talk` event is published by `publish_due_async`, and its `extra` is unchanged.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_event_page.py tests/content/test_publish_due.py`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests: they pass.
- [ ] **Step 5: Commit** `feat(events): public pages carry only a type's public extra`.

### Task 11: The final bus events and durable delivery

**Files:**
- Modify: `contracts/events.py` (five new dataclasses, Ruling 23; docstring with the delivery rules of Ruling 24), `content/bus.py` (`emit` also queues the durable publish when `durable_transport` and handlers exist), `content/workflow.py`, `content/events_write.py`, `content/overrides.py`, `content/events_trash.py` (the emission points), `content/publish_due.py` (attaches `worker_bus()`)
- Test: `tests/content/test_bus.py`, `tests/content/test_bus_emission.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_bus.py`:
    - `test_all_events_serialisable`: `check_serializable` for each of the nine;
    - `test_dataclass_shapes` (field order);
    - `test_durable_published_in_transaction`: a fake `durable_transport` with a handler records `enqueue` before commit and nothing after a rollback;
    - `test_no_durable_without_handlers`.
  - `test_bus_emission.py`, parametrized over the transitions of Ruling 23:
    - unpublish → `EventUnpublished(was_scheduled=False)`;
    - unschedule → `EventUnpublished(True)`;
    - clearing `cancelled` → `EventReinstated(None)`;
    - clearing a cancelled override → `EventReinstated(original_start)`;
    - a skipped override → `OccurrenceSkipped`;
    - restoring a published event → `EventRestored`;
    - a title or venue change → `EventUpdated(("texts","venue_name"))`;
    - a draft write → nothing;
    - a published reschedule → only `EventRescheduled` (no `EventUpdated`).

    Plus `test_publish_due_publishes_durably`: with `worker_bus` monkeypatched to a bus with a fake transport and a durable handler, the beat enqueues one `EventPublished`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_bus.py tests/content/test_bus_emission.py tests/content/test_publish_due.py`. Expected: fail.
- [ ] **Step 3: Implement.** `publish_durable` runs in the request's transaction before `finalize_session`. The in-process publish stays on `on_commit`.
- [ ] **Step 4: Run** the tests, PR 2's `tests/content/test_workflow.py` and `tests/content/test_events_write.py`: all pass. Then from the root run `uv run python scripts/check_sibling_contracts.py`: it passes.
- [ ] **Step 5: Commit** `feat(events): complete bus events, published durably as well`.

**End of batch B.** Run batch A's end checks again.

---

### Task 12: The TS registry, the lazy guarded glob, the boundary and the exports

**Files:**
- Create: `ui/extensions/types.ts`, `ui/extensions/registry.ts`, `ui/extensions/load.ts`, `ui/extensions/PluginBoundary.tsx`, `ui/extensions/translateKey.ts`
- Modify: `index.ts` (Ruling 30), `ui/utils/api.ts` (`ApiError.messages`, filled from each 422 item's `msg`)
- Test: `ui/extensions/registry.test.ts`, `ui/extensions/load.test.ts`, `ui/extensions/PluginBoundary.test.tsx`, `ui/extensions/plugin-files.test.ts`

**Interfaces:**

```ts
export type LazyComponent<P> = () => Promise<{ default: ComponentType<P> }>;
export type EditorSectionProps = { extra: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void;
  errors: Record<string, string>; readOnly: boolean; locale: string; eventId: string | null };
export type SourceSettingsProps = { settings: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void;
  errors: Record<string, string>; calendar: { id: string; name: string; default_timezone: string } };
export type PublicDetailProps = { occurrence: Occurrence | null; event: { id: string; type: string; title: string } | null;
  publicExtra: Record<string, unknown>; locale: string };
export type EventTypeRegistration = { id: string; Chip?: LazyComponent<EventChipProps>; Detail?: LazyComponent<DetailProps>;
  EditorSection?: LazyComponent<EditorSectionProps>; PublicDetail?: LazyComponent<PublicDetailProps> };
export type SourceRegistration = { id: string; Chip?: …; Detail?: …; SettingsSection?: LazyComponent<SourceSettingsProps>;
  PublicDetail?: LazyComponent<PublicDetailProps> };
export type ToolbarItemRegistration = { id: string; placement: 'start' | 'end'; surfaces: ('console' | 'public')[];
  Component: LazyComponent<ToolbarSlotProps> };
export function registerEventType(r: EventTypeRegistration): void;   // throws on duplicate id
export function registerSource(r: SourceRegistration): void;
export function registerToolbarItem(r: ToolbarItemRegistration): void;
export function eventType(id: string): ResolvedType | undefined;     // components already React.lazy-wrapped, memoised
export function source(id: string): ResolvedSource | undefined;
export function toolbarItems(placement, surface): ResolvedToolbarItem[];
export function clearExtensions(): void;                             // tests
export function loadEventExtensions(loaders?: Record<string, () => Promise<unknown>>): Promise<void>;
export function useEventExtensions(): boolean;
export function PluginBoundary(props: { name: string; fallback: ReactNode; children: ReactNode }): JSX.Element;
export function translateKey(t: Translate, key: string, fallback: string): string;
```

- [ ] **Step 1: Write the failing tests:**
  - `registry.test.ts`:
    - `duplicate id throws`;
    - `lookup returns lazy-wrapped components, the same object each time`;
    - `toolbar items filtered by surface and sorted by id`.
  - `load.test.ts`:
    - `a throwing plugin does not stop the others` (loaders injected: one rejects, one registers; `console.error` names the path, and the second registration exists);
    - `runs once`;
    - `glob pattern resolves in workspace and site-packages layouts`: a pure function `pluginGlobRoot()` exported for the test, asserting `path.resolve('modules/events/sm_events/ui/extensions', '../../../..')` ends in `modules`, and the same from `.venv/lib/python3.12/site-packages/sm_events/ui/extensions` ends in `python3.12`.
  - `PluginBoundary.test.tsx`:
    - `render error falls back`;
    - `lazy rejection falls back`.
  - `plugin-files.test.ts` (node): every `modules/*/*/events-extensions.ts` in the repo has static imports only from `@simple-module-py/events` or `import type`, and every component is passed as `() => import(…)`.
  - `api.ts`: `422 messages keyed by dotted loc`.
- [ ] **Step 2: Run** (headroom first) `npx vitest run modules/events/sm_events/ui/extensions modules/events/sm_events/ui/utils`. Expected: fail.
- [ ] **Step 3: Implement.** `load.ts` contains the literal `import.meta.glob('../../../../*/*/events-extensions.ts')`, and the injected `loaders` parameter defaults to it.
- [ ] **Step 4: Run** vitest, `npx tsc --noEmit -p modules/events/tsconfig.json`, `npx biome check modules/events` and `uv run python scripts/check_ts_imports.py`: all pass.
- [ ] **Step 5: Commit** `feat(events): frontend extension registry and guarded plugin loading`.

### Task 13: Calendar slots, the source status notice and the source filter

**Files:**
- Create: `ui/extensions/slots.tsx`
- Modify: `ui/calendar/console/ConsoleCalendar.tsx` (`slots={buildSlots('console')}` after `useEventExtensions()`), `ui/public/PublicCalendarGrid.tsx` (`buildSlots('public')`), `ui/calendar/StatusBar.tsx` (the `sources` notice), `ui/calendar/Filters.tsx` plus `ui/calendar/types.ts` (optional `sources?: FilterOption[]` prop; `OccurrenceQuery.sources: string[]`; `CalendarState.sources`), `ui/utils/types-events.ts` (`OccurrencePage.sources?`), `ui/utils/api-events.ts` (`source` params), locales (`extensions.status.*`, `calendar.filters.sources`)
- Test: `ui/extensions/slots.test.tsx`, `ui/page-tests/CalendarSources.test.tsx`

- [ ] **Step 1: Write the failing tests:**
  - `slots.test.tsx`:
    - `chip dispatches on source then type then Default`;
    - `public surface uses PublicDetail or Default, never Detail`;
    - `a crashing plugin chip renders Default`;
    - `toolbar end renders console items only on console`;
    - `script-like title renders as text` (no `<script>` element in the DOM).
  - `CalendarSources.test.tsx` (FakeGrid):
    - `status notice lists non-ok sources by label`;
    - `label key missing falls back to id`;
    - `source filter sends source params`;
    - `no sources filter when none enabled`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/extensions/slots.test.tsx modules/events/sm_events/ui/page-tests/CalendarSources.test.tsx`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest over `modules/events`, then tsc and biome: all pass.
- [ ] **Step 5: Commit** `feat(events): plugin chips, details and toolbar items in the calendar`.

### Task 14: Editor sections and the type picker

**Files:**
- Create: `ui/components/editor/TypeSection.tsx`
- Modify: `ui/components/editor/EventForm.tsx` (mounts `TypeSection`), `ui/hooks/useEvent.ts` (`extra` state, dirty tracking, `extra` sent only when changed), `pages/EventEditor.tsx` (props `types`), locales (`types.*`)
- Test: `ui/page-tests/TypeSection.test.tsx`

- [ ] **Step 1: Write the failing tests:**
  - `picker shown on create only with two or more types`;
  - `type read-only after create`;
  - `section receives extra and onChange, save sends extra`;
  - `server 422 extra.speaker reaches section errors with the server message`;
  - `locked event passes readOnly`;
  - `uninstalled type shows notice and never sends extra`;
  - `no section registered sends no extra`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/TypeSection.test.tsx`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest over `modules/events`, then tsc and biome: all pass.
- [ ] **Step 5: Commit** `feat(events): plugin editor sections and the event type picker`.

### Task 15: The public detail and the Sources dialog

**Files:**
- Create: `ui/public/PluginDetail.tsx`, `ui/components/calendars/SourcesDialog.tsx`, `ui/components/calendars/JsonSettings.tsx`, `ui/utils/api-extensions.ts` (`listSources`, `listTypes`, `putCalendarSources`)
- Modify: `pages/PublicEvent.tsx` (`PluginDetail` beneath the description), `ui/components/calendars/CalendarRow.tsx` (the "Sources" action), `pages/Calendars.tsx` (dialog state), `ui/utils/types.ts` (`CalendarSource`), locales (`sources.*`)
- Test: `ui/page-tests/SourcesDialog.test.tsx`, `ui/page-tests/PublicPluginDetail.test.tsx`

- [ ] **Step 1: Write the failing tests:**
  - `SourcesDialog.test.tsx`:
    - `lists registered sources with public badge`;
    - `enable shows plugin SettingsSection or JSON fallback`;
    - `not installed entry kept on save`;
    - `422 settings error lands on the section`;
    - `action hidden without visibility right`;
    - `save sends PUT with entries`.
  - `PublicPluginDetail.test.tsx`:
    - `renders PublicDetail with publicExtra only`;
    - `no registration renders nothing`;
    - `a rejected lazy import renders nothing and the page still renders`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/SourcesDialog.test.tsx modules/events/sm_events/ui/page-tests/PublicPluginDetail.test.tsx`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest over `modules/events`, then tsc, biome, `check_rules.py` and `check_locales.py`: all pass. Then build once (`npm run build` in the host, headroom first) and confirm that the public `PublicEvent` chunk graph contains no file from `ui/components/editor/` (grep the build manifest).
- [ ] **Step 5: Commit** `feat(events): public plugin details and the calendar Sources dialog`.

**End of batch C.** Run `npx vitest run modules/events`, tsc, biome, `check_ts_imports.py`, `check_file_size.py` and the events pytest.

---

### Task 16: `sm_records.contracts.dated`

**Files:**
- Create: `modules/records/sm_records/contracts/dated.py`
- Test: `modules/records/tests/contracts/test_dated.py`

**Interfaces:**

```python
MAX_DATED_BATCH: Final = 1000
@dataclass(frozen=True)
class DatedCaller: roles: tuple[str, ...]; permissions: frozenset[str]; role_map: Mapping[str, Any] | None = None
@dataclass(frozen=True)
class DatedHit: uuid: str; type_key: str; locale: str; display_title: str; start: date | datetime; end: date | datetime | None
@dataclass(frozen=True)
class DatedPage: hits: list[DatedHit]; truncated: bool
@dataclass(frozen=True)
class DatedTypeInfo: key: str; label: str; is_public: bool; fields: list[tuple[str, str, Literal["date","datetime"]]]  # (key, label, kind), indexed only
class DatedQueryError(ValueError): reason: Literal["not_a_date", "not_indexed", "reindexing", "kind_mismatch"]
async def dated_records(session, *, tenant_id: str, type_key: str, field: str, end_field: str | None = None,
                        lo: date | datetime, hi: date | datetime, caller: DatedCaller | None,
                        locale: str | None, limit: int) -> DatedPage                 # Ruling 32
async def dated_types(session, *, tenant_id: str, caller: DatedCaller) -> list[DatedTypeInfo]
```

`dated_records` uses `list_records` (or `page_of` with a published-and-locale `narrow`) with `Filter(field, GTE, lo)`, `Filter(field, LT, hi)` and `Sort(field)`, at `page_size=limit + 1`, `with_total=False`. `QueryError` becomes `DatedQueryError`.

- [ ] **Step 1: Write the failing tests** (records' fixtures; a type `deadlines` with an indexed `date` field `due` and a `datetime` field `at`):
  - `test_range_half_open_and_sorted`;
  - `test_limit_and_truncated`;
  - `test_drafts_never_returned`;
  - `test_trash_excluded`;
  - `test_anonymous_needs_public_type`;
  - `test_view_permission_required`;
  - `test_allowed_roles_narrowing_and_type_grant`, with the wildcard rule: an admin role not in `allowed_roles` gets an empty page;
  - `test_unknown_type_or_field_is_empty`;
  - `test_not_indexed_raises`;
  - `test_kind_mismatch_raises` (a `datetime` bound on a `date` field);
  - `test_translatable_filters_locale`;
  - `test_tenant_pinned` (`unbound_tenant`, multi mode: tenant `b`'s records never appear for `a`);
  - `test_dated_types_lists_readable_indexed_fields_only`;
  - `test_contract_surface` (`__all__`).
- [ ] **Step 2: Run** (headroom first) `cd modules/records && uv run pytest -q tests/contracts/test_dated.py`. Expected: ImportError.
- [ ] **Step 3: Implement.** Keep the file under 240 lines. If it grows, split out `_dated_access.py`, re-exported.
- [ ] **Step 4: Run** the tests on SQLite and Postgres (`smpy_records_test`): both pass. Then from the root `uv run basedpyright`: 0 errors.
- [ ] **Step 5: Commit** `feat(records): a dated-records contract for calendars`.

### Task 17: The `records:dates` source and the `events` extra

**Files:**
- Create: `modules/records/sm_records/events_extensions.py`, `sm_records/integrations/__init__.py`, `sm_records/integrations/events/__init__.py`, `sm_records/integrations/events/settings.py`, `sm_records/integrations/events/source.py`
- Modify: `modules/records/pyproject.toml` (the extra of Ruling 31 with its floor comment), `uv.lock`, root `pyproject.toml` (pyright include), `modules/records/sm_records/locales/en.json`/`de.json` (`events.source.label`, `events.settings.*`)
- Test: `modules/records/tests/integrations/__init__.py`, `tests/integrations/events/test_source.py`, `tests/integrations/events/test_settings.py`, `tests/integrations/events/test_registration.py`

- [ ] **Step 1: Write the failing tests** (each file starts with `pytest.importorskip("sm_events")`):
  - `test_registration.py`:
    - `test_events_extensions_imports_lazily`: in a subprocess, `import sm_records.events_extensions` leaves `sm_events` absent from `sys.modules`;
    - `test_registers_records_dates` (through events' real `load_extensions` with records' entry point present);
    - `test_only_integrations_import_events`: a grep over `sm_records/` finds `sm_events` only under `integrations/events/` and only as `sm_events.contracts`.
  - `test_settings.py`:
    - `test_one_to_five_mappings`;
    - `test_check_settings_unknown_type`;
    - `test_check_settings_unreadable_type`;
    - `test_check_settings_not_indexed`;
    - `test_check_settings_kind_mismatch`;
    - `test_end_field_differs`.
  - `test_source.py` (a `SourceContext` built by hand over records' test session):
    - `test_date_field_all_day`;
    - `test_datetime_with_end_field`;
    - `test_datetime_duration_fallback_and_end_before_start`;
    - `test_lookback_shows_running_multi_day`;
    - `test_key_title_url_shape`;
    - `test_anonymous_url_none_and_public_types_only`;
    - `test_role_narrowed_type_hidden_for_viewer`;
    - `test_limit_plus_one`;
    - `test_items_validate_through_events` (each item passes events' `to_occurrences`).
  - From the root, `test_records_source_through_read` in `modules/events/tests/integration/test_records_source.py`, also with `importorskip("sm_records")`: an `events_app` with records mounted, a calendar with `records:dates` enabled and the occurrences read returning the record. It is the only events test that touches records, and it imports only records' public test seeding through the HTTP API.
- [ ] **Step 2: Run** `cd modules/records && uv run pytest -q tests/integrations` and `cd modules/events && uv run pytest -q tests/integration`. Expected: fail.
- [ ] **Step 3: Implement**, then from the root `uv sync --all-packages --all-extras --no-extra anonymize` (headroom first).
- [ ] **Step 4: Run** the tests on SQLite and Postgres (both pass), then `uv run python scripts/check_rules.py`, `check_sibling_contracts.py`, `basedpyright` and `check_hardcoded_strings.py`: all pass.
- [ ] **Step 5: Commit** `feat(records): show records' dates on events calendars (optional events extra)`.

### Task 18: Records' frontend: settings section and detail

**Files:**
- Create: `modules/records/sm_records/events-extensions.ts`, `sm_records/ui/events/RecordDatesSettings.tsx`, `sm_records/ui/events/RecordDateDetail.tsx`
- Modify: `modules/records/package.json` (`@simple-module-py/events` as an optional peer, in `peerDependenciesMeta` too), records' locales (`events.settings.*`)
- Test: `sm_records/ui/events/RecordDatesSettings.test.tsx`

- [ ] **Step 1: Write the failing tests:**
  - `lists only indexed date and datetime fields of the chosen type`;
  - `adds up to five mappings`;
  - `end field excludes the start field and other kinds`;
  - `errors under mappings.0.field are shown`;
  - `detail shows Open record when url is set`.
- [ ] **Step 2: Run** `npx vitest run modules/records/sm_records/ui/events`. Expected: fail.
- [ ] **Step 3: Implement.** `events-extensions.ts` contains only `registerSource({ id: 'records:dates', SettingsSection: () => import('./ui/events/RecordDatesSettings'), Detail: () => import('./ui/events/RecordDateDetail') })`. Events' `plugin-files.test.ts` now covers this file.
- [ ] **Step 4: Run** vitest over `modules/records/sm_records/ui/events` and `modules/events/sm_events/ui/extensions`, `npx tsc --noEmit -p modules/records/tsconfig.json`, biome, and `check_ts_imports.py`: all pass.
- [ ] **Step 5: Commit** `feat(records): calendar source settings and detail for records' dates`.

### Task 19: The host e2e

**Files:**
- Create: `tests/e2e/events-extensions.spec.ts`

- [ ] **Step 1: Write the spec** (standalone; it seeds everything itself through the APIs with `moduleCsrfHeader`):
  - it creates a records type with a unique key and an indexed `date` field `due` (display field `title`), and a published record due tomorrow;
  - it creates an internal calendar and `PUT`s its sources with `records:dates` and one mapping;
  - `/admin/events/` shows a chip with the record's title on tomorrow's date;
  - clicking it shows the detail with "Open record", which navigates to `/admin/records/<key>/<uuid>`;
  - the Calendars screen's Sources dialog shows the source enabled, with the mapping rendered by records' section;
  - there is no `Content Security Policy` console message and no page error.
- [ ] **Step 2: Run** (headroom first) `npx playwright test tests/e2e/events-extensions.spec.ts`. Expected: it passes once batches A–D are in. Stop the server afterwards.
- [ ] **Step 3: Commit** `test(e2e): a records date on the events calendar`.

### Task 20: The plugin guide, docs and branch verification

**Files:**
- Create: `modules/events/docs/writing-a-plugin.md`. It covers registration and why a file instead of `on_startup`, the id rules, a complete worked source (a `holidays:public` source with a settings model), a complete worked type with an editor section (`acme:talk`, with `extra_model`, `public_fields` and `events-extensions.ts` with lazy `EditorSection` and `PublicDetail`), and the context and session rules (savepoint, read-only, sequential, no commit). It also covers the time budget and item cap, validation, the tenancy and viewer rules, what a `public` source must guarantee, the frontend surfaces and the public constraints, bus events and durable subscriptions, identical installs in web and every worker image, versioning and floors (the `# floor:` comment, `check_sibling_contracts.py`, a `>=` range on events), and testing a plugin.
- Modify: `modules/events/README.md` (an Extensions section; status: PR 6 of 10), `modules/events/docs/index.md` (links; the bus-events list; the status row), `modules/records/README.md` and `modules/records/docs/` index (the `events` extra), `CHANGELOG.md` (0.0.16 Added: the events extension registry, `records:dates`, the bus events, durable delivery), `docs/module-layout.md` (the root-table row `events_extensions.py`, `events-extensions.ts`: "events' loader (`calendar/extensions.py`) and its `ui/extensions/load.ts` glob (`*/*/events-extensions.ts`)"; mention records' `integrations/`)
- Modify: `CLAUDE.md`, a paragraph modelled on the images-plugin one: "A plugin registers events sources and types from `events_extensions.py`, never from `on_startup` …". It covers ids `<entry-point>:<name>`, freeze, identical installs, the savepoint and budget, `public = True` only for public data, `extra` of an uninstalled type kept byte for byte, `events-extensions.ts` registering lazy components only, and records' `events` extra with `contracts.dated`. Also add one line to the events paragraph: bus events are published durably too, and in-process subscribers miss worker changes.
- Modify: the spec (add "Amendments (PR 6)" listing Rulings 2, 5, 7, 8, 11, 12, 13, 15, 19, 21–25, 27, 32)

- [ ] **Step 1: Lint set** (headroom first), from the root:
  - `uv run ruff check modules/events modules/records scripts host`
  - `uv run ruff format --check <files touched>`
  - `uv run basedpyright`
  - `npx biome check modules/events modules/records`
  - `npx tsc --noEmit -p modules/events/tsconfig.json` and the same for records
  - `uv run python scripts/check_metadata.py`, `check_rules.py`, `check_sibling_contracts.py`, `moved_paths.py --check`, `check_ts_imports.py`, `check_readmes.py`, `check_hardcoded_strings.py`, `check_file_size.py` (no WARNING under `modules/events` or in the records files touched), `check_locales.py`, `check_migration_heads.py` and `bump_version.py --check-current`

  All pass.
- [ ] **Step 2: Targeted suites, one at a time:**
  1. `cd modules/events && uv run pytest -q -n 8` on SQLite, then on `smpy_events_test` on Postgres.
  2. `cd modules/records && uv run pytest -q -n 8 tests/contracts tests/integrations` on SQLite and Postgres.
  3. From the root: `uv run pytest -q -n 8 scripts/tests host/tests/test_host_boots.py host/tests/test_events_wiring.py host/tests/test_tenancy_parity.py`.
  4. `npx vitest run modules/events modules/records/sm_records/ui/events`.

  All pass. Drop the scratch databases.
- [ ] **Step 3: Fresh-import check** for every new `.py` file in both modules (`uv run python -c "import …"`).
- [ ] **Step 4: Commit** `docs(events): plugin guide, extension docs and amendments`.
- [ ] **Step 5: Hand over to `/ship`.** Browser QA:
  - enable `records:dates` on a calendar through the Sources dialog;
  - see the record on the console calendar, filter it out with the source filter, and open the record;
  - make the type non-public and check that the public grid on a public calendar shows nothing from it;
  - with a dev-only failing source (the fixture plugin, installed editable for QA only), see the status notice and confirm the built-in events still show.

  Screenshots of the Sources dialog, a records chip with its detail, and the status notice go in the PR.

## Verification checklist (before `/ship`)

- Task 20 Step 1's lint set passes, including `basedpyright` over records' `contracts` and `integrations/events`.
- The events pytest passes on SQLite and Postgres. Records' `tests/contracts` and `tests/integrations` pass. `scripts/tests` and the host tests pass, and so does `npx vitest run` over both frontends.
- `tests/e2e/events-extensions.spec.ts` passes.
- `check_migration_heads.py` reports the same single head as PR 5, because this PR adds no migration.
- No file touched is at 280 lines or more.
- `git diff --stat feat/events-pr5-feeds` touches only `modules/events/**`, `modules/records/sm_records/{contracts/dated.py,events_extensions.py,events-extensions.ts,integrations/**,ui/events/**,locales/*}`, `modules/records/{pyproject.toml,package.json,README.md,docs/**,tests/contracts/test_dated.py,tests/integrations/**}`, `tests/e2e/events-extensions.spec.ts`, the root `pyproject.toml`, `uv.lock`, `package-lock.json` (only if the peer entry changes it), `CHANGELOG.md`, `CLAUDE.md`, `docs/module-layout.md`, the spec and this plan.
- The Review Focus tests exist and pass: grep for each test name listed there.

## Open points

1. **Public plugin occurrences outside the grid and feeds** (Ruling 15). The upcoming list, sitemap and JSON-LD show this module's events only. If a site wants records' public dates in its list too, the list needs a generic item row with no event page.
2. **Plugins are trusted code** (Rulings 7 and 8). The savepoint, timeout and validation catch bugs, not malice. A plugin that blocks the event loop with synchronous work, or swallows `CancelledError`, cannot be pre-empted. Moving plugin calls to a separate process is out of scope.
3. **In-process subscribers miss worker changes** (Ruling 24). Durable subscribers see scheduled publishes, and nobody sees imports (PR 5 Ruling 29). If a consumer needs imported changes, the import could publish one summary event (`EventsImported(calendar_id, counts)`) durably. That is a small follow-up issue, not this PR.
4. **The viewer's roles** (Ruling 6). The framework's `ResourcePrincipal` has no roles, so events builds `SourceViewer` itself, from `request.state.user.roles` and, for feeds, from PR 5's directory lookup. If the framework adds roles to the principal (or ships PR 5's open point 1, an offline principal), `SourceViewer` should come from it. Mention this on that upstream issue rather than filing a new one.
5. **JSON storage of `extra`** (Task 9 Step 3). If PR 1's column is JSONB on Postgres, "byte for byte" means "value-equal" there. The guide states which.
6. **The ★ rulings** most likely to change are:
   - ids namespaced by entry-point name (2);
   - `SourceOccurrence` rather than `Occurrence` (5);
   - savepoint and sequential calls rather than a session per call (7);
   - the budget numbers (8);
   - statuses omitted from public answers (11);
   - no data migration for calendar sources, one entry per source per calendar, and the visibility right to enable one (12);
   - public sources only on public calendars (13);
   - plugin items not in the public list or sitemap (15);
   - an immutable type (19);
   - uninstalled types refusing `extra` writes (21);
   - public extra by `public_fields` (22);
   - the five new bus events (23) and durable delivery (24);
   - lazy registrations (25);
   - public plugin components (27);
   - the records contract, published-only records (32).
