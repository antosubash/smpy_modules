# Events PR 5: private feed tokens and `.ics` upload. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user can subscribe to any calendar they may view through a private link that serves, on every request, exactly what that user may see **now**, and that dies the moment their access does. A manager can upload an `.ics` file into a calendar, see a preview (new, updated, skipped with reasons, dropped properties), and apply it as drafts or published events, with re-imports updating by UID.

**Architecture:** Two halves under `sm_events/feeds/`. `feeds/tokens/` owns the token codec (32 random bytes, SHA-256 at rest), the service (create, list, revoke, limits), the resolver (one narrow `all_tenants()` hash lookup, then the token's tenant bound and the owner's access re-derived through `core/access/offline.py` and PR 1/2's policy), cleanup (bus handlers and a janitor step) and a log filter that keeps the token out of the framework's request log. The route `web/endpoints/public/_private_feed.py` is the module's one documented tenancy exception; every refusal falls through to one 404 builder, padded to a latency floor. `feeds/importing/` follows newsletter's staged import: the upload stores raw bytes on an `events_import` row, `events.run_import` pre-scans and parses them with `icalendar` into `events_import_item` rows (a verdict and a mapped payload each) and clears the bytes, the preview reads those rows, and apply runs leased, resumable slices whose batches write each item through PR 2's write internals in a savepoint. Feeds reuse PR 4's ICS writer; the import reuses PR 2's validators.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy async, `icalendar` 7.x (from PR 4), `hashlib`/`secrets`, the framework's `background_tasks` (Celery) through PR 2's worker runtime, pytest (SQLite, plus Postgres opt-in through `tests/pg_support.py`), React 19 + Inertia, `@simple-module-py/ui`, vitest (happy-dom), Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`. This plan covers Delivery row 5 and draws on "Anti-goals" (a feed token that outlives its owner's access; leaking across tenants), "Access", "Tenancy" (the one documented exception), "ICS" ("Private feed tokens" and "Upload"), "Settings" (`import_max_bytes`) and "Background work" (`events.run_import`). Precedent plans: `docs/superpowers/plans/2026-11-17-events-pr2-events.md` (validators, write path, revisions, the worker runtime) and `docs/superpowers/plans/2026-11-17-events-pr4-public.md` (the ICS writer, the public routers, cache and tenant rules). Precedent code to read before starting: `modules/newsletter/sm_newsletter/imports/` (all of it: `staging.py`, `fence.py`, `runner.py`, `launch.py`, `janitor.py`, `constants.py`), `modules/newsletter/sm_newsletter/web/endpoints/unsubscribe.py` and `public_tenant.py` with `modules/newsletter/tests/web/test_unsubscribe_tenancy.py`, `modules/images/sm_images/ingest/guards.py` (`read_bounded`) and `modules/images/sm_images/ingest/imports/log_redact.py` with its test, and the framework's `simple_module_hosting/_observability.py` (`RequestLoggingMiddleware` logs `path` at INFO) and `_rate_limit.py` (logs the path on a 429).

## Depends on PRs 2–4

Before Task 1 the branch is rebased onto the finished `feat/events-pr4-public` (itself on PR 3 → PR 2 → PR 1). The implementer of batch A **re-checks every name below against the real code first** and corrects this plan's references in the task text (never by renaming PR 2–4 code) wherever they differ. Stop and report if a *behaviour*, not only a name, differs, in particular: if `visible_events(who, include_unpublished=False)` can return a draft for any principal; if PR 4's feed read cannot be narrowed to a caller-supplied select; or if PR 2's write functions have no seam below the rights check that a system write could call.

