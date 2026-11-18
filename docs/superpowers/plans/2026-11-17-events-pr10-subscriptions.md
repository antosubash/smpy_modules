# Events PR 10: external ICS subscriptions. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A calendar owner (or `events.manage`) subscribes a calendar to a remote ICS URL. A beat task fetches it through a client that only ever connects to an address it has checked, follows redirects by hand and re-checks each hop, caps time, bytes and parser work, and sends `If-None-Match`/`If-Modified-Since`. The VEVENTs are mapped by PR 5's import mapper and cached in `events_external_item`. A built-in source shows them read-only, marked external, through PR 6's runner and PR 2's bounded expansion. They are never re-exported in this module's feeds, never reminded, and never offered as newsletter cards. The URL is stored encrypted and is never shown again in full.

**Architecture:** Everything new lives in `sm_events/feeds/subscriptions/`, split by responsibility. `url_safety.py` is a third copy of the SSRF address guard (parity family "SSRF address guard"). `policy.py` holds events' own URL rules: `webcal` rewriting, https only, ports, the intranet switch. `dns.py` resolves on a bounded thread pool. `client.py` is the pinned transport, and `fetch.py` makes one conditional, capped GET with manual redirects. `urls.py` handles encryption and the masked display. `store.py` and `items.py` map, upsert and prune, and `window.py` and `source.py` are the read side. `schedule.py`, `lease.py` and `refresh.py` are the beat. `service.py` and `validate.py` hold the console rules. The stored-secret crypto gets an events copy (`core/crypto.py`), joins both crypto parity families, and gains a column target in `scripts/reencrypt_secrets.py`. The console gets a per-calendar Subscriptions dialog and a built-in frontend source registration whose detail renders the external link safely.

**Tech Stack:** Python 3.12, `httpx` 0.28 (already locked through images; events gains a direct `httpx>=0.27` range, plus `httpcore`/`anyio` for the `netsafe` copy), `cryptography` (already locked), `icalendar` 7.x (PR 4), SQLModel/SQLAlchemy async, the framework's `background_tasks` (Celery beat) through PR 2's worker runtime, pytest (SQLite, plus opt-in Postgres through `tests/pg_support.py`), React 19 + Inertia, `@simple-module-py/ui`, vitest (happy-dom).

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`, Delivery row 10. It draws on "ICS" → Subscriptions ("fetched by a beat task with `ETag`, cached in `events_external_item`, the URL checked as ai checks a base URL (public addresses only, re-checked on redirect)"; "External subscriptions are never re-exported"), the anti-goals "A subscription URL used to reach an internal address", "An internal or private event reaching the public" and "Leaking across tenants", Settings (`subscription_refresh_minutes`) and Background work (`events.refresh_subscriptions`). Precedent plans: PR 2 (Rulings 7, 12 and 13: an expansion is always bounded by the window and the cap), PR 4 (the ICS writer, feeds), PR 5 (Rulings 19–26: pre-scan, value reading, mapper and its bounds; Ruling 12: the log filter; the janitor), PR 6 (Rulings 5–16: `SourceOccurrence`, the runner, public and private sources, feeds), PR 8 (the worker runtime under strict isolation, `settings_for`). Precedent code to read in full before starting: `modules/ai/sm_ai/core/url_safety.py`, `modules/ai/sm_ai/connections/pinned.py`, `modules/ai/sm_ai/connections/base_url.py`, `modules/images/sm_images/ingest/imports/{url_safety,dns,netsafe,fetch,errors}.py`, their tests (`modules/images/tests/support/fetch.py`, `modules/images/tests/ingest/imports/test_imports_fetch*.py`, `test_imports_url_safety.py`, `modules/ai/tests/**/test_pinned.py`, `test_url_safety.py`, `test_base_url.py`), `scripts/tests/parity_families.py`, `parity_crypto.py`, `parity_support.py`, `modules/newsletter/sm_newsletter/core/crypto.py`, `scripts/reencrypt_secrets.py`, `scripts/reencrypt_support.py` and `docs/secret-key-rotation.md`.

## Depends on PRs 2–9

Before Task 1, rebase the branch onto the finished `feat/events-pr9-registration` (PR 9 → 8 → … → 1). The implementer of each batch **first re-checks every symbol below against the real code**. Where a name differs, correct this plan's task text; never rename earlier PRs' code. Stop and report if a *behaviour* differs, in particular:
- PR 6's runner does not run each call inside a savepoint with a timeout, or does not cap a call at `ctx.limit`;
- PR 6's feeds build their plugin calls without going through one function this PR can narrow;
- PR 5's `map_calendar` evaluates a VTIMEZONE, or calls dateutil on raw file text;
- PR 2's `expand.instances` iterates without an `until` bounded by `window_end`.

| Area | Symbols relied on |
|---|---|
| Access (PR 1) | `core/access.POLICY`, `visible_calendars(who)`, `calendar_rights(db, who, calendar)` and its visibility/owner right (`can_change_visibility`), `load_calendar` (or its PR 1 name); permission constants `PERM_VIEW`, `PERM_MANAGE`, `PERM_PUBLISH` |
| Time and rules (PR 2) | `calendar/times.py` `Span`, `to_span`, `localize`, `all_day_dates`; `calendar/rrule.py` `parse`, `validate`, `Rule`; `calendar/expand.py` `instances`, `Instance`; `InvalidTimes`, `InvalidRule`; constants `MAX_SERIES_EVENT_DAYS`, `SERIES_FETCH_MAX` |
| Read (PR 2/6) | `calendar/occurrence.py` `Occurrence`, `OccurrencePage`, `OccurrenceFilters`; `calendar/sources.py` `sort_key`, `register_builtins()`; `calendar/plugin_scope.plugin_calls(db, viewer, source_viewer, filters)`; `calendar/plugin_runner.run_sources`, `Call`, `RunResult`; `calendar/source_entries.SourceEntry`; `calendar/plugin_validate.to_occurrences`; `calendar/registry.register_builtin_source`, `get_source`, `ensure_loaded` |
| Plugin types (PR 6) | `calendar/extension_types.py` `SourceOccurrence`, `SourceContext`, `SourceCalendar`, `SourceStatus`; `contracts/extensions.py` `__all__` |
| Feeds (PR 4/5/6) | `feeds/select.feed_events`, `feeds/ics_calendar.build`, `feeds/plugin_items.py` (plugin items → VEVENTs) and whatever function it gets its calls from; `web/endpoints/public/_feeds.py`, `_private_feed.py`; `FEED_DAYS_BACK`, `FEED_DAYS_AHEAD` |
| Import (PR 5) | `feeds/importing/scan.scan(data) -> Scanned`, `sniff(head)`; `ImportFailure(code)`; `feeds/importing/values` (`ItemSkip`); `feeds/importing/mapper.map_calendar(cal, *, calendar_tz, categories) -> Mapped`, `MappedEvent`, `MappedOverride`; `feeds/importing/text.clean_title`; `feeds/importing/fence.py`; `feeds/importing/launch.py` (eager inline / enqueue); `feeds/importing/janitor.py` (`events.janitor`); `feeds/tokens/log_redact.py` (the filter pattern); constants `IMPORT_MIN_BYTES`, `IMPORT_BODY_CEILING`, `IMPORT_MAX_EVENTS`, `IMPORT_MAX_OVERRIDES`; the `import_max_bytes` setting and its clamp |
| Public (PR 4/6) | `web/endpoints/public/_api.py` (`/api/occurrences`), `_listing.py` (passes `sources={SOURCE_EVENTS}`), sitemap, JSON-LD; `core/access/public.ANONYMOUS` |
| Cards (PR 7) | `contracts/cards.py` (published events of public calendars only) |
| Reminders (PR 8) | `reminders/candidates.py` (followed events only), `reminders/follows.py` |
| Worker (PR 2/8) | `core/worker.py` (`run_platform`, `reset_worker_runtime`), `tasks.py`, `task_config.py` (`QUEUE_DEFAULT`, `TASK_ROUTES`, `BEAT_SCHEDULE`), `background_tasks.settings_for(EventsSettings, PACKAGE, ttl=30)` as PR 8 reads settings in a worker, the `worker_db` fixture (`tenant_strict=True`) |
| Tenancy | `core/tenancy` (`tenant_scope`, `all_tenants`, `bound_tenant`); `simple_module_db.all_tenants`, `finalize_session`. **Parity-checked: this PR edits none of `core/tenancy/*`.** |
| Models | `models/_cols.py` (`big_pk`, `pk_uuid`, `fk_uuid`, `dt_col`, `json_col`, `flag`), the soft-delete mixin `Calendar` uses, `Calendar.default_timezone`, `Calendar.is_deleted` |
| Migrations | the single head after PR 9 (`uv run python scripts/check_migration_heads.py`) |
| TS (PR 1/3/6) | `pages/Calendars.tsx`, `ui/components/calendars/CalendarRow.tsx`, `ui/components/ConfirmDialog.tsx`, `ui/utils/api.ts` (`ApiError`, `send`, `errorText`), `ui/utils/i18n.ts` (`useT`, `keys`), `ui/extensions/registry.ts` (`registerSource`), `ui/extensions/slots.tsx`, `ui/calendar/StatusBar.tsx`, `ui/page-tests/test-dom.tsx`, `support.tsx` (`stubFetch`) |
| Tests | `tests/support/app.py` (`build_app`, `as_user`, `client`, `multi_client`, `csrf_client`), `tests/support/access.py` (`principal`, `seed_calendars` → `P`, `I`, `U`), `tests/support/calendars.seed_event`, the `unbound_tenant` marker, `tests/pg_support.py`, PR 5's `tests/feeds/importing/corpus.py` |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**The stored URL**
1. ★ **The URL is a secret and is stored encrypted.** Google's "secret address", Outlook's published-calendar links and most providers put a bearer token in the path or query, so the URL is the credential. `events_subscription.url_enc` holds `enc:v2:` ciphertext from a new events copy of the stored-secret crypto (`sm_events/core/crypto.py`, `_INFO = b"sm_events:settings"`, newsletter's copy including the worker fallback to `SM_SECRET_KEY`, because the fetch runs in a Celery worker that builds no app). `url_display` holds the masked form in the clear: `scheme://host[:port]/…`, with the host as IDNA ASCII. The API, the Inertia props, every log line, every error body and every status code carry only `url_display`. There is no endpoint that returns the URL, and a `PATCH` can only replace it.

   Storing the URL plain and never returning it was the alternative. It is simpler (no crypto copy, no rotation work), but a database dump or backup would then hand out every subscriber's tokens, and the repo's rule since #350 is that a stored secret is never kept in the clear.

   Consequences:
   - a fifth copy joins "stored-secret crypto" and "stored-secret crypto: worker fallback" in `scripts/tests/parity_crypto.py`;
   - `scripts/reencrypt_support.py` gains `COLUMN_TARGETS = {"sm_events": (("events_subscription", "url_enc"),)}`, and `reencrypt_secrets.py` rewrites those rows across all tenants, under the same all-or-nothing rule and per-row compare-and-set;
   - `docs/secret-key-rotation.md` lists the column;
   - a URL that no longer decrypts (key lost, previous key dropped too early) puts the subscription in `error` with code `url_unreadable`; it is not fetched, and the dialog asks for the URL again.
2. **No URL hash.** A duplicate is found by decrypting the calendar's rows (at most `SUBSCRIPTIONS_PER_CALENDAR`), so nothing derived from the URL can be checked against a guess. The same normalised URL twice on one calendar gives 409 `subscription_exists`. The same URL on two calendars is allowed (the same rule as UIDs).

**URL policy** (checked on save **and** on every fetch, because DNS can change)
3. **Normalising.** Surrounding whitespace is stripped. `webcal://` and `webcals://` are rewritten to `https://` (case-insensitive). The fragment is dropped. The result is at most `SUBSCRIPTION_URL_MAX = 2000` characters (otherwise `url_invalid`). The URL is parsed with `httpx.URL`, the parser the request is built with, so the host that is validated is the host that is dialled.
4. ★ **https only, unless the intranet switch is on.** `http://` is refused (`url_scheme`) unless `allow_private_subscription_urls` is on, and is then allowed for any host. A redirect from https to http is refused (`insecure_redirect`) in every mode. A token in a URL must not cross the network in the clear, and an intranet calendar server is the one realistic case for http.
5. ★ **Userinfo is refused** (`url_userinfo`): `https://user:pass@host/` would put a credential in the `Authorization` header and in the stored string. A provider that needs credentials puts a token in the path, which is what this feature supports.
6. **Ports.** By default only the scheme's default port is allowed (443, or 80 for http), otherwise `url_port`. With the intranet switch on, any port from 1 to 65535 is allowed.
7. **Addresses.** Every address the host resolves to must pass the guard. One failing address refuses the whole URL, so a DNS answer with one public and one private address is refused. The guard is images' `is_public_address` (copied, parity family "SSRF address guard"): loopback, RFC 1918, link-local (including `169.254.169.254`), CGNAT, benchmarking, multicast, unspecified, reserved, ULA (including `fd00:ec2::254`), site-local, and any IPv4-mapped, IPv4-compatible, NAT64, 6to4 or Teredo form of one of them are all refused. IP literals are checked the same way. An unresolvable host is `url_unresolvable`; a refused address is `url_not_public`.
8. ★ **The intranet switch lifts private ranges only.** `allow_private_subscription_urls: bool = False` (SYSTEM setting) lets an address in RFC 1918, ULA (`fc00::/7`), CGNAT or `198.18.0.0/15` through. It **never** lets through loopback, link-local (the metadata addresses), unspecified, multicast or reserved addresses, or an embedded form of them. This is stricter than ai's switch, which skips the address check entirely: a calendar on the office network is a real need, but the worker's own loopback services and the cloud metadata endpoint are not. With the switch on the connection is still pinned to the checked address, so rebinding is still closed. This is events' own function, `policy.address_allowed(ip, *, allow_private)`, kept outside the parity-shared names.
9. ★ **Who can open an intranet URL.** The switch is written on the framework Settings screen, which requires `settings.edit`. The framework has no per-field write permission (its `manage_url` is module-wide), so `events.manage` is enforced where the URL is used instead: a URL that passes only because of the switch (a private address, http, or a non-default port) can be saved only by a holder of `events.manage`. Anyone else gets 422 `url_not_public`, `url_scheme` or `url_port` as if the switch were off. An internal target therefore needs both permissions, as ai's does. Turning the switch off does not delete stored intranet subscriptions: their next fetch fails `url_not_public` and the dialog shows it. A per-field write permission is open point 1.

**Fetching**
10. **One fetch** (`fetch.py`, `async def fetch_feed(url, *, etag, last_modified, max_bytes, allow_private, clock) -> FetchResult`):
    - The fetch builds `httpx.Request`s itself and hands them **directly** to `PinnedTransport.handle_async_request`, never to an `httpx.AsyncClient`. The client logs `HTTP Request: GET <full URL>` at INFO, which would write the token into the log. Driving the transport also means there is no cookie jar, no auth flow, no proxy mounting and no environment reading. Timeouts go in the `timeout` request extension.
    - Headers are exactly `Host` (set by httpx from the URL), `User-Agent: SimpleModule-Events/<installed version>`, `Accept: text/calendar, text/plain;q=0.5`, `Accept-Encoding: identity`, and the conditional headers of Ruling 13. ★ The User-Agent names neither the host, nor the tenant, nor a contact. Nothing else is sent: no cookies, no `Authorization`, no `Referer`.
    - `PinnedTransport` (copied from images and adapted to `policy.resolve_allowed`) resolves and checks the host for **every** request it sends. It rewrites only the URL's host to a checked IP, keeps the `Host` header and sets `sni_hostname`, so TLS sends SNI for the name and verifies the certificate against the name. It tries at most `MAX_ADDRESSES_PER_HOP = 4` addresses, and only after connect failures. Its connection layer is kept per original origin, and is hardened by the `netsafe` copy (a cancelled TLS handshake closes its socket). `trust_env=False`, `verify=True`, no keep-alive.
    - Redirects are followed by hand, at most `SUBSCRIPTION_MAX_REDIRECTS = 3`. Each `Location` is joined to the current URL, normalised by Ruling 3 (`webcal:` included), checked by Rulings 4–8, and requested through a fresh transport call, which resolves and checks it again. More hops give `too_many_redirects`, a downgrade gives `insecure_redirect`, and a redirect without `Location` gives `http_status`. Conditional headers are sent on the first hop only. ★ A permanent redirect (301/308) never rewrites the stored URL.
    - Time. DNS for each hop takes at most `DNS_TIMEOUT_SECONDS = 5` on a dedicated pool (images' `dns.py`, copied). Connect takes at most 5 s, each read at most 15 s, and one absolute deadline of `SUBSCRIPTION_FETCH_SECONDS = 30` covers every hop, the headers and the body (`asyncio.timeout_at`). Expiry gives `timeout`.
    - Final response. A 2xx is accepted. A 304 (on the first hop, with conditional headers sent) is `not_modified`. 410 gives `gone`. Any other status gives `http_status`, with the number recorded in `last_http_status`; a number from the remote is safe to show, its reason text is not.
    - Body. A `Content-Encoding` other than identity is refused (`unsupported_encoding`), so no decoder can inflate past the cap. That is the decompression-bomb guard, and it is images' rule (★ open point 3: gzip). A `Content-Length` over the cap is refused before reading (`too_large`). The raw body is streamed (`aiter_raw`) with a running byte count and stops at the cap (`too_large`). The cap is the `import_max_bytes` setting under PR 5's clamp, so the parser bounds and the network bound are one knob.
    - Content type. The media type (before `;`) must be one of `text/calendar`, `text/plain`, `application/octet-stream`, `application/ics` or `text/x-vcalendar`, or be absent. Anything else, `text/html` above all, gives `unexpected_content_type`. Then PR 5's `sniff` must pass on the first bytes (`ics_invalid`), and that is the real check.
    - Every failure is a `FetchFailure(code, http_status=None)` whose message is the code. A library exception's text is never kept: it can carry the URL. The fetcher logs the subscription id, the code and `url_display` only.
11. **Stable failure codes** (stored in `error_code` and localised in the dialog): `url_invalid`, `url_scheme`, `url_userinfo`, `url_port`, `url_unresolvable`, `url_not_public`, `url_unreadable`, `too_many_redirects`, `insecure_redirect`, `timeout`, `connect_failed`, `tls_failed`, `http_status`, `gone`, `too_large`, `unsupported_encoding`, `unexpected_content_type`, `ics_encoding`, `ics_invalid`, `too_many_events`, `internal`. `connect_failed` and `tls_failed` come from `httpx.ConnectError` (an `ssl.SSLError` cause gives `tls_failed`). Any other exception is `internal`, logged with `logger.exception` naming the subscription id only.

**Scheduling, leases and failure**
12. **Refresh interval.** The setting `subscription_refresh_minutes: int = 60` (spec) is the default. A subscription may set its own `refresh_minutes`. Both are clamped to `[SUBSCRIPTION_MIN_REFRESH_MINUTES = 15, SUBSCRIPTION_MAX_REFRESH_MINUTES = 1440]` where they are read; the API refuses values outside the range with FastAPI's 422. After a success (200 or 304), `next_fetch_at = now + interval × jitter`, where jitter is uniform in `[0.9, 1.1]` (`random.Random` injected for tests). A new or resumed subscription, a changed URL and "Refresh now" set `next_fetch_at = now`.
13. **Conditional requests.** A 200 stores `etag` (at most 200 characters of printable ASCII, otherwise dropped) and `last_modified` (at most 64 characters, the raw header). The next fetch sends `If-None-Match` and `If-Modified-Since` with them. A 304 updates `last_fetched_at`, `last_ok_at`, `consecutive_failures = 0`, `status = ok` and `next_fetch_at`, and touches **no** item. A URL change clears both validators.
14. **Backoff and disabling.** A failure sets `status = error`, `error_code`, `consecutive_failures += 1` and `next_fetch_at = now + min(interval × 2^(failures−1), SUBSCRIPTION_MAX_BACKOFF = 24 h) × jitter`. After `SUBSCRIPTION_MAX_FAILURES = 10` consecutive failures, or at once on `gone` or `url_unreadable`, the status becomes `disabled` and the last `error_code` is kept as the reason. A disabled or paused subscription is never picked by the beat. "Resume" sets `status = pending`, clears `consecutive_failures` and makes it due now. ★ The policy codes (`url_*`, `insecure_redirect`) count as ordinary failures, not as an immediate disable, because an operator may be about to turn the intranet switch on.
15. **The beat task** `events.refresh_subscriptions` runs every 60 s on queue `events` (`expires` 55).
    - **Enumeration.** Under `with simple_module_db.all_tenants():`, one statement tagged `tenancy.all_tenants(...)` selects `(tenant_id, id)` of the oldest due rows across all tenants: `status IN ('pending','ok','error') AND NOT is_deleted AND next_fetch_at <= now AND (lease_until IS NULL OR lease_until < now)`, ordered by `next_fetch_at` and limited to `2 × SUBSCRIPTION_TICK_FETCHES`. It joins `events_calendar` so that a subscription of a trashed calendar is never picked. Both the context and the tag are needed: the tag alone is refused under strict isolation (PR 2 review finding; PR 8's reminders tick does the same). Ordering by due time across tenants keeps one busy tenant from starving the others.
    - **Per tenant.** The rows are grouped by tenant, and each is worked under `tenant_scope(t)` in a fresh session. A claim is a compare-and-set: `UPDATE events_subscription SET lease_owner = :me, lease_until = now + SUBSCRIPTION_LEASE WHERE tenant_id = :t AND id = :id AND <the due predicate>`, finished with `finalize_session`. A row count of 0 means another worker took it. On Postgres the candidate read uses `FOR UPDATE SKIP LOCKED` inside the claim transaction. `lease_owner` is a fresh `uuid4().hex` per tick.
    - **Fetch.** The fetch runs with **no** database session open.
    - **Store.** One transaction stores the result **fenced** on `lease_owner = :me AND lease_until > now` through `lease.fenced` (Task 8), which follows PR 5's `fence.py` pattern. A lost lease rolls the store back and logs `lease_lost`. Then the lease is cleared.
    - **Budget per tick.** At most `SUBSCRIPTION_TICK_FETCHES = 20` fetches, `SUBSCRIPTION_TICK_BYTES = 50 MiB` received, and `SUBSCRIPTION_TICK_SECONDS = 45` of wall clock. A fetch starts only when 30 s of the budget is left. Fetches are sequential. Rows that do not fit wait for the next tick.
    - `SUBSCRIPTION_LEASE = 2 min`, which is more than the fetch deadline plus the store. A crashed worker's lease expires and the row is picked up again.
    - **Settings in the worker** come from `background_tasks.settings_for(EventsSettings, PACKAGE, ttl=30)`, as in PR 8.
    - A tenant whose work raises is logged and counted, and the others continue.
    - The task returns, and logs, `{tenants, fetched, not_modified, failed, skipped_budget, lease_lost}`, with counts only.
16. **Refresh now, and the first fetch.** Create, a URL change, resume and `POST …/refresh` set `next_fetch_at = now` and then call `launch.refresh_one(tenant, id)`. This is PR 5's launch pattern: with `task_always_eager` it runs the same claim → fetch → store inline after the commit; otherwise it enqueues `events.refresh_subscription` (one subscription, the same body) through `enqueue_after_commit`. A host with neither beat nor eager mode refreshes only when asked, and this is documented. ★ "Refresh now" is refused with 429 `refresh_too_soon` (and `Retry-After`) while `last_fetched_at` is less than `SUBSCRIPTION_REFRESH_NOW_SECONDS = 300` old, or while a lease is held. This is per subscription, in the database, so it holds across replicas.

**Parsing and storing**
17. **Reuse PR 5's pre-scan and mapper** (no second parser). The body goes through `scan(data)`, whose bounds are PR 5's `IMPORT_MAX_*`; its `ImportFailure(code)` becomes the subscription's failure with the same code. Then `icalendar.Calendar.from_ical` runs inside `try` (failure: `ics_invalid`, with the message dropped). Then `map_calendar(cal, calendar_tz=calendar.default_timezone, categories={})` runs. Two small, additive changes go into PR 5's code, and the import ignores both:
    - `MappedEvent.url: str | None`, the VEVENT's `URL` when it is an absolute http(s) URL of at most 2000 characters without whitespace or control characters, else `None`;
    - `text.clean_line(raw, max_len)`, the single-line cleaner behind `clean_title` (control and direction characters removed, whitespace collapsed, cut). The mapper's `venue_name` goes through it, if it does not already.
18. **What an item keeps** (plain text only: no description, no HTML, ever). `title` (PR 5's cleaned title, ≤ 300), `location` (`venue_name`, ≤ 200), `url` (Ruling 17), `cancelled` (`STATUS:CANCELLED`), `private_class` (`CLASS:PRIVATE`/`CONFIDENTIAL`, from `MappedEvent.private_class`), the times, the rule and the overrides. The description, attendees, organiser, alarms, attachments and every `X-*` property are dropped. ★ This is a calendar *overlay*: a description is where remote HTML and tracking links live, and it would need PR 2's sanitiser on content nobody here reviewed. The occurrence links to `url` for detail.
19. **Rules and zones follow PR 5's rulings unchanged.** An unknown `TZID` skips the item (`unknown_timezone`). A rule outside PR 2's allow-list, `RDATE` or `EXRULE` skips it (`unsupported_rule`). ★ A skipped series is not kept as a one-off, because showing one date of a weekly meeting misrepresents the calendar. A start that is not in its rule is adjusted (`start_adjusted`). EXDATEs become `skipped` overrides and RECURRENCE-ID children become `moved` or `cancelled` overrides. Skips are counted per code in `last_counts`, and the dialog shows them.
20. **Storage shape: normalised columns, plus overrides as JSON.** `events_external_item` mirrors the columns the read needs from `events_event`: `all_day`, `starts_at`, `ends_at` (UTC, PR 2's all-day convention), `timezone`, `rrule` (PR 2's normalised text, already allow-listed), and `recurrence_until`. Overrides are a JSON list `[{original_start, kind, starts_at, ends_at}]` (UTC ISO strings, at most `IMPORT_MAX_OVERRIDES`), because they are read only together with their item. Two prefilter columns make one window predicate serve one-offs and series alike: `span_start` = the minimum of `starts_at` and every moved start, and `span_end` = `ends_at` for a one-off, otherwise the maximum of `recurrence_until` and every moved end, or `NULL` when the rule is endless. The window predicate is `span_start < :end AND (span_end IS NULL OR span_end > :start)`. A compact JSON blob per item was the alternative. It would need every row loaded to filter by date, and would not let the read reuse PR 2's `Span`/`Rule` directly.
21. **Mapping to columns.** Each mapped item goes through PR 2's `times.to_span(..., recurring=bool(rrule))`, `rrule.parse` and `rrule.validate` (for `recurrence_until`). A moved override's local times are converted with `to_span` in the item's timezone. `InvalidTimes` or `InvalidRule` at this point skips the item with that error's code. The mapper has already run the same checks, so this is defence in depth and is counted.
22. **Upsert, hash and prune** (one transaction per subscription, inside the fence).
    - The key is `(tenant_id, subscription_id, uid)`. The mapper folds `RECURRENCE-ID` children into their master's overrides, so a UID is one row; a UID longer than 255 characters is skipped by the mapper.
    - `content_hash` is the SHA-256 of the canonical JSON of every stored field. An existing row with the same hash only gets `seen_generation` set.
    - The subscription's `generation` is incremented once per successful 200. After the upsert, `DELETE FROM events_external_item WHERE tenant_id = :t AND subscription_id = :s AND seen_generation < :generation`.
    - ★ **Items are deleted only after a 200 whose body was scanned, parsed and mapped in full.** They are never deleted on a 304, a fetch failure, a scan or parse failure, a lost lease or an exception: each of those leaves the previous items in place, still shown.
    - A body that maps to zero items (a feed that really was emptied) deletes everything, because that is what the remote now says.
    - Writes go in chunks of 500.
23. **Limits.**
    - At most `SUBSCRIPTIONS_PER_CALENDAR = 10` and `SUBSCRIPTIONS_PER_TENANT = 100` live subscriptions; one more gives 409 `subscription_limit`.
    - At most `IMPORT_MAX_EVENTS` (5,000) VEVENTs per feed, from PR 5's scan. More fails the fetch with `too_many_events` and keeps the old items (open point 2).
    - `label` is a single line of 1–100 characters. `color` is `#rrggbb` or `null` (null means the calendar's colour). `title` is ≤ 300, `location` ≤ 200, `url` ≤ 2000, `uid` ≤ 255.

**Reading**
24. ★ **One built-in source, `subscriptions`, with an implicit entry per calendar.** It is registered in PR 6's `register_builtins()` through `register_builtin_source`, so like `events` it has no namespace. It has `label_key = "events.subscriptions.source"`, `icon = "rss"`, `public = True` (the per-subscription flag gates the public surface, Ruling 26), and `settings_model = None`.
    - It is **never** stored in `events_calendar.sources` and never listed by `GET /api/events/sources` or the Sources dialog: a `PUT …/sources` naming it gets PR 6's 422 `builtin_source`.
    - `plugin_scope.plugin_calls` gains `include_subscriptions: bool = True`. When it is true, it adds a synthetic `SourceEntry(id="subscriptions", settings={})` for every calendar in scope that has at least one live subscription (one grouped query). The call then runs through PR 6's runner like any plugin: savepoint, timeout, budget, `SourceOccurrence` validation and the 500-item call cap.
    - Per-subscription entries were the alternative. They would put up to 10 runner calls per calendar against PR 6's 16-call budget, and add a second management surface for the same thing.
    - The calendar's `StatusBar` shows the source's status under its label ("External calendars could not be loaded (timed out)").
25. **What an external occurrence looks like.**
    - `key` is `f"{subscription_id.hex}:{sha256(uid)[:24]}"`, plus `f":{original_start:%Y%m%dT%H%M%SZ}"` for a series instance (within PR 6's key alphabet, ≤ 80 characters).
    - `title` is the item's title. `status` is `cancelled` for a cancelled item or a cancelled override.
    - `color` is the subscription's colour, else `None` (the calendar's).
    - `url` is the item's URL. `timezone` and the all-day dates are the item's. `lang` is `None`. `updated_at` is the item's `updated_at`.
    - ★ **The subscription's label travels on the occurrence.** PR 6's `SourceOccurrence` and PR 2's `Occurrence` gain one additive optional field, `origin_label: str | None` (plain text, ≤ 100, validated like the title). Any plugin may use it, and the chip shows it as a badge. Without it, the "external, from <label>" marking would need a second lookup on every surface, the public grid and the pagebuilder blocks included.
26. **Visibility.**
    - The source returns items only for the calendar the runner passes (`ctx.calendar.id`). PR 6's scope already limits calendars to those the viewer may see.
    - ★ **On the public surface** (`ctx.viewer is None`) it returns only items of subscriptions with `public = true`, and never an item with `private_class`. Subscriptions default to `public = false`.
    - Setting `public = true` needs `events.publish` as well as the subscription right (Ruling 30), because it puts unreviewed remote content on the public site. It is accepted only while the calendar is `public` (otherwise 422 `subscription_not_public_calendar`). Narrowing the calendar later needs no clean-up, because PR 6's scope stops calling the source for anonymous reads.
    - Signed-in viewers of the calendar see every item, including `private_class` ones (the calendar's own audience).
    - Paused, errored and disabled subscriptions keep showing their cached items; only deleting a subscription removes them. The dialog shows how stale they are (`last_ok_at`).
27. **Bounded expansion** (PR 2 Rulings 7 and 13). `window.py` selects one-off rows ordered by `starts_at` with `LIMIT ctx.limit + 1`, and series rows with `LIMIT SERIES_FETCH_MAX` (going over sets the source's answer to `limit + 1` items, so the runner reports `truncated`), both under Ruling 20's predicate. Every series is expanded lazily with `expand.instances(..., window_start=start, window_end=end, recurrence_until=row.recurrence_until)`, so no expansion runs past the window. Overrides are applied in memory (`skipped` dropped, `cancelled` marked, `moved` replaced by its new span, if that span intersects the window). One `heapq.merge` by `sort_key` stops at `ctx.limit + 1`. The runner then keeps the first `ctx.limit` and marks `truncated`.
28. **Never re-exported, never reminded, never a card** (spec: "External subscriptions are never re-exported").
    - PR 6's feed path (`feeds/plugin_items.py`) builds its calls with `include_subscriptions=False` and also filters out `SOURCE_SUBSCRIPTIONS` explicitly: the public `calendar.ics`, `c/{cal}.ics`, the private token feed and the single-event `.ics`.
    - PR 6 Ruling 15 already keeps plugin sources out of the server-rendered listing, the sitemap and JSON-LD, and a test pins that it holds for this source too.
    - Reminders follow events only (PR 8 Ruling 16).
    - `contracts.cards` reads events only (PR 7).
    - `contracts.occurrences` (siblings' read) includes external items exactly as the console read does, under the caller's viewer. With no `source_viewer` they are `skipped`/`no_viewer` (PR 6 Ruling 13).

**Console and API**
29. **Routes** (`/api/events`, `RequiresCsrf`, `{"detail","code"}` envelope):

    | Method and path | Needs | Answer |
    |---|---|---|
    | `GET /calendars/{id}/subscriptions` | subscription right on the calendar | 200 `[SubscriptionOut]`, ordered by label |
    | `POST /calendars/{id}/subscriptions` | subscription right; `events.publish` for `public: true`; `events.manage` for an intranet URL | 201 `SubscriptionOut` (then refresh) |
    | `PATCH /subscriptions/{id}` | the same rights (`url`, `label`, `color`, `refresh_minutes`, `public`) | 200 `SubscriptionOut` |
    | `POST /subscriptions/{id}/refresh` | subscription right | 202 `SubscriptionOut`, or 429 `refresh_too_soon` |
    | `POST /subscriptions/{id}/pause`, `/resume` | subscription right | 200 `SubscriptionOut` |
    | `DELETE /subscriptions/{id}` | subscription right | 204 |

    `SubscriptionOut` carries `{id, calendar_id, url_display, label, color, refresh_minutes, effective_refresh_minutes, public, status, error_code, last_http_status, last_fetched_at, last_ok_at, next_fetch_at, consecutive_failures, item_count, last_counts}` and never the URL. Request bodies use `extra="forbid"`; `url` is write-only.
30. ★ **The subscription right is the calendar's visibility right** (the owner or `events.manage`, PR 1's `can_change_visibility`), the same right as PR 6's Sources dialog, because a subscription changes what the calendar's audience sees, and a subscription URL is a credential that only the owner should handle. Every route also needs `events.view`. A calendar the caller cannot see gives 404, and one they can see without the right gives 403 `forbidden`. A subscription of another tenant, of a calendar the caller cannot see, or one that is deleted gives 404, the same answer as an id that does not exist.
31. **Save-time checking.** `POST`, and a `PATCH` with `url`, run Rulings 3–9 including DNS (bounded, 5 s) before anything is written. A refusal is 422 with the code mapped from the guard: `url_invalid`, `url_scheme`, `url_userinfo`, `url_port`, `url_unresolvable` or `url_not_public`, with a fixed `detail` that never echoes the URL. The save does not fetch. The first fetch runs through Ruling 16, and its result shows in the dialog.
32. ★ **Delete is final.** The row is soft-deleted (`is_deleted`, the spec's convention), `url_enc` is overwritten with `""` in the same statement so that a deleted row holds no secret, and its items are deleted in the same transaction. There is no restore (the URL is gone). PR 5's `events.janitor` purges soft-deleted subscriptions after `SUBSCRIPTION_DELETED_KEPT_DAYS = 30`. Trashing the calendar keeps the subscriptions but stops their fetches (Ruling 15) and hides them; restoring the calendar resumes them. A hard-deleted calendar cascades.
33. **The dialog.** The Calendars screen gains a "Subscriptions" row action, shown when `can_change_visibility`. It opens `SubscriptionsDialog`:
    - **The list.** Each row shows the label with its colour swatch, `url_display` in monospace, a status badge (`pending`, `ok`, `error`, `paused`, `disabled`), "Last updated <relative last_ok_at>", the item count, the localised message of `error_code` (with `last_http_status` for `http_status`) and the skip counts ("12 events skipped: unknown time zone (10), unsupported repeat rule (2)"). Its actions are Refresh now (disabled for 5 minutes after a fetch, with the 429 shown as a message), Pause/Resume, Edit and Delete (confirmed: "Its 214 cached events disappear from the calendar.").
    - **The form**, for add and edit. It has URL (`type="url"`, `autocomplete="off"`, empty on edit with the hint "Leave empty to keep the current address"), label, colour, refresh interval (minutes, placeholder shows the default) and "Show on the public site", which is enabled only for a public calendar and a holder of `events.publish`. The sentence under the URL field reads: "Treat this address like a password: it is stored encrypted and never shown again."
    - **After save**, the URL field is cleared and the row shows the masked address only.
34. **Rendering an external occurrence** (frontend). Events registers its own built-in source entry with the TS registry (`registerSource({id: 'subscriptions', Chip, Detail, PublicDetail})`, from `ui/extensions/builtins.ts`, loaded before the plugin glob):
    - The chip shows the title with an "External" icon and the `origin_label` badge.
    - The detail shows the title, the time, the location as text, "From <origin_label> (external calendar)", and, when `url` is set, `<a href={url} target="_blank" rel="noopener noreferrer nofollow">`. It is a plain anchor, never an Inertia `Link`, and React's escaping is the only HTML path. Nothing uses `dangerouslySetInnerHTML`.
    - No drag, resize, "Move", "Remind me" or edit control is offered (`editable: false`).

**Errors and constants**
35. New HTTP codes: 409 `subscription_exists`, `subscription_limit`; 422 `url_invalid`, `url_scheme`, `url_userinfo`, `url_port`, `url_unresolvable`, `url_not_public`, `subscription_not_public_calendar`; 429 `refresh_too_soon`. PR 2's 403 `publish_required` is reused for the public flag. Every bound named above lives in `core/constants.py`.

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, alembic or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr10` on branch `feat/events-pr10-subscriptions`, stacked on `feat/events-pr9-registration` → … → `feat/events-pr1-scaffold`. Before Task 1, rebase onto the finished PR 9 branch and run the "Depends on" check. Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points from the worktree root, and module tests from the module directory: `cd modules/events && uv run pytest …`.
- Implementers are Claude subagents. Each one runs pytest in the foreground, commits its own tasks (one commit per task) and never pushes.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- **No real network in any test.** DNS is faked by swapping the guard module's `socket` attribute (images' `FakeSocket`, never `socket.getaddrinfo` itself: asyncpg would break). HTTP is faked by replacing the transport's inner factory with an `httpx.MockTransport`. The one real socket is the loopback TLS test (Task 4), with the guard widened inside that test only.
- Names: package `sm_events`, tables `events_subscription` and `events_external_item`, tasks `events.refresh_subscriptions` and `events.refresh_subscription`, queue `events`, source id `subscriptions` (`SOURCE_SUBSCRIPTIONS`), locale section `subscriptions`.
- The version stays what the base has (`uv run python scripts/bump_version.py --check-current`).
- Pins are ranges, never `==`. The new direct dependencies are `httpx>=0.27,<1`, `httpcore>=1,<2` and `anyio>=4,<5` (the versions already locked through images) and `cryptography>=42`. `icalendar` and `simple_module_background_tasks` come from earlier PRs.
- Settings stay DB-backed with no environment reads. `subscription_refresh_minutes` and `allow_private_subscription_urls` go in `EventsSettings`, never in `.env.example`. The one environment read is the stored-secret crypto's (`SM_SECRET_KEY` fallback and `SM_SECRET_KEY_PREVIOUS`). CLAUDE.md's sentence listing those modules gains events.
- Every query on an events table runs with a tenant bound. Core statements carry their own `tenant_id` predicate. `all_tenants()` is added in exactly two places: the beat's enumeration (Ruling 15) and the janitor's purge enumeration. `reencrypt_secrets.py` is a maintenance script under `simple_module_db.all_tenants()` too.
- Do not edit `sm_events/core/tenancy/*`. The `url_safety.py` and `core/crypto.py` copies change only together with their families (`uv run pytest -q scripts/tests/test_helper_parity.py`).
- **The subscription URL never appears** in a log record (including httpx's, httpcore's, the request log and uvicorn's), an error body, a status code, an Inertia prop, a revision or an exception message that is stored. Only `url_display`.
- 300-line cap; keep every `.py`/`.ts`/`.tsx` under 280 lines. The split is fixed in the File structure below.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`).
- No new Inertia page. `en.json` and `de.json` keep identical key trees and placeholders (`scripts/check_locales.py`); UI strings go through `t(keys.events.…)`.
- Postgres checks use dev-services' Postgres and scratch databases (`smpy_events_check` for alembic, `smpy_events_test` for pytest). Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **SSRF, including redirects and DNS rebinding.** A URL whose host resolves to `10.0.0.5`, to `[::ffff:127.0.0.1]`, to `64:ff9b::a9fe:a9fe` (NAT64 of the metadata address), or to one public and one private address must be refused, on save and on fetch. So must a public URL that redirects to `http://169.254.169.254/` or to a host that resolves privately, a `webcal://` redirect to a private host, and a redirect loop. When DNS answers public on the save check and private on the fetch, the fetch is refused. When DNS answers differently on two lookups within one fetch, the connection goes only to the address checked for that request. Covered by Task 3 (`test_address_matrix`, `test_mixed_answer_refused`, `test_intranet_switch_never_opens_loopback_or_metadata`) and Task 5 (`test_redirect_to_private_refused`, `test_rebinding_between_save_and_fetch`, `test_connection_pinned_to_checked_address`, `test_redirect_loop_capped`, `test_https_to_http_refused`).
2. **The stored URL as a secret.** The URL with its token never appears in an API response, a list, an Inertia prop, an error body, `error_code`, a log record at DEBUG from httpx, httpcore or events, or the database in the clear. A deleted row holds no ciphertext. Covered by Task 2 (`test_url_column_is_ciphertext`), Task 5 (`test_no_url_in_any_log_record`), Task 11 (`test_url_never_returned`, `test_delete_wipes_ciphertext`) and Task 2's re-encryption test.
3. **Remote content as untrusted.** An HTML error page served with 200, a 20 MiB body, an endless chunked body, a gzip bomb, a `Content-Length` lie, a hostile ICS file (PR 5's corpus), a 5,001-VEVENT feed and a title of `<img src=x onerror=alert(1)>` each end as a coded failure or as inert text, within the fetch deadline. Covered by Task 5 (`test_html_refused`, `test_body_cap_streams`, `test_encoded_body_refused`, `test_deadline_covers_slow_body`), Task 6 (`test_hostile_corpus_through_store`, `test_title_html_is_text`) and Task 12 (`ExternalDetail` renders the title as text).
4. **Re-export.** With a public, `public = true` subscription holding items on a public calendar, the public `calendar.ics`, `c/{cal}.ics`, the private token feed, the single-event `.ics`, the sitemap, the server-rendered listing, JSON-LD, the newsletter card search and the reminders tick contain nothing from it. Covered by Task 10 (`test_never_reexported`).
5. **Worker leases and strict tenancy.** Two workers ticking at once on Postgres fetch each subscription once. A worker whose lease expired mid-fetch cannot store. The tick on a `tenant_strict=True` engine enumerates through `simple_module_db.all_tenants()` and never writes tenant B's items under tenant A. Covered by Task 8 (`test_two_workers_one_fetch[pg]`, `test_lost_lease_cannot_store`) and Task 9 (`test_tick_under_strict_isolation`, `test_per_tenant_isolation`).
6. **Deleting items on a failed fetch.** A 304, a 500, a timeout, a `too_large` body, a scan failure, a parse failure and a lost lease each leave every item and `generation` unchanged; only a full 200 prunes. Covered by Task 6 (`test_prune_only_after_full_success`) and Task 9 (`test_failure_keeps_items`).

---

## File structure

`modules/events/sm_events/`:

| File | Responsibility | ≤ lines |
|---|---|---|
| `models/subscription.py` | `Subscription` (`events_subscription`) | 90 |
| `models/external_item.py` | `ExternalItem` (`events_external_item`) | 70 |
| `core/crypto.py` | stored-secret crypto copy (newsletter's, with the worker fallback) | 250 |
| `feeds/subscriptions/__init__.py` | docstring: Rulings 1–34 in brief, the "never re-exported" rule | 40 |
| `feeds/subscriptions/url_safety.py` | images' copy of the guard (parity family) | 190 |
| `feeds/subscriptions/policy.py` | `normalise`, `check`, `address_allowed`, `resolve_allowed`, `Policy` | 170 |
| `feeds/subscriptions/dns.py` | images' bounded resolver pool, adapted to `resolve_allowed` | 120 |
| `feeds/subscriptions/netsafe.py` | images' copy (parity family "pinned transport hardening") | 100 |
| `feeds/subscriptions/client.py` | `PinnedTransport`, `inner_transport` | 130 |
| `feeds/subscriptions/fetch.py` | `fetch_feed`, `FetchResult`, `FetchFailure`, redirects, caps | 250 |
| `feeds/subscriptions/urls.py` | `seal`, `unseal`, `display_of` | 80 |
| `feeds/subscriptions/items.py` | `MappedEvent` → `ItemRow` values, `content_hash`, span columns | 170 |
| `feeds/subscriptions/store.py` | `store_feed` (scan, parse, map, upsert, prune, counts) | 200 |
| `feeds/subscriptions/window.py` | SQL: subscriptions of a calendar, items in a window | 110 |
| `feeds/subscriptions/source.py` | `SubscriptionsSource` (expansion, overrides, merge) | 200 |
| `feeds/subscriptions/schedule.py` | interval, jitter, backoff, disable (pure) | 90 |
| `feeds/subscriptions/lease.py` | due predicate, claim, fenced store, release | 150 |
| `feeds/subscriptions/refresh.py` | `refresh_async` (enumerate, budget, per tenant), `refresh_one_async` | 230 |
| `feeds/subscriptions/launch.py` | `refresh_one` (eager inline or enqueue after commit) | 60 |
| `feeds/subscriptions/validate.py` | save-time URL check, dedupe, limits, rights | 170 |
| `feeds/subscriptions/service.py` | create, update, pause, resume, refresh, delete, list | 230 |
| `web/endpoints/subscriptions_api.py` | the routes | 200 |
| `web/schemas/subscriptions.py` | `SubscriptionIn`, `SubscriptionPatch`, `SubscriptionOut` | 110 |
| `ui/components/subscriptions/SubscriptionsDialog.tsx`, `SubscriptionForm.tsx`, `SubscriptionRow.tsx` | the dialog | ≤ 220 each |
| `ui/components/subscriptions/ExternalChip.tsx`, `ExternalDetail.tsx` | the external occurrence | ≤ 120 each |
| `ui/extensions/builtins.ts` | the built-in TS source registration | 40 |
| `ui/hooks/useSubscriptions.ts`, `ui/utils/api-subscriptions.ts` | client and state | ≤ 150 each |

Modified: `core/constants.py`, `core/errors.py`, `core/settings/__init__.py`, `models/__init__.py`, `calendar/extension_types.py` and `calendar/occurrence.py` (`origin_label`), `calendar/plugin_validate.py`, `calendar/plugin_scope.py` (`include_subscriptions`), `calendar/sources.py` (`register_builtins`), `feeds/plugin_items.py`, `feeds/importing/mapper.py` and `text.py` (`url`, `clean_line`), `feeds/importing/janitor.py`, `tasks.py`, `task_config.py`, `module.py` (router), `web/endpoints/views.py` (Calendars props `can_publish`), `pages/Calendars.tsx`, `ui/components/calendars/CalendarRow.tsx`, `ui/extensions/load.ts`, `ui/calendar/StatusBar.tsx`, `locales/en.json`, `locales/de.json`. Repo: `scripts/tests/parity_families.py`, `parity_crypto.py`, `scripts/reencrypt_support.py`, `scripts/reencrypt_secrets.py`, `scripts/tests/test_reencrypt*.py`, `host/migrations/versions/<rev>_events_subscriptions.py`, `docs/secret-key-rotation.md`, `CLAUDE.md`, `CHANGELOG.md`.

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events suite green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: tables, URL safety, the pinned client, the fetcher** | 1–5 | constants, errors, settings, both tables and the migration; the crypto copy and re-encryption; the guard copy and events' policy; DNS pool, netsafe and the pinned transport; the conditional, capped, redirect-checked fetch |
| **B: parse/store, the source, the beat with leases** | 6–10 | mapping and storing with prune-on-success; the built-in source in the read; schedule and leases; the beat, refresh-one and the janitor; the never-re-exported matrix |
| **C: API, console dialog, docs, module close-out** | 11–13 | the service and API; the Subscriptions dialog and the external chip/detail; docs, CLAUDE.md, CHANGELOG, spec and index close-out, branch verification |

---

### Task 1: Constants, errors, settings, the two tables and their migration

**Files:**
- Modify: `sm_events/core/constants.py`. Add every bound and code of Rulings 1–35, plus `SOURCE_SUBSCRIPTIONS = "subscriptions"`, `SUBSCRIPTION_STATUSES = ("pending", "ok", "error", "paused", "disabled")`, `SUBSCRIPTION_FAILURE_CODES` (Ruling 11's tuple), `URL_REFUSAL_CODES = {"invalid_url": "url_invalid", "invalid_scheme": "url_scheme", "userinfo_not_allowed": "url_userinfo", "port_not_allowed": "url_port", "missing_host": "url_invalid", "unresolvable_host": "url_unresolvable", "non_public_address": "url_not_public"}`, `REFRESH_SUBSCRIPTIONS = "events.refresh_subscriptions"` and `REFRESH_SUBSCRIPTION = "events.refresh_subscription"`.
- Modify: `sm_events/core/errors.py`. Add `SubscriptionExists(Conflict)`, `SubscriptionLimit(Conflict)`, `UrlRefused(Invalid)` (constructed with one of the six `url_*` codes), `SubscriptionNotPublicCalendar(Invalid)` and `RefreshTooSoon` (429, carrying `retry_after: int`, which the handler sends as `Retry-After`).
- Modify: `sm_events/core/settings/__init__.py`. Add `subscription_refresh_minutes: int = 60` (docstring: clamped to 15–1440 where it is read) and `allow_private_subscription_urls: bool = False` (docstring: Rulings 8–9 in two sentences; no validators, per the module's docstring).
- Create: `sm_events/models/subscription.py`, `sm_events/models/external_item.py`, and export both from `models/__init__.py`.
- Create: `host/migrations/versions/<rev>_events_subscriptions.py`, chained off the single head.
- Test: `tests/core/test_errors.py`, `tests/core/test_settings.py`, `tests/models/test_subscription_models.py`

**Interfaces:**
- `Subscription` (`MultiTenantMixin`, the module's soft-delete mixin):
  - identity and ownership: `id` (UUID PK), `calendar_id` (FK `events_calendar.id` `ON DELETE CASCADE`, indexed), `created_by` (str 64);
  - the URL: `url_enc` (Text), `url_display` (str 300);
  - the console's fields: `label` (str 100), `color` (str 7, nullable), `refresh_minutes` (int, nullable), `public` (bool, default false);
  - state: `status` (str 16, default `pending`), `error_code` (str 40, nullable), `last_http_status` (int, nullable);
  - conditional requests: `etag` (str 200, nullable), `last_modified` (str 64, nullable);
  - times: `last_fetched_at`, `last_ok_at`, `next_fetch_at` (indexed with `status`);
  - counters: `consecutive_failures` (int 0), `generation` (int 0), `item_count` (int 0), `last_counts` (JSON `{stored, skipped, reasons: {code: n}}`);
  - the lease: `lease_owner` (str 32, nullable), `lease_until` (nullable);
  - audit: `created_at`, `updated_at`.
  - Indexes: `ix_events_subscription_due (status, next_fetch_at)` and `ix_events_subscription_calendar (tenant_id, calendar_id)`.
- `ExternalItem` (`MultiTenantMixin`, no soft delete):
  - identity: `id` (big PK, `sqlite_autoincrement`), `subscription_id` (FK `events_subscription.id` `ON DELETE CASCADE`), `uid` (str 255);
  - times and rule: `all_day`, `starts_at`, `ends_at`, `timezone` (str 64), `rrule` (str 500, nullable), `recurrence_until` (nullable), `overrides` (JSON list), `span_start`, `span_end` (nullable);
  - content: `title` (str 300), `location` (str 200, nullable), `url` (str 2000, nullable), `cancelled`, `private_class`;
  - bookkeeping: `content_hash` (str 64), `seen_generation` (int), `updated_at`.
  - Unique: `uq_events_external_item_uid (tenant_id, subscription_id, uid)`. Index: `ix_events_external_item_window (tenant_id, subscription_id, span_start)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_errors.py::test_subscription_codes`: parametrized over each new class, checking status, code and the `{"detail","code"}` body. `RefreshTooSoon(retry_after=120)` renders `Retry-After: 120`.
  - `test_settings.py::test_subscription_defaults`: `EventsSettings().subscription_refresh_minutes == 60` and `allow_private_subscription_urls is False`.
  - `test_subscription_models.py`: `test_tables_and_indexes` (names, the unique constraint, both FKs `CASCADE`); `test_tenant_guarded` (an unbound select on either table raises `TenantUnbound`); `test_item_uid_unique_per_subscription`.
- [ ] **Step 2: Run** (headroom first) `cd modules/events && uv run pytest -q tests/core/test_errors.py tests/core/test_settings.py tests/models/test_subscription_models.py`. Expected: ImportError.
- [ ] **Step 3: Implement.** Then autogenerate from the worktree root (`uv run alembic revision --autogenerate -m "events subscriptions"`), trim it to the two tables, and check it on SQLite and Postgres (`smpy_events_check`): `alembic upgrade heads`, `alembic check`, `alembic downgrade -1`, `upgrade heads`. Run `uv run python scripts/check_migration_heads.py`.
- [ ] **Step 4: Run** the tests (pass), `uv run python scripts/check_hardcoded_strings.py` and `scripts/check_rules.py` (pass).
- [ ] **Step 5: Commit** `feat(events): subscription and external item tables`.

### Task 2: The stored-secret crypto copy, sealing the URL, and re-encryption

**Files:**
- Create: `sm_events/core/crypto.py` (a copy of `modules/newsletter/sm_newsletter/core/crypto.py`, with `PACKAGE` from events' constants and events' own three messages)
- Create: `sm_events/feeds/subscriptions/__init__.py` (docstring), `feeds/subscriptions/urls.py`
- Modify: `modules/events/pyproject.toml` (`cryptography>=42`), `uv.lock`
- Modify: `scripts/tests/parity_crypto.py` (add `EVENTS = "modules/events/sm_events/core/crypto.py"` to both families, with `_EVENTS_MESSAGES`), `scripts/reencrypt_support.py` (`COLUMN_TARGETS`, `ColumnRow`, and the planning function extended to column rows), `scripts/reencrypt_secrets.py` (read and rewrite column targets under `simple_module_db.all_tenants()`, using Core with a compare-and-set `WHERE id = :id AND url_enc = :old`)
- Test: `tests/feeds/subscriptions/test_urls.py`, `scripts/tests/test_reencrypt_support.py` (extend), `scripts/tests/test_secret_crypto_formats.py` (extend with events' vectors), `scripts/tests/test_helper_parity.py` (runs as is)

**Interfaces:**

```python
# urls.py
def seal(url: str) -> str                    # crypto.encrypt_value(url)
def unseal(stored: str) -> str               # raises UrlUnreadable when it does not open (never returns plaintext for a bad prefix)
def display_of(url: str) -> str              # "https://cal.example.com/…"; port kept when not the scheme default
class UrlUnreadable(Exception): ...
# reencrypt_support.py
COLUMN_TARGETS: Final[dict[str, tuple[tuple[str, str], ...]]] = {"sm_events": (("events_subscription", "url_enc"),)}
```

- [ ] **Step 1: Write the failing tests:**
  - `test_urls.py`:
    - `test_seal_round_trip`;
    - `test_url_column_is_ciphertext`: a `Subscription` saved with `seal(u)` has `url_enc.startswith("enc:v2:")`, and the raw column contains no substring of `u`'s path;
    - `test_unseal_with_previous_key` (`SM_SECRET_KEY_PREVIOUS` set, a value sealed under the old key opens);
    - `test_unseal_unreadable` (a wrong key or `enc:v9:` raises `UrlUnreadable`);
    - `test_display_of`, parametrized: `https://calendar.google.com/calendar/ical/x%40group/private-abc/basic.ics` → `https://calendar.google.com/…`; `http://10.0.0.5:8080/a?token=t` → `http://10.0.0.5:8080/…`; an IDN host → its `xn--` form;
    - `test_worker_fallback_reads_env_secret` (no app, with `SM_SECRET_KEY` in the environment).
  - `test_secret_crypto_formats.py`: events' `enc:v2:` vector under the fixed test key decrypts, and the derivation uses info `b"sm_events:settings"`.
  - `test_reencrypt_support.py`: `test_column_rows_planned` (a row under the previous key gives `ROTATE`; a current one `CURRENT`; an unreadable one `UNREADABLE` stops the run; an empty `url_enc` (a deleted row) gives `EMPTY`).
- [ ] **Step 2: Run** `cd modules/events && uv run pytest -q tests/feeds/subscriptions/test_urls.py`, and from the root `uv run pytest -q scripts/tests/test_reencrypt_support.py scripts/tests/test_secret_crypto_formats.py scripts/tests/test_helper_parity.py`. Expected: fail.
- [ ] **Step 3: Implement.** Copy the crypto file byte for byte apart from the messages, and add the copy to both parity families. `reencrypt_secrets.py` prints column rows as `events_subscription.url_enc (tenant <t>, id <id>)`, never with a value.
- [ ] **Step 4: Run** the same commands: all pass.
- [ ] **Step 5: Commit** `feat(events): encrypt subscription URLs with the stored-secret crypto`.

### Task 3: The address guard copy and events' URL policy

**Files:**
- Create: `sm_events/feeds/subscriptions/url_safety.py` (a byte-for-byte copy of `modules/images/sm_images/ingest/imports/url_safety.py`, except the module docstring and the log message inside `resolve_public`, which the family's `differ` allows)
- Create: `sm_events/feeds/subscriptions/policy.py`
- Modify: `scripts/tests/parity_families.py` (add `Copy("modules/events/sm_events/feeds/subscriptions/url_safety.py")` to "SSRF address guard". `check_url` and `resolve_public` stay in `differ`, because ai still differs; extend the reason to say that events' copy equals images')
- Test: `tests/feeds/subscriptions/test_policy.py`, `tests/support/net.py` (a port of `modules/images/tests/support/fetch.py`: `resolver`, `inner`, `body`, `PUBLIC_IP`, `OTHER_PUBLIC_IP`, `PUBLIC_IPV6`, patching **events'** `url_safety.socket`)

**Interfaces:**

```python
@dataclass(frozen=True)
class Policy:
    allow_private: bool                       # the setting
    may_use_private: bool = True              # False on a save by a non-manager (Ruling 9)
def normalise(raw: str) -> str                # Ruling 3; raises UnsafeURLError("invalid_url")
def check(url: str | httpx.URL, policy: Policy) -> tuple[str, int]
    # Rulings 4-6: scheme (https, or http with the switch), userinfo, port; literal IPs via address_allowed
def address_allowed(ip: IPAddress, *, allow_private: bool) -> bool
    # is_public_address(ip) or (allow_private and ip is in RFC1918 | fc00::/7 | 100.64/10 | 198.18/15
    #   and not loopback/link-local/metadata/unspecified/multicast/reserved, embedded forms included)
def resolve_allowed(url: httpx.URL, policy: Policy) -> tuple[str, tuple[str, ...]]
    # blocking; getaddrinfo through url_safety's `socket`; every address must pass; codes as images'
def effective(policy_setting: bool, *, may_use_private: bool) -> Policy
```

- [ ] **Step 1: Write the failing tests** (`test_policy.py`, using `tests/support/net.resolver`):
  - `test_normalise`: `" webcal://Cal.Example/x.ics#frag "` → `"https://cal.example/x.ics"`; `webcals:` too; 2001 characters → `invalid_url`.
  - `test_scheme_rules`: `http://` is refused (`invalid_scheme`) with the switch off and allowed with it on; `ftp:`, `file:`, `data:`, `javascript:` and `gopher:` are always refused.
  - `test_userinfo_refused`: `https://u:p@h/`, `https://u@h/` and `https://%75@h/` give `userinfo_not_allowed`.
  - `test_ports`: 443 passes; 8443 gives `port_not_allowed` with the switch off and passes with it on; port 0 is refused.
  - `test_address_matrix`, parametrized over resolved addresses, expecting refusal with the switch off: `127.0.0.1`, `10.1.2.3`, `172.16.0.1`, `192.168.1.1`, `100.64.0.1`, `169.254.169.254`, `0.0.0.0`, `224.0.0.1`, `240.0.0.1`, `198.18.0.1`, `::1`, `::`, `fe80::1`, `fc00::1`, `fd00:ec2::254`, `::ffff:127.0.0.1`, `::ffff:10.0.0.1`, `::127.0.0.1`, `64:ff9b::a9fe:a9fe`, `2002:7f00:0001::`, a Teredo address embedding `10.0.0.1`, and `ff02::1`. `93.184.216.34` and `2606:2800:220:1:248:1893:25c8:1946` pass.
  - `test_literal_hosts`: `https://[::ffff:7f00:1]/`, `https://2130706433/` and `https://0x7f.1/` are refused without DNS (whatever httpx parses them to, the result is not public).
  - `test_mixed_answer_refused`: a host resolving to `[PUBLIC_IP, "10.0.0.1"]` is refused.
  - `test_intranet_switch_opens_private_ranges_only`: with `allow_private=True`, `10.1.2.3`, `192.168.1.1`, `fd12::1` and `100.64.0.1` pass.
  - `test_intranet_switch_never_opens_loopback_or_metadata`: with `allow_private=True`, `127.0.0.1`, `::1`, `169.254.169.254`, `fd00:ec2::254`, `fe80::1`, `0.0.0.0`, `::ffff:127.0.0.1`, `64:ff9b::7f00:1` and `224.0.0.1` are still refused.
  - `test_non_manager_cannot_use_switch`: `Policy(allow_private=True, may_use_private=False)` behaves like the switch off for addresses, scheme and ports.
  - `test_unresolvable` (`unresolvable_host`), and `test_error_never_echoes_url` (`str(exc)` is the code only).
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_policy.py`, and from the root `uv run pytest -q scripts/tests/test_helper_parity.py`. Expected: fail.
- [ ] **Step 3: Implement.** `address_allowed` reuses `_embedded_ipv4` and `_METADATA` from the copy, and keeps its private-range table in `policy.py`.
- [ ] **Step 4: Run** both: pass.
- [ ] **Step 5: Commit** `feat(events): subscription URL policy over the shared address guard`.

### Task 4: The bounded resolver, `netsafe` and the pinned transport

**Files:**
- Create: `sm_events/feeds/subscriptions/dns.py` (images' `dns.py`, calling `policy.resolve_allowed(url, policy)` and raising `FetchFailure("timeout")` on expiry; pool prefix `sm-events-dns`, `POOL_SIZE = 4`)
- Create: `sm_events/feeds/subscriptions/netsafe.py` (a byte-for-byte copy of images')
- Create: `sm_events/feeds/subscriptions/client.py`
- Modify: `modules/events/pyproject.toml` (`httpx>=0.27,<1`, `httpcore>=1,<2`, `anyio>=4,<5`), `uv.lock`; `scripts/tests/parity_families.py` (a new family "pinned transport hardening": images' and events' `netsafe.py`, `shared=None`)
- Test: `tests/feeds/subscriptions/test_client.py`, `tests/feeds/subscriptions/test_client_tls.py` (a port of `modules/images/tests/ingest/imports/test_imports_fetch_tls.py`)

**Interfaces:**

```python
class PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, policy: Policy, *, inner: Callable[[], httpx.AsyncBaseTransport] | None = None) -> None
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response
        # resolve_bounded(request.url, policy) per request; host rewritten to each checked IP (≤ 4, connect errors only);
        # Host header kept; extensions["sni_hostname"] = host on https; inner per original origin, hardened
    async def aclose(self) -> None
def inner_transport() -> httpx.AsyncBaseTransport   # AsyncHTTPTransport(verify=True, trust_env=False, limits=Limits(max_keepalive_connections=0))
```

- [ ] **Step 1: Write the failing tests:**
  - `test_client.py`:
    - `test_connection_pinned_with_host_and_sni`: the inner handler sees `url.host == PUBLIC_IP`, `Host: cal.example` and `sni_hostname == "cal.example"`.
    - `test_connection_pinned_to_checked_address`: the resolver returns `PUBLIC_IP` on its first call and `"127.0.0.1"` on every later one. One `handle_async_request` dials `PUBLIC_IP` only, and a second request is refused. This is the rebinding simulation: the check and the connection use one answer.
    - `test_ipv6_pinned`.
    - `test_dead_first_address_falls_back`, `test_non_connect_errors_do_not_retry`, `test_at_most_four_addresses`.
    - `test_private_refused_before_connect` (the inner handler sees nothing).
    - `test_dns_timeout_fails_closed`: a resolver that sleeps 10 s gives `FetchFailure("timeout")` within `DNS_TIMEOUT_SECONDS + 1`.
    - `test_proxy_env_ignored`: with `HTTPS_PROXY` set, the inner handler still gets the pinned IP.
  - `test_client_tls.py`: the images TLS proof ported (a loopback TLS server with a certificate for `cal.example`; DNS faked to 127.0.0.1; `address_allowed` widened to 127.0.0.1 inside the test only): the name verifies, and `wrong.example` on the same IP fails `tls`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_client.py tests/feeds/subscriptions/test_client_tls.py`. Expected: fail.
- [ ] **Step 3: Implement**, then `uv sync --all-packages --all-extras --no-extra anonymize` from the root (headroom first).
- [ ] **Step 4: Run** the tests and `scripts/tests/test_helper_parity.py`: pass.
- [ ] **Step 5: Commit** `feat(events): pinned transport for subscription fetches`.

### Task 5: One fetch: conditional, capped, redirect-checked

**Files:**
- Create: `sm_events/feeds/subscriptions/fetch.py`
- Test: `tests/feeds/subscriptions/test_fetch.py`, `tests/feeds/subscriptions/test_fetch_limits.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FetchResult:
    status: Literal["ok", "not_modified"]
    body: bytes                     # b"" for not_modified
    etag: str | None; last_modified: str | None; http_status: int
class FetchFailure(Exception):
    def __init__(self, code: str, *, http_status: int | None = None) -> None    # str(self) == code
async def fetch_feed(url: str, *, policy: Policy, etag: str | None, last_modified: str | None,
                     max_bytes: int, timeout: float = SUBSCRIPTION_FETCH_SECONDS,
                     transport_factory: Callable[[Policy], httpx.AsyncBaseTransport] | None = None) -> FetchResult
USER_AGENT: Final[str]              # f"SimpleModule-Events/{version}"
```

- [ ] **Step 1: Write the failing tests** (`resolver` plus `inner` from `tests/support/net.py`):
  - `test_fetch.py`:
    - `test_ok_returns_body_and_validators`.
    - `test_headers_exact`: the request carries exactly `host`, `user-agent`, `accept`, `accept-encoding: identity`, and no `cookie`, `authorization` or `referer`. The User-Agent matches `^SimpleModule-Events/[^ ]+$`.
    - `test_conditional_headers_first_hop_only`.
    - `test_304_is_not_modified`.
    - `test_410_is_gone`, and `test_status_codes` (404 and 500 give `http_status` with the number).
    - `test_redirect_followed_and_each_hop_pinned` (two public hops, each dialled at its own checked IP).
    - `test_redirect_to_private_refused`: `Location: http://169.254.169.254/latest/meta-data/`, `Location: https://internal.example/` (resolving to `10.0.0.1`) and `Location: webcal://internal.example/` each give a `url_*` failure, and the inner handler never sees the second host.
    - `test_https_to_http_refused`: `insecure_redirect`, even with the switch on.
    - `test_redirect_loop_capped`: A → B → A … gives `too_many_redirects` after 3 hops, and exactly 4 requests are seen.
    - `test_redirect_without_location`.
    - `test_rebinding_between_save_and_fetch`: the host resolves public, then the table is switched to `10.0.0.1`. `fetch_feed` gives `url_not_public` and nothing is dialled.
    - `test_cookies_not_carried`: hop 1 answers `Set-Cookie: s=1` and a 302, and hop 2's request has no `cookie`.
    - `test_no_url_in_any_log_record`: with `caplog` at DEBUG for the root logger, a successful fetch, a redirect, a refused redirect and a 500 of `https://cal.example/private-TOKEN123/basic.ics` leave no record whose `getMessage()` or `__dict__` values contain `TOKEN123`.
  - `test_fetch_limits.py`:
    - `test_html_refused`: `Content-Type: text/html` gives `unexpected_content_type`.
    - `test_missing_content_type_sniffed`: a body starting `<html>` gives `ics_invalid`, and a body starting `BEGIN:VCALENDAR` passes.
    - `test_accepted_media_types`, parametrized over the five types of Ruling 10, with parameters such as `; charset=utf-8`.
    - `test_encoded_body_refused`: `Content-Encoding: gzip` with a 10 KB gzip of 1 GB of zeros (built with `zlib` streaming, never in memory) gives `unsupported_encoding`, without decompressing.
    - `test_declared_length_over_cap_refused_before_read` (the handler's body generator is never iterated).
    - `test_body_cap_streams`: an endless chunked body gives `too_large` after `max_bytes + chunk` bytes.
    - `test_exactly_cap_accepted`.
    - `test_deadline_covers_slow_body`: a body that yields one byte per second gives `timeout` within `timeout + 1` s (the test passes `timeout=2`).
    - `test_connect_and_tls_errors_mapped` (`connect_failed`, `tls_failed`).
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_fetch.py tests/feeds/subscriptions/test_fetch_limits.py`. Expected: fail.
- [ ] **Step 3: Implement.** Build each hop's request with `httpx.Request("GET", url, headers=…, extensions={"timeout": {"connect": 5, "read": 15, "write": 5, "pool": 5}})` and call `transport.handle_async_request` inside `asyncio.timeout_at(deadline)`. Use a fresh `PinnedTransport` per hop, and close each response and transport in `finally`. Copy images' `_capped_body` loop.
- [ ] **Step 4: Run** the tests: pass.
- [ ] **Step 5: Commit** `feat(events): safe conditional fetch of a subscription feed`.

**End of batch A.** Run the events suite for `tests/feeds/subscriptions`, `scripts/tests/test_helper_parity.py`, `basedpyright` (unchanged include list), `check_rules.py`, `check_file_size.py` and `check_hardcoded_strings.py`.

---

### Task 6: Mapping and storing, with pruning only after full success

**Files:**
- Modify: `sm_events/feeds/importing/mapper.py` (`MappedEvent.url`), `feeds/importing/text.py` (`clean_line`; `clean_title` built on it), and the venue mapping through `clean_line`. Add their tests to PR 5's `test_mapper.py` and `test_text.py`.
- Create: `sm_events/feeds/subscriptions/items.py`, `feeds/subscriptions/store.py`
- Test: `tests/feeds/subscriptions/test_items.py`, `tests/feeds/subscriptions/test_store.py`, `tests/support/subscriptions.py` (`seed_subscription(db, calendar, **fields)` with a sealed URL, `ics(*vevents) -> bytes`, `vevent(**props) -> str`)

**Interfaces:**

```python
# items.py
@dataclass(frozen=True)
class ItemValues:
    uid: str; all_day: bool; starts_at: datetime; ends_at: datetime; timezone: str
    rrule: str | None; recurrence_until: datetime | None; overrides: list[dict[str, Any]]
    span_start: datetime; span_end: datetime | None
    title: str; location: str | None; url: str | None; cancelled: bool; private_class: bool
    content_hash: str
def to_values(mapped: MappedEvent) -> ItemValues           # raises ItemSkip(code) on InvalidTimes/InvalidRule (Ruling 21)
# store.py
@dataclass(frozen=True)
class StoreCounts: stored: int; skipped: int; reasons: dict[str, int]
async def store_feed(db, sub: Subscription, *, calendar_tz: str, body: bytes) -> StoreCounts
    # scan -> from_ical -> map_calendar(categories={}) -> to_values -> upsert by uid (hash short-circuit)
    # -> generation += 1 -> delete seen_generation < generation -> item_count, last_counts
    # raises FetchFailure(ics_encoding | ics_invalid | too_many_events) BEFORE any write
```

- [ ] **Step 1: Write the failing tests:**
  - PR 5's tests: `test_mapped_url_http_only` (`URL:javascript:x`, `URL:data:x` and a URL containing a space give `None`; `https://a/x` is kept); `test_clean_line` (control characters, U+202E and a 201-character venue).
  - `test_items.py`:
    - `test_one_off_columns` (UTC, `span_start == starts_at`, `span_end == ends_at`).
    - `test_series_span`: weekly with `COUNT=3` gives `span_end == recurrence_until`; an endless rule gives `span_end is None`; a moved override two weeks after the last instance stretches `span_end`, and one before the start lowers `span_start`.
    - `test_all_day_uses_pr2_convention`.
    - `test_hash_stable_and_sensitive` (equal for equal input; any field change alters it).
    - `test_title_html_is_text`: `SUMMARY:<img src=x onerror=alert(1)>` is stored verbatim as text (no tag removal is needed, because nothing renders HTML; Task 12 proves the rendering), with control characters removed.
  - `test_store.py`:
    - `test_first_fetch_stores_and_counts`: three VEVENTs (one with `TZID=My Zone`, one with `FREQ=SECONDLY`) give `stored=1`, `skipped=2`, `reasons={"unknown_timezone": 1, "unsupported_rule": 1}`, `generation == 1` and `item_count == 1`.
    - `test_unchanged_rewrites_nothing`: the same body twice leaves `updated_at` of each row unchanged and gives `generation == 2`.
    - `test_changed_item_updated`.
    - `test_vanished_item_deleted_after_success`.
    - `test_empty_feed_clears`.
    - `test_prune_only_after_full_success`: with three items stored, each of `scan` failure (a NUL byte), `from_ical` failure (monkeypatched to raise), `too_many_events` (5,001 VEVENTs built by the corpus) and an exception raised in `to_values` for the second item leaves all three rows, `generation` and `item_count` unchanged after the session rolls back.
    - `test_hostile_corpus_through_store`: every builder of PR 5's `tests/feeds/importing/corpus.py` raises a `FetchFailure` with PR 5's code in under 2 s, and writes nothing.
    - `test_recurrence_children_fold_into_master` (one row, with overrides).
    - `test_other_subscription_untouched` (the prune is scoped to its subscription and tenant).
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_items.py tests/feeds/subscriptions/test_store.py tests/feeds/importing/test_mapper.py tests/feeds/importing/test_text.py`. Expected: fail.
- [ ] **Step 3: Implement.** Map everything in memory first, then write. The upsert selects the subscription's existing `(uid, id, content_hash)` once, then runs inserts, updates and a `seen_generation` bump in chunks of 500. The delete is one Core statement with its own `tenant_id` predicate.
- [ ] **Step 4: Run** the tests on SQLite and Postgres: pass. Run PR 5's import tests (`tests/feeds/importing`) too: still pass.
- [ ] **Step 5: Commit** `feat(events): store external items, pruning only after a full fetch`.

### Task 7: The `subscriptions` source in the occurrences read

**Files:**
- Create: `sm_events/feeds/subscriptions/window.py`, `feeds/subscriptions/source.py`
- Modify: `calendar/extension_types.py` (`SourceOccurrence.origin_label: str | None = None`, ≤ 100), `calendar/occurrence.py` (`Occurrence.origin_label: str | None = None`), `calendar/plugin_validate.py` (validate and copy `origin_label` like the title), `calendar/sources.py` (`register_builtins` also registers `SUBSCRIPTIONS_SOURCE`), `calendar/plugin_scope.py` (`include_subscriptions: bool = True`; the synthetic entry of Ruling 24), `web/endpoints/extensions_api.py` (`GET /sources` excludes built-ins, if it does not already), `ui/utils/types-events.ts` (`origin_label?: string | null`)
- Test: `tests/feeds/subscriptions/test_source.py`, `tests/calendar/test_plugin_scope.py` (extend), `tests/web/test_sources_api.py` (extend)

**Interfaces:**

```python
# window.py
async def live_subscriptions(db, calendar_id: uuid.UUID, *, public_only: bool) -> list[Subscription]
async def calendars_with_subscriptions(db, calendar_ids: Collection[uuid.UUID]) -> set[uuid.UUID]
async def items_in_window(db, subscription_ids: Collection[uuid.UUID], start: datetime, end: datetime,
                          *, limit: int, public_only: bool) -> tuple[list[ExternalItem], list[ExternalItem], bool]
    # (one-offs ordered by starts_at LIMIT limit+1, series LIMIT SERIES_FETCH_MAX, series_truncated)
# source.py
class SubscriptionsSource:            # id = SOURCE_SUBSCRIPTIONS, label_key, icon "rss", public True, settings_model None, color None
    async def occurrences(self, ctx: SourceContext, start: datetime, end: datetime) -> list[SourceOccurrence]
SUBSCRIPTIONS_SOURCE: Final = SubscriptionsSource()
def item_key(sub_id: uuid.UUID, uid: str, original_start: datetime | None) -> str
```

- [ ] **Step 1: Write the failing tests:**
  - `test_source.py` (items seeded with Task 6's `store_feed`, or inserted directly):
    - `test_one_off_and_series_in_window`: a weekly Vienna 10:00 series across 29 March keeps 10:00 local.
    - `test_overrides_applied`: an EXDATE is gone, a cancelled instance has `status cancelled`, and a moved instance shows at its new time with its original key.
    - `test_moved_into_window_from_outside` (the span columns find it).
    - `test_expansion_stops_at_window`: an endless daily rule over a 400-day window yields at most `ctx.limit + 1` items, and `instances` is called with `window_end == end` (spied).
    - `test_cap_reports_truncated_through_runner`: 600 one-offs give 500 items and status `truncated`.
    - `test_public_only_items_for_anonymous`: with `ctx.viewer=None`, a `public=false` subscription gives nothing, and a `public=true` one gives its items except `private_class` ones.
    - `test_signed_in_sees_private_class`.
    - `test_paused_and_error_still_shown`, `test_deleted_hidden`.
    - `test_fields`: `origin_label` equals the label, `color` the subscription colour, `editable False`, `url` kept, `lang None`, and the key matches `^[0-9a-f]{32}:[0-9a-f]{24}(:\d{8}T\d{6}Z)?$`.
    - `test_other_calendar_and_tenant_isolated`.
  - `test_plugin_scope.py`: `test_implicit_subscriptions_entry` (a calendar with a live subscription gets one `subscriptions` call without any stored entry; a calendar without one gets none; `include_subscriptions=False` gives none).
  - `test_sources_api.py`: `test_builtin_subscriptions_not_listed` and `test_put_subscriptions_entry_refused` (422 `builtin_source`).
  - `test_plugin_validate.py`: `test_origin_label_cleaned_and_bounded` (control characters stripped, 101 characters invalid).
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_source.py tests/calendar/test_plugin_scope.py tests/calendar/test_plugin_validate.py tests/web/test_sources_api.py`. Expected: fail.
- [ ] **Step 3: Implement.** The source expands each series with PR 2's `instances` and applies overrides keyed by `original_start`. It turns one-offs and instances into `SourceOccurrence` (all-day: `start_date`/`end_date` from `times.all_day_dates`) and merges them with `heapq.merge` by `(start, end, key)`, stopping at `ctx.limit + 1`.
- [ ] **Step 4: Run** the tests on SQLite and Postgres: pass. Run PR 6's `tests/calendar` and `tests/web/test_occurrences_api.py`: still pass.
- [ ] **Step 5: Commit** `feat(events): external subscriptions as a built-in read-only source`.

### Task 8: Schedule, backoff and leases

**Files:**
- Create: `sm_events/feeds/subscriptions/schedule.py`, `feeds/subscriptions/lease.py`
- Test: `tests/feeds/subscriptions/test_schedule.py`, `tests/feeds/subscriptions/test_lease.py`

**Interfaces:**

```python
# schedule.py (pure)
def effective_minutes(sub_minutes: int | None, setting_minutes: int) -> int           # clamp [15, 1440]
def after_success(now: datetime, minutes: int, rng: random.Random) -> datetime
def after_failure(now: datetime, minutes: int, failures: int, code: str, rng: random.Random) -> tuple[datetime, str]
    # (next_fetch_at, status): "disabled" at failures >= 10 or code in {"gone", "url_unreadable"}, else "error"
# lease.py
def due(now: datetime) -> ColumnElement[bool]                    # Ruling 15's predicate (without the calendar join)
async def claim(db, sub_id: uuid.UUID, *, owner: str, now: datetime) -> bool
async def fenced(db, sub_id: uuid.UUID, *, owner: str, now: datetime) -> Subscription | None
    # SELECT ... FOR UPDATE (pg) WHERE lease_owner = owner AND lease_until > now; None = lease lost
async def release(db, sub: Subscription) -> None
```

- [ ] **Step 1: Write the failing tests:**
  - `test_schedule.py`:
    - `test_clamp` (5 → 15, 2000 → 1440, `None` → the setting);
    - `test_jitter_bounds` (1,000 draws within ±10%);
    - `test_backoff_doubles_and_caps` (failures 1–6 at 60 minutes give 1, 2, 4, 8, 16 and then 24 hours, each ±10%);
    - `test_disable_after_ten`;
    - `test_gone_and_unreadable_disable_at_once`;
    - `test_url_codes_do_not_disable_at_once`.
  - `test_lease.py`:
    - `test_claim_once`: two claims in a row; the second is false.
    - `test_expired_lease_reclaimable`.
    - `test_paused_disabled_deleted_not_due`.
    - `test_lost_lease_cannot_store`: worker A claims and its lease expires (clock moved), worker B claims, and A's `fenced` returns `None`.
    - `test_two_workers_one_fetch[pg]` (Postgres only): two sessions on two connections call `claim` concurrently for the same 20 due ids through `asyncio.gather`, and each id is won exactly once.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_schedule.py tests/feeds/subscriptions/test_lease.py`, with `SM_TEST_DATABASE_URL` for the pg case. Expected: fail.
- [ ] **Step 3: Implement.** `claim` is one Core `UPDATE … WHERE tenant_id = :t AND id = :id AND <due>` and checks `rowcount == 1`.
- [ ] **Step 4: Run** the tests on SQLite and Postgres: pass.
- [ ] **Step 5: Commit** `feat(events): subscription scheduling, backoff and leases`.

### Task 9: The beat, refresh-one and the janitor

**Files:**
- Create: `sm_events/feeds/subscriptions/refresh.py`, `feeds/subscriptions/launch.py`
- Modify: `sm_events/task_config.py`. Add `REFRESH_SUBSCRIPTIONS` and `REFRESH_SUBSCRIPTION`, routed to queue `events`, and `BEAT_SCHEDULE["events-refresh-subscriptions"] = {"task": REFRESH_SUBSCRIPTIONS, "schedule": 60.0, "options": {"queue": "events", "expires": 55}}`.
- Modify: `sm_events/tasks.py`. Add `refresh_subscriptions()` and `refresh_subscription(tenant_id: str, subscription_id: str)`, each through `run_platform`, each logging counts only.
- Modify: `feeds/importing/janitor.py` (purge subscriptions soft-deleted more than 30 days ago, per tenant), the `Makefile` and `.github/workflows/ci.yml` worker comments (add `events.refresh_subscriptions`).
- Test: `tests/feeds/subscriptions/test_refresh.py`, `tests/feeds/subscriptions/test_refresh_worker.py`, `tests/core/test_task_discovery.py` (extend), `tests/feeds/importing/test_janitor.py` (extend)

**Interfaces:**

```python
async def refresh_async(session_factory, *, now: datetime, settings: EventsSettings,
                        fetcher=fetch_feed, rng: random.Random | None = None,
                        clock: Callable[[], float] = time.monotonic) -> dict[str, int]
    # keys: tenants, fetched, not_modified, failed, skipped_budget, lease_lost
async def refresh_one_async(session_factory, *, tenant_id: str, subscription_id: uuid.UUID, now: datetime,
                            settings: EventsSettings, fetcher=fetch_feed) -> str     # the outcome
def refresh_one(db_session, *, tenant_id: str, subscription_id: uuid.UUID) -> None
    # eager: schedule refresh_one_async after commit; else enqueue_after_commit(REFRESH_SUBSCRIPTION, ...)
```

One subscription's pass, the same in both entry points: claim (and commit), unseal the URL, then fetch with no session open. Then, in one fenced transaction, either `store_feed` and the success fields, or the failure fields of Rulings 13–14, then `release`, then `finalize_session`.

- [ ] **Step 1: Write the failing tests** (`fetcher` is a fake returning scripted `FetchResult`s or raising `FetchFailure`):
  - `test_refresh.py`:
    - `test_due_rows_fetched_and_stored`.
    - `test_not_modified_touches_no_item` (`generation` and items unchanged; `last_ok_at` and `next_fetch_at` updated; failures reset).
    - `test_failure_keeps_items`, parametrized over `timeout`, `http_status` (500), `too_large` and `ics_invalid`: the items and `generation` are unchanged, `status` is `error`, the code is stored, and `next_fetch_at` follows the backoff.
    - `test_disabled_after_ten_failures_shows_reason`.
    - `test_unreadable_url_disables_without_fetch` (the fetcher is not called).
    - `test_trashed_calendar_not_fetched`.
    - `test_budget_fetch_count` (25 due rows give 20 fetched and `skipped_budget = 5`).
    - `test_budget_bytes`, `test_budget_seconds` (a fake clock).
    - `test_fair_across_tenants` (two tenants with 15 due rows each, interleaved by `next_fetch_at`: both get work in one tick).
    - `test_one_tenant_raising_does_not_stop_others`.
    - `test_settings_read_in_worker` (`allow_private_subscription_urls` comes from `settings_for`, monkeypatched, and reaches the fetcher's `Policy`).
    - `test_policy_rechecked_at_fetch` (the switch turned off after save gives `url_not_public` on the next fetch, with the real `fetch_feed` and the fake resolver).
    - `test_refresh_one_eager_runs_inline` (`task_always_eager`).
    - `test_refresh_one_skips_when_leased`.
  - `test_refresh_worker.py`:
    - `test_tick_under_strict_isolation`: on PR 2's `worker_db` with `tenant_strict=True` and two tenants, each tenant's subscription is stored in its own tenant, and nothing raises `TenantUnbound`. Monkeypatching `simple_module_db.all_tenants` to a null context makes the enumeration fail, which proves the test exercises it.
    - `test_per_tenant_isolation`: a fetch result for tenant B's subscription never writes rows under tenant A, even with A bound by the caller.
    - `test_task_unbinds_callers_tenant` (newsletter's port).
    - `test_eager_task_runs` (`refresh_subscriptions.apply()`).
  - `test_task_discovery.py`: both task names are discovered, and the beat entry above is present.
  - `test_janitor.py`: `test_purges_old_deleted_subscriptions` (31 days old is gone, 29 days old stays, a live one stays, per tenant).
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_refresh.py tests/feeds/subscriptions/test_refresh_worker.py tests/core/test_task_discovery.py tests/feeds/importing/test_janitor.py`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests on SQLite and Postgres (pass), then from the root `uv run pytest -q host/tests/test_host_boots.py host/tests/test_events_wiring.py` (pass).
- [ ] **Step 5: Commit** `feat(events): refresh subscriptions on the events beat`.

### Task 10: Never re-exported, never reminded, never a card

**Files:**
- Modify: `sm_events/feeds/plugin_items.py` (build calls with `include_subscriptions=False` and drop `SOURCE_SUBSCRIPTIONS` from any call list it receives)
- Test: `tests/feeds/subscriptions/test_never_reexported.py`

**Interfaces:**
- Consumes `seed_subscription` and `store_feed` from Task 6, PR 4's `seed_public_fixture`, PR 5's token creation helper, PR 7's `contracts.cards` search and PR 8's reminder tick entry point.

- [ ] **Step 1: Write the failing test** `test_never_reexported`. It uses one public calendar with a published event `Ours`, and a `public=true` subscription on it whose stored items have the unique titles `ExtOneOff-9f3` and `ExtSeries-9f3`. It is parametrized over the following surfaces, and each must contain `Ours` where that surface lists events at all, and neither external title nor the substring `subscriptions:`:
  - `GET {prefix}/calendar.ics`;
  - `GET {prefix}/c/{slug}.ics`;
  - the private token feed of a manager's token;
  - `GET {prefix}/{event_slug}.ics`;
  - `GET {prefix}/sitemap.xml`;
  - the server-rendered `GET {prefix}/` listing HTML;
  - the event page's JSON-LD;
  - `sm_events.contracts.cards` searched with `q="Ext"`;
  - PR 8's reminder tick, run with a follower on `Ours`, which sends mail for `Ours` only.

  Add `test_public_grid_does_show_public_items`: `GET {prefix}/api/occurrences` over the range shows both external titles with `origin_label` (the one public surface that shows them, PR 6 Ruling 15). Add `test_public_grid_hides_non_public_subscription` too.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_never_reexported.py`. Expected: the feed cases fail.
- [ ] **Step 3: Implement** the `plugin_items.py` change.
- [ ] **Step 4: Run** it, and PR 4–6's feed tests (`tests/feeds`, `tests/web/public`): pass.
- [ ] **Step 5: Commit** `fix(events): external subscriptions never reach this module's feeds`.

**End of batch B.** Run `tests/feeds`, `tests/calendar` and `tests/web` of the events module on SQLite, the Postgres-marked tests of Tasks 6–9, `basedpyright`, `check_rules.py`, `check_file_size.py` and `check_sibling_contracts.py`.

---

### Task 11: The service and the API

**Files:**
- Create: `sm_events/feeds/subscriptions/validate.py`, `feeds/subscriptions/service.py`, `web/endpoints/subscriptions_api.py`, `web/schemas/subscriptions.py`
- Modify: `sm_events/module.py` (include the router), `web/endpoints/views.py` (the Calendars page props gain `can_publish: bool` and `subscription_defaults: {refresh_minutes}`)
- Test: `tests/feeds/subscriptions/test_service.py`, `tests/web/test_subscriptions_api.py`

**Interfaces:**

```python
# web/schemas/subscriptions.py (extra="forbid")
class SubscriptionIn(BaseModel):  url: str; label: SingleLine(1..100); color: HexColor | None = None
                                  refresh_minutes: int | None = Field(None, ge=15, le=1440); public: bool = False
class SubscriptionPatch(BaseModel): url: str | None = None; label: ... | None = None; color: HexColor | None = None
                                    refresh_minutes: int | None = None; public: bool | None = None   # explicit null clears color/refresh_minutes
class SubscriptionOut(BaseModel): # Ruling 29's fields; no url
# validate.py
async def check_url_for_save(raw: str, *, settings: EventsSettings, is_manager: bool) -> tuple[str, str]
    # (normalised url, url_display); UrlRefused(code) per Ruling 31; resolve via dns.resolve_bounded
async def require_subscription_right(db, who, calendar_id) -> Calendar        # 404 / 403 per Ruling 30
async def load_subscription(db, who, sub_id) -> tuple[Subscription, Calendar] # 404 for invisible, deleted, foreign
# service.py
async def create(db, who, calendar_id, body: SubscriptionIn, *, settings, can_publish: bool, is_manager: bool) -> Subscription
async def update(db, who, sub_id, body: SubscriptionPatch, *, settings, can_publish, is_manager) -> Subscription
async def pause(db, who, sub_id) -> Subscription; async def resume(db, who, sub_id) -> Subscription
async def refresh_now(db, who, sub_id, *, now: datetime) -> Subscription     # RefreshTooSoon(retry_after)
async def delete(db, who, sub_id) -> None                                     # Ruling 32
async def list_for(db, who, calendar_id) -> list[Subscription]
def to_out(sub: Subscription, *, setting_minutes: int) -> SubscriptionOut
```

- [ ] **Step 1: Write the failing tests:**
  - `test_service.py`:
    - `test_create_seals_and_masks`, `test_duplicate_url_conflict` (also after `webcal:` normalisation), and `test_limits` (an 11th per calendar and a 101st per tenant give `subscription_limit`).
    - `test_public_flag_needs_publish_and_public_calendar`.
    - `test_intranet_url_needs_manager`: switch on, `10.0.0.5`. The owner without `events.manage` gets `url_not_public`, and a manager succeeds. Switch off: the manager also gets `url_not_public`.
    - `test_url_change_clears_validators_and_is_due`, `test_pause_resume`.
    - `test_refresh_too_soon` (within 300 s of `last_fetched_at` gives `retry_after` equal to the remainder; while leased it is refused too).
    - `test_delete_wipes_ciphertext` (after delete, `url_enc == ""`, `is_deleted`, and no item of that subscription remains).
  - `test_subscriptions_api.py`:
    - `test_rights_matrix`, parametrized over PR 1's principals (`M`, `O`, `O+P`, `SE`, `SV`, `E`, `V`, `N`, `A`) on `P`, `I` and `U`: only the owner and `M` reach 2xx. Others who can see the calendar get 403 `forbidden`, the rest 404. Anonymous gets the framework's 401.
    - `test_existence_hiding`: another tenant's, an invisible calendar's and a deleted subscription's id each give the same 404 body as a random UUID, on every route.
    - `test_url_never_returned`: create, list, patch, refresh, pause and resume responses, and the Calendars page props, contain `url_display` and never the path or query of the submitted URL.
    - `test_save_refusals_mapped`, parametrized over Task 3's cases: 422 with each `url_*` code, and a `detail` without the URL.
    - `test_create_triggers_first_fetch` (eager, with the fake fetcher: after the request the status is `ok` and the item count is set).
    - `test_csrf_required` and `test_extra_fields_forbidden`.
- [ ] **Step 2: Run** `uv run pytest -q tests/feeds/subscriptions/test_service.py tests/web/test_subscriptions_api.py`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests on SQLite and Postgres: pass.
- [ ] **Step 5: Commit** `feat(events): subscriptions API`.

### Task 12: The Subscriptions dialog and the external chip and detail

**Files:**
- Create: `ui/components/subscriptions/SubscriptionsDialog.tsx`, `SubscriptionForm.tsx`, `SubscriptionRow.tsx`, `ExternalChip.tsx`, `ExternalDetail.tsx`; `ui/extensions/builtins.ts`; `ui/hooks/useSubscriptions.ts`; `ui/utils/api-subscriptions.ts`
- Modify: `ui/components/calendars/CalendarRow.tsx` (the "Subscriptions" action when `can_change_visibility`), `pages/Calendars.tsx` (mounts the dialog and passes `can_publish`), `ui/extensions/load.ts` (`registerBuiltins()` runs before the glob), `ui/calendar/StatusBar.tsx` (the label for `subscriptions`), `ui/utils/api.ts` (`errorText` for the new codes), `locales/en.json` and `de.json` (`subscriptions.*`: the dialog, the form, statuses, every failure code of Ruling 11, every skip reason PR 5 can produce, the source label, "External", "From {label}")
- Test: `ui/page-tests/SubscriptionsDialog.test.tsx`, `ui/page-tests/ExternalDetail.test.tsx`

**Interfaces:**
- `api-subscriptions.ts`: `listSubscriptions(calendarId)`, `createSubscription(calendarId, body)`, `updateSubscription(id, patch)`, `refreshSubscription(id)`, `pauseSubscription(id)`, `resumeSubscription(id)`, `deleteSubscription(id)`, all through `send` with CSRF. `SubscriptionOut` is typed as in Ruling 29.
- `builtins.ts`: `registerBuiltins(): void` → `registerSource({id: 'subscriptions', Chip: () => import('../components/subscriptions/ExternalChip'), Detail: () => import('../components/subscriptions/ExternalDetail'), PublicDetail: () => import('../components/subscriptions/ExternalDetail')})`.

- [ ] **Step 1: Write the failing tests:**
  - `SubscriptionsDialog.test.tsx`:
    - `lists rows with masked url, status, last updated, count and skip reasons`.
    - `add form posts and clears the url field`.
    - `edit leaves url empty and omits it from the patch unless typed`.
    - `public toggle disabled unless the calendar is public and the caller can publish`.
    - `refresh shows refresh_too_soon message` (a stubbed 429).
    - `error_code is shown localised with http status` (for `http_status`, 503).
    - `delete confirms with the item count`.
    - `refusal codes render their messages` (each `url_*`).
    - `de catalogue renders` (no raw keys).
  - `ExternalDetail.test.tsx`:
    - `renders title and location as text`: a title of `<img src=x onerror=alert(1)>` appears as literal text, and `container.querySelector('img')` is null.
    - `link has target blank and rel noopener noreferrer nofollow`.
    - `no link when url is null`.
    - `shows From label`.
    - `no edit, move or remind controls`.
- [ ] **Step 2: Run** (headroom first) `npx vitest run modules/events/sm_events/ui/page-tests/SubscriptionsDialog.test.tsx modules/events/sm_events/ui/page-tests/ExternalDetail.test.tsx`. Expected: fail.
- [ ] **Step 3: Implement.** Keep each file under 220 lines, splitting `SubscriptionRow` from the dialog. Follow `@simple-module-py/ui` dialog patterns as PR 5's `SubscribeDialog` and PR 6's `SourcesDialog` do.
- [ ] **Step 4: Run** the tests, `npx tsc --noEmit -p modules/events`, `uv run python scripts/check_locales.py` and `uv run python scripts/check_ts_imports.py`: all pass.
- [ ] **Step 5: Commit** `feat(events): Subscriptions dialog and external occurrence detail`.

### Task 13: Docs, CLAUDE.md, CHANGELOG, module close-out and branch verification

**Files:**
- Create: `modules/events/docs/subscriptions.md`. It covers:
  - the user guide: adding a subscription, what "external" means, the public flag, refresh, pause and delete;
  - operations: the worker and beat (`events.refresh_subscriptions`, queue `events`), what a host without beat does, the URL policy of Rulings 3–8 with a table of refused ranges, the intranet switch and the two permissions it needs, every failure code with what to do, backoff and the disable rule, why URLs are encrypted and masked and what `url_unreadable` means after a key rotation, the 5,000-VEVENT and `import_max_bytes` limits, that proxies are never used (`trust_env` off; an egress proxy is open point 4), and the User-Agent string.
- Modify: `modules/events/docs/index.md`. Rewrite "Status" as the module overview: the ten delivered parts in one table, linking each area's doc (`feeds.md`, `writing-a-plugin.md`, `reminders.md`, `registration.md`, `subscriptions.md`), with "Later delivery remains" removed.
- Modify: `modules/events/README.md` (a Subscriptions section with the two settings and the screen), `CHANGELOG.md` (the events entry gains subscriptions), `docs/secret-key-rotation.md` (lists `events_subscription.url_enc` and that `reencrypt_secrets.py` rewrites it).
- Modify: `docs/superpowers/specs/2026-11-17-events-module-design.md`. Set the status line to `Status: approved 2026-11-17 (issue #400); implemented in PRs 1–10`, add a "Done" column to the Delivery table with each PR's state, and add an "Amendments (PR 10)" paragraph: one source `subscriptions` with implicit entries, `origin_label`, the URL encrypted, items without descriptions, the intranet switch never opening loopback or link-local.
- Modify: `CLAUDE.md`. Add three sentences to the events paragraph: "Subscription URLs are fetched only through `sm_events.feeds.subscriptions.fetch` (the pinned transport, every hop re-checked, no `AsyncClient` so the URL never reaches httpx's log), are stored only as `enc:v2:` (`url_enc`, a column target of `scripts/reencrypt_secrets.py`) and are shown only as `url_display`. External items are plain text and carry no description; never render them as HTML. They are never re-exported: a feed builds its plugin calls with `include_subscriptions=False`." Also add events to the sentence listing the modules that read `SM_SECRET_KEY_PREVIOUS` and fall back to `SM_SECRET_KEY`, and to the list of `core/crypto.py` copies ("Change the five copies together").
- Test: none new. This task verifies.

- [ ] **Step 1: Write the docs** above.
- [ ] **Step 2: Run** the module's targeted suites once more, `tests/feeds/subscriptions` and `tests/web/test_subscriptions_api.py`, on SQLite and on Postgres (`smpy_events_test`). Then from the root (headroom first, one at a time): `uv run pytest -q scripts/tests`, `make lint` (ruff, basedpyright, `check_rules`, `check_file_size`, `check_hardcoded_strings`, `check_locales`, `check_ts_imports`, `check_sibling_contracts`, `moved_paths --check`), `uv run python scripts/check_migration_heads.py`, `uv run python scripts/bump_version.py --check-current`, and `npx vitest run modules/events`. Expected: all green. Drop `smpy_events_check` and `smpy_events_test`, and say so.
- [ ] **Step 3: Manual check, left to `/ship`'s QA** (no e2e spec; see open point 5). With the app running and network access, subscribe a calendar to a real public holiday feed. Check that its items appear marked "External" with the label, that "Refresh now" gives a 304 on the second try (the dialog shows `last_ok_at` moving and the item count steady), that a `http://127.0.0.1/` URL is refused at save, and that the public grid shows the items only after the public flag is set. Capture screenshots of the dialog, an external chip and the detail for the PR.
- [ ] **Step 4: Commit** `docs(events): subscriptions guide and operations, module close-out`.

---

## Verification checklist

- [ ] Every ruling has a task: 1–2 → Tasks 2 and 11; 3–9 → Task 3 (save-time use in Task 11); 10–11 → Tasks 4–5; 12–16 → Tasks 8–9 and 11; 17–23 → Task 6 (limits in Task 11); 24–27 → Task 7; 28 → Task 10; 29–33 → Task 11; 34 → Task 12; 35 → Task 1.
- [ ] The parity suite covers the guard copy (three members), `netsafe` (two) and the crypto copy (five, plus three in the worker-fallback family).
- [ ] `grep -rn "AsyncClient" modules/events/sm_events` finds nothing.
- [ ] `grep -rn "all_tenants" modules/events/sm_events/feeds/subscriptions` finds only `refresh.py`'s enumeration.
- [ ] Every new `.py`/`.ts`/`.tsx` is under 280 lines (`check_file_size.py` shows no new WARNING).
- [ ] `alembic check` is clean on SQLite and Postgres, with one head.
- [ ] Review Focus 1–6 each have their named tests passing.

## Open points

1. **A per-field write permission for module settings (framework).** The intranet switch can only require `settings.edit` where it is written, so Ruling 9 enforces `events.manage` where a URL is saved. File an upstream issue in `simple_module_python` asking for a `json_schema_extra` write permission (ai has the same need and solved it with its own settings page).
2. **Feeds over 5,000 VEVENTs.** Large Google calendars keep years of history. The scan's bound fails them with `too_many_events`. A later change could stream-skip VEVENTs that ended more than a year ago before counting, but that needs a scan mode that can skip instead of fail.
3. **gzip.** Ruling 10 refuses encoded bodies, as images does. If a provider ignores `Accept-Encoding: identity`, a bounded incremental `zlib` decoder (decoded bytes counted against the cap) is the follow-up.
4. **A shared pinned client upstream.** images, ai and now events each keep a guard copy, and images and events each keep a pinned transport. A framework `simple_module_core.net` with one guard and one pinned transport (with an egress-proxy mode that keeps pinning) would remove three copies. File it upstream as a reproducible issue citing the three paths.
5. **e2e.** ★ No browser spec. The save-time check resolves DNS and refuses loopback even with the intranet switch on (Ruling 8), so a spec on CI would need a public URL, which means network access in CI. Serving a fixture from the test host would need a test-only bypass of the guard, which this plan refuses to add. The module tests cover the flows, and `/ship`'s QA exercises a real public feed.
6. **Windows time zone names** inherit PR 5's open point 5: until it is solved, Outlook feeds with Windows `TZID`s skip those items as `unknown_timezone`, and the dialog counts them.