| Kind | Symbol this plan relies on |
|---|---|
| Access (PR 1) | `sm_events.core.access.POLICY`, `visible_calendars(who, action=ACTION_VIEW) -> Select[Calendar]` (trash excluded), `ACTION_WRITE_EVENTS`, `calendar_rights(db, who, calendar)` (`core/access/rights.py`); principal rule: without `events.view` a signed-in principal gets `public` only |
| Access (PR 2) | `sm_events.core.access.events.visible_events(who, *, include_unpublished: bool) -> Select[Event]`, `is_locked(event)`, `EventRights`, `load_event` |
| Members (PR 1) | `sm_events.web.services.members`: `unscoped_single(request)`, `members_only`, `active_member`, `directory_or_unavailable`; the owner-naming rule of "Amendments (PR 1)" (`owner_name`) |
| Time (PR 2) | `sm_events.calendar.times`: `Span`, `to_span(*, all_day, timezone, start, end, recurring)`, `to_local`, `localize(naive, tz)`, `is_nonexistent`, `all_day_dates`; `InvalidTimes` codes |
| Recurrence (PR 2) | `sm_events.calendar.rrule.parse(text, *, all_day, timezone) -> Rule`, `validate(rule, span, *, all_day, timezone) -> datetime | None`, `build(...)`; `sm_events.calendar.expand.instances(...)`, `is_occurrence(original_start, *, rule, span, all_day, timezone)`; `InvalidRule` codes `invalid_rrule`, `rrule_frequency_refused`, `start_not_in_rule` |
| Content (PR 2) | `content.richtext.clean`; `content.texts.apply_texts(db, event, texts, *, locales, creating)`, `texts_of`; `web.schemas.texts.TextIn`; `content.guard.claim_revision(db, event_id, expected, *, actor, trashed=False)`; `content.revisions.record(db, event, *, action, actor, note=None)`; `content.events_write.create_event`/`update_event` and whatever internal they call after the rights check; `content.overrides.set_override` and its upsert internal; `content.series_change.orphans`; `content.fields` (category check); `content.bus` (`attach`, `emit`; no `muted`) |
| Models (PR 1/2) | `Event` (`uid` ≤ 255, unique `uq_events_event_uid (tenant_id, calendar_id, uid)` across the trash), `EventText`, `OccurrenceOverride`, `Calendar` (`default_timezone`, `is_deleted`), `Category` (`names`), `EventStatus`, `OverrideKind`, `models/_cols.py` (`big_pk`, `pk_uuid`, `fk_uuid`, `dt_col`, `json_col`, `flag`) |
| Worker (PR 2) | `sm_events/tasks.py`, `sm_events/task_config.py` (`QUEUE_DEFAULT = "events"`, `TASK_ROUTES`, `BEAT_SCHEDULE`), `sm_events/core/worker.py` (`run_platform`, `reset_worker_runtime`), `content/publish_due.py` (the per-tenant pattern) |
| ICS (PR 4) | `sm_events.feeds.select.feed_events(db, *, calendar_id, locale, default_locale, now, url_for) -> FeedRead`, `FeedEvent`, `single_event`; `feeds.ics_calendar.build(items, *, name, timezone, first, last) -> bytes`; `feeds.ics_event.components`; `feeds.plaintext.to_text`; constants `FEED_MAX_EVENTS`, `FEED_MAX_COMPONENTS`, `FEED_DAYS_BACK`, `FEED_DAYS_AHEAD`, `ICS_MEDIA_TYPE`, `PRODID`, `RESERVED_SLUGS` (contains `"feed"`), `FEED_RATE` |
| Public web (PR 4) | `web/endpoints/public/__init__.py` (`public_router(locale)`, route order), `_urls.py` (`absolute`, `event_path`, `calendar_ics_path`, `use`), `_cache.py` (`PublicErrorRoute`), `core/boot.py` (`mount_public_routers`, `exempt_public_routes`, `register_public_rate_limits`), `core/public_prefix.effective`, `core/locales` |
| Tenancy | `sm_events.core.tenancy`: `tenant_scope`, `all_tenants`, `valid_tenant`, `bound_tenant`, `mode_of`, `TenancyMode`, `DEFAULT_TENANT`; `simple_module_db.no_tenant`, `finalize_session`. **Parity-checked: this PR edits none of `core/tenancy/*`.** |
| Constants | `PACKAGE`, `MODULE_NAME`, `ROUTE_PREFIX_API`, `VIEW_PREFIX`, `PERM_*`, `NOT_FOUND_DETAIL`, `UID_SUFFIX`, `NOTE_MAX`, `MAX_EVENT_DAYS`, `MAX_SERIES_EVENT_DAYS`, `RRULE_MAX_COUNT` |
| TS (PR 1–4) | `ui/utils/api.ts` (`ApiError`, `errorText`), `ui/utils/i18n.ts` (`useT`, `keys`), `ui/components/calendars/CalendarRow.tsx`, `ui/components/ConfirmDialog.tsx`, `ui/page-tests/test-dom.tsx`, `ui/page-tests/support.tsx` (`stubFetch`), PR 4's `ui/public/SubscribeBox.tsx` (public feed URL and `webcal:` link) |
| Tests | `tests/support/app.py` (`build_app`, `as_user`, the fake `Directory`, `client`, `multi_client`, `csrf_client`), `tests/support/access.py` (`principal`, `seed_calendars` with `P`/`I`/`U`), `tests/support/calendars.py` (`seed_event`, PR 4's `seed_public_fixture`), the `unbound_tenant` marker, `tests/pg_support.py`; e2e `tests/e2e/helpers.ts` (`login`, `moduleCsrfHeader`, `uniqueSlug`) |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**Tokens**
1. **Format and storage** (spec: 32 random bytes, only the SHA-256 stored, #366). A token is `"evf_" + base64url(secrets.token_bytes(32))` without padding, 47 characters, shape `^evf_[A-Za-z0-9_-]{43}$`. The prefix lets secret scanners and the log filter recognise it. Only `token_hash = sha256(token.encode()).hexdigest()` is stored, unique across all tenants; nothing else derived from the token (no hint, no prefix) is kept, and nothing depends on `SM_SECRET_KEY`. The token appears once, in the `201` body of the create call (`Cache-Control: no-store`, `Referrer-Policy: no-referrer`), and never again: not in a list, not in a log line, not in an error.
2. **Table `events_feed_token`**: `id` (UUID PK), `tenant_id` (`MultiTenantMixin`), `calendar_id` (FK `events_calendar.id` `ON DELETE CASCADE`, indexed), `user_id` (str 64), `token_hash` (str 64, unique `uq_events_feed_token_hash`), `label` (str 100), `locale` (str `LOCALE_MAX`), `created_at`, `last_used_at` (nullable), `revoked_at` (nullable). Index `ix_events_feed_token_owner (tenant_id, calendar_id, user_id)`. No soft delete: revoking sets `revoked_at`, the janitor deletes later (Ruling 14).
3. **One user, one calendar, a label and a language.** `label` is a `SingleLine` of 1–100 characters. `locale` must be in `content_locales`; when absent it is the console locale if that is a content locale, else the default one. At most `FEED_TOKENS_PER_USER_CALENDAR = 5` unrevoked tokens per `(user, calendar)`; one more gets 409 `token_limit`.
4. ★ **Who may do what.** Creating needs `events.view` and view access to the calendar through `POLICY` (any visibility: a private link to a public calendar is redundant but harmless), and an offline principal that resolves for the caller (Ruling 7), otherwise 503 `private_feeds_unavailable` (so nobody is handed a link that could never work). Each user lists and revokes their own tokens. `events.manage` lists everyone's tokens on a calendar (`?all=true`) and revokes any (spec). A calendar owner without `events.manage` sees only their own: the spec gives "other people's tokens" to `events.manage`. A calendar the caller cannot see is 404 on every route, and so is someone else's token for a non-manager.
5. ★ **A feed carries published events only, even when its owner can write drafts.** A feed is a copy that leaves the console's access control: clients sync it to phones, share it with a household and cache it for days. A draft is unreviewed, and a scheduled event is still embargoed. The console calendar already shows writers their drafts. So the feed's select is `visible_events(who, include_unpublished=False)`, and a token's content does not depend on whether its owner writes.
6. **Every request re-derives access** (spec: "serves what that user may see now"). In order, with no early return (Ruling 9): the row exists and `revoked_at IS NULL`; the request's *host* tenant is absent or equals the row's (Ruling 8); the offline principal for `(row.user_id, row.tenant_id)` resolves (Ruling 7: account known and active, a member of that tenant, roles known); the calendar is in `visible_calendars(who)` (not trashed, `events.view` still held, still the owner, still shared, or still `internal`/`public`, or `events.manage`); then the feed is `feed_events` over `visible_events(who, include_unpublished=False)` narrowed to that calendar. Nothing is cached between requests.
7. ★ **The offline principal** (`core/access/offline.py`, `async def feed_principal(app, db, *, user_id, tenant_id) -> ResourcePrincipal | None`). The framework resolves permissions only for a request's own principal, so this composes its public pieces: `get_user_directory(app).get_many(db, [user_id], with_roles=True)` (unknown, `is_active` false, or `roles is None` (Keycloak keeps roles in the IdP) → `None`); on a multi-tenant host `tenant_member_ids(app, db, tenant_id, [user_id])` must contain the user (`None` → fail closed); then `resolve_principal_permissions(request, OfflineUser(id, roles, tenant_id), registry)` with the role map and grant sources of `app.state.sm.permissions`. The membership role (`tenant:<role>`) that the tenants resolver adds per request has no public read: Task 3 Step 0 greps `tenants.contracts` and `simple_module_core.tenancy` for one and uses it if present; otherwise the stopgap leaves the tenant role out, which can only *narrow* what a feed serves (fail closed), and the gap goes upstream (open point 1). If the framework already ships an offline resolver (`grep -rn "def principal_for\|def permissions_for_user"`), use it instead and delete this ruling's body. The same function answers Ruling 4's create check.
8. **The one documented tenancy exception** (spec, Tenancy). The route runs `with no_tenant():` (a visitor's session or header tenant is left, as newsletter's unsubscribe does), looks the hash up in one statement tagged `tenancy.all_tenants(...)` whose only predicate is `token_hash = :h` (it selects `id, tenant_id, calendar_id, user_id, locale, revoked_at`), and then does everything else under `tenant_scope(row.tenant_id)`. A tenant the request's **host** resolved (`request.state.tenant_source` in `{"subdomain", "fixed"}`, events' own copy of newsletter's `host_tenant`) that differs from the row's refuses the token (Ruling 9). A tenant that came from the visitor (session, header, claim) proves nothing and is ignored. The route is not under PR 4's `public_tenant` or `bind_public`.
9. ★ **One answer for "no".** Malformed, unknown, revoked, host-tenant mismatch, user gone, inactive or no longer a member, roles unknown, `events.view` lost, share removed, visibility narrowed, calendar trashed: all reach the single `_deny()` at the end of the handler, which builds `404` with body `{"detail":"Not found","code":"not_found"}`, `Content-Type: application/json`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`, and no `Vary`, `ETag` or `Set-Cookie`. No branch returns its own response. A malformed token skips the database (there is nothing to find). Constant-time comparison is unnecessary for a hash lookup; what differs is the work after it (no row: one statement; a row without access: four or five). That difference only tells someone who already holds a token whether it once existed, because 256-bit tokens cannot be found by timing, but it is still closed: every deny is delayed to `FEED_DENY_FLOOR_SECONDS = 0.25` after the handler started (`asyncio.sleep(remaining)`), which is above the slowest access path in the tests. A success is not padded. An internal failure (database or directory error) answers `503` `no-store` with a fixed body, logged by exception class only; it is the one other shape, and it says nothing about the token.
10. ★ **A served feed is never cached shareably and never validated.** `200`, `Content-Type: text/calendar; charset=utf-8`, `Cache-Control: private, no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`, no `ETag`, no `Content-Disposition` (subscriptions open inline). No 304 path: it would be a second success shape to keep uniform, and calendar clients poll a few times a day, so the bandwidth it saves is small under PR 4's 5,000-component cap. `GET` and `HEAD` (headers of `GET`, no body).
11. **Rate limits.** Per IP: `RateLimitRule(FEED_PRIVATE_RATE = "30/minute", key="ip", methods={"GET","HEAD"})` on the private feed path, registered next to PR 4's rules; Task 5 proves which rule the registry matches for `/events/feed/x.ics` and makes it this one. Per token: the framework keys only by IP, user or tenant, so events keeps an in-process window (`feeds/tokens/throttle.py`, at most `FEED_TOKEN_RATE = 20` hits per `FEED_TOKEN_WINDOW_SECONDS = 600`, an LRU of `FEED_THROTTLE_KEYS = 10_000` keys). It is keyed by the SHA-256 of the *presented* string before any lookup, so a valid and an invented token over the limit get the same `429` with `Retry-After` and `no-store`, and the limit tells nobody which tokens exist. It is per process; this is documented, and the upstream ask is open point 2.
12. **The token never reaches a log or an error.** `RequestLoggingMiddleware` logs `path` at INFO, the rate limiter logs the path on a 429, and uvicorn's access log prints it. `feeds/tokens/log_redact.py` (images' `log_redact` pattern) installs a `logging.Filter` on `simple_module.request`, `uvicorn.access` and the rate limiter's logger (Task 2 reads its name from `simple_module_hosting/_rate_limit.py`), rewriting `(/feed/)[^/?#\s"']+` to `\1<redacted>` in `record.msg`, every string in `record.args`, and the `path` attribute the middleware passes as `extra`. It is installed in `on_startup`, idempotently. The route itself logs nothing that names the token, and its exceptions are logged by class name only (an exception message can carry the path). Proxies and load balancers are outside the process: `docs/feeds.md` tells operators to redact `/feed/` paths, as newsletter's operations doc does for `/newsletter/u/`. A framework-level redaction hook is open point 3.
13. **`last_used_at` is coarse and harmless.** After the body is built and the read session is closed, a separate short session runs `UPDATE events_feed_token SET last_used_at = :now WHERE tenant_id = :t AND id = :id AND (last_used_at IS NULL OR last_used_at < :now - FEED_LAST_USED_GRANULARITY)` (1 hour), finished with `finalize_session`. No lock is held while the feed is built, two concurrent fetches both match at most once per hour, and any failure is logged by class and ignored: the feed is still served.
14. **Revocation cascades.** Correctness never depends on cleanup: every case below is refused on the next request by Ruling 6, and cleanup only removes rows.

    | Event | Refused at once by | Row removed by |
    |---|---|---|
    | owner or manager revokes | `revoked_at` | janitor, `FEED_REVOKED_KEPT_DAYS = 30` days later |
    | calendar trashed | `visible_calendars` (trash excluded) | nothing: ★ a restored calendar's links work again, still under the owner's current access |
    | calendar hard-deleted | the row is gone | FK `ON DELETE CASCADE` |
    | share removed, visibility narrowed, `events.view` or `events.manage` lost | `visible_calendars(who)` | nothing (a re-grant revives the link) |
    | user disabled (`UserDisabled`) | directory `is_active` | nothing (reactivation revives it) |
    | membership removed (`MembershipRemoved`) | `tenant_member_ids` | bus handler: that user's tokens in that tenant |
    | user deleted (`UserDeleted`) | directory lookup misses | bus handler: every token of that user, in every tenant (one narrow `all_tenants()` delete with its own `user_id` predicate) |
    | tenant deleted (`TenantDeleted`) | membership misses | bus handler: that tenant's tokens |

    The handlers run in the web process (the framework's bus); a missed event leaves a row that still serves nothing. The janitor (Task 14) also deletes revoked tokens past 30 days.
15. **Feed content.** PR 4's writer, with the token's `locale` and PR 4 Ruling 12's text fallback, PR 4's window and caps, `X-WR-CALNAME` = the calendar's name and `X-WR-TIMEZONE` = its `default_timezone`. `URL` is the public event URL when the calendar is `public`, otherwise the absolute console URL of the event (`/admin/events/edit/{id}`), which a token holder can open only after signing in. A truncated feed sets `X-Events-Truncated: 1` as PR 4's does.
16. **Address.** `{public_prefix}/feed/{token}.ics`, on the default-locale router only (the language is on the row), registered before `/{slug}.ics`. `feed` is already a reserved slug (PR 4 Ruling 9). PR 4's public exemption covers `GET`/`HEAD` under the prefix, so no session is needed, and a `POST` there still needs one. No CSRF (safe methods only).

**Import**
17. ★ **Permission: `events.manage`** (spec, Access lists import under it), plus view and `write_events` on the chosen calendar (implied by manage). Applying as published needs `events.publish` as well (403 `publish_required`), and updating a locked existing event needs it per item (Ruling 28). Rights are checked when the request is made (upload, apply). The worker re-checks only database facts (the import row is still `queued`/`running` in its tenant, the calendar exists and is not trashed), because a Celery worker builds no app, so it has no user directory or grant sources. An import that runs for a few minutes after its manager lost the role finishes; this window is documented.
18. ★ **The upload's bytes live on the import row, not in `file_storage`.** `events_import.source` is a `LargeBinary` column holding at most the cap (≤ 20 MiB), written by the upload request and set to `NULL` by the parse step, so raw bytes exist for seconds to minutes. Trade-off: `simple_module_file_storage` would keep bytes out of the database and WAL, but it adds a dependency, a backend that must exist in every worker image, its own tenancy and an orphan to reap when a row is deleted without its object. Under a 5 MB default the column is simpler and transactional with its row, and Postgres `bytea` handles it.
19. **Limits.** Setting (spec) `import_max_bytes: int = 5 * 1024 * 1024`, runtime, read per request and clamped to `[IMPORT_MIN_BYTES = 64 KiB, IMPORT_BODY_CEILING = 20 MiB]`. `register_body_limits` registers `POST {ROUTE_PREFIX_API}/imports` at `IMPORT_BODY_CEILING + 1 MiB` (it runs before settings hydrate, so it cannot read the setting), and the handler reads the part with images' `read_bounded` pattern, stopping at the clamped cap: more is 413 `import_too_large`. Constants (not settings; nothing here is an operator's tune): `IMPORT_MAX_EVENTS = 5000` VEVENTs, `IMPORT_MAX_COMPONENTS = 20_000` components of any kind, `IMPORT_MAX_DEPTH = 3` (VCALENDAR › VEVENT › VALARM; VCALENDAR › VTIMEZONE › STANDARD), `IMPORT_MAX_TIMEZONES = 100`, `IMPORT_MAX_PROPERTIES = 500` per component, `IMPORT_MAX_LINE = 65_536` bytes per unfolded content line, `IMPORT_MAX_EVENT_BYTES = 262_144` per VEVENT, `IMPORT_MAX_OVERRIDES = 730` RECURRENCE-ID components per UID, `IMPORT_DESCRIPTION_MAX = 20_000` characters, `IMPORT_ACTIVE_MAX = 5` unfinished imports per tenant (409 `import_busy`), `IMPORT_APPLY_BATCH = 50`, `IMPORT_SLICE_SECONDS = 45`, `IMPORT_LEASE = 5 min`, `IMPORT_TTL = 24 h`, `IMPORT_KEEP_REASONS = 1000`.
20. **Hostile input is refused before `icalendar` sees it.** `feeds/importing/scan.py` reads the bytes once: strict UTF-8 after stripping a BOM (otherwise the import fails with `ics_encoding`); CRLF, LF and CR line ends accepted; lines unfolded per RFC 5545 §3.1; any unfolded line over `IMPORT_MAX_LINE`, a NUL byte, a first content line other than `BEGIN:VCALENDAR` (case-insensitive), more than one VCALENDAR, unbalanced or mismatched `BEGIN`/`END`, nesting beyond `IMPORT_MAX_DEPTH`, or any count over Ruling 19's bounds fails the whole import with `ics_invalid` or `too_many_events` and a counter of which bound tripped (never a value from the file). Only then does `icalendar.Calendar.from_ical` run, inside `try`; its exception becomes `ics_invalid` and its message is never stored (it can echo content). The upload request itself only sniffs that the first non-blank line is `BEGIN:VCALENDAR` (422 `ics_invalid`), so an obviously wrong file fails at once.
21. **Parsing is a background step** (spec). Upload creates the row as `uploaded` and launches `events.run_import`. A slice that finds `uploaded` claims it (`parsing`, under the lease), runs scan, parse and mapping in memory, writes every `events_import_item` in chunks of 500 and the counts, sets `source = NULL` and moves to `staged`, all in one fenced transaction: a crash leaves `uploaded`/`parsing`, and the janitor relaunches it. Within the bounds of Ruling 19 one parse fits a slice. A slice that finds `queued`/`running` applies (Ruling 28). States: `uploaded`, `parsing`, `staged`, `queued`, `running`, `done`, `failed` (with `error_code`).

**Mapping a VEVENT** (`feeds/importing/values.py` and `mapper.py`; values are read from each property's raw text and parameters, never through `icalendar`'s timezone resolution, so a file's VTIMEZONE bodies are never evaluated)
22. **Times.**
    - `TZID` that `zoneinfo` knows → that zone. A Windows name (`W. Europe Standard Time`) → its IANA zone through `icalendar`'s own Windows mapping when the installed version has one (Task 10 records the name); an Outlook `tzone://Microsoft/<name>` is stripped to `<name>` first. ★ Any other `TZID` → the event is skipped with `unknown_timezone`: a file's VTIMEZONE could define the offsets, but evaluating it is exactly the VTIMEZONE bomb, and a series cannot keep its wall clock without a real zone.
    - `…Z` (UTC) without `TZID` → the event's `timezone` is the calendar's `default_timezone` and its local times are that instant there. Floating (no `Z`, no `TZID`) → read in the calendar's `default_timezone`, noted `floating_time`.
    - `VALUE=DATE` → all-day; `DTEND` (exclusive) minus one day is PR 2's inclusive `end`. `DTSTART` and `DTEND` of different kinds → skipped `invalid_times`.
    - `DURATION` instead of `DTEND` → `start + duration` (all-day: whole days only, otherwise `invalid_times`); negative or zero for a timed event → `invalid_times`. ★ Neither `DTEND` nor `DURATION`: a date is one day (RFC 5545), and a timed event gets `IMPORT_DEFAULT_DURATION = 1 h`, noted `default_duration` (RFC 5545 gives it zero length, which PR 2 refuses).
    - A local time in a DST gap is shifted forward (RFC 5545 §3.3.5, `times.localize` then back to wall clock) and noted `shifted_local_time`, so PR 2's `invalid_local_time` never fires on an import. Then `times.to_span(..., recurring=bool(rrule))`; `end_before_start` or `duration_too_long` skips the event with that code.
23. **Recurrence.** One `RRULE` goes through PR 2's `rrule.parse` (the allow-list) and `validate`. Refused parts, sub-daily frequencies, `COUNT` over 730, `UNTIL` over 100 years, a second `RRULE`, `RDATE` or `EXRULE` → skipped `unsupported_rule` (dropping any of them would silently change which dates the event has). ★ **A start that is not an occurrence of its rule is adjusted, not refused**: RFC 5545 counts that `DTSTART` as an extra first instance, PR 2 refuses the mismatch (its Ruling 6), and skipping would lose a whole series over one stray date. So the start moves to the first rule instance after it (with the same duration), `COUNT` drops by one (the RFC count included the extra instance; `COUNT=1` leaves a one-off at the first rule instance), and the item is noted `start_adjusted` with the dropped original date shown in the preview. A rule with no instance after the start is skipped `unsupported_rule`.
24. **Overrides.** `EXDATE` values (any number of properties, each possibly a list) that are occurrences of the (adjusted) rule become `skipped` overrides; others are ignored and noted `exdate_ignored`. A VEVENT with the master's `UID` and a `RECURRENCE-ID` becomes `cancelled` when `STATUS:CANCELLED`, else `moved` with its own start and end, read by Ruling 22 (PR 2 Ruling 10: only times; a differing `SUMMARY`, `LOCATION` or `DESCRIPTION` is noted `override_fields_dropped`). A `RECURRENCE-ID` that is not an occurrence of the rule, has the other value kind, carries `RANGE=THISANDFUTURE`, or moves beyond `MAX_SERIES_EVENT_DAYS` is dropped and noted. More than `IMPORT_MAX_OVERRIDES` for one UID skips the event (`too_many_overrides`). `RECURRENCE-ID` components without a master → each skipped `override_without_master`.
25. **Fields and text** (spec: text in the calendar's default content locale, which is `content_locales[0]`; the description passes PR 2's sanitiser as plain text turned into paragraphs).
    - `SUMMARY` → `title`: control and direction characters removed, whitespace collapsed, cut to 300 characters; empty → `IMPORT_UNTITLED = "Untitled event"`, noted `untitled`.
    - `DESCRIPTION` → plain text cut to `IMPORT_DESCRIPTION_MAX`, HTML-escaped, blank lines → `<p>` paragraphs, single line breaks → `<br>`, then `richtext.clean`. `URL` (http/https only) is appended as `<p><a href="…">…</a></p>`. `X-ALT-DESC` (HTML) is dropped: the plain text is what every client also writes.
    - `LOCATION` → `venue_name` (≤ 200); a `LOCATION` that is exactly one http(s) URL → `online_url` and `attendance_mode = "online"`. `GEO` → `latitude`/`longitude` when both are in range.
    - `STATUS:CANCELLED` on the master → `cancelled = True`; other statuses are ignored.
    - `CATEGORIES` → an existing category whose default-locale name matches one value case-insensitively (the first match); none → dropped, noted `category_dropped`. The import never creates categories.
    - ★ `CLASS:PRIVATE` or `CLASS:CONFIDENTIAL` → imported as a **draft** even when the import is applied as published, noted `kept_draft_private`: such an event was marked not-for-everyone at its source, and a public calendar would publish it.
    - **Dropped and counted per property name**: `ATTENDEE`, `ORGANIZER` (it carries an address), `VALARM`, `ATTACH`, `RELATED-TO`, `X-ALT-DESC`, every other `X-*` and every property not named in this ruling. `type` is always `"event"`; `extra` is `{}`.
26. **UID** (spec: kept verbatim, unique per tenant + calendar + uid). Kept exactly; over 255 characters → skipped `uid_too_long`. A VEVENT without `UID` gets a deterministic one, `sha256(raw DTSTART line + "\n" + SUMMARY)[:32] + "@import" + UID_SUFFIX`, so re-importing the same file finds it again; noted `uid_generated`. Two masters with one `UID` in a file: the higher `SEQUENCE` wins, then the later one; the other is skipped `duplicate_uid`.
27. **The preview** is the staged items. Each item has a verdict: `new` (the UID is not in the calendar), `update` (the UID is on a live event of that calendar; its id and current `revision` are stored as `existing_event_id` and `expected_revision`), or `skip` with a reason code. A UID held by a **trashed** event of that calendar is `skip` `uid_in_trash` (the unique index spans the trash, and resurrecting an event the user deleted is not the import's call). The import row carries `counts` (`{new, update, skip}`), `reasons` (`{code: count}` for skips and notes), `dropped` (`{property: count}`) and `total`. A UID in another calendar is a new event there (spec: two events).

**Applying**
28. **Apply** (`POST …/apply`, body `{publish: bool}`) moves `staged` → `queued` and launches the task. Slices take `IMPORT_APPLY_BATCH` items with `outcome IS NULL` in `seq` order; each batch is one transaction holding the item writes, their outcomes and the fenced counter update (newsletter's `fence.py`, copied). Each item runs in a savepoint (`begin_nested`): a PR 2 validation error (an event error class) gives `outcome = "skipped"` and that error's code; any other exception gives `outcome = "failed"`, `write_failed`, logged by class name; the rest of the batch continues. A retried batch re-reads items whose `outcome` is still `NULL`, so a crash redoes only the rolled-back batch, and a finished item is never written twice.
    - **New** → PR 2's create path: status `draft`, or `published` with `published_at = now` when `publish` (except Ruling 25's private class), `revision 1`, the mapped text in the default locale (slug derived), overrides inserted, revision `created`.
    - **Update** → PR 2's update path with `claim_revision(expected=item.expected_revision, actor=created_by)`: `Stale` → `skipped`, `changed_since_preview`. The file wins for what it maps (times, rule, overrides, cancelled, venue/online/geo, the default-locale title and description); other locales, category (unless the file names one that matches), image, registration URL, organiser, `extra` and status are untouched: an update never publishes or unpublishes. The file's overrides replace the event's, with orphans dropped as PR 2's `drop_orphaned_overrides` does. A locked existing event needs `events.publish` recorded on the import (the applier's rights at apply time), otherwise `skipped`, `publish_required`.
    - **Unchanged**: an update whose mapped values equal the event's current ones writes nothing (`outcome = "unchanged"`), so re-importing the same file is a no-op with no revision.
    - Revisions record `actor = import.created_by` and `note = f"import #{import.id}"`. Slugs, sanitising and the stale guard are PR 2's, unchanged.
29. ★ **An import emits no bus events.** Its sessions never have a bus attached (PR 2's `bus.emit` without a bus publishes nothing), in the worker and in eager mode alike, so behaviour does not depend on the deployment. A worker has no bus anyway (PR 2 open point 2), and 5,000 `EventPublished` for one upload would flood every subscriber. The import row records the counts. Consumers that need imported changes are PR 2's open point 2; documented.
30. **Cleanup** (newsletter's janitor, `events.janitor`, hourly on queue `events`). One narrow `all_tenants()` read of `(tenant_id, id, status)` candidates, then per tenant under `tenant_scope`: delete `staged`, `done` and `failed` imports older than `IMPORT_TTL` from their last change (items cascade; staged items hold event text), relaunch `uploaded`/`queued` older than `IMPORT_LEASE` (a lost message) and `parsing`/`running` whose lease ran out. In the same task: delete revoked feed tokens older than `FEED_REVOKED_KEPT_DAYS`. Counts only in its log line.
31. **Errors** (`{"detail","code"}` envelope). New HTTP codes: 409 `token_limit`, `import_busy`, `import_state`; 413 `import_too_large`; 422 `ics_invalid`; 503 `private_feeds_unavailable`. Import failure codes (on the row): `ics_encoding`, `ics_invalid`, `too_many_events`, `import_failed`. Item reason codes: `unknown_timezone`, `invalid_times`, `end_before_start`, `duration_too_long`, `unsupported_rule`, `too_many_overrides`, `override_without_master`, `uid_too_long`, `uid_in_trash`, `duplicate_uid`, `changed_since_preview`, `publish_required`, `write_failed`. Notes: `floating_time`, `default_duration`, `shifted_local_time`, `start_adjusted`, `exdate_ignored`, `override_fields_dropped`, `override_dropped`, `category_dropped`, `kept_draft_private`, `untitled`, `uid_generated`, `description_truncated`.
32. **Screens.** The Calendars screen gains a "Subscribe" action per row opening `SubscribeDialog`: for a `public` calendar PR 4's feed URL and `webcal:` link first; for every calendar the caller may view "Create a private link" (label, language), then the link shown once in a read-only field with Copy and the sentence "You will not see this link again. Anyone who has it sees what you can see in this calendar."; then the caller's links (label, language, created, last used, Revoke with a confirm); for `events.manage` a second tab "Everyone's links" (user name by PR 1's naming rule, else "Unknown user"). The Import screen is `/admin/events/import` (`events.manage`; menu entry "Import" after Categories, `order=420`).

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, alembic, Playwright or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. At most one Playwright run at a time, and stop its server when done. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr5` on branch `feat/events-pr5-feeds`, stacked on `feat/events-pr4-public` → `feat/events-pr3-calendar` → `feat/events-pr2-events` → `feat/events-pr1-scaffold`. Before Task 1, rebase onto the finished PR 4 branch and run the "Depends on" check. Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points from the worktree root, and module tests from the module directory: `cd modules/events && uv run pytest …`.
- Implementers are Claude subagents. Each runs pytest in the foreground, commits its own tasks (one commit per task) and never pushes.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- Names: package `sm_events`, npm `@simple-module-py/events`, locale namespace `events`, API prefix `/api/events`, view prefix `/admin/events`, tables `events_feed_token`, `events_import`, `events_import_item`, tasks `events.run_import` and `events.janitor`, queue `events`, page `Events/Import`.
- Version stays what the base has (`uv run python scripts/bump_version.py --check-current`).
- No new Python or npm dependency: `icalendar` comes from PR 4 and `simple_module_background_tasks` from PR 2. Pins stay ranges.
- Settings stay DB-backed with no environment reads; the one new field, `import_max_bytes`, goes in `EventsSettings`, never in `.env.example`.
- Every query on an events table runs with a tenant bound. Core statements carry their own `tenant_id` predicate. `all_tenants()` is used in exactly four places: the token hash lookup (Ruling 8), the `UserDeleted` cleanup (Ruling 14), and the janitor's and the import task's tenant enumeration (Ruling 30). A test greps for it (Task 5).
- Do not edit `sm_events/core/tenancy/*` (parity family, `scripts/tests/parity_tenancy.py`).
- The token, its hash, a file's cell values and a library exception's message never appear in a log line, an error body, a revision note or an import reason. Codes and counts only.
- 300-line cap; keep every `.py`/`.ts`/`.tsx` under 280 lines. The split is fixed in the File structure below.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`); every bound named in the Rulings lives there too.
- Only real Inertia pages go under `sm_events/pages/`: `Import.tsx` in this PR.
- `en.json` and `de.json` keep identical key trees and placeholders (`scripts/check_locales.py`); UI strings go through `t(keys.events.…)`.
- Postgres checks use dev-services' Postgres and scratch databases (`smpy_events_check` for alembic, `smpy_events_test` for pytest). Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **Token disclosure.** The token appears only in the create response: never in the list API, the revoke response, a log record (the request log, the 429 warning, uvicorn's access line, an exception), an error body or the Inertia props. Covered by Task 2 (`test_filter_rewrites_msg_args_and_path_extra`), Task 5 (`test_no_token_in_any_log_record`, which runs a feed fetch, a deny, a 429 and a forced 500 through `RequestLoggingMiddleware` and the rate limiter with `caplog` at DEBUG, then asserts neither the token nor its hash is in any record's `getMessage()` or `__dict__`) and Task 7 (`test_token_shown_once`).
2. **Uniform answers and timing.** Unknown, malformed, revoked, user deactivated, user no longer a member, share removed, `events.view` lost, calendar trashed and wrong host tenant give byte-identical responses (status, body, every header except `Date` and `X-Correlation-ID`), each no faster than the floor. Covered by Task 5 (`test_deny_matrix_byte_identical`, `test_deny_respects_floor`).
3. **Access re-checked on every request.** The same token serves, then stops serving after each change in Ruling 14's table, then (where the table says so) serves again after the change is undone, with no restart and no cache. Covered by Task 4 (`test_resolve_follows_access_changes`) and Task 5 (`test_revocation_matrix_http`).
4. **Hostile ICS input.** A 21 MB body, invalid UTF-8, a 1 MB unfolded line, 10,000 nested `BEGIN:VALARM`, 5,001 VEVENTs, 101 VTIMEZONEs (and one with 50,000 `RDATE`s), a NUL byte, two VCALENDARs, unbalanced `END`, `FREQ=SECONDLY`, `RDATE`, an unknown `TZID` and a `RECURRENCE-ID` storm each fail fast (under 2 s on SQLite) with a code and no value echoed. Covered by Task 9 (`test_hostile_corpus`), Task 11 (`test_mapper_hostile_rules`) and Task 12 (`test_upload_too_large_streams`).
5. **Import idempotency and retries.** Applying the same file twice gives `unchanged` for every item the second time with no new revision; a crash mid-batch redoes only that batch; an edit between preview and apply gives `changed_since_preview`; the golden round trip (PR 4 export → import into another calendar) reproduces times, rules, overrides, titles and status. Covered by Task 13 (`test_reimport_unchanged`, `test_stale_since_preview`) and Task 14 (`test_crash_mid_batch_resumes`, `test_golden_round_trip`).
6. **Tenant binding in the worker and the feed.** The task body never runs unbound or in the caller's tenant: a slice for tenant `b` writes only `b`'s rows even when called with `a` bound; a token of tenant `b` served on the apex binds `b`, is refused on `a`'s subdomain, and a visitor's session tenant `a` does not change it. Covered by Task 5 (`test_cross_tenant_token`) and Task 14 (`test_slice_binds_import_tenant`).

---

## File structure

| File | Responsibility | Target lines |
|---|---|---|
| `models/feed_token.py` | `FeedToken` (Ruling 2) | 40 |
| `models/imports.py` | `EventImport`, `EventImportItem` | 110 |
| `core/access/offline.py` | `OfflineUser`, `feed_principal` (Ruling 7) | 140 |
| `feeds/tokens/__init__.py` | docstring: the rules of Rulings 1–16 in brief | 30 |
| `feeds/tokens/codec.py` | `new_token`, `hash_token`, `well_formed` | 50 |
| `feeds/tokens/service.py` | create, list, revoke, limits | 200 |
| `feeds/tokens/resolve.py` | `lookup`, `resolve` → `FeedAccess | None`, `touch_last_used` | 200 |
| `feeds/tokens/throttle.py` | per-token in-process window | 80 |
| `feeds/tokens/log_redact.py` | the log filter and `install` | 80 |
| `feeds/tokens/cleanup.py` | bus handlers, revoked sweep | 130 |
| `web/endpoints/public/_host_tenant.py` | events' copy of `host_tenant` | 30 |
| `web/endpoints/public/_private_feed.py` | the route, `_deny`, the floor | 200 |
| `web/endpoints/feed_tokens_api.py` | token API | 170 |
| `web/schemas/feed_tokens.py` | `TokenCreate`, `TokenOut`, `TokenCreated` | 80 |
| `feeds/importing/__init__.py` | docstring: Rulings 17–30 in brief | 30 |
| `feeds/importing/scan.py` | the pre-scan (Ruling 20) | 220 |
| `feeds/importing/values.py` | date-time, TZID, duration reading (Ruling 22) | 230 |
| `feeds/importing/text.py` | title cleanup, plain text → paragraphs | 90 |
| `feeds/importing/mapper.py` | VEVENT group → `MappedEvent` (fields, UID, dropped) | 240 |
| `feeds/importing/mapper_series.py` | rule, start adjustment, EXDATE, RECURRENCE-ID (Rulings 23–24) | 230 |
| `feeds/importing/staging.py` | upload row, parse step, verdicts, counts | 240 |
| `feeds/importing/fence.py` | claim and fenced writes (newsletter's copy) | 100 |
| `feeds/importing/write.py` | create/update/unchanged for one item | 250 |
| `feeds/importing/apply.py` | one batch with savepoints | 150 |
| `feeds/importing/runner.py` | slices: parse or apply | 230 |
| `feeds/importing/launch.py` | eager inline / enqueue | 60 |
| `feeds/importing/janitor.py` | imports and revoked tokens (Ruling 30) | 170 |
| `web/endpoints/imports_api.py` | import API | 240 |
| `web/schemas/imports.py` | `ImportOut`, `ImportItemOut`, `ImportItemPage`, `ApplyIn` | 110 |
| `pages/Import.tsx` | the Import screen | ≤ 200 |
| `ui/components/feeds/SubscribeDialog.tsx`, `CreateLinkForm.tsx`, `CreatedLink.tsx`, `TokenList.tsx` | Subscribe dialog | ≤ 200 each |
| `ui/components/import/UploadForm.tsx`, `ImportProgress.tsx`, `PreviewTable.tsx`, `ImportResult.tsx` | Import screen parts | ≤ 200 each |
| `ui/hooks/useFeedTokens.ts`, `ui/hooks/useImport.ts`, `ui/utils/api-feeds.ts`, `ui/utils/api-import.ts` | client and state | ≤ 150 each |

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events suite green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: token table, service, feed route** | 1–6 | constants, errors, setting, the three tables and their migration; codec and log filter; the offline principal; token service and resolver; the private feed route with uniform answers, floor, limits and the leak tests; revocation cleanup |
| **B: token console** | 7–8 | the token API; the Subscribe dialog on the Calendars screen |
| **C: import** | 9–15 | pre-scan; value reading; the mapper; upload and parse staging; the item writer; runner, batches, launch, tasks and janitor with the golden round trip; the import API |
| **D: import screen, e2e, docs** | 16–18 | the Import screen and menu; `events-feeds.spec.ts`; docs, CLAUDE.md, CHANGELOG and branch verification |

---

### Task 1: Constants, errors, the setting, the tables and their migration

**Files:**
- Modify: `sm_events/core/constants.py` (every bound, code and detail of Rulings 1–31; `_PAGE_IMPORT = f"{MODULE_NAME}/Import"`, `IMPORT_URL = f"{VIEW_PREFIX}/import"`, `MENU_LABEL_IMPORT = "Import"`, `MENU_LABEL_KEY_IMPORT = "events.menu.import"`, `MENU_ICON_IMPORT = "upload"`, `TOKEN_PREFIX = "evf_"`, `TOKEN_PATTERN`, `FEED_PATH_SEGMENT = "feed"`, `IMPORT_STATES`, `ITEM_VERDICTS = ("new", "update", "skip")`, `ITEM_OUTCOMES = ("created", "updated", "unchanged", "skipped", "failed")`)
- Modify: `sm_events/core/errors.py` (`TokenLimit(Conflict)`, `ImportBusy(Conflict)`, `ImportState(Conflict)`, `ImportTooLarge` (413), `IcsInvalid(Invalid)`, `PrivateFeedsUnavailable(ServiceUnavailable)`; plus `ImportFailure(Exception)` carrying a failure `code` only, not an HTTP error)
- Modify: `sm_events/core/settings/__init__.py` (`import_max_bytes: int = 5 * 1024 * 1024`, docstring naming the clamp)
- Create: `sm_events/models/feed_token.py`, `sm_events/models/imports.py`; export from `models/__init__.py`
- Create: `host/migrations/versions/<rev>_events_feed_tokens_and_imports.py`
- Test: `tests/core/test_errors.py`, `tests/core/test_settings.py`, `tests/models/test_models.py`

**Interfaces:**
- `FeedToken` (Ruling 2). `EventImport` (`events_import`, `{"sqlite_autoincrement": True}` as newsletter's, index `(tenant_id, created_at)` and `(status, lease_until)`): `id` big PK, `calendar_id` (FK `ON DELETE CASCADE`), `created_by` (str 64), `status`, `filename` (str 200), `size_bytes`, `source: bytes | None` (`LargeBinary`), `publish: bool`, `may_publish: bool` (the applier's `events.publish` at apply time), `total`, `counts: dict`, `reasons: dict`, `dropped: dict`, `created`, `updated`, `unchanged`, `skipped`, `failed`, `processed`, `error_code`, `lease_owner`, `lease_until`, `created_at`, `updated_at`, `finished_at`. `EventImportItem` (`events_import_item`, unique `(import_id, seq)`, index `(tenant_id, import_id, outcome)`): `id` big PK, `import_id` (FK `events_import.id` `ON DELETE CASCADE`), `seq`, `uid` (str 255), `verdict`, `reason` (str 40, nullable), `notes: list[str]`, `title` (str 300), `starts_at`, `all_day`, `recurring`, `existing_event_id` (UUID, nullable, no FK), `expected_revision` (nullable), `payload: dict` (the `MappedEvent` as JSON), `outcome`, `outcome_code`, `event_id` (nullable).

- [ ] **Step 1: Write the failing tests:**
  - `test_errors.py::test_pr5_codes`: parametrized `(cls, status, code)` over the six new HTTP classes; each body is exactly `{"detail","code"}`.
  - `test_settings.py::test_import_max_bytes`: default `5242880`, no `requires_restart`.
  - `test_models.py::test_feed_token_hash_unique_across_tenants` (`unbound_tenant`): two rows with one hash in tenants `a` and `b` raise `IntegrityError`.
  - `test_models.py::test_import_cascade`: deleting an `EventImport` deletes its items; deleting the calendar deletes its imports and tokens.
  - `test_models.py::test_import_source_binary`: a 1 MiB `bytes` round-trips.
- [ ] **Step 2: Run** `~/.claude/bin/wait-for-headroom`, then `cd modules/events && uv run pytest -q tests/core/test_errors.py tests/core/test_settings.py tests/models`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the constants, errors, setting and models.
- [ ] **Step 4: Migration.** `uv run python scripts/check_migration_heads.py` from the root; chain off the single head it prints (stop and report on two). Autogenerate against a scratch SQLite file exactly as PR 2 Task 7 Step 3 does (`SM_DATABASE_URL=sqlite+aiosqlite:////tmp/events-mig5.db`, `upgrade heads`, `make migration msg="events feed tokens and imports"`). The revision creates only the three tables and their indexes; give it a docstring. Run `upgrade`, `check`, `downgrade -1`, `upgrade`, `check`, delete the file; then the same on Postgres `smpy_events_check` (downgrade to the named parent) and drop the database.
- [ ] **Step 5: Run** Step 2's tests (PASS), `check_migration_heads.py` (one head, the new revision) and `uv run python scripts/check_hardcoded_strings.py` (PASS).
- [ ] **Step 6: Commit** `feat(events): feed token and import tables`.

### Task 2: The token codec and the log filter

**Files:**
- Create: `sm_events/feeds/tokens/__init__.py`, `feeds/tokens/codec.py`, `feeds/tokens/log_redact.py`
- Modify: `sm_events/module.py` (`on_startup` calls `log_redact.install()` first)
- Test: `tests/feeds/tokens/__init__.py`, `tests/feeds/tokens/test_codec.py`, `tests/feeds/tokens/test_log_redact.py`

**Interfaces:**

```python
def new_token() -> str                       # TOKEN_PREFIX + urlsafe_b64encode(token_bytes(32)).rstrip(b"=")
def hash_token(token: str) -> str            # sha256 hex of token.encode("utf-8")
def well_formed(token: str) -> bool          # re.fullmatch(TOKEN_PATTERN)
# log_redact.py
LOGGERS: Final[tuple[str, ...]]              # "simple_module.request", "uvicorn.access", the rate limiter's logger name
def redact(text: str) -> str                 # (/feed/)[^/?#\s"']+ -> \1<redacted>
class Filter(logging.Filter)                 # msg, args (tuple or dict), and record.path
def install() -> None                        # idempotent
```

- [ ] **Step 1: Write the failing tests:**
  - `test_codec.py::test_shape_and_entropy`: 1,000 tokens are distinct, each matches `TOKEN_PATTERN`, is 47 characters and decodes to 32 bytes.
  - `test_codec.py::test_hash_is_sha256_hex`: `hash_token("evf_x") == hashlib.sha256(b"evf_x").hexdigest()`.
  - `test_codec.py::test_well_formed`: rejects `""`, the token plus one character, a `+` or `/` inside, a missing prefix and 10,000 characters.
  - `test_log_redact.py::test_filter_rewrites_msg_args_and_path_extra`: a record with `msg="%s %s"`, `args=("GET", "/events/feed/evf_abc.ics")` and `extra={"path": "/de/events/feed/evf_abc.ics?x=1"}` comes out with `<redacted>` in all three and `?x=1` gone with the token segment only; `/events/feedback` is untouched.
  - `test_log_redact.py::test_install_idempotent_on_each_logger`.
  - `test_log_redact.py::test_rate_limit_logger_name_exists`: the name in `LOGGERS` equals `simple_module_hosting._rate_limit.logger.name`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/tokens`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): feed token codec and log redaction`.

### Task 3: The offline principal

**Files:**
- Create: `sm_events/core/access/offline.py`
- Modify: `tests/support/app.py` (the fake `Directory` returns `roles` when `with_roles=True`; `build_app` installs a permissions registry with a role map `{"viewer": ["events.view"], "manager": ["events.view", "events.manage"]}` and an optional grant source; a fake `tenant_members` store)
- Test: `tests/core/access/test_offline.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class OfflineUser:            # duck-typed like UserContext for resolve_principal_permissions
    id: str; roles: tuple[str, ...]; tenant_id: str
    permissions: tuple[str, ...] = (); scopes: None = None; required_permission: None = None
async def feed_principal(app, db, *, user_id: str, tenant_id: str,
                         request: Request) -> ResourcePrincipal | None
    # Ruling 7; None on unknown/inactive/roles None/not a member/no membership store on multi
```

- [ ] **Step 0: Look upstream first.** `grep -rn "def principal_for\|def permissions_for_user\|def member_role\|role_of" $(uv run python -c "import simple_module_core,tenants,os;print(os.path.dirname(simple_module_core.__file__), os.path.dirname(tenants.__file__))")`. If an offline resolver exists, wrap it and note it in the commit. If a membership-role read exists in `tenants.contracts` or `simple_module_core.tenancy`, add `tenant:<role>` to `roles`. Otherwise keep the stopgap of Ruling 7 and write the gap down for open point 1.
- [ ] **Step 1: Write the failing tests:**
  - `test_role_permissions`: a known, active `viewer` resolves to a principal holding `events.view` only; a `manager` also holds `events.manage`.
  - `test_grant_source_counts`: a grant source adding `events.publish` for that user is reflected.
  - `test_fail_closed`: parametrized: unknown id, `is_active=False`, `roles=None`, multi mode with the user absent from `tenant_members`, multi mode with no membership store: each gives `None`.
  - `test_single_tenant_skips_membership`.
  - `test_wildcard_role`: a role mapped to `*` resolves to a principal that passes `who.has("events.manage")`.
- [ ] **Step 2: Run** `uv run pytest -q tests/core/access/test_offline.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it, and the PR 1 suites that use the harness (`tests/web/test_calendars_api.py tests/web/test_shares_api.py`): PASS.
- [ ] **Step 5: Commit** `feat(events): resolve a token owner's principal without a session`.

### Task 4: Token service and resolver

**Files:**
- Create: `sm_events/feeds/tokens/service.py`, `feeds/tokens/resolve.py`
- Modify: PR 4's `sm_events/feeds/select.py`: `feed_events(..., events: Select | None = None)`, defaulting to `public_events()`, so a caller can pass its own visible-events select (PR 4's tests unchanged)
- Test: `tests/feeds/tokens/test_service.py`, `tests/feeds/tokens/test_resolve.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Created:
    token: FeedToken; secret: str             # secret returned once, never stored
async def create_token(db, request, who: ResourcePrincipal, calendar_id: uuid.UUID, *,
                       label: str, locale: str | None, now: datetime) -> Created
    # NotFound (calendar invisible), TokenLimit, PrivateFeedsUnavailable (Ruling 4); never commits
async def list_tokens(db, who, calendar_id, *, everyone: bool) -> list[FeedToken]   # everyone needs manage, else Forbidden
async def revoke_token(db, who, token_id: uuid.UUID, *, now: datetime) -> None      # NotFound unless own or manage
# resolve.py
@dataclass(frozen=True)
class TokenRow:
    id: uuid.UUID; tenant_id: str; calendar_id: uuid.UUID; user_id: str; locale: str; revoked: bool
async def lookup(db, token: str) -> TokenRow | None            # the one all_tenants() read (Ruling 8)
@dataclass(frozen=True)
class FeedAccess:
    row: TokenRow; who: ResourcePrincipal; calendar: Calendar
async def resolve(app, db, request, row: TokenRow | None, *, host_tenant: str | None) -> FeedAccess | None
    # under tenant_scope(row.tenant_id) by the caller; Ruling 6's checks, every one evaluated in order
async def touch_last_used(factory, row: TokenRow, *, now: datetime) -> None   # Ruling 13
```

- [ ] **Step 1: Write the failing tests:**
  - `test_service.py`:
    - `test_create_returns_secret_once`: the returned `secret` hashes to the stored `token_hash`; no column equals the secret.
    - `test_create_needs_view`: `V` on `P` (private, not shared) gets `NotFound`; `SV` on `P` succeeds; `A` gets `NotFound`.
    - `test_limit_five_active`: the sixth gives `TokenLimit`; after one revoke a new one succeeds.
    - `test_label_and_locale`: a label with a newline is refused by the schema (Task 7); an unknown locale gives `UnknownLocale`; absent locale picks the default.
    - `test_unavailable_without_roles`: a directory returning `roles=None` gives `PrivateFeedsUnavailable`.
    - `test_list_own_vs_everyone`: `SV` lists only their own; `everyone=True` for `SV` raises `Forbidden`; `M` sees all.
    - `test_revoke_rules`: own revoke works; another user's token is `NotFound` for `SE` and revocable by `M`; a second revoke is a no-op.
  - `test_resolve.py` (calendar `P` shared with `SV`, one published and one draft event):
    - `test_lookup_is_tenant_free` (`unbound_tenant`): `lookup` finds tenant `b`'s row with nothing bound and issues exactly one statement (an `after_cursor_execute` counter).
    - `test_resolve_follows_access_changes`: one token of `SV`; `resolve` gives access; then, each followed by the reverse change where Ruling 14 says it revives: revoke (no revival), remove the share, make the directory report `is_active=False`, drop `events.view` from the role map, trash the calendar, remove the membership (multi): each gives `None`, and the revivable ones give access again.
    - `test_host_tenant_mismatch`: `host_tenant="a"` for a `b` row gives `None`; `None` and `"b"` give access.
    - `test_feed_is_published_only`: the access's feed (`feed_events(events=visible_events(who, include_unpublished=False).where(calendar))`) holds the published UID, not the draft, for an owner with `events.edit`.
    - `test_touch_coarse`: two touches within an hour write once; a touch after an hour writes again; a database error inside `touch_last_used` is swallowed and logged by class.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/tokens/test_service.py tests/feeds/tokens/test_resolve.py`: FAIL.
- [ ] **Step 3: Implement.** `resolve` computes every check into a list of booleans and returns `None` if any is false, rather than returning at the first failure; this keeps the order of statements the same for every refusal that has a row.
- [ ] **Step 4: Run** it on SQLite and Postgres, plus PR 4's `tests/feeds/test_select.py`: PASS.
- [ ] **Step 5: Commit** `feat(events): private feed tokens and their access check`.

### Task 5: The private feed route

**Files:**
- Create: `sm_events/feeds/tokens/throttle.py`, `web/endpoints/public/_host_tenant.py`, `web/endpoints/public/_private_feed.py`
- Modify: `web/endpoints/public/__init__.py` (include the private feed router on the default-locale router before `/{slug}.ics`), `core/boot.py` (the `FEED_PRIVATE_RATE` rule), `scripts/tests/test_helper_parity.py`/its families (events' `host_tenant` joins newsletter's family if one exists)
- Modify: `host/tests/test_events_wiring.py` (the path)
- Test: `tests/web/public/test_private_feed.py`, `tests/web/public/test_private_feed_leaks.py`, `tests/web/public/test_private_feed_logs.py`

**Interfaces:**

```python
# throttle.py
class TokenThrottle:
    def __init__(self, *, limit: int, window: float, max_keys: int, clock=time.monotonic) -> None
    def hit(self, presented: str) -> float | None          # None if allowed, else retry-after seconds
# _private_feed.py
router: APIRouter                                          # GET|HEAD /feed/{token}.ics
def deny() -> Response                                     # Ruling 9's exact response
async def private_feed(request, token: str) -> Response    # Rulings 8-16
```

- [ ] **Step 1: Write the failing tests:**
  - `test_private_feed.py`:
    - `test_serves_calendar`: `200`, `text/calendar; charset=utf-8`, `Cache-Control: private, no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`, no `ETag`, no `Set-Cookie`; the body parses with `icalendar`, holds the published event's UID and not the draft's, `X-WR-CALNAME` is the calendar's name.
    - `test_head_matches_get_headers`.
    - `test_locale_from_row`: a `de` token gives the `de` `SUMMARY`.
    - `test_url_property`: a public calendar's event `URL` is the public event URL; an internal calendar's is the absolute console URL.
    - `test_anonymous_and_signed_in_same_body`: with a session cookie of `M` the body equals the anonymous request's.
    - `test_no_csrf_no_session_needed`.
    - `test_ip_rate_limit`: the 31st request in a minute from one IP gets `429`; the registry match for `/events/feed/x.ics` is the `FEED_PRIVATE_RATE` rule.
    - `test_token_throttle_uniform`: 21 requests with a valid token and 21 with an invented well-formed one both end in `429` with `no-store` and `Retry-After`; the throttle is checked before `lookup` (monkeypatch `lookup` to count calls).
    - `test_internal_error_is_503_without_token`: `resolve` monkeypatched to raise: `503`, `no-store`, fixed body.
    - `test_last_used_touched_after_success_only`.
  - `test_private_feed_leaks.py`:
    - `test_deny_matrix_byte_identical`: parametrized over `malformed`, `unknown`, `revoked`, `user_inactive`, `not_member` (multi), `roles_unknown`, `share_removed`, `view_lost`, `calendar_trashed`, `wrong_host_tenant` (a `subdomain` source for tenant `a`, token of `b`): status, body bytes and the header dict minus `date` and `x-correlation-id` equal `unknown`'s.
    - `test_deny_respects_floor`: with `FEED_DENY_FLOOR_SECONDS` monkeypatched to `0.05`, every case of the matrix takes at least 0.05 s (`time.perf_counter` around the request); a success is not padded (under 0.05 s with a stubbed body builder).
    - `test_cross_tenant_token` (`unbound_tenant`, multi): tenant `b`'s token on the apex serves `b`'s calendar; with a header or session tenant `a` it still serves `b`'s; on `a`'s subdomain it is the deny.
    - `test_feed_is_not_under_public_tenant`: the route's dependencies include neither PR 4's `public_tenant` nor `bind_public`.
    - `test_all_tenants_call_sites`: a grep over `modules/events/sm_events` finds `all_tenants(` only in `feeds/tokens/resolve.py`, `feeds/tokens/cleanup.py`, `feeds/importing/janitor.py`, `feeds/importing/runner.py` (if it enumerates) and PR 2's `content/publish_due.py`; update the list here if PR 2 differs.
  - `test_private_feed_logs.py::test_no_token_in_any_log_record`: an app with `RequestLoggingMiddleware` and the rate limiter, `caplog.set_level(DEBUG)`, `log_redact.install()`; run a success, a deny, a `429` and the `503`; neither the token nor its hash occurs in any record's `getMessage()` or in `str(record.__dict__)`.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/public/test_private_feed.py tests/web/public/test_private_feed_leaks.py tests/web/public/test_private_feed_logs.py`, then from the root `uv run pytest -q host/tests/test_events_wiring.py`: FAIL.
- [ ] **Step 3: Implement.** The handler records `started = time.perf_counter()`; computes `allowed`/`access` along one path (throttle → `well_formed` → `lookup` in its own session under `no_tenant()` → `tenant_scope(row.tenant_id)` → `resolve` → build); and every refusal ends in the one `return await _padded(deny(), started)` at the end of the handler; the only other non-success returns are the throttle's `429` (before any lookup) and the `503` of an internal failure. Build the body with PR 4's `feed_events(events=…)` and `build`, close the read session, then `touch_last_used`.
- [ ] **Step 4: Run** the same on SQLite and Postgres: PASS. Then `uv run pytest -q scripts/tests/test_helper_parity.py` from the root: PASS.
- [ ] **Step 5: Commit** `feat(events): the private feed, with one answer for every refusal`.

### Task 6: Revocation cleanup

**Files:**
- Create: `sm_events/feeds/tokens/cleanup.py`
- Modify: `sm_events/module.py` (subscribe the handlers in `on_startup` through the app's event bus: `UserDeleted`, `MembershipRemoved`, `TenantDeleted`; import each event class inside a guarded block and skip one the installed framework lacks, with a log line)
- Test: `tests/feeds/tokens/test_cleanup.py`

**Interfaces:**

```python
async def on_user_deleted(event) -> None          # all_tenants() DELETE ... WHERE user_id = :u (own predicate)
async def on_membership_removed(event) -> None    # tenant_scope(event.tenant_id); DELETE WHERE tenant_id AND user_id
async def on_tenant_deleted(event) -> None        # tenant_scope; DELETE WHERE tenant_id
async def sweep_revoked(db, *, now: datetime) -> int   # revoked_at < now - FEED_REVOKED_KEPT_DAYS, bound tenant; used by Task 14
```

Each handler opens its own session from `app.state.sm.db.session_factory`, finishes with `finalize_session`, and logs a count and the exception class on failure (never re-raises into the bus).

- [ ] **Step 1: Write the failing tests:**
  - `test_user_deleted_removes_everywhere` (`unbound_tenant`): tokens of `u` in tenants `a` and `b` are gone, `v`'s remain.
  - `test_membership_removed_only_that_tenant`.
  - `test_tenant_deleted`.
  - `test_handler_failure_is_swallowed`: a failing session logs `TokenCleanup failed (OperationalError)` and raises nothing.
  - `test_sweep_revoked_keeps_30_days`: revoked 29 days ago stays, 31 days ago goes, unrevoked stays.
  - `test_subscriptions_registered`: after startup the bus has a handler for each of the three classes the framework has.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/tokens/test_cleanup.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): remove feed tokens when their user, membership or tenant goes`.

**End of batch A.** Run `cd modules/events && uv run pytest -q -n 8` (headroom first), `check_file_size.py` (no WARNING under `modules/events`), `check_hardcoded_strings.py`, `check_sibling_contracts.py` and `ruff check modules/events`.

---

### Task 7: The token API

**Files:**
- Create: `sm_events/web/schemas/feed_tokens.py`, `sm_events/web/endpoints/feed_tokens_api.py`
- Modify: `web/endpoints/__init__.py` (include the router under the admin router's `bind_admin` and CSRF)
- Test: `tests/web/test_feed_tokens_api.py`

**Interfaces.** Every route requires `events.view`.

| Method and path | Body / query | Success | Errors |
|---|---|---|---|
| `GET /api/events/calendars/{id}/feed-tokens` | `all` (bool) | 200 `list[TokenOut]` | 403 (`all` without manage), 404 |
| `POST /api/events/calendars/{id}/feed-tokens` | `TokenCreate{label, locale?}` | 201 `TokenCreated` with `no-store` and `Referrer-Policy: no-referrer` | 404, 409 `token_limit`, 422, 503 `private_feeds_unavailable` |
| `DELETE /api/events/feed-tokens/{token_id}` | none | 204 | 404 |

- `TokenOut`: `id`, `label`, `locale`, `created_at`, `last_used_at`, `user_id`, `user_name` (PR 1's owner-naming rule: a name only for an active member of the bound tenant with a display name, else `null`), `mine: bool`. Never the token or its hash.
- `TokenCreated`: `TokenOut` plus `url` (the absolute `{public_base}{prefix}/feed/{token}.ics`) and `webcal_url` (`webcal://` + the same without scheme). PR 4's `_urls.absolute` builds it.

- [ ] **Step 1: Write the failing tests:**
  - `test_token_shown_once`: the create body has `url` containing the token; the list body and the `DELETE` response contain neither the token nor its hash (searched as substrings of the raw bytes).
  - `test_create_headers`: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`.
  - `test_invisible_calendar_404_everywhere`.
  - `test_all_needs_manage`.
  - `test_user_name_rule`: an address-only label gives `null`.
  - `test_error_envelopes`: `token_limit`, `private_feeds_unavailable` and a 422 label are `{"detail","code"}` (the 422 keeps FastAPI's list shape).
  - `test_writes_need_csrf`.
  - `test_tenant_isolation` (`unbound_tenant`, multi): another tenant's token id is 404 for `DELETE`; another tenant's calendar id is 404.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_feed_tokens_api.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): API for private feed links`.

### Task 8: The Subscribe dialog

**Files:**
- Create: `ui/utils/api-feeds.ts`, `ui/hooks/useFeedTokens.ts`, `ui/components/feeds/SubscribeDialog.tsx`, `ui/components/feeds/CreateLinkForm.tsx`, `ui/components/feeds/CreatedLink.tsx`, `ui/components/feeds/TokenList.tsx`
- Modify: `ui/components/calendars/CalendarRow.tsx` (a "Subscribe" action; if the file passes 250 lines, move the action menu into `ui/components/calendars/RowActions.tsx`), `pages/Calendars.tsx` (props: `content_locales`, `can_manage`; their server side in `web/endpoints/views.py`), `ui/utils/api.ts` (`errorText` for the new codes), `locales/en.json`/`de.json` (`feeds.*`, `errors.*`)
- Test: `ui/page-tests/SubscribeDialog.test.tsx`, `ui/page-tests/useFeedTokens.test.tsx`

**Interfaces:** `listTokens(calendarId, all)`, `createToken(calendarId, {label, locale})`, `revokeToken(id)`, all through `ApiError`. Ruling 32 fixes the dialog's content. The created link lives only in component state and is cleared when the dialog closes; it is never written to the URL, `localStorage` or a toast. Copy uses `navigator.clipboard.writeText` with a selectable read-only input as the fallback.

- [ ] **Step 1: Write the failing tests:**
  - `public calendar shows the public feed first` (PR 4's URL and `webcal:` link).
  - `private calendar shows only the private link section`.
  - `create shows the link once`: after create the URL and the "You will not see this link again" sentence are shown; after closing and reopening, the list shows the label and no URL.
  - `copy writes the url` (clipboard spy).
  - `revoke asks then removes`.
  - `token_limit shows its message`.
  - `everyone tab only for managers`, with "Unknown user" for `user_name: null`.
  - `useFeedTokens.test.tsx`: `create does not cache the secret in the list state`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/SubscribeDialog.test.tsx modules/events/sm_events/ui/page-tests/useFeedTokens.test.tsx`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, `npx tsc --noEmit -p modules/events/tsconfig.json`, `npx biome check modules/events`, `check_locales.py` and the PR 1 Calendars page tests: PASS.
- [ ] **Step 5: Commit** `feat(events): Subscribe dialog with private links`.

**End of batch B.** Run the module suite (`-n 8`), `npx vitest run modules/events`, tsc, biome, `check_file_size.py`.

---

### Task 9: The pre-scan

**Files:**
- Create: `sm_events/feeds/importing/__init__.py`, `feeds/importing/scan.py`
- Create: `tests/feeds/importing/__init__.py`, `tests/feeds/importing/corpus.py` (functions that build each hostile file as bytes; no binary fixtures committed)
- Test: `tests/feeds/importing/test_scan.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Scanned:
    text: str                       # decoded, BOM stripped, line ends normalised (folding kept for icalendar)
    events: int; components: int; timezones: int
def scan(data: bytes) -> Scanned    # raises ImportFailure(code="ics_encoding" | "ics_invalid" | "too_many_events")
def sniff(head: bytes) -> bool      # first non-blank line is BEGIN:VCALENDAR (the upload's quick check)
```

- [ ] **Step 1: Write the failing tests:**
  - `test_accepts_simple_file`, `test_bom_and_line_ends` (CRLF, LF, CR).
  - `test_hostile_corpus`: parametrized `(builder, code)`: invalid UTF-8 → `ics_encoding`; a NUL byte, a 1 MB unfolded line, 10,000 nested `BEGIN:VALARM`, depth 4, two VCALENDARs, unbalanced `END`, mismatched `END:VTODO`, content before `BEGIN:VCALENDAR`, 501 properties in one VEVENT, a 300 KB VEVENT, 101 VTIMEZONEs, 20,001 components → `ics_invalid`; 5,001 VEVENTs → `too_many_events`. Each finishes in under 2 s (`time.monotonic`), and `str(exc)` contains no byte of the file's content beyond the code.
  - `test_folded_lines_measured_unfolded`: a 70,000-byte DESCRIPTION folded at 75 octets fails; a 60,000-byte one passes.
  - `test_sniff`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/importing/test_scan.py`: FAIL.
- [ ] **Step 3: Implement** a single pass over lines with a depth stack and counters; never build the components here.
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): bounded pre-scan of uploaded calendars`.

### Task 10: Reading dates, times and zones

**Files:**
- Create: `sm_events/feeds/importing/values.py`
- Test: `tests/feeds/importing/test_values.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class When:
    all_day: bool; timezone: str; start: str; end: str      # PR 2's local wall-clock strings
    notes: tuple[str, ...]
def resolve_tzid(tzid: str | None) -> str | None             # Ruling 22: IANA, Windows, tzone://; None = unknown
def read_when(vevent: icalendar.Event, *, calendar_tz: str) -> When        # ItemSkip(code) on refusal
def read_instant(prop, *, tz: str, all_day: bool) -> datetime | date      # RECURRENCE-ID / EXDATE values, from raw text
class ItemSkip(Exception): code: str
```

- [ ] **Step 0: Library probe.** In a test, print `icalendar.__version__` and look for its Windows-zone mapping (`grep -rn "WINDOWS_TO_OLSON\|windows" $(python -c "import icalendar,os;print(os.path.dirname(icalendar.__file__))")`). Record the name in the module docstring. If there is none, Windows names are unknown zones (open point 5).
- [ ] **Step 1: Write the failing tests:**
  - `test_tzid_vienna`: `DTSTART;TZID=Europe/Vienna:20260316T100000` / `DTEND…T113000` gives `When(False, "Europe/Vienna", "2026-03-16T10:00", "2026-03-16T11:30")`.
  - `test_windows_and_tzone`: `W. Europe Standard Time` and `tzone://Microsoft/W. Europe Standard Time` give `Europe/Berlin` (or the mapping's value).
  - `test_unknown_tzid_skips`: `TZID=My Custom Zone` with a VTIMEZONE in the file raises `ItemSkip("unknown_timezone")`, and the VTIMEZONE is never evaluated (monkeypatch `icalendar.Timezone.to_tz` to fail).
  - `test_utc_goes_to_calendar_zone`: `20260701T080000Z` with calendar zone `Europe/Vienna` gives `10:00` local in Vienna.
  - `test_floating_noted`.
  - `test_all_day_exclusive_end`: `DTSTART;VALUE=DATE:20260329` / `DTEND;VALUE=DATE:20260331` gives `start="2026-03-29"`, `end="2026-03-30"`.
  - `test_duration`: `PT90M`; `P2D` on a date; `PT1H` on a date → `invalid_times`; `-PT1H` → `invalid_times`.
  - `test_no_end`: a date gives one day; a time gives one hour plus `default_duration`.
  - `test_mixed_kinds_skip`.
  - `test_gap_shifted`: `TZID=Europe/Vienna:20260329T023000` gives `03:30` and `shifted_local_time`.
  - `test_instant_list`: an `EXDATE` with three comma-separated values gives three instants.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/importing/test_values.py`: FAIL.
- [ ] **Step 3: Implement.** Read each property's `to_ical()` text and its `TZID`/`VALUE` parameters; parse `YYYYMMDD[THHMMSS[Z]]` yourself.
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): read imported dates, times and zones`.

### Task 11: The mapper

**Files:**
- Create: `sm_events/feeds/importing/text.py`, `feeds/importing/mapper.py`, `feeds/importing/mapper_series.py`
- Test: `tests/feeds/importing/test_text.py`, `tests/feeds/importing/test_mapper.py`, `tests/feeds/importing/test_mapper_series.py`

**Interfaces:**

```python
class MappedOverride(BaseModel):
    original_start: datetime; kind: Literal["skipped", "cancelled", "moved"]; start: str | None; end: str | None
class MappedEvent(BaseModel):                     # what an item's payload holds (JSON)
    uid: str; times: TimesIn; rrule: str | None; cancelled: bool
    attendance_mode: str; venue_name: str | None; online_url: str | None
    latitude: float | None; longitude: float | None; category_id: uuid.UUID | None
    title: str; description: str                  # cleaned HTML
    private_class: bool; overrides: list[MappedOverride]
@dataclass(frozen=True)
class Mapped:
    items: list[tuple[MappedEvent | None, str | None, tuple[str, ...]]]   # (event, skip code, notes) in file order
    dropped: Counter[str]
def map_calendar(cal: icalendar.Calendar, *, calendar_tz: str, categories: Mapping[str, uuid.UUID]) -> Mapped
    # groups by UID (masters, RECURRENCE-ID children), applies Rulings 22-26; pure
# text.py
def clean_title(raw: str) -> tuple[str, tuple[str, ...]]
def description_html(plain: str, url: str | None) -> tuple[str, tuple[str, ...]]   # ends in richtext.clean
# mapper_series.py
def map_series(master, children, *, when: When) -> tuple[str | None, When, list[MappedOverride], tuple[str, ...]]
```

- [ ] **Step 1: Write the failing tests:**
  - `test_text.py`: `test_title_cleanup` (control and RTL-override characters gone, 301 characters cut, empty → `"Untitled event"` with `untitled`), `test_paragraphs` (`"a\n\nb\nc"` → `<p>a</p><p>b<br>c</p>`), `test_html_in_plain_is_escaped` (`<script>` text comes out as `&lt;script&gt;`), `test_url_appended_http_only` (`javascript:` URL is dropped), `test_description_truncated`.
  - `test_mapper.py`:
    - `test_fields`: LOCATION, GEO (and one out of range dropped), `STATUS:CANCELLED`, a URL-only LOCATION giving `online_url` and `online`.
    - `test_categories_matched_case_insensitively_never_created`.
    - `test_class_private_kept_draft`.
    - `test_dropped_counted`: ATTENDEE ×3, ORGANIZER, VALARM, ATTACH and `X-FOO` give those counts in `dropped`.
    - `test_uid_rules`: verbatim; 256 characters → `uid_too_long`; missing → the deterministic UID, the same on a second parse, with `uid_generated`; duplicate masters → higher `SEQUENCE` wins and the other is `duplicate_uid`.
    - `test_mapper_hostile_rules`: parametrized `FREQ=SECONDLY`, `BYHOUR=1`, `COUNT=731`, two RRULEs, an `RDATE`, an `EXRULE`: each item is skipped `unsupported_rule` in under 1 s.
  - `test_mapper_series.py`:
    - `test_exdate_to_skipped` and `test_exdate_not_an_occurrence_ignored`.
    - `test_recurrence_id_moved_and_cancelled`.
    - `test_override_fields_dropped_noted`.
    - `test_thisandfuture_dropped`.
    - `test_override_without_master`.
    - `test_too_many_overrides`: 731 children skip the event.
    - `test_start_adjusted`: `DTSTART` on a Tuesday with `FREQ=WEEKLY;BYDAY=MO;COUNT=5` gives the next Monday and `COUNT=4`, noted `start_adjusted`; `COUNT=1` gives a one-off on that Monday; a rule with no later instance is `unsupported_rule`.
    - `test_all_day_series_values_are_dates`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/importing/test_text.py tests/feeds/importing/test_mapper.py tests/feeds/importing/test_mapper_series.py`: FAIL.
- [ ] **Step 3: Implement.** Validate every series through PR 2's `rrule.parse` and `validate` (catching `InvalidRule` by code), and every span through `times.to_span`; never call dateutil on raw file text.
- [ ] **Step 4: Run** it: PASS.
- [ ] **Step 5: Commit** `feat(events): map imported VEVENTs onto events and overrides`.

### Task 12: Upload and the parse step

**Files:**
- Create: `sm_events/feeds/importing/fence.py` (a copy of `modules/newsletter/sm_newsletter/imports/fence.py` over `EventImport`, with `parsing` claimable from `uploaded` as `running` is from `queued`), `feeds/importing/staging.py`
- Modify: `sm_events/module.py` (`register_body_limits`: `^{ROUTE_PREFIX_API}/imports/?$`, `IMPORT_BODY_CEILING + 1 MiB`, `POST`)
- Test: `tests/feeds/importing/test_staging.py`, `tests/feeds/importing/test_fence.py`

**Interfaces:**

```python
def effective_max_bytes(settings) -> int                       # clamp (Ruling 19)
async def read_upload(file: UploadFile, *, limit: int) -> bytes   # chunks; ImportTooLarge past limit; IcsInvalid on a failed sniff
async def create_import(db, who, *, calendar_id, filename: str, data: bytes, now) -> EventImport
    # NotFound / Forbidden (Ruling 17), ImportBusy; status "uploaded"; filename basename, control chars stripped, <= 200
async def parse_step(db, imp: EventImport, *, owner: str, now) -> None
    # fenced; scan -> from_ical -> map_calendar -> verdicts (one query for the calendar's UIDs, trash included)
    # -> items in chunks of 500 -> counts, reasons, dropped -> source = None -> "staged"; ImportFailure -> "failed"
```

- [ ] **Step 1: Write the failing tests:**
  - `test_upload_too_large_streams`: a 21 MB stream with the limit at 5 MiB stops reading after 5 MiB + one chunk and raises `ImportTooLarge`.
  - `test_clamp`: `import_max_bytes` of 1 and of 10⁹ clamp to 64 KiB and 20 MiB.
  - `test_sniff_on_upload`: a PNG gives `IcsInvalid`.
  - `test_create_needs_manage_and_calendar`: `E` without manage gets `Forbidden`; `M` on a trashed calendar gets `NotFound`.
  - `test_busy`: the sixth unfinished import gives `ImportBusy`.
  - `test_parse_verdicts`: a file with UIDs `new@x`, `old@x` (live in the calendar, revision 3), `gone@x` (trashed there), `other@x` (only in another calendar) and one `FREQ=SECONDLY` gives `new`, `update` with `expected_revision == 3`, `skip uid_in_trash`, `new`, `skip unsupported_rule`; counts and reasons match; `source is None`; status `staged`.
  - `test_parse_failure_records_code`: invalid UTF-8 gives status `failed`, `error_code == "ics_encoding"`, no items, `source is None`.
  - `test_parse_is_all_or_nothing`: an exception after the first chunk leaves the row `uploaded`/`parsing` with no items.
  - `test_fence.py`: the ported `claim`/`fenced` tests (busy, gone, lease lost).
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/importing/test_staging.py tests/feeds/importing/test_fence.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): stage uploaded calendars for preview`.

### Task 13: Writing one item

**Files:**
- Create: `sm_events/feeds/importing/write.py`
- Modify (only if PR 2 has no seam below its rights check): `content/events_write.py` and `content/overrides.py`, extracting the post-rights bodies into `_create_core(db, data, *, actor, locales, status, published_at)`, `_update_core(db, event, data, *, actor, locales, drop_orphaned)` and `_upsert_override(db, event, override)`, with every PR 2 test unchanged; a moves-only commit of its own before this task's
- Test: `tests/feeds/importing/test_write.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Written:
    outcome: Literal["created", "updated", "unchanged", "skipped"]; code: str | None; event_id: uuid.UUID | None
async def write_item(db, imp: EventImport, item: EventImportItem, *, locales: tuple[str, ...], now) -> Written
    # Ruling 28; no bus attached; revision actor imp.created_by, note f"import #{imp.id}"
def same_as(event: Event, texts, overrides, mapped: MappedEvent) -> bool    # the unchanged test
```

- [ ] **Step 1: Write the failing tests:**
  - `test_new_draft_and_published`: `publish=False` gives a draft; `publish=True` gives `published` with `published_at == now`; a `private_class` item stays a draft; each has revision 1 with the import note and the file's UID.
  - `test_update_file_wins_for_mapped_fields`: times, rule, venue and the default-locale title change; the `de` text, image and category (file names none) stay; status stays `published`.
  - `test_update_replaces_overrides`: the old skipped override not in the file is gone, the file's moved one is present.
  - `test_reimport_unchanged`: writing the same item twice gives `updated` then `unchanged`, and the second adds no revision.
  - `test_stale_since_preview`: the event edited after staging (revision 4, expected 3) gives `skipped`, `changed_since_preview`, nothing written.
  - `test_locked_needs_publish`: a published existing event with `may_publish=False` gives `skipped`, `publish_required`.
  - `test_pr2_validation_becomes_skip`: a mapped span PR 2 refuses gives `skipped` with PR 2's code.
  - `test_no_bus_events`: a recording bus on the app sees nothing after a created, an updated and a cancelled item.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/importing/test_write.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it plus PR 2's `tests/content` on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): write imported events through the normal write path`.

### Task 14: Runner, batches, launch, tasks and the janitor

**Files:**
- Create: `sm_events/feeds/importing/apply.py`, `feeds/importing/runner.py`, `feeds/importing/launch.py`, `feeds/importing/janitor.py`
- Modify: `sm_events/task_config.py` (`RUN_IMPORT = "events.run_import"`, `JANITOR = "events.janitor"`, both routed to `events`; `BEAT_SCHEDULE["events-janitor"] = {"task": JANITOR, "schedule": 3600.0, "options": {"queue": "events", "expires": 3500}}`), `sm_events/tasks.py` (`run_import(tenant_id: str, import_id: int)` that runs one slice and re-enqueues itself on `"more"`; `janitor()`), `Makefile` and `.github/workflows/ci.yml` comment blocks that list events' tasks
- Test: `tests/feeds/importing/test_runner.py`, `tests/feeds/importing/test_janitor.py`, `tests/feeds/importing/test_golden.py`, `tests/core/test_task_discovery.py`

**Interfaces:**

```python
async def apply_batch(db, imp, items: Sequence[EventImportItem], *, owner, locales, now) -> BatchResult   # savepoint per item
SliceResult = Literal["done", "more", "busy", "gone"]
async def run_import_async(factory, *, tenant_id: str, import_id: int, now=None, clock=time.monotonic) -> SliceResult
    # always under tenant_scope(tenant_id); claim -> parse_step (uploaded) or batches (queued/running) -> release or done;
    # re-checks the calendar is live (ImportFailure "import_failed" otherwise); done deletes nothing (Ruling 30 does)
async def launch(app, *, tenant_id: str, import_id: int) -> None    # newsletter's launch.py, eager inline loop
async def janitor_async(factory, *, now) -> dict[str, int]          # Ruling 30 plus cleanup.sweep_revoked per tenant
```

- [ ] **Step 1: Write the failing tests:**
  - `test_runner.py`:
    - `test_parse_then_apply_eager`: under `task_always_eager`, `launch` after upload reaches `staged`; after apply it reaches `done` with `created/updated/unchanged/skipped/failed/processed` matching the items.
    - `test_slices_resume`: with `IMPORT_APPLY_BATCH` patched to 2 and the slice clock patched to expire after one batch, 5 items take 3 slices answering `more`, `more`, `done`.
    - `test_crash_mid_batch_resumes`: `write_item` raises `RuntimeError` on the 3rd item of a batch once: the batch rolls back, the next slice redoes it, and no event exists twice.
    - `test_item_failure_isolated`: an `IntegrityError` inside one item's savepoint gives `failed`, `write_failed`, and its neighbours are written.
    - `test_slice_binds_import_tenant` (`unbound_tenant`): called with tenant `a` bound and `tenant_id="b"`, every written row is `b`'s, and an import id of `a` passed with `tenant_id="b"` answers `gone`.
    - `test_lost_lease_writes_nothing`.
    - `test_calendar_trashed_mid_import_fails`.
    - `test_non_eager_enqueues`: with eager off, `launch` calls `run_import.s(...).apply_async(queue="events")` (spy) and runs nothing inline.
  - `test_janitor.py`: `test_expires_after_ttl` (staged, done and failed older than 24 h deleted with their items; younger kept), `test_relaunches_lost` (`uploaded`/`queued` older than the lease and `parsing`/`running` with an expired lease are relaunched; a live lease is not), `test_sweeps_revoked_tokens`, `test_per_tenant` (`unbound_tenant`), `test_counts_only_in_log`.
  - `test_golden.py::test_golden_round_trip`: build a calendar with PR 4's fixture series (Vienna weekly with moved, cancelled and skipped overrides), an all-day multi-day event, a cancelled one-off and a UTC one-off; export it with PR 4's `feed_events` + `build`; import the bytes into a second, empty calendar and apply as published. For each event: the same UID, `all_day`, `timezone`, `starts_at`/`ends_at`, `rrule`, `cancelled`, `venue_name`, coordinates and title, and the same set of `(original_start, kind, starts_at, ends_at)` overrides; the description contains the original's plain text. Then `test_golden_reimport_is_noop`: importing the same bytes into the second calendar again gives only `unchanged`.
  - `test_task_discovery.py`: the beat entry for `events.janitor` and both task routes.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/importing/test_runner.py tests/feeds/importing/test_janitor.py tests/feeds/importing/test_golden.py tests/core/test_task_discovery.py`: FAIL.
- [ ] **Step 3: Implement.** The task body uses PR 2's `run_platform` and has the worker-runtime guard PR 2's `test_worker.py` pins; port `test_the_task_unbinds_the_callers_tenant` for `run_import`.
- [ ] **Step 4: Run** it on SQLite and Postgres, plus from the root `uv run pytest -q host/tests/test_host_boots.py host/tests/test_events_wiring.py`: PASS.
- [ ] **Step 5: Commit** `feat(events): run imports in leased slices, with a janitor`.

### Task 15: The import API

**Files:**
- Create: `sm_events/web/schemas/imports.py`, `sm_events/web/endpoints/imports_api.py`
- Modify: `web/endpoints/__init__.py`
- Test: `tests/web/test_imports_api.py`

**Interfaces.** Every route requires `events.view` and `events.manage`.

| Method and path | Body / query | Success | Errors |
|---|---|---|---|
| `GET /api/events/imports` | `page` | 200 `{items: list[ImportOut], total}` (newest first) | 422 |
| `POST /api/events/imports` | multipart `calendar_id`, `file` | 202 `ImportOut` | 404, 409 `import_busy`, 413 `import_too_large`, 422 `ics_invalid` |
| `GET /api/events/imports/{id}` | none | 200 `ImportOut` | 404 |
| `GET /api/events/imports/{id}/items` | `verdict`, `outcome`, `page`, `page_size` (≤ 100) | 200 `ImportItemPage` | 404, 422 |
| `POST /api/events/imports/{id}/apply` | `ApplyIn{publish}` | 202 `ImportOut` | 403 `publish_required`, 404, 409 `import_state` |
| `DELETE /api/events/imports/{id}` | none | 204 (staged, failed or done only) | 404, 409 `import_state` |

- `ImportOut`: `id`, `calendar` `{id, name}`, `status`, `filename`, `size_bytes`, `total`, `counts`, `reasons`, `dropped`, the outcome counters, `processed`, `error_code`, `publish`, `created_at`, `finished_at`. `ImportItemOut`: `seq`, `uid`, `verdict`, `reason`, `notes`, `title`, `starts_at`, `all_day`, `recurring`, `outcome`, `outcome_code`, `event_id`. Never `source` or `payload`.
- Apply re-checks the calendar's `write_events` for the caller and records `may_publish = who.has(PERM_PUBLISH)` on the row.

- [ ] **Step 1: Write the failing tests:**
  - `test_upload_preview_apply_eager`: upload a three-event file, poll `GET` until `staged`, list items, apply, poll until `done`, and the events exist in the calendar.
  - `test_publish_needs_permission`.
  - `test_apply_twice_conflicts`.
  - `test_discard`.
  - `test_needs_manage`: `E` gets 403 on every route.
  - `test_no_source_or_payload_in_responses`.
  - `test_error_envelopes`.
  - `test_body_limit_registered`: a 22 MB body is refused before the handler (413 from the framework).
  - `test_writes_need_csrf`.
  - `test_tenant_isolation` (`unbound_tenant`, multi).
- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_imports_api.py`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: PASS.
- [ ] **Step 5: Commit** `feat(events): import API`.

**End of batch C.** Run the module suite (`-n 8`), `basedpyright`, `check_sibling_contracts.py`, `check_file_size.py` (no WARNING under `modules/events`), `check_hardcoded_strings.py`, `ruff check modules/events`.

---

### Task 16: The Import screen and its menu entry

**Files:**
- Create: `pages/Import.tsx`, `ui/components/import/UploadForm.tsx`, `ui/components/import/ImportProgress.tsx`, `ui/components/import/PreviewTable.tsx`, `ui/components/import/ImportResult.tsx`, `ui/hooks/useImport.ts`, `ui/utils/api-import.ts`
- Modify: `web/endpoints/views.py` (`GET /import`, `events.manage`: props `{**view_props, "calendars": [{id, name, color}] where the caller has write_events, "can_publish": bool, "max_bytes": effective_max_bytes(settings), "import_id": str | None}` from `?id=`), `web/endpoints/menu.py` (the Import entry, `order=420`, permissions `[PERM_VIEW, PERM_MANAGE]`), `ui/utils/api.ts` (`errorText` for the import codes, plus a `reason` label for every item code and note of Ruling 31), locales (`import.*`, `menu.import`)
- Modify: `host/tests/test_menu_labels.py` (item count +1), `host/tests/test_events_wiring.py` (`/admin/events/import`)
- Test: `tests/web/test_views.py`, `ui/page-tests/Import.test.tsx`

**Interfaces:** `UploadForm` picks a calendar and a file (`accept=".ics,text/calendar"`), refuses a file over `max_bytes` client-side with the same message as the 413, and posts. `useImport` polls `GET /imports/{id}` every second while `uploaded`/`parsing`/`queued`/`running` and stops on any other state or after leaving the page; the id is mirrored in `?id=` so a reload resumes. `PreviewTable` shows counts as filter chips (new, update, skip), then rows (title, start in the event's local time, recurring icon, verdict badge, reason and notes as labels), paged by 50; the dropped properties are a list below ("Not imported: 3 attendees, 1 alarm"). Apply offers "Import as drafts" and, with `can_publish`, "Import and publish". `ImportResult` shows the outcome counters and the rows filtered by outcome with their codes, each created or updated row linking to the editor. A failed import shows its `error_code` message and a "Start again" button.

- [ ] **Step 1: Write the failing tests:**
  - `test_views.py::test_import_page_needs_manage` (`E` 403, `M` 200 with the props).
  - `Import.test.tsx`:
    - `upload then preview`: the polled `staged` state renders counts and rows.
    - `oversized file refused before upload`.
    - `publish button only with can_publish`.
    - `apply polls to done and shows the result`.
    - `failed import shows its code message`.
    - `reload with ?id= resumes polling`.
    - `polling stops on unmount` (fake timers).
    - `every reason code has a label` (iterates the code list exported from `api.ts`).
- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_views.py`, from the root `uv run pytest -q host/tests/test_menu_labels.py host/tests/test_events_wiring.py`, and `npx vitest run modules/events/sm_events/ui/page-tests/Import.test.tsx`: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same, tsc, biome, `check_rules.py` and `check_locales.py`: PASS.
- [ ] **Step 5: Commit** `feat(events): Import screen`.

### Task 17: `events-feeds.spec.ts`

**Files:**
- Create: `tests/e2e/events-feeds.spec.ts`, `tests/e2e/fixtures/events-import.ics` (three VEVENTs: a timed one-off in `Europe/Vienna`, a weekly series with one `EXDATE`, an all-day event; plus one `ATTENDEE` and one `VALARM` to see "Not imported")
- Test: the spec itself

**Interfaces:** standalone (CLAUDE.md "Every e2e spec file stands alone"): every name is `uniqueSlug`-based and the file seeds its own calendar and event through the API with `moduleCsrfHeader`. The CSP console check of `events.spec.ts` (a `problems` list asserted empty in `afterEach`).

- [ ] **Step 1: Write the spec:**
  - `private link serves, then stops after revoke`: create an internal calendar and a published event through the API; open Calendars, Subscribe on that row, create a private link with a label, read the URL from the read-only field; `const anon = await playwright.request.newContext()` (no cookies); `GET` it: 200, `text/calendar`, the body contains the event's title; close and reopen the dialog: the URL is not shown, the label is; revoke and confirm; `GET` again: 404 with `{"detail":"Not found","code":"not_found"}`.
  - `import preview and apply`: open `/admin/events/import`, choose the calendar, upload the fixture, wait for the preview (3 new, "Not imported" lists the attendee and the alarm), "Import and publish", wait for the result (3 created), open the Events list filtered to the calendar and see the three titles.
- [ ] **Step 2: Run** (headroom first; the server from `tests/e2e/start-test-server.sh`, which runs tasks eagerly) `npx playwright test tests/e2e/events-feeds.spec.ts`: PASS. Then `--repeat-each=2` once to prove it stands alone: PASS. Stop the server.
- [ ] **Step 3: Commit** `test(events): e2e for private links and import`.

### Task 18: Docs and branch verification

**Files:**
- Create: `modules/events/docs/feeds.md` (public feeds briefly, private links: what they serve (published only, the owner's current access), how to create and revoke, the cascade table of Ruling 14, the uniform 404 and the floor, rate limits (the per-token one is per process), **operators must redact `/feed/` paths in proxy and load-balancer logs** (the in-process filter covers the framework's request log, the rate limiter and uvicorn only), the offline-principal limits (Keycloak: no private links; multi-tenant: tenant-role permissions not counted until upstream), no `SM_SECRET_KEY` dependency)
- Create: `modules/events/docs/import.md` (who may import, limits and the setting, the mapping rules of Rulings 22–26 as a table, start adjustment, verdicts and codes, re-import by UID and what an update keeps, no bus events, the worker re-check window, the janitor, `make worker`/`beat` and eager hosts)
- Modify: `modules/events/docs/index.md` (links and a status row), `modules/events/README.md` (Usage: Subscribe and Import; the API tables of Tasks 7 and 15; status PR 5 of 10), `CHANGELOG.md` (Added: private feed links, `.ics` import, `events.run_import`, `events.janitor`, setting `import_max_bytes`)
- Modify: `CLAUDE.md`, the events paragraph only, adding: "**`{public_prefix}/feed/{token}.ics` is events' one documented exception** to "the public surface binds the resolved tenant": it looks the SHA-256 of the token up in one `all_tenants()` read, binds that row's tenant, re-derives the owner's access through `core/access/offline.py` on every request and answers every refusal with one padded 404; only a host-derived tenant can refuse a token. The token is shown once, never logged (`feeds/tokens/log_redact.py`), and an `.ics` import writes through PR 2's write path with no bus attached."
- Modify: `docs/module-layout.md` (the events row counts), the spec's "Amendments" (add "Amendments (PR 5)" listing Rulings 1, 5, 7, 9, 10, 17, 18, 22 (unknown zones), 23 (start adjustment), 25 (private class) and 29)
- [ ] **Step 1: Lint set** (headroom first), from the root: `uv run ruff check modules/events scripts host`, `uv run ruff format --check <files touched>`, `uv run basedpyright`, `npx biome check modules/events`, `npx tsc --noEmit -p modules/events/tsconfig.json`, and `uv run python scripts/check_metadata.py`, `check_rules.py`, `check_sibling_contracts.py`, `moved_paths.py --check`, `check_ts_imports.py`, `check_readmes.py`, `check_hardcoded_strings.py`, `check_file_size.py` (no WARNING under `modules/events`), `check_locales.py`, `check_migration_heads.py` and `bump_version.py --check-current`. All pass.
- [ ] **Step 2: Targeted suites, one at a time:** `cd modules/events && uv run pytest -q -n 8` on SQLite, then on `smpy_events_test`; from the root `uv run pytest -q -n 8 scripts/tests host/tests/test_tenancy_parity.py host/tests/test_events_wiring.py host/tests/test_menu_labels.py host/tests/test_host_boots.py`; `npx vitest run modules/events`. All pass. Do not run other modules' suites.
- [ ] **Step 3: Fresh-import check** for every new `modules/events/sm_events/**/*.py`.
- [ ] **Step 4: Commit** `docs(events): private feeds and calendar import`.
- [ ] **Step 5: Hand over to `/ship`.** Browser QA: create a private link on an internal calendar and subscribe to it from a real client or `curl`; unshare the calendar from that user and see the feed 404; reshare and see it serve; trash and restore the calendar; revoke; check the dev server's log for `<redacted>`; import a Google Calendar export and an Outlook export (Windows zone names), preview, apply as drafts, re-import and see "unchanged"; import a hostile file and see its code. Screenshots of the Subscribe dialog (before and after create), the preview table and the result go in the PR.

## Verification checklist (before `/ship`)

- Task 18 Step 1's lint set passes.
- The events pytest passes on SQLite and Postgres; `scripts/tests` and the host tests pass; `npx vitest run modules/events` passes; `events-feeds.spec.ts` passes twice in a row.
- `alembic check` is clean on SQLite and Postgres after upgrade, downgrade and upgrade; `check_migration_heads.py` reports one head, this PR's revision.
- No file under `modules/events` is at 280 lines or more.
- `grep -rn "all_tenants(" modules/events/sm_events` lists only Global Constraints' call sites.
- `git diff --stat feat/events-pr4-public` touches only `modules/events/**`, `host/migrations/versions/<rev>_events_feed_tokens_and_imports.py`, `host/tests/test_events_wiring.py`, `host/tests/test_menu_labels.py`, `tests/e2e/events-feeds.spec.ts`, `tests/e2e/fixtures/events-import.ics`, `Makefile`, `.github/workflows/ci.yml` (comments), `scripts/tests` (helper parity, if a family exists), `CHANGELOG.md`, `CLAUDE.md`, `docs/module-layout.md`, the spec and this plan.
- The Review Focus tests exist and pass: grep for each test name listed there.

## Open points

1. **No offline principal in the framework.** Events resolves a token owner's permissions from the directory's roles, membership and grant sources (Ruling 7), but the membership role (`tenant:<role>`) and the tenant's status (suspended) have no public read, so on a multi-tenant host a member whose `events.view` comes only from their tenant role gets the 404, and a suspended tenant's links keep serving until membership changes. File upstream in `simple_module_python`: `principal_for(app, db, user_id, tenant_id) -> principal | None` (directory, tenant status, membership role, grant sources, the scope rules) with a reproduction from Task 3's tests. Reminders (PR 8) need the same function.
2. **Rate limits keyed by a path segment.** The framework keys only by IP, user or tenant, so the per-token limit is in-process (Ruling 11). Ask upstream for a key kind that hashes a path parameter, then drop `throttle.py`.
3. **A framework hook to redact paths in its own logs.** Events and newsletter both carry capability tokens in paths; events installs a filter on framework loggers (Ruling 12), newsletter documents the risk only. Ask upstream for `register_log_redactions(patterns)` used by `RequestLoggingMiddleware` and the rate limiter; then newsletter can use it too (a follow-up issue in this repo).
4. **Trashing a calendar does not revoke its links** (Ruling 14): restoring it revives them, under the owner's current access. If the maintainer prefers trash to revoke, `trash_calendar` gains one `UPDATE` setting `revoked_at`.
5. **Windows zone names** depend on `icalendar` shipping a mapping (Task 10 Step 0). If it does not, Outlook exports with Windows `TZID`s are skipped `unknown_timezone`; the fallback would be CLDR's `windowsZones.xml` table (Unicode licence, check it first) in `feeds/importing/`.
6. **Imports emit no bus events** (Ruling 29), the same gap as PR 2's scheduled publishing. One cross-process bus upstream would close both.
7. **The ★ rulings** most likely to change are: who may create and see tokens (4), published-only feeds (5), the offline-principal stopgap (7), the deny floor (9), no validators on private feeds (10), `events.manage` for import (17), bytes in a column rather than `file_storage` (18), unknown zones skipped and the default one-hour duration (22), start adjustment (23), private class kept as draft (25) and no bus events (29).
