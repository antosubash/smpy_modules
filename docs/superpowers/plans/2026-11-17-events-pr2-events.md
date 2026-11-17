# Events PR 2: events, texts, recurrence, the occurrences read, workflow. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Events become real. A writer creates one-off, all-day, multi-day and recurring events with texts in each content locale on a calendar they may write. Overrides skip, cancel or move one occurrence. The occurrences read answers every range question within fixed bounds. Events move draft → in_review → published, either directly or on a schedule. Every write carries `expected_revision` and records a revision. The console gets an Events list and an event editor.

**Architecture:** The time maths and RRULE handling are pure functions in `calendar/` (`times.py`, `rrule.py`, `expand.py`), and property-style tests pin them before any database code exists. `calendar/occurrences.py` is the one read: it selects visible events through `core/access/events.py`, expands series lazily and merges them in a heap, so the work stays bounded by the 2,000-occurrence cap and not by the number of instances in the range. The built-in source is one function behind the `Source` protocol that PR 6's registry will hold. `content/` owns writes: texts and slugs, the sanitiser, revisions and the compare-and-set on `revision`, events, overrides, the workflow and bus emission after commit. `web/` has thin routers. `contracts/` exposes the read and the bus events. `tasks.py` runs `events.publish_due` through a worker runtime copied from newsletter.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy async, `python-dateutil` (`rrule`, 3.0.0 in `uv.lock`), `zoneinfo`, the framework's `background_tasks` (Celery), pytest (SQLite, plus Postgres opt-in through `tests/pg_support.py`), React 19 + Inertia, `@simple-module-py/ui`, vitest (happy-dom).

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`. This plan covers Delivery row 2 and draws on "The core idea", Data model, Access, Background work, Layout and "Amendments (PR 1)". The precedent plan is `docs/superpowers/plans/2026-11-17-events-pr1-scaffold.md`. Read `modules/events/docs/index.md` and the PR 1 code under `modules/events/` before starting.

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**Times**
1. ★ **The API takes local wall-clock times plus a `timezone`, never UTC.** A body carries `times: {all_day, timezone, start, end}`. A timed event sends `start` and `end` as `YYYY-MM-DDTHH:MM[:SS]` without an offset; an all-day event sends `YYYY-MM-DD`. The server converts with `zoneinfo`. Responses return the UTC `starts_at`/`ends_at` and also `start_local`/`end_local` in the same form as the input. This way the browser never converts to an arbitrary IANA zone. PR 3's drag will convert in the client with Temporal.
2. **All-day storage.** `starts_at` is local midnight of the first day, `ends_at` is local midnight of the day **after** the last day (exclusive), both converted to UTC. The API's all-day `end` is the **inclusive** last date. Occurrences of an all-day event carry `start_date`/`end_date` (ISO dates, `end_date` exclusive), so no client ever has to recompute them from UTC.
3. **Bounds.** A timed `end` must be after `start`; an all-day `end` may equal `start` (one day). A one-off event lasts at most `MAX_EVENT_DAYS = 366` days, and a recurring event or a moved occurrence at most `MAX_SERIES_EVENT_DAYS = 31`. The second bound is also the look-back the occurrences read uses for series that started before the range. Errors: 422 `end_before_start` and 422 `duration_too_long`.
4. **Wall-clock gaps and folds.** A master `start` or `end` that falls in a DST gap gets 422 `invalid_local_time`, because a person typed something that does not exist. A time that occurs twice uses its first occurrence (`fold=0`). An *expanded* instance that falls in a gap is shifted forward by the gap (RFC 5545 §3.3.5; this is what `zoneinfo` gives a naive `fold=0` time). A timed instance's end is its start plus the master's **exact** duration (RFC 5545 §3.8.5.3). An all-day instance lasts the master's number of **days**.

**Recurrence**
5. ★ **RRULE allow-list**, stored normalised (parts in a fixed order, no `RRULE:` prefix, ≤ 500 characters):
   - `FREQ` is one of `DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`. `SECONDLY`, `MINUTELY` and `HOURLY` give 422 `rrule_frequency_refused` (spec).
   - `INTERVAL` is 1–99. `COUNT` is 1–730. `UNTIL` must not be before the start and must not be more than 100 years after it. `COUNT` and `UNTIL` together are refused. A rule with neither is endless, and `recurrence_until` is then `NULL`.
   - Allowed by-parts: `BYDAY` (ordinals −5…5 only with `MONTHLY`/`YEARLY`), `BYMONTHDAY` (±1…31), `BYMONTH` (1–12), `BYSETPOS` (±1…366, and only alongside another `BY` part), `WKST`.
   - Refused: `BYHOUR`, `BYMINUTE`, `BYSECOND` (they make a rule sub-daily), `BYWEEKNO` and `BYYEARDAY`, plus anything not listed above. Any of these, or an unparseable string, gives 422 `invalid_rrule` with the offending part named in `detail`.
   - A timed rule's `UNTIL` is stored as UTC `…Z`, and a date given for it means the end of that local day. An all-day rule's `UNTIL` is stored as a `DATE`.
6. ★ **The start must be the first occurrence of its rule.** If it is not, the request gets 422 `start_not_in_rule`. RFC 5545 counts a non-matching `DTSTART` as an extra instance, but dateutil does not, and the editor always builds a rule its start matches. Refusing the mismatch removes an ambiguity that feeds and imports would otherwise inherit.
7. **Every expansion has an `until`.** dateutil loops until year 9999 on a rule that can never match, such as 30 February. So `expand.py` never iterates a rule without passing `until = min(recurrence_until, window_end)`. A `COUNT` rule is expanded as the same rule with `until = recurrence_until`, which is equivalent because `recurrence_until` is the start of the COUNT-th instance. Validation and derivation use `until = start + 100 years`.
8. **`recurrence_until` is the UTC end of the last occurrence**, or `NULL` when the rule is endless. The series prefilter is `rrule IS NOT NULL AND (recurrence_until IS NULL OR recurrence_until > :start)`.
9. ★ **Sub-events and recurrence exclude each other.** A recurring event cannot have sub-events, and a sub-event cannot recur. The parent must be in the same calendar and must not itself have a parent (one level). A parent's times do not constrain its children's. Violations get 422 `invalid_parent`. A parent with live (untrashed) children cannot be trashed (409 `has_sub_events`). `calendar_id` and `parent_id` cannot be changed after create (422 `immutable_field`): moving an event to another calendar is a later feature.

**Overrides**
10. **Override rules.** An override is written only on a recurring event (otherwise 422 `not_recurring`), and only for an `original_start` that really is an occurrence of the current rule (otherwise 422 `not_an_occurrence`). `original_start` is the instance's UTC start; for an all-day series it is local midnight in UTC. `skipped` removes the occurrence, and `cancelled` keeps it with `status: "cancelled"`. ★ `moved` may change **only the start and the end** (local wall clock, in the event's timezone), within `MAX_SERIES_EVENT_DAYS`, and may move anywhere in time. It cannot change title, place or category: those changes are "all", or they need a separate event. Every override has an optional `note` (≤ 1000 characters). One override exists per `(event, original_start)`, and a second write replaces the first.
11. **Changing a series' rule, start, timezone or all-day flag runs a preview first.** `POST /api/events/recurrence/preview` returns the next occurrences and the overrides the change would orphan. A `PATCH` that would orphan overrides, without `drop_orphaned_overrides: true`, gets 409 `overrides_orphaned`. With the flag, the orphans are deleted in the same transaction and recorded in the revision. Orphans are not remapped: moving a weekly 10:00 series to 11:00 orphans every override, as the spec says.

**Occurrences read**
12. **The occurrence `key`.** A one-off is `"{event_id}"`. A series instance is `"{event_id}:{original_start UTC as %Y%m%dT%H%M%SZ}"`, and a moved instance keeps its original key. This makes it stable per source (spec).
13. ★ **Ordering and truncation.** Results are sorted by `(start, end, source, key)` ascending, the first 2,000 are returned, and `truncated` is true when there are more. One-offs come from SQL ordered by `starts_at` with `LIMIT 2001`. Series rows are capped at `SERIES_FETCH_MAX = 2000` per read; going over also sets `truncated`. Each series is a lazy generator, and they are merged with `heapq.merge` together with the moved-override stream, stopping at 2,001. So the work done is bounded by roughly 2,000 plus the number of series, whatever the range holds. A range over 366 days gets 422 `range_too_long`, and `end <= start` gets 422 `invalid_range` (spec bounds, enforced in the read and not in the router).
14. **What an occurrence carries.** The spec's fields, plus three:
    - `start_date`/`end_date` (all-day only, ruling 2);
    - `event_status` (`draft` | `in_review` | `published`; `None` for other sources), so PR 3 can mark drafts;
    - `original_start` (spec).

    Other fields:
    - `color` is the category's colour, else the calendar's.
    - `title` and `lang` come from the text in `locale`, else the default content locale, else the first text by locale.
    - `url` is the editor URL when the viewer may write the event, else `None`. Public URLs come in PR 4.
    - `editable` follows the write rule in ruling 16.
15. **Filters.** `calendar_ids` (calendars the viewer cannot see are dropped silently, never an error, so existence cannot be probed), `category_ids`, `types`, `locale`, `include_unpublished` (default true; it only ever widens to drafts where the viewer has `write_events`). The public surface (PR 4) passes no viewer and gets `public` calendars and `published` events only (spec).

**Access and workflow**
16. ★ **One visibility rule for events** lives in `core/access/events.py`. An event is visible when its calendar is visible **and** it is `published` or the viewer has `write_events` on its calendar. An event that is **locked** (`published`, or scheduled with `publish_at` set) can be changed, trashed, restored or have overrides written only by someone with `write_events` **and** `events.publish`. Any other writer who can see it gets 403 `publish_required`, and someone who cannot see it gets 404. Locking scheduled events is my addition to the spec: otherwise a writer could change a draft a publisher had already approved for a time.
17. **Workflow transitions**, each a `POST` with `expected_revision`. A disallowed transition gets 409 `invalid_transition`.

    | action | from | to | needs |
    |---|---|---|---|
    | `submit` | draft | in_review | write |
    | `withdraw` | in_review | draft | write |
    | `approve` (body `publish_at_local?`, wall clock in the event's timezone) | draft, in_review | published (now) or scheduled (future `publish_at`, status unchanged) | write and publish |
    | `reject` (body `note`, required, 1–1000) | in_review | draft | write and publish |
    | `unschedule` | scheduled | same status, `publish_at` cleared | write and publish |
    | `unpublish` | published | draft (`published_at` kept as history, `publish_at` cleared) | write and publish |

    A publisher may approve a draft directly, without a review. `published_at` is set on every publish. A `publish_at` in the past publishes at once. Editing an `in_review` event keeps it `in_review`.
18. **Revisions.** Every write, the beat's included, increments `revision` and writes `events_revision(number = new revision)`.
    - The snapshot holds every `Event` column except `id`, `tenant_id`, the audit and soft-delete columns, plus `texts` (`{locale: every text field}`) and `overrides` (`[{original_start, kind, starts_at, ends_at, note}]`), all as JSON-safe values (ISO strings).
    - `action` is one of `created`, `updated`, `override_set`, `override_cleared`, `submitted`, `withdrawn`, `approved`, `scheduled`, `unscheduled`, `rejected`, `unpublished`, `published_scheduled`, `trashed`, `restored`.
    - `actor` is the user id, and `None` for the beat.
    - ★ A new nullable column `events_revision.note` (≤ 1000) holds the reject note and the list of orphaned overrides. This is the one migration of this PR.
    - Only the newest `REVISIONS_KEPT = 100` are kept per event, and older ones are deleted on write.
    - History is read-only in PR 2: there is no "restore this revision".
19. **Stale guard.** A write's first statement is a compare-and-set: `UPDATE events_event SET revision = revision + 1, updated_at, updated_by WHERE tenant_id = :t AND id = :id AND revision = :expected AND is_deleted = :trashed` (Core, with its own `tenant_id` predicate). A row count of 0 then gives 409 `stale`, or 404 when the event is gone or invisible (a second read tells the two apart). On Postgres this also takes the row lock first, so two writers serialise. The 409 body stays `{"detail","code"}`, and the editor re-reads the event to show its conflict panel.

**Content**
20. **Texts.** `texts` is `{locale: TextIn | null}` and every key must be in `content_locales` (otherwise 422 `unknown_locale`). ★ An event always has a text in the default locale (`content_locales[0]`), otherwise 422 `default_locale_required`. A `PATCH` replaces each locale it names, `null` deletes that locale's text (never the default's), and locales it leaves out are untouched. `TextIn` has `title` (1–300, single line), `slug?`, `summary?` (≤ 1000, multi-line), `description` (rich text), `seo_title?` (≤ 300), `seo_description?` (≤ 500) and `noindex`.
21. **Slugs and redirects.** A slug is unique per `(tenant, locale, slug)` across the trash (PR 1's index). An absent slug is derived from the title with `slugify(title, fallback="event")` and deduplicated within the locale (`-2`, `-3`, …). An explicit slug that is taken gets 409 `slug_taken`, through `slug_write(db, "uq_events_event_text_slug")`. A rename writes `events_redirect(locale, old_slug → event)`. Claiming a slug deletes any redirect `(locale, slug)`, so the event that holds a slug now wins over an old link, and renaming back removes the redirect.
22. ★ **The rich-text allow-list** is newsletter's set (`p br strong em u s a ul ol li blockquote`) plus `h2 h3`. The only attribute kept is `a[href]`, restricted to `http:`, `https:` and `mailto:`. Dropped-content tags lose their contents (newsletter's `DROP_CONTENT`), and `b` and `i` are renamed. The output is idempotent. The sanitiser runs at save and again wherever the HTML is rendered (PR 4). It is written in events (`content/richtext.py`, about 120 lines) and never imported from newsletter. Raw input over 200,000 characters gets 422 `description_too_long`, and so does cleaned output over 100,000.
23. **Other fields.**
    - `type` must be `"event"` on create (otherwise 422 `unknown_type`) and is immutable. `extra` is never writable in PR 2; it is returned read-only and preserved untouched.
    - `category_id` must exist in the bound tenant, otherwise 422 `unknown_category`.
    - `online_url`, `registration_url` and `image` accept `http`/`https` only.
    - `latitude` is in −90…90 and `longitude` in −180…180.
    - `attendance_mode` is from `ATTENDANCE_MODES`.
    - `cancelled` is a plain flag; changing it on a locked event needs publish.
    - `uid` is `f"{uuid4()}@simple-module-events"`, set once.
24. **Trash.** Delete is a soft delete that needs `expected_revision`. Restore needs the same right as delete (write, plus publish when the event is locked), and the event comes back with the status it had. There is no purge in PR 2. Events of a trashed calendar are invisible because their calendar is.
25. **Bus events** (`sm_events.contracts.events`, dataclasses on the framework's `Event`). Every event carries `tenant_id`, `event_id`, `calendar_id` and `uid`. They are emitted only for events that are, or were, published, and only after commit (records' `on_commit` pattern).
    - `EventPublished(published_at)` on `approve` (now) and in the beat.
    - ★ `EventRescheduled(original_start: datetime | None, old_start, old_end, new_start, new_end, rule_changed: bool)`. `original_start` is `None` for a change to the whole event or series, and set for a moved occurrence. It is emitted on a time, timezone, all-day or rule change of a published event, and on a `moved` override.
    - `EventCancelled(original_start: datetime | None)` on setting `cancelled` (`None`) or on a `cancelled` override.
    - `EventDeleted(was_published: bool)` on trash.

    Reinstating, unpublishing and `skipped` emit nothing in PR 2 (open point 3).
26. **List paging.** `GET /api/events/events` uses `page` (from 1) and `page_size` (1–100, default 50) and returns `{items, total, page, page_size}`, ordered by `starts_at` ascending, then `id`. A series matches a date range when it intersects the range (the master's `starts_at < to`, and `recurrence_until` `NULL` or `> from`), and a one-off when `starts_at < to AND ends_at > from`. `q` (≤ 100 characters) is a case-insensitive substring match on any locale's title. Trashed events are listed with `trashed=true`, for events the caller could restore.
27. **Errors** use the `{"detail","code"}` envelope (spec). New codes:
    - 409: `stale`, `overrides_orphaned`, `has_sub_events`, `invalid_transition`
    - 403: `publish_required`
    - 422: `invalid_rrule`, `rrule_frequency_refused`, `start_not_in_rule`, `invalid_local_time`, `end_before_start`, `duration_too_long`, `range_too_long`, `invalid_range`, `default_locale_required`, `unknown_category`, `unknown_type`, `invalid_parent`, `immutable_field`, `not_recurring`, `not_an_occurrence`, `description_too_long`

    PR 1 already has `not_found`, `forbidden`, `slug_taken`, `unknown_locale` and `tenant_required`.
28. **Screens.** `/admin/events/` keeps its 303 to Calendars until PR 3. New screens: the Events list at `/admin/events/list` and the editor at `/admin/events/edit/new?calendar=<id>` and `/admin/events/edit/{id}`. A new menu entry "Events" (`events.view`, `order=395`) sits before Calendars.
29. ★ **The description editor** is a small `contentEditable` field with a toolbar (bold, italic, heading, lists, link) in `ui/components/editor/RichTextField.tsx`. It adds no new npm dependency. The server's sanitiser is the only trust boundary, and the field loads only HTML the server has already cleaned. The recurrence editor covers daily, weekly (weekdays), monthly (day of month, or nth weekday) and yearly, ending never, after N, or on a date. It shows any other stored rule as "Custom rule" in a raw text field, which the server validates.
30. **Scheduled publishing** is `events.publish_due`, run by beat every 60 s on queue `events` (`expires` 55). It enumerates tenants in one narrow `all_tenants()` read of due rows. Then, for each tenant under `tenant_context`, it publishes at most `PUBLISH_DUE_BATCH = 200` due rows (`FOR UPDATE SKIP LOCKED` on Postgres) and finishes each tenant with `finalize_session`. It does not re-check the scheduler's permission at publish time: the `scheduled` revision records who scheduled it. A host without beat never auto-publishes; this is documented.

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, alembic or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr2` on branch `feat/events-pr2-events`, which is stacked on `feat/events-pr1-scaffold`. Before Task 1, rebase onto that branch's current tip (it was one commit ahead when this plan was written). Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points from the worktree root, and module tests from the module directory: `cd modules/events && uv run pytest …`.
- Implementers are Claude subagents. Each one commits its own tasks, one commit per task, and never pushes.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- Names: package `sm_events`, npm `@simple-module-py/events`, locale namespace `events`, API prefix `/api/events`, view prefix `/admin/events`, table prefix `events_`, task names `events.<name>`, queue `events`.
- Version stays `0.0.15` (`uv run python scripts/bump_version.py --check-current`).
- Pins are ranges, never `==`. New dependencies:
  - `python-dateutil>=2.9,<4`;
  - `simple_module_background_tasks>=0.0.44,<0.1  # floor: background_tasks.core and .worker paths first shipped in 0.0.44` (newsletter's line, `modules/newsletter/pyproject.toml:17`).

  If the framework bump PR #412 has landed, raise the floors and their comments as it does.
- Settings stay DB-backed, with no environment reads. PR 2 adds no settings field (`content_locales` and `default_timezone` already exist).
- Every query on an events table runs with a tenant bound. Core statements carry their own `tenant_id` predicate, and `all_tenants()` is used only in the beat's tenant enumeration.
- 300-line cap. Keep every `.py`/`.ts`/`.tsx` under 280 lines; each task names where its area splits.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`). The new numeric bounds in Task 1 also live there.
- Only real Inertia pages go under `sm_events/pages/`: `Events.tsx` and `EventEditor.tsx` in this PR.
- `en.json` and `de.json` keep identical key trees and placeholders (`scripts/check_locales.py`). UI strings go through `t(keys.events.…)`.
- Postgres checks use dev-services' Postgres and scratch databases (`smpy_events_check` for alembic, `smpy_events_test` for pytest). Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **Timezone and DST expansion.** A weekly 10:00 Europe/Vienna series must stay at 10:00 local across both transitions (UTC 09:00 → 08:00). An instance in the spring gap moves forward, and one in the autumn fold takes the first time. Covered by Task 3 (`test_weekly_keeps_wall_clock_across_dst`, `test_gap_instance_shifts_forward`, `test_fold_instance_takes_first`) and Task 6 (`test_read_across_dst`).
2. **All-day boundaries.** An all-day event on 2026-03-29 in Vienna (a 23-hour day) must be the dates `2026-03-29`–`2026-03-30` (exclusive), and must appear in a range that starts at 23:30 UTC on 28 March. It must not appear in a range that ends at the event's local midnight. Covered by Task 2 (`test_all_day_storage_on_short_day`) and Task 6 (`test_all_day_range_edges`).
3. **Unbounded expansion.** An endless daily rule with a 366-day range, an impossible rule (30 February), and 3,000 daily series must each return at most 2,000 items quickly, with `truncated` set. A range of 367 days gets 422. Covered by Task 4 (`test_impossible_rule_terminates`) and Task 6 (`test_cap_and_truncation`, `test_many_series_bounded`).
4. **Drafts leaking.** A view-only viewer, a share-view holder and an anonymous principal never receive a draft, `in_review` or scheduled event from the occurrences read, the list, `GET /events/{id}` (404), the preview or the contract. Covered by Task 5's truth table and Task 6's `test_drafts_never_reach_viewers`.
5. **Published-event edits without `events.publish`.** A `PATCH`, an override, `cancelled`, trash and restore on a published or scheduled event by a writer without publish must get 403 `publish_required` and leave revision and history unchanged. Covered by Task 12 (`test_locked_event_needs_publish`) and Task 15 (`test_api_locked_matrix`).
6. **Stale writes.** Two writes with the same `expected_revision`: the second gets 409 `stale`, nothing is written, and no revision or bus event results. A stale override or workflow call likewise. Covered by Task 10 (`test_cas_loses_once`) and Task 15 (`test_stale_everywhere`).
7. **Slug redirects per locale.** Renaming the `de` slug records a `de` redirect only. A new event claiming an old slug removes that redirect. Renaming back removes the redirect. The same slug in `en` and `de` on two events is fine. Covered by Task 9.
8. **Sanitising the description.** `<img onerror>`, `<a href="javascript:…">`, `<a href=" jav&#x09;ascript:">`, nested `<script>`, `<svg>`, a `style` attribute and a 25-level nesting all come out inert, and `clean(clean(x)) == clean(x)`. Covered by Task 8.

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events suite green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: time, recurrence, the read** | 1–6 | constants, errors, dependency; `times`, `rrule`, `expand`; the event-visibility rule; the occurrences read over rows inserted directly |
| **B: content, workflow, API** | 7–15 | migration; sanitiser; texts and slugs; revisions and the stale guard; bus plumbing; event writes; overrides and the series preview; workflow; the HTTP API |
| **C: contracts and the beat** | 16–17 | `contracts.occurrences`, `contracts.mounted`, pyright; `events.publish_due`, the worker runtime, queues |
| **D: screens and docs** | 18–23 | views and menu; the API client and recurrence utilities; the Events list; the editor; workflow, history and conflict; docs |

---

### Task 1: Constants, error codes and the dateutil dependency

**Files:**
- Modify: `modules/events/pyproject.toml` (add `python-dateutil>=2.9,<4`), `uv.lock`
- Modify: `sm_events/core/constants.py`, `sm_events/core/errors.py`
- Test: `tests/core/test_errors.py`

**Interfaces:**
- Constants added:
  - bounds: `MAX_EVENT_DAYS = 366`, `MAX_SERIES_EVENT_DAYS = 31`, `MAX_RANGE_DAYS = 366`, `MAX_OCCURRENCES = 2000`, `SERIES_FETCH_MAX = 2000`, `RRULE_MAX_LEN = 500`, `RRULE_MAX_INTERVAL = 99`, `RRULE_MAX_COUNT = 730`, `RRULE_MAX_YEARS = 100`, `REVISIONS_KEPT = 100`, `PREVIEW_MAX = 50`, `PREVIEW_DEFAULT = 10`, `EVENTS_PAGE_MAX = 100`, `EVENTS_PAGE_DEFAULT = 50`, `DESCRIPTION_RAW_MAX = 200_000`, `DESCRIPTION_MAX = 100_000`, `NOTE_MAX = 1000`, `QUERY_MAX = 100`, `PUBLISH_DUE_BATCH = 200`;
  - names: `EVENT_SLUG_FALLBACK = "event"`, `UID_SUFFIX = "@simple-module-events"`, `SOURCE_EVENTS = "events"`;
  - one `*_CODE` and one `*_DETAIL` per new code in ruling 27.
- `errors.py` new classes, each a subclass of PR 1's `Conflict`/`Forbidden`/`Invalid`, with its code: `Stale`, `OverridesOrphaned`, `HasSubEvents`, `InvalidTransition`, `PublishRequired`, `InvalidRule` (default code `invalid_rrule`; also raised with `rrule_frequency_refused` and `start_not_in_rule`), `InvalidTimes` (raised with `invalid_local_time`, `end_before_start` or `duration_too_long`), `InvalidRange` (`invalid_range`, `range_too_long`), `DefaultLocaleRequired`, `UnknownCategory`, `UnknownType`, `InvalidParent`, `ImmutableField`, `NotRecurring`, `NotAnOccurrence` and `DescriptionTooLong`.

- [ ] **Step 1: Write the failing test** `test_errors.py::test_new_codes`: parametrized over `(cls, status, code)` for each class above; `cls().status_code == status` and `cls().code == code`, and the rendered body through `install_exception_handlers` is exactly `{"detail", "code"}`.
- [ ] **Step 2: Run** `~/.claude/bin/wait-for-headroom`, then `cd modules/events && uv run pytest -q tests/core/test_errors.py`. Expected: ImportError.
- [ ] **Step 3: Implement.** Then run `uv sync --all-packages --all-extras --no-extra anonymize` from the root (headroom first).
- [ ] **Step 4: Run** the test (passes), then `uv run python scripts/check_hardcoded_strings.py` and `scripts/check_rules.py` (both pass).
- [ ] **Step 5: Commit** `feat(events): error codes and bounds for events`.

### Task 2: Times: local wall clock ↔ UTC, all-day storage, bounds

**Files:**
- Create: `sm_events/calendar/times.py` (pure)
- Test: `tests/calendar/test_times.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Span:                       # what is stored
    starts_at: datetime           # aware UTC
    ends_at: datetime             # aware UTC (all-day: exclusive local midnight)
def to_span(*, all_day: bool, timezone: str, start: str, end: str, recurring: bool) -> Span
    # parses "YYYY-MM-DD" (all-day) or "YYYY-MM-DDTHH:MM[:SS]" (timed, no offset; one with an offset is invalid_local_time)
    # raises InvalidTimes(code=invalid_local_time | end_before_start | duration_too_long)
def to_local(span: Span, *, all_day: bool, timezone: str) -> tuple[str, str]
    # inverse; all-day end is the inclusive last date
def localize(naive: datetime, tz: ZoneInfo) -> datetime          # fold=0, gaps shift forward; returns UTC
def is_nonexistent(naive: datetime, tz: ZoneInfo) -> bool        # round-trip check
def all_day_dates(span: Span, timezone: str) -> tuple[date, date] # (first, exclusive end)
```

- [ ] **Step 1: Write the failing tests:**
  - `test_timed_round_trip`: `to_span(all_day=False, timezone="Europe/Vienna", start="2026-07-01T10:00", end="2026-07-01T11:30", recurring=False)` gives `starts_at == 2026-07-01T08:00Z` and `ends_at == 09:30Z`, and `to_local` returns the inputs (with seconds dropped when zero).
  - `test_all_day_storage_on_short_day`: Vienna, `"2026-03-29"`–`"2026-03-29"` gives `starts_at == 2026-03-28T23:00Z` and `ends_at == 2026-03-29T22:00Z` (23 h), and `all_day_dates` gives `(2026-03-29, 2026-03-30)`.
  - `test_all_day_multi_day_inclusive_end`: `"2026-08-01"`–`"2026-08-03"` is stored with its end at local midnight of 4 August.
  - `test_gap_is_refused`: `start="2026-03-29T02:30"` in Vienna gives `invalid_local_time`.
  - `test_fold_takes_first`: `2026-10-25T02:30` in Vienna gives `00:30Z`.
  - `test_end_before_start`: an equal timed end fails; an all-day end equal to the start passes; an all-day end before the start fails.
  - `test_duration_bounds`: 366 days passes and 367 days fails (`duration_too_long`) for a one-off; 31 days passes and 32 fails when `recurring=True`.
  - `test_offset_input_refused`: `"2026-07-01T10:00+02:00"` gives `invalid_local_time`.
  - `test_property_round_trip` (hypothesis is not installed: a seeded `random.Random(0)` loop of 500 cases over 6 zones, including `Australia/Lord_Howe` with its 30-minute DST, and `Pacific/Apia`): for every non-gap local time, `to_local(to_span(x)) == x`.
- [ ] **Step 2: Run** `cd modules/events && uv run pytest -q tests/calendar/test_times.py`: fails.
- [ ] **Step 3: Implement.** Use `zoneinfo.ZoneInfo`. An unknown timezone is refused by the schema (PR 1's `timezones.is_known`), not here.
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): wall-clock and all-day time conversion`.

### Task 3: RRULE parse, validate, normalise and derive `recurrence_until`

**Files:**
- Create: `sm_events/calendar/rrule.py` (pure; about 200 lines, and if it grows past 250 split out `rrule_parts.py` with the part parsers)
- Test: `tests/calendar/test_rrule.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Rule:
    text: str                      # normalised, no "RRULE:" prefix
    freq: str
    count: int | None
    until: datetime | date | None  # UTC aware (timed) or date (all-day)
def parse(text: str, *, all_day: bool, timezone: str) -> Rule    # InvalidRule(code=...)
def build(rule: Rule, *, dtstart_local: datetime, until_local: datetime | None) -> dateutil.rrule.rrule
    # naive local dtstart; count dropped and until=until_local always (ruling 7)
def validate(rule: Rule, span: Span, *, all_day: bool, timezone: str) -> datetime | None
    # checks start_not_in_rule; returns recurrence_until (UTC end of last occurrence) or None
```

The normalised part order is `FREQ, INTERVAL (omitted when 1), COUNT, UNTIL, BYMONTH, BYMONTHDAY, BYDAY, BYSETPOS, WKST`.

- [ ] **Step 1: Write the failing tests:**
  - `test_normalises`: `"rrule:byday=we,mo;freq=weekly;interval=1"` becomes `"FREQ=WEEKLY;BYDAY=MO,WE"`.
  - `test_refuses_subdaily`: parametrized over `SECONDLY`, `MINUTELY` and `HOURLY`, each giving `rrule_frequency_refused`.
  - `test_refused_parts`: `BYHOUR`, `BYMINUTE`, `BYSECOND`, `BYWEEKNO`, `BYYEARDAY`, `X-FOO` and `DTSTART=` each give `invalid_rrule`, with the part named in `detail`.
  - `test_bounds`: `INTERVAL=0` and `100`, `COUNT=0` and `731`, `COUNT` with `UNTIL`, `BYSETPOS` alone, `BYDAY=2MO` with `WEEKLY`, an `UNTIL` before the start, an `UNTIL` more than 100 years later, and 501 characters all give `invalid_rrule`.
  - `test_start_not_in_rule`: a start on Tuesday with `FREQ=WEEKLY;BYDAY=MO` gives `start_not_in_rule`.
  - `test_until_derivation`: `FREQ=DAILY;COUNT=3` from 2026-07-01 10:00–11:00 Vienna gives `recurrence_until == 2026-07-03T09:00Z` (the end of the third instance), and `UNTIL=20260705T235959Z` gives the end of 5 July's instance. An endless rule gives `None`. An all-day `UNTIL=20260705` gives the exclusive local midnight after 5 July.
  - `test_timed_until_as_date`: `UNTIL=20260705` on a timed rule is normalised to the UTC end of that local day.
  - `test_impossible_rule_terminates`: `FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30` starting 2026-02-28 gives `start_not_in_rule` within 1 s (`time.monotonic`).
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_rrule.py`: fails.
- [ ] **Step 3: Implement.** Parse parts yourself (split on `;` and `=`, upper-case) and use `dateutil.rrule.rrule` with explicit keyword arguments, never `rrulestr` on raw user text, so only allow-listed parts ever reach dateutil.
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): RRULE allow-list, normalisation and recurrence_until`.

### Task 4: Expansion on the event's wall clock

**Files:**
- Create: `sm_events/calendar/expand.py` (pure)
- Test: `tests/calendar/test_expand.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Instance:
    original_start: datetime   # UTC
    start: datetime            # UTC
    end: datetime              # UTC
def instances(*, rule: Rule, span: Span, all_day: bool, timezone: str,
              window_start: datetime, window_end: datetime,
              recurrence_until: datetime | None) -> Iterator[Instance]
    # lazy, ascending by start; yields instances whose [start, end) intersects the window;
    # iterates from window_start - (span duration) and never without an until (ruling 7)
def is_occurrence(original_start: datetime, *, rule, span, all_day, timezone) -> bool
```

- [ ] **Step 1: Write the failing tests:**
  - `test_weekly_keeps_wall_clock_across_dst`: weekly Monday 10:00 Vienna from 2026-03-16, 4 weeks: UTC starts are `09:00, 09:00, 08:00, 08:00` (the switch is on 29 March).
  - `test_gap_instance_shifts_forward`: daily 02:30 Vienna across 2026-03-29: that day's instance is `01:30Z` (03:30 local).
  - `test_fold_instance_takes_first`: daily 02:30 across 2026-10-25: `00:30Z`.
  - `test_all_day_series_days_not_hours`: a weekly all-day Sunday series across 29 March: each instance spans exactly one local date (`end - start` is 23 h on 29 March and 24 h otherwise).
  - `test_window_overlap_from_before`: a 3-day weekly series is included when the window starts in the middle of an instance.
  - `test_lazy_and_bounded`: `itertools.islice(instances(endless daily, 366-day window), 5)` returns within 50 ms, and consuming it fully yields 366 or 367 items.
  - `test_is_occurrence`: true for the third instance, and false for that instance plus one minute.
  - `test_property_wall_clock` (a seeded loop of 300 cases over random zones, freq and interval, weekly/monthly): for every instance not in a gap, its local wall time equals the master's local time.
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_expand.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): DST-correct lazy expansion of a series`.

### Task 5: Who sees and who writes an event

**Files:**
- Create: `sm_events/core/access/events.py`
- Test: `tests/core/access/test_event_access.py`
- Modify: `tests/support/calendars.py` (add `async seed_event(db, calendar, **fields) -> Event`, which inserts an `Event` and its default-locale `EventText` directly)

**Interfaces:**

```python
def visible_events(who: ResourcePrincipal, *, include_unpublished: bool = True) -> Select
    # select(Event) where calendar_id IN (visible_calendars(who) ids) and
    # (status == "published" or (include_unpublished and calendar_id IN POLICY.filter(who, write_events) ids))
def is_locked(event: Event) -> bool                          # published, or publish_at is not None
@dataclass(frozen=True)
class EventRights:
    view: bool; write: bool; publish: bool; locked: bool
async def event_rights(db, who, event: Event) -> EventRights  # from calendar_rights(); view mirrors visible_events
def require(rights: EventRights, *, publish: bool = False) -> None
    # not view -> NotFound; not write -> Forbidden; (locked or publish) and not rights.publish -> PublishRequired
async def load_event(db, who, event_id, *, trashed: bool = False) -> tuple[Event, EventRights]
    # NotFound for missing, other tenant, or invisible
```

- [ ] **Step 1: Write the failing tests.** Seed PR 1's `P`, `I` and `U` calendars (`tests/support/access.seed_calendars`), each with one draft, one in_review, one scheduled and one published event. `test_truth_table` is parametrized over PR 1's principals (`M`, `M+P`, `O`, `O+P`, `O-`, `SV`, `SE`, `E`, `E+P`, `V`, `N`, `A`) and asserts the set of `(calendar, status)` visible through `visible_events`. Writers on a calendar see all four statuses; everyone else who can see the calendar sees only `published`; `O-`, `N` and `A` see only `U`'s published event. Add:
  - `test_rights_locked`: for `SE` on `P`, the published event is `write=True, publish=False, locked=True`, and `require` raises `PublishRequired`; for `O+P` it passes.
  - `test_scheduled_is_locked`.
  - `test_include_unpublished_false_hides_drafts_even_for_writers`.
  - `test_load_event_invisible_is_404`: `V` loading `I`'s draft gets `NotFound`.
  - `test_trashed_calendar_hides_events`.
- [ ] **Step 2: Run** `uv run pytest -q tests/core/access/test_event_access.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and on Postgres (`SM_TEST_DATABASE_URL=…/smpy_events_test`): both pass.
- [ ] **Step 5: Commit** `feat(events): event visibility and write rights`.

### Task 6: The occurrences read and the built-in source

**Files:**
- Create: `sm_events/calendar/occurrence.py` (the `Occurrence` and `OccurrencePage` pydantic models, frozen)
- Create: `sm_events/calendar/sources.py` (the `Source` protocol, `SourceContext`, `EVENTS_SOURCE`, `SOURCES: dict[str, Source]`)
- Create: `sm_events/calendar/window.py` (the SQL: one-offs, series and overrides in a window)
- Create: `sm_events/calendar/occurrences.py` (the read: bounds, merge, cap)
- Test: `tests/calendar/test_occurrences.py` and `tests/calendar/test_occurrences_bounds.py`

**Interfaces:**

```python
class Occurrence(BaseModel):  # frozen
    source: str; key: str; calendar_id: uuid.UUID
    start: datetime; end: datetime; all_day: bool; timezone: str
    start_date: date | None; end_date: date | None
    title: str; lang: str; color: str; url: str | None
    status: Literal["confirmed", "cancelled"]; type: str; editable: bool
    event_id: uuid.UUID | None; original_start: datetime | None; event_status: str | None
class OccurrencePage(BaseModel):
    items: list[Occurrence]; truncated: bool

@dataclass(frozen=True)
class OccurrenceFilters:
    calendar_ids: frozenset[uuid.UUID] | None = None
    category_ids: frozenset[uuid.UUID] | None = None
    types: frozenset[str] | None = None
    locale: str | None = None
    include_unpublished: bool = True
@dataclass(frozen=True)
class SourceContext:
    tenant_id: str; viewer: ResourcePrincipal; default_locale: str; editor_url: Callable[[uuid.UUID], str]
class Source(Protocol):
    id: str
    def occurrences(self, db, ctx: SourceContext, start: datetime, end: datetime,
                    filters: OccurrenceFilters) -> AsyncIterator[Occurrence]   # ascending by (start, end, key)
async def occurrences(db, *, tenant_id: str, viewer: ResourcePrincipal, start: datetime, end: datetime,
                      filters: OccurrenceFilters, default_locale: str) -> OccurrencePage
    # aware start/end; InvalidRange on end <= start or > MAX_RANGE_DAYS; tenant must equal the bound tenant;
    # merges every source in SOURCES (only "events" in PR 2) with heapq.merge on (start, end, source, key); cap MAX_OCCURRENCES
```

- `window.py` uses three statements, all built on `visible_events(viewer, include_unpublished=…)` plus the filters, with the calendar and category joined for colour:
  - one-offs: `rrule IS NULL AND starts_at < :end AND ends_at > :start`, ordered by `starts_at`, `LIMIT MAX_OCCURRENCES + 1`;
  - series: `rrule IS NOT NULL AND starts_at < :end AND (recurrence_until IS NULL OR recurrence_until > :start)`, `LIMIT SERIES_FETCH_MAX + 1`;
  - overrides: `event_id IN (series ids) AND (original_start in [start - 31 d, end) OR starts_at in [start - 31 d, end))`.

  Texts come from a single query for all event ids.
- An all-day occurrence sets `start_date`/`end_date` from `times.all_day_dates`. `event.cancelled` or a `cancelled` override gives `status="cancelled"`. A `skipped` instance is dropped. A `moved` instance keeps its original key and `original_start` and goes into the merge at its new time.

- [ ] **Step 1: Write the failing tests** (`test_occurrences.py`, rows seeded through `seed_event` and direct `OccurrenceOverride` inserts):
  - `test_one_off_and_series_merge_sorted`.
  - `test_key_shapes` (ruling 12).
  - `test_read_across_dst`: a Vienna weekly series read over a range spanning 29 March gives 09:00Z then 08:00Z starts.
  - `test_all_day_range_edges`: an all-day event on 2026-03-29 Vienna is in `[2026-03-28T23:30Z, +1h)`, is not in `[.., 2026-03-28T23:00Z)`, and its `start_date/end_date` are `2026-03-29/2026-03-30`.
  - `test_overrides_applied`: skipped is absent, cancelled has `status == "cancelled"`, and moved sits at its new time with its original key.
  - `test_moved_into_window_from_outside`: an override moving an instance from last month into the window appears.
  - `test_moved_out_of_window_disappears`.
  - `test_cancelled_event_marks_all`.
  - `test_title_fallback_and_lang`: locale `de` with only an `en` text gives the `en` title and `lang == "en"`.
  - `test_color_category_then_calendar`.
  - `test_filters`: calendar, category and type; an invisible calendar id in `calendar_ids` is silently dropped.
  - `test_drafts_never_reach_viewers`: for `V`, `SV`, `A` and `O-`, the read over all three calendars contains only published events; for `SE` it also contains `P`'s drafts with `event_status == "draft"` and `editable == True`.
  - `test_editable_and_url`: a published event gives `editable == False` and `url is None` for `SE` (no publish), and `True` plus the editor URL for `O+P`.
  - `test_tenant_mismatch_raises` (`unbound_tenant`): `tenant_id="b"` while `"default"` is bound raises `ValueError`.

  `test_occurrences_bounds.py`:
  - `test_range_bounds`: 366 days passes, 366 days plus 1 s raises `InvalidRange(range_too_long)`, `end == start` raises `invalid_range`, and a naive datetime raises `ValueError`.
  - `test_cap_and_truncation`: 10 endless daily series over 366 days give exactly 2000 items, `truncated` is true, and the items are sorted.
  - `test_exact_cap_not_truncated`: exactly 2000 gives `truncated` false.
  - `test_many_series_bounded`: 3,000 daily series seeded in one bulk insert, over a 30-day window, finish in under 5 s on SQLite, with `truncated` true and 2000 items.
  - `test_impossible_stored_rule_terminates`: a row whose `rrule` is written directly to `FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30` finishes in under 1 s and yields nothing for it.
- [ ] **Step 2: Run** `uv run pytest -q tests/calendar/test_occurrences.py tests/calendar/test_occurrences_bounds.py`: fails.
- [ ] **Step 3: Implement.** `occurrences.py` holds the bounds and the merge; `sources.py` holds the built-in source, which calls `window.py` and `expand.instances`. A source is one object behind `Source`, so PR 6 only swaps `SOURCES` for its registry.
- [ ] **Step 4: Run** it on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): the bounded occurrences read with the built-in source`.

**End of batch A.** Run `cd modules/events && uv run pytest -q -n 8` (headroom first), plus `uv run python scripts/check_file_size.py` and `scripts/check_hardcoded_strings.py`.

---

### Task 7: Migration: `events_revision.note`

**Files:**
- Modify: `sm_events/models/revision.py` (`note: str | None = Field(default=None, max_length=NOTE_MAX)`)
- Create: `host/migrations/versions/<rev>_events_revision_note.py`
- Modify: `tests/models/test_models.py` (`test_revision_note_nullable`)

- [ ] **Step 1: Write the failing test** `test_revision_note_nullable`: a `Revision` without `note` flushes, and one with a 1000-character note flushes.
- [ ] **Step 2: Run** `uv run pytest -q tests/models`: fails.
- [ ] **Step 3: Check the head first.** `uv run python scripts/check_migration_heads.py`. When this plan was written the head was `b8e1d0783868` (PR 1). The framework bump PR #412 also chains off `541bfbe29a28`: if it has merged into the base, the head here may be a merge revision. Chain off whatever single head the script prints, and if it prints two, stop and report. Then autogenerate against a scratch SQLite file, exactly as PR 1 Task 5 Step 4 does (`SM_DATABASE_URL=sqlite+aiosqlite:////tmp/events-mig2.db`, `upgrade heads`, `make migration msg="events revision note"`). The revision must add only `events_revision.note` (`batch_alter_table` on SQLite). Give it a docstring. Run `upgrade`, `check`, `downgrade -1`, `upgrade` and `check`, then delete the file.
- [ ] **Step 4: Postgres.** On `smpy_events_check`: `upgrade heads`, `check`, `downgrade <parent>`, `upgrade heads`, `check`. Drop the database. Then run the Step 2 test (passes) and `check_migration_heads.py` (one head, the new revision).
- [ ] **Step 5: Commit** `feat(events): a note on each event revision`.

### Task 8: The rich-text sanitiser

**Files:**
- Create: `sm_events/content/__init__.py` (docstring), `sm_events/content/richtext.py`
- Test: `tests/content/__init__.py`, `tests/content/test_richtext.py`

**Interfaces:** `ALLOWED_TAGS` (ruling 22), `DROP_CONTENT`, `def clean(raw: str) -> str` (raises `DescriptionTooLong` over the raw or cleaned bound). The structure is newsletter's `_Cleaner` (`modules/newsletter/sm_newsletter/content/richtext.py:41-126`, read it and do **not** import it) with its own `_href`: http/https/mailto, control and whitespace characters stripped before the scheme check, absolute URLs only.

- [ ] **Step 1: Write the failing tests:**
  - `test_allowed_kept`, for every tag in the allow-list.
  - `test_attributes_dropped`: `<p style=… onclick=…>` becomes `<p>`.
  - `test_img_and_events_gone`: `<img src=x onerror=alert(1)>` becomes `""`.
  - `test_script_style_svg_contents_dropped`.
  - `test_href_schemes`: parametrized over `javascript:`, `JaVaScRiPt:`, `" jav&#x09;ascript:"`, `data:`, `vbscript:` and a relative `/x` (all unwrapped to their text), against `https://a`, `http://a` and `mailto:x@y` (kept).
  - `test_nested_anchor_unwrapped`.
  - `test_depth_cap`: 25 nested `<em>` keep at most 20 levels and close properly.
  - `test_idempotent`: a seeded loop over 200 random tag soups gives `clean(clean(x)) == clean(x)`.
  - `test_b_i_renamed`.
  - `test_bounds`: a raw input of 200,001 characters raises `DescriptionTooLong`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_richtext.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): allow-list sanitiser for descriptions`.

### Task 9: Texts, slugs and redirects

**Files:**
- Create: `sm_events/content/texts.py`, `sm_events/content/redirects.py`
- Modify: `sm_events/calendar/slugs.py` (add `async free_text_slug(db, locale: str, base: str, *, except_event: uuid.UUID | None = None) -> str`, which is `free_slug` scoped to `EventText.locale`)
- Create: `sm_events/web/schemas/texts.py` (`TextIn`, `TextOut`)
- Test: `tests/content/test_texts.py`

**Interfaces:**

```python
async def apply_texts(db, event: Event, texts: Mapping[str, TextIn | None], *,
                      locales: tuple[str, ...], creating: bool) -> list[str]   # locales changed
    # ruling 20 and 21; UnknownLocale, DefaultLocaleRequired, SlugTaken (via slug_write)
async def record_rename(db, *, event_id, locale, old_slug) -> None             # in redirects.py
async def release_slug(db, *, locale, slug) -> None                            # delete redirect (locale, slug)
async def texts_of(db, event_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, EventText]]
```

- `TextIn`: `title` (`SingleLine`, 1–300, stripped), `slug: Slug | None` (PR 1's `Slug`, but `max_length=TEXT_SLUG_MAX`), `summary` (`MultiLine`, ≤ 1000), `description: str = ""` (cleaned in `apply_texts`, not in the schema, so the error carries its code), `seo_title`, `seo_description`, `noindex`.

- [ ] **Step 1: Write the failing tests:**
  - `test_default_locale_required_on_create`.
  - `test_null_deletes_but_never_default`.
  - `test_unknown_locale`.
  - `test_slug_derived_per_locale`: two events titled "Konzert" in `de` get `konzert` and `konzert-2`, while the `en` "Konzert" stays `konzert`.
  - `test_explicit_slug_taken_409`: also when it is held by a trashed event.
  - `test_rename_records_redirect_in_that_locale_only`.
  - `test_claim_releases_redirect`: event B takes A's old `de` slug, and the `(de, old)` redirect row is gone.
  - `test_rename_back_removes_redirect`.
  - `test_description_cleaned_on_save`.
  - `test_slug_race_is_conflict`: the pre-check is monkeypatched to say free, and the `IntegrityError` becomes `SlugTaken`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_texts.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): texts per locale with slug redirects`.

### Task 10: Revisions and the stale guard

**Files:**
- Create: `sm_events/content/revisions.py`, `sm_events/content/guard.py`
- Test: `tests/content/test_revisions.py`, `tests/content/test_guard.py`

**Interfaces:**

```python
# guard.py
async def claim_revision(db, event_id: uuid.UUID, expected: int, *, actor: str | None,
                         trashed: bool = False) -> int     # new revision; Stale or NotFound (ruling 19)
# revisions.py
def snapshot(event: Event, texts: Mapping[str, EventText], overrides: Sequence[OccurrenceOverride]) -> dict
async def record(db, event: Event, *, action: str, actor: str | None, note: str | None = None) -> Revision
    # loads texts and overrides, writes number = event.revision, prunes beyond REVISIONS_KEPT
async def list_revisions(db, event_id) -> list[Revision]   # newest first, no snapshot loaded into the response
async def get_revision(db, event_id, number) -> Revision   # NotFound
```

- Constants: `REVISION_ACTIONS` (the tuple in ruling 18).

- [ ] **Step 1: Write the failing tests:**
  - `test_cas_loses_once`: two `claim_revision(…, expected=1)` calls in sequence: the first returns 2, the second raises `Stale`.
  - `test_cas_missing_is_not_found`.
  - `test_cas_other_tenant_is_not_found` (`unbound_tenant`).
  - `test_cas_trashed_needs_flag`.
  - `test_snapshot_fields`: the snapshot's keys are exactly the listed columns plus `texts` and `overrides`, and it is JSON serialisable (`json.dumps`).
  - `test_snapshot_preserves_extra`.
  - `test_prune_keeps_100`: after 105 records only numbers 6–105 remain.
  - `test_note_stored`.
  - On Postgres only (`pytest.mark.skipif` without `SM_TEST_DATABASE_URL`), `test_concurrent_cas_serialises`: two sessions claim at once, and exactly one wins.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_revisions.py tests/content/test_guard.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): revisions and the expected_revision guard`.

### Task 11: Bus events and after-commit emission

**Files:**
- Create: `sm_events/contracts/__init__.py` (docstring only for now; `mounted` arrives in Task 16), `sm_events/contracts/events.py`
- Create: `sm_events/content/bus.py`
- Create: `sm_events/web/endpoints/deps.py` addition: `async def event_db(request, db=Depends(get_db)) -> AsyncSession`, which attaches `request.app.state.sm.event_bus` to the session (records' `request_db`, `modules/records/sm_records/web/deps.py:72-95`)
- Test: `tests/content/test_bus.py`

**Interfaces:**
- `contracts/events.py`: the four dataclasses of ruling 25, each `@dataclass(frozen=True)` subclassing `simple_module_core.events.Event`, with fields in the order `tenant_id, event_id, calendar_id, uid, …`. The docstring states the after-commit rule and that a worker publishes nothing (open point 2).
- `content/bus.py`: `attach(session, bus)`, `emit(session, *events)` (`register_on_commit` with the bound tenant re-bound around the publish), `async commit(session)` (`mark_written` and then `finalize_session`) and `async rollback(session)` (`discard_on_commit_callbacks`). This is a reduced copy of `modules/records/sm_records/core/events.py:91-180` without `held`/`muted`.

- [ ] **Step 1: Write the failing tests:**
  - `test_emitted_after_commit_only`: with a recording bus attached, `emit` and then `rollback` publish nothing, while `emit` and then `commit` publish exactly one event.
  - `test_no_bus_no_publish`.
  - `test_tenant_rebound_on_publish` (`unbound_tenant`): the handler sees `current_tenant_id == "b"`.
  - `test_dataclass_shapes`: the field names of each class, in order.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_bus.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: passes. Then from the root `uv run python scripts/check_sibling_contracts.py` (passes).
- [ ] **Step 5: Commit** `feat(events): bus events published after commit`.

### Task 12: Event writes: create, update, trash, restore, sub-events

**Files:**
- Create: `sm_events/web/schemas/events_in.py` (`TimesIn`, `EventCreate`, `EventPatch`, `Expected`)
- Create: `sm_events/content/fields.py` (field validation that needs the database: category, parent)
- Create: `sm_events/content/events_write.py` (create and update)
- Create: `sm_events/content/events_trash.py` (trash and restore)
- Test: `tests/content/test_events_write.py`, `tests/content/test_events_trash.py`, `tests/content/test_subevents.py`

**Interfaces:**

```python
class TimesIn(BaseModel): all_day: bool = False; timezone: TimezoneName; start: str; end: str
class EventCreate(BaseModel):
    calendar_id: uuid.UUID; parent_id: uuid.UUID | None = None; type: str = DEFAULT_EVENT_TYPE
    times: TimesIn; rrule: str | None = None; cancelled: bool = False
    attendance_mode: Literal[*ATTENDANCE_MODES] = "in_person"; venue_name, address, online_url,
    latitude, longitude, category_id, organiser, image, registration_url   # all optional
    texts: dict[str, TextIn]
class EventPatch(BaseModel):   # every field optional; exclude_unset semantics
    expected_revision: int; times: TimesIn | None; rrule: str | None; ...; texts: dict[str, TextIn | None] | None
    drop_orphaned_overrides: bool = False
    # calendar_id, parent_id, type: present -> ImmutableField (model_validator, mode="before")

async def create_event(db, who, data: EventCreate, *, locales) -> Event
    # rights via calendar_rights(write_events) else NotFound/Forbidden; status draft; revision 1; uid;
    # rrule parsed+validated (Task 3), recurrence_until set; texts; revision "created"
async def update_event(db, who, event_id, data: EventPatch, *, locales) -> Event
    # load_event -> require(publish=locked) -> claim_revision -> apply -> orphan check (Task 13) ->
    # revision "updated" -> emit EventRescheduled / EventCancelled when published (ruling 25)
async def trash_event(db, who, event_id, expected: int) -> None      # HasSubEvents; EventDeleted
async def restore_event(db, who, event_id, expected: int) -> Event
```

- `TimezoneName` is a new `Annotated` validator in `web/schemas/_fields.py` built on `timezones.is_known` (PR 1 validates calendars inline; extract it and reuse it there).
- `update_event` recomputes the `Span` when `times` is sent, or when `rrule` changes (the duration bound depends on recurrence), and re-derives `recurrence_until`.

- [ ] **Step 1: Write the failing tests:**
  - `test_create_defaults`: draft, revision 1, a `uid` ending `@simple-module-events`, a `created` revision row, and `type == "event"`.
  - `test_create_needs_write_events`: `V` on `I` gets `Forbidden`, `V` on `P` gets `NotFound`, and `SE` on `P` succeeds.
  - `test_unknown_type_and_category`.
  - `test_series_create_sets_recurrence_until`.
  - `test_series_duration_bound`: a 32-day recurring event gives `duration_too_long`.
  - `test_patch_partial`: changing only the venue leaves the texts untouched and bumps the revision by one.
  - `test_patch_stale`.
  - `test_immutable_fields`.
  - `test_extra_preserved`: a row with `extra={"x": 1}` keeps it after a PATCH.
  - `test_locked_event_needs_publish`: on a published event, `SE` PATCH, `cancelled=True`, trash and restore each raise `PublishRequired`, and the revision count is unchanged; `O+P` succeeds.
  - `test_draft_write_no_bus`: a draft time change emits nothing.
  - `test_published_reschedule_emits`: a published event's time change emits one `EventRescheduled` with old and new UTC times and `original_start is None`.
  - `test_cancel_emits_cancelled`.
  - `test_trash_restore`: restore brings back the old status, `trash` emits `EventDeleted(was_published=…)`, and the trashed event is gone from `visible_events`.
  - `test_subevents.py`:
    - `test_child_same_calendar`;
    - `test_no_grandchildren`;
    - `test_recurring_parent_refused`;
    - `test_recurring_child_refused`;
    - `test_adding_rrule_to_a_parent_refused` (PATCH);
    - `test_parent_with_children_cannot_be_trashed` (409 `has_sub_events`, and trashing the children first lets it through).
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_events_write.py tests/content/test_events_trash.py tests/content/test_subevents.py`: fails.
- [ ] **Step 3: Implement.** Services never commit; the endpoint finishes through `bus.commit`/`finalize_session` (Task 14). Split if `events_write.py` nears 250 lines: `_apply.py` takes the field mapping.
- [ ] **Step 4: Run** it on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): create, edit, trash and restore events`.

### Task 13: Overrides and the series-change preview

**Files:**
- Create: `sm_events/content/overrides.py`, `sm_events/content/series_change.py`
- Create: `sm_events/web/schemas/overrides.py` (`OverrideIn`, `OverrideOut`, `PreviewIn`, `PreviewOut`)
- Modify: `content/events_write.py` (`update_event` calls `series_change.orphans` and raises or drops)
- Test: `tests/content/test_overrides.py`, `tests/content/test_series_change.py`

**Interfaces:**

```python
class OverrideIn(BaseModel):
    expected_revision: int; original_start: AwareDatetime; kind: Literal[*OVERRIDE_KINDS]
    start: str | None = None; end: str | None = None   # local wall clock, required iff kind == "moved"
    note: str | None   # MultiLine, <= NOTE_MAX
async def set_override(db, who, event_id, data: OverrideIn) -> OccurrenceOverride
    # NotRecurring, NotAnOccurrence (expand.is_occurrence), times.to_span(recurring=True); upsert;
    # claim_revision; revision "override_set"; emit Rescheduled (moved) / Cancelled (cancelled) when published
async def clear_override(db, who, event_id, override_id: int, expected: int) -> None   # "override_cleared"
async def orphans(db, event: Event, *, rule: Rule | None, span: Span, all_day: bool, timezone: str)
    -> list[OccurrenceOverride]       # overrides whose original_start is no longer an occurrence
async def preview(db, who, data: PreviewIn) -> PreviewOut
    # PreviewIn: times, rrule, event_id?, after?: AwareDatetime, count (1..PREVIEW_MAX, default PREVIEW_DEFAULT)
    # PreviewOut: occurrences [{start, end, start_local, end_local}], recurrence_until, orphaned: list[OverrideOut]
    # with event_id: load_event (view); without: pure computation
```

- [ ] **Step 1: Write the failing tests:**
  - `test_override_on_one_off_refused`.
  - `test_override_not_an_occurrence`.
  - `test_moved_needs_times_and_only_times`: extra fields are refused by the schema (`extra="forbid"`).
  - `test_moved_duration_bound`.
  - `test_second_write_replaces`.
  - `test_clear`.
  - `test_override_bumps_revision_and_records`.
  - `test_override_on_published_needs_publish`.
  - `test_moved_emits_rescheduled_with_original_start`.
  - `test_series_change.py`:
    - `test_rule_change_reports_orphans`: weekly MO → TU orphans a Monday override, and `PATCH` without the flag raises `OverridesOrphaned` and changes nothing (revision unchanged).
    - `test_drop_flag_deletes_and_notes`: the revision `note` lists the dropped originals.
    - `test_start_shift_orphans_all`.
    - `test_unchanged_rule_no_orphans`.
    - `test_preview_next_n_after`: count 10 after a date, with local times.
    - `test_preview_without_event_is_pure`.
    - `test_preview_invisible_event_404`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_overrides.py tests/content/test_series_change.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: both pass.
- [ ] **Step 5: Commit** `feat(events): occurrence overrides and the series-change preview`.

### Task 14: Workflow

**Files:**
- Create: `sm_events/content/workflow.py`
- Create: `sm_events/web/schemas/workflow.py` (`Expected`, `ApproveIn {expected_revision, publish_at_local: str | None}` (`YYYY-MM-DDTHH:MM`, read in the event's timezone through `times.localize`; a gap time gives 422 `invalid_local_time`), `RejectIn {expected_revision, note}`)
- Test: `tests/content/test_workflow.py`

**Interfaces:**

```python
TRANSITIONS: Mapping[str, tuple[frozenset[str], bool]]   # action -> (from statuses, needs publish); ruling 17
async def transition(db, who, event_id, action: str, *, expected: int,
                     publish_at: datetime | None = None, note: str | None = None, now: datetime) -> Event
    # load_event -> require(publish=needs or locked) -> state check (InvalidTransition) -> claim_revision ->
    # apply -> revisions.record(action, note) -> emit EventPublished on publish
```

- [ ] **Step 1: Write the failing tests:**
  - `test_transition_table`: parametrized over every `(action, from status, scheduled?)`; allowed cells land in the ruled state, and the rest raise `InvalidTransition` with the revision unchanged.
  - `test_submit_by_writer_without_publish`.
  - `test_approve_needs_publish`.
  - `test_approve_future_schedules`: the status stays the same, `publish_at` is set, `is_locked` is true, the revision action is `scheduled`, and there is no bus event.
  - `test_approve_past_publishes_now`: `published_at == now`, plus `EventPublished`.
  - `test_reject_note_required_and_recorded`.
  - `test_unpublish_keeps_published_at`.
  - `test_unschedule`.
  - `test_stale_transition`.
  - `test_view_only_404`.
  - `test_approve_local_publish_at`: `"2026-07-01T10:00"` on a Vienna event schedules for `08:00Z`.
- [ ] **Step 2: Run** `uv run pytest -q tests/content/test_workflow.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): review and publishing workflow`.

### Task 15: The HTTP API

**Files:**
- Create: `sm_events/web/schemas/events_out.py` (`EventOut`, `EventListItem`, `EventPage`, `RevisionOut`, `RevisionDetail`)
- Create: `sm_events/web/schemas/occurrences.py` (query parsing)
- Create: `sm_events/content/listing.py` (`list_events`, ruling 26)
- Create: `sm_events/web/endpoints/events_api.py` (CRUD and list)
- Create: `sm_events/web/endpoints/events_actions_api.py` (workflow, revisions, overrides, preview)
- Create: `sm_events/web/endpoints/occurrences_api.py`
- Create: `sm_events/web/services/events_out.py` (render `EventOut` with rights and local times)
- Modify: `web/endpoints/__init__.py` (include the three routers)
- Test: `tests/web/test_events_api.py`, `tests/web/test_events_actions_api.py`, `tests/web/test_occurrences_api.py`, `tests/content/test_listing.py`

**Interfaces.** Every route requires `events.view`, uses `event_db`, finishes with `bus.commit` and is under the parent router's `bind_admin` and CSRF.

| Method and path | Body / query | Success | Errors |
|---|---|---|---|
| `GET /api/events/events` | `calendar` (repeatable), `status`, `category`, `from`, `to`, `q`, `trashed`, `locale`, `page`, `page_size` | 200 `EventPage` | 422 |
| `POST /api/events/events` | `EventCreate` | 201 `EventOut` | 403, 404, 409 `slug_taken`, 422 |
| `GET /api/events/events/{id}` | `locale?` | 200 `EventOut` | 404 |
| `PATCH /api/events/events/{id}` | `EventPatch` | 200 | 403 `publish_required`, 404, 409 `stale`/`overrides_orphaned`/`slug_taken`, 422 |
| `DELETE /api/events/events/{id}?expected_revision=` | none | 204 | 403, 404, 409 `stale`/`has_sub_events` |
| `POST /api/events/events/{id}/restore` | `Expected` | 200 | 403, 404, 409 |
| `POST /api/events/events/{id}/{submit,withdraw,approve,reject,unschedule,unpublish}` | `Expected`/`ApproveIn`/`RejectIn` | 200 | 403, 404, 409 `invalid_transition`/`stale` |
| `GET /api/events/events/{id}/revisions` | none | 200 `list[RevisionOut]` | 404 |
| `GET /api/events/events/{id}/revisions/{number}` | none | 200 `RevisionDetail` | 404 |
| `POST /api/events/events/{id}/overrides` | `OverrideIn` | 200 `OverrideOut` | 403, 404, 409 `stale`, 422 |
| `DELETE /api/events/events/{id}/overrides/{override_id}?expected_revision=` | none | 204 | 403, 404, 409 |
| `POST /api/events/recurrence/preview` | `PreviewIn` | 200 `PreviewOut` | 404, 422 |
| `GET /api/events/occurrences` | `start`, `end` (aware ISO), `calendar`, `category`, `type` (repeatable), `locale`, `include_unpublished` | 200 `OccurrencePage` | 422 `invalid_range`/`range_too_long` |

- `EventOut` carries every column, `start_local`/`end_local`, `texts: dict[str, TextOut]`, `overrides: list[OverrideOut]`, `sub_events: list[{id, title, start_local}]` (≤ 200), `scheduled: bool`, `extra` (read-only), and `can_write`, `can_publish` and `locked`.

- [ ] **Step 1: Write the failing tests** (through `tests/support/app.py`):
  - `test_create_read_update_round_trip` (local times in, local times out).
  - `test_error_envelope_on_every_new_code`: one request per code in ruling 27, and each body is exactly `{"detail","code"}`.
  - `test_api_locked_matrix`: `SE` vs `O+P` on a published event for PATCH, DELETE, restore, override and cancel.
  - `test_stale_everywhere`: PATCH, DELETE, restore, every workflow action and override set/clear with an old revision get 409 `stale`.
  - `test_view_only_sees_published_only`: list, GET (404 on a draft) and occurrences.
  - `test_list_filters_and_paging`: status, category, date range intersecting a series, `q` over a `de` title, `page_size=101` gives 422, and `total` is correct.
  - `test_trashed_list_only_restorable`.
  - `test_occurrences_api_bounds`: a naive `start` gives 422, 367 days gives `range_too_long`, and `truncated` is serialised.
  - `test_preview_api`.
  - `test_revisions_api`: list newest first, without snapshots.
  - `test_writes_need_csrf`.
  - `test_tenant_isolation` (`unbound_tenant`, multi mode): another tenant's event id is a 404 on every route.
  - `test_bus_events_after_commit_http`: a published reschedule through PATCH is seen by a handler on the harness bus; a refused PATCH publishes nothing.
  - `test_listing.py`: `test_series_intersects_range` and `test_one_off_intersects_range`.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_events_api.py tests/web/test_events_actions_api.py tests/web/test_occurrences_api.py tests/content/test_listing.py`: fails.
- [ ] **Step 3: Implement.** Keep routers thin: each handler loads, calls one service and renders.
- [ ] **Step 4: Run** it on SQLite and Postgres (both pass), then the fresh-import check over every new module (`uv run python -c "import …"`).
- [ ] **Step 5: Commit** `feat(events): events, workflow, overrides and occurrences API`.

**End of batch B.** Run the module suite (`-n 8`), `check_file_size.py`, `check_hardcoded_strings.py` and `ruff check modules/events`.

---

### Task 16: `contracts.occurrences` and `contracts.mounted`

**Files:**
- Modify: `sm_events/contracts/__init__.py` (add `def mounted(app: Any) -> bool`: `getattr(app.state, PACKAGE, None) is not None`, as `modules/news/news/contracts/articles.py:52-54` does)
- Create: `sm_events/contracts/occurrences.py`
- Modify: root `pyproject.toml` `[tool.pyright] include` (add `"modules/events/sm_events/contracts"` in sorted position under "The contracts packages")
- Test: `tests/contracts/__init__.py`, `tests/contracts/test_occurrences_contract.py`

**Interfaces:**

```python
from sm_events.calendar.occurrence import Occurrence, OccurrencePage   # re-exported
async def occurrences(session: AsyncSession, *, tenant_id: str, viewer: ResourcePrincipal | None,
                      start: datetime, end: datetime, calendar_ids: Iterable[uuid.UUID] | None = None,
                      category_ids: Iterable[uuid.UUID] | None = None, types: Iterable[str] | None = None,
                      locale: str | None = None, default_locale: str = "en") -> OccurrencePage
    # binds tenant_scope(tenant_id) itself; viewer None -> anonymous principal (public calendars,
    # published events only, include_unpublished forced False); never commits
```

In this file, SQLModel columns go through `sqlmodel.col()`, and any suppression is `# pyright: ignore[rule]` with its reason.

- [ ] **Step 1: Write the failing tests:**
  - `test_anonymous_gets_public_published_only`.
  - `test_viewer_matches_internal_read`: the same items as `calendar.occurrences.occurrences`.
  - `test_contract_binds_tenant` (`unbound_tenant`): called with nothing bound and `tenant_id="b"`, it returns only `b`'s events.
  - `test_mounted`: true on the test app and false on a bare `FastAPI()`.
  - `test_contract_surface`: `__all__ == ["Occurrence", "OccurrencePage", "occurrences"]`.
- [ ] **Step 2: Run** `uv run pytest -q tests/contracts`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it (passes), then from the root `uv run basedpyright` (0 errors) and `uv run python scripts/check_sibling_contracts.py` (passes).
- [ ] **Step 5: Commit** `feat(events): the occurrences contract`.

### Task 17: `events.publish_due`, the worker runtime and the queues

**Files:**
- Modify: `modules/events/pyproject.toml` (the `simple_module_background_tasks` line from Global Constraints), `uv.lock`
- Modify: `sm_events/core/constants.py` (`_MODULE_BACKGROUND_TASKS = "BackgroundTasks"`, added to `DEPENDS_ON`), and PR 1's `test_meta` (`depends_on` gains it)
- Create: `sm_events/task_config.py`, `sm_events/tasks.py`
- Create: `sm_events/core/worker.py` (a copy of `modules/newsletter/sm_newsletter/core/worker.py` with `sm_events.core.tenancy.install_guard` and "events" in the error text)
- Create: `sm_events/content/publish_due.py`
- Modify: `Makefile` line 69 (`-Q images,newsletter,events,celery`) and its comment block (lines 59-65: add events and `events.publish_due`); `.github/workflows/ci.yml` lines 735-742 (the comment and `-Q images,newsletter,events,celery`)
- Test: `tests/core/test_task_discovery.py`, `tests/core/test_worker.py`, `tests/content/test_publish_due.py`

**Interfaces:**
- `task_config.py`: `PUBLISH_DUE = "events.publish_due"`, `QUEUE_DEFAULT = "events"`, `QUEUES = {QUEUE_DEFAULT}`, `TASK_ROUTES = {PUBLISH_DUE: {"queue": "events"}}`, `PUBLISH_DUE_INTERVAL_SECONDS = 60.0`, `BEAT_SCHEDULE = {"events-publish-due": {"task": PUBLISH_DUE, "schedule": 60.0, "options": {"queue": "events", "expires": 55}}}`. Keep it free of heavy imports.
- `tasks.py`: `@shared_task(name=PUBLISH_DUE) def publish_due() -> dict[str, int]`, which runs `run_platform(lambda f: publish_due_async(f, now=utcnow()))` and logs `"events.publish_due: %d tenant(s), %d published, %d failed"`. Also add `worker_process_init` → `reset_worker_runtime` (newsletter's `tasks.py:118-124`).
- `content/publish_due.py`: `async def publish_due_async(session_factory, *, now: datetime) -> dict[str, int]` (keys `tenants`, `published`, `failed`). It runs one `all_tenants()` read of `select(distinct(Event.tenant_id)).where(Event.status.in_(("draft","in_review")), Event.publish_at <= now)`. Then, per tenant, a fresh session under `tenant_context(t)`: due rows `ORDER BY publish_at LIMIT PUBLISH_DUE_BATCH`, with `with_for_update(skip_locked=True)` on Postgres. Each row is published by setting status, `published_at = now` and `publish_at = None`, then `claim_revision(expected=row.revision, actor=None)` and `revisions.record("published_scheduled")`. A `Stale` skips the row: someone edited it, and the next tick sees it again. A tenant that raises is logged, counted in `failed` and rolled back, and the others continue. Each tenant finishes with `finalize_session`. No bus is attached in a worker.

- [ ] **Step 1: Write the failing tests:**
  - `test_task_discovery.py`: a port of newsletter's `test_the_task_module_sits_where_autodiscovery_imports_it`, `test_the_framework_loads_routes_and_beat_from_the_package` (`config.queues == frozenset({"events"})`) and the beat-entry assertion above.
  - `test_worker.py`: a port of newsletter's `test_the_task_unbinds_the_callers_tenant`, `test_a_task_body_refuses_a_running_loop`, `test_worker_engine_is_guarded_and_rebuilt_in_a_forked_child` and `test_worker_process_init_forgets_the_runtime`, with their `worker_db` fixture copied from `modules/newsletter/tests/core/test_worker.py`.
  - `test_publish_due.py`:
    - `test_publishes_only_due`: a past `publish_at` is published and a future one is untouched.
    - `test_per_tenant` (`unbound_tenant`): two tenants each get their own published rows, and the revision row is in the right tenant.
    - `test_batch_cap`: 201 due rows give 200 published.
    - `test_trashed_not_published`.
    - `test_already_published_skipped`.
    - `test_failing_tenant_does_not_stop_others`: monkeypatch `claim_revision` to raise for tenant `a`.
    - `test_eager_task_runs` (`publish_due.apply()` under `task_always_eager`).
- [ ] **Step 2: Run** `uv run pytest -q tests/core/test_task_discovery.py tests/core/test_worker.py tests/content/test_publish_due.py`: fails.
- [ ] **Step 3: Implement**, then run `uv sync --all-packages --all-extras --no-extra anonymize` (headroom first).
- [ ] **Step 4: Run** the tests on SQLite and Postgres (both pass), and from the root `uv run pytest -q host/tests/test_host_boots.py host/tests/test_events_wiring.py` (passes).
- [ ] **Step 5: Commit** `feat(events): scheduled publishing on the events queue`.

**End of batch C.** Run the module suite, `basedpyright`, `check_sibling_contracts.py` and `check_rules.py`.

---

### Task 18: Views, menu and page props

**Files:**
- Modify: `sm_events/core/constants.py`: `_PAGE_EVENTS = f"{MODULE_NAME}/Events"`, `_PAGE_EVENT_EDITOR = f"{MODULE_NAME}/EventEditor"`, `EVENTS_URL = f"{VIEW_PREFIX}/list"`, `EVENT_EDIT_URL = f"{VIEW_PREFIX}/edit"`, `MENU_LABEL_EVENTS = "Events"`, `MENU_LABEL_KEY_EVENTS = "events.menu.events"` and `MENU_ICON_EVENTS = "calendar-days"`
- Modify: `web/endpoints/views.py` (three routes), `web/endpoints/menu.py` (the Events entry, `order=395`), `locales/en.json` and `de.json` (`menu.events`)
- Modify: `host/tests/test_menu_labels.py` (the item count goes from 16 to 17), `host/tests/test_events_wiring.py` (paths)
- Test: `tests/web/test_views.py`

**Interfaces:**
- `GET /list` (`events.view`) renders `_PAGE_EVENTS` with `{**view_props, "content_locales", "can_create": bool(any calendar with write_events), "categories": [CategoryOut], "calendars": [{id, name, color, can_write_events}]}`.
- `GET /edit/new?calendar=<uuid>` (`events.view`; 404 unless the caller has `write_events` on that calendar) and `GET /edit/{event_id}` (`events.view`; 404 when invisible) render `_PAGE_EVENT_EDITOR` with `{**view_props, "event_id": str | None, "calendar": {id, name, default_timezone}, "content_locales", "categories", "default_timezone"}`. Event data is loaded from the API, not from props.
- `GET /` still answers 303 to Calendars.

- [ ] **Step 1: Write the failing tests:**
  - `test_list_page_props`.
  - `test_editor_new_needs_write`: `V` on `I` gets 404, and `E` on `I` gets 200.
  - `test_editor_invisible_event_404`.
  - `test_root_still_redirects_to_calendars`.
  - The `test_events_wiring` path set gains `/admin/events/list` and `/admin/events/edit/{event_id}`.
  - In the menu, Events comes before Calendars.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_views.py`, then from the root `uv run pytest -q host/tests/test_events_wiring.py host/tests/test_menu_labels.py`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same (passes), plus `check_hardcoded_strings.py` and `check_locales.py`.
- [ ] **Step 5: Commit** `feat(events): Events list and editor views, menu entry`.

### Task 19: The frontend API client, types and recurrence utilities

**Files:**
- Create: `sm_events/ui/utils/api-events.ts`, `ui/utils/types-events.ts`, `ui/utils/recurrence.ts`, `ui/utils/recurrence.test.ts`
- Modify: `ui/utils/api.ts` (`errorText` maps every new code to `keys.events.errors.*`), `locales/en.json`/`de.json` (`errors.*`, `recurrence.*`)
- Test: `ui/page-tests/useEvents.test.tsx` (the client through `stubFetch`)

**Interfaces:**
- `api-events.ts`: `listEvents(query)`, `getEvent(id, locale?)`, `createEvent(body)`, `updateEvent(id, body)`, `trashEvent(id, rev)`, `restoreEvent(id, rev)`, `transition(id, action, body)`, `listRevisions(id)`, `getRevision(id, n)`, `setOverride(id, body)`, `clearOverride(id, overrideId, rev)`, `previewRecurrence(body)` and `listOccurrences(query)`. All go through PR 1's `ApiError`.
- `recurrence.ts`:
  - `type RuleForm = {freq: 'DAILY'|'WEEKLY'|'MONTHLY'|'YEARLY'; interval: number; byDay: Weekday[]; monthly: {mode: 'day'|'nth'; nth?: -1|1|2|3|4}; end: {kind: 'never'} | {kind: 'count'; count: number} | {kind: 'until'; date: string}}`
  - `parseRule(text: string | null, start: string): RuleForm | {custom: string} | null`
  - `buildRule(form: RuleForm, start: string): string`, which returns the server's normalised text, always including the start's weekday for weekly
  - `summarise(form: RuleForm | {custom: string}): string`, which uses `t(keys.events.recurrence.*)`, plurals by count, and weekday names from `Intl.DateTimeFormat`

- [ ] **Step 1: Write the failing tests** in `recurrence.test.ts`:
  - `round-trips every supported form`: for each form, `parseRule(buildRule(f)) ≡ f`.
  - `unknown parts become custom` (`BYSETPOS` with `BYMONTHDAY`, for instance).
  - `weekly always includes the start weekday`.
  - `summaries in en`: `"Every week on Monday and Wednesday, 10 times"`, `"Every 2 months on the last Friday, until 31 Dec 2026"`.
  - `de catalogue has every key` (covered by `check_locales`).
  - In `useEvents.test.tsx`: `sends expected_revision on update and maps 409 stale`.
- [ ] **Step 2: Run** `~/.claude/bin/wait-for-headroom`, then `npx vitest run modules/events/sm_events/ui/utils/recurrence.test.ts modules/events/sm_events/ui/page-tests/useEvents.test.tsx`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same, `npx tsc --noEmit -p modules/events/tsconfig.json` and `npx biome check modules/events`: all pass.
- [ ] **Step 5: Commit** `feat(events): events API client and recurrence form helpers`.

### Task 20: The Events list screen

**Files:**
- Create: `sm_events/pages/Events.tsx`, `ui/components/events/EventFilters.tsx`, `ui/components/events/EventRow.tsx`, `ui/hooks/useEvents.ts`
- Modify: locales (`list.*`)
- Test: `ui/page-tests/Events.test.tsx`

**Interfaces:** a filter bar (calendar, status, category, from/to dates, text) whose state is mirrored in the URL query. A table showing the title in the console locale with a `lang` badge on fallback, the calendar swatch, the local start in the event's timezone (plus the timezone when it differs from the browser's), a recurrence icon with its summary as a tooltip, a status badge (`Scheduled` when `scheduled`) and a cancelled marker. Paging (previous/next and the total), "New event" (a calendar picker over the calendars with `can_write_events`), and an Active/Trash toggle where trash rows offer Restore. Each row links to the editor.

- [ ] **Step 1: Write the failing tests:**
  - `renders rows with status and scheduled badges`.
  - `filters write to the query and refetch`.
  - `text filter is debounced`.
  - `paging`.
  - `New event hidden without can_create`.
  - `trash then restore sends expected_revision`.
  - `fallback title shows lang badge`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/Events.test.tsx`: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, tsc, biome and `uv run python scripts/check_rules.py`: all pass.
- [ ] **Step 5: Commit** `feat(events): Events list screen`.

### Task 21: The editor: fields, texts per locale, rich text, recurrence and preview

**Files:**
- Create: `sm_events/pages/EventEditor.tsx` (layout and data loading only)
- Create: `ui/components/editor/EventForm.tsx` (times, place, category, flags), `ui/components/editor/TimesFields.tsx`, `ui/components/editor/TextsTabs.tsx`, `ui/components/editor/RichTextField.tsx`, `ui/components/editor/RecurrenceEditor.tsx`, `ui/components/editor/OccurrencesPreview.tsx`, `ui/components/editor/OverrideDialog.tsx`
- Create: `ui/hooks/useEvent.ts` (load and save with `expected_revision`, and the dirty state), `ui/hooks/usePreview.ts` (a debounced `previewRecurrence`)
- Modify: locales (`editor.*`)
- Test: `ui/page-tests/EventEditor.test.tsx`, `ui/page-tests/RecurrenceEditor.test.tsx`, `ui/page-tests/RichTextField.test.tsx`

**Interfaces:**
- Times: an all-day toggle switches between `date` and `datetime-local` inputs. The timezone uses PR 1's datalist field, defaulting to the calendar's.
- `TextsTabs`: one tab per content locale with a missing marker. The default locale cannot be removed; other tabs have "Remove this language", which sends `null`. Each tab has title, slug (placeholder "derived from the title"), summary, `RichTextField` and an SEO disclosure. Server 422 field errors go through PR 1's `useFormErrors`/`field-errors` with `loc` `texts.<locale>.<field>`.
- `RecurrenceEditor`: "Does not repeat", or the `RuleForm` controls, with the `summarise` line underneath. It is disabled with an explanation on a sub-event and on an event that has sub-events (ruling 9).
- `OccurrencesPreview`: the next 10 from `usePreview`, in local time. For a saved series, each row has actions "Skip", "Cancel" and "Move…" (`OverrideDialog` with start/end and a note) and a "Restore" for an existing override. Every action sends the event's current `expected_revision` and then reloads.
- Saving a changed rule or start first calls the preview. When `orphaned` is non-empty, a confirm dialog lists them, and only on confirm is `PATCH` sent with `drop_orphaned_overrides: true`.

- [ ] **Step 1: Write the failing tests:**
  - `EventEditor.test.tsx`:
    - `creates an event with texts in two locales` (asserts the body).
    - `all-day switches inputs and sends dates`.
    - `server field error lands on the de title`.
    - `default locale tab cannot be removed`.
    - `save sends expected_revision`.
  - `RecurrenceEditor.test.tsx`:
    - `summary updates as the form changes`.
    - `weekly preselects the start weekday`.
    - `custom rule shown raw`.
    - `orphaned overrides need confirmation`: a preview returning one orphan shows the dialog, cancel sends nothing, and confirm sends the flag.
    - `skip writes an override`.
    - `move dialog sends local times`.
  - `RichTextField.test.tsx`:
    - `emits HTML on input`.
    - `toolbar buttons call execCommand` (spy).
    - `link button refuses javascript:`.
    - `loads server HTML`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/EventEditor.test.tsx modules/events/sm_events/ui/page-tests/RecurrenceEditor.test.tsx modules/events/sm_events/ui/page-tests/RichTextField.test.tsx`: fails.
- [ ] **Step 3: Implement.** Keep `EventEditor.tsx` under 200 lines and each component under 250.
- [ ] **Step 4: Run** vitest, tsc, biome and `check_rules.py`: all pass.
- [ ] **Step 5: Commit** `feat(events): event editor with texts, recurrence and overrides`.

### Task 22: Workflow bar, revision history and the conflict panel

**Files:**
- Create: `ui/components/editor/WorkflowBar.tsx`, `ui/components/editor/RevisionHistory.tsx`, `ui/components/editor/ConflictPanel.tsx`, `ui/components/editor/ScheduleDialog.tsx`, `ui/components/editor/RejectDialog.tsx`
- Modify: `pages/EventEditor.tsx` (mount them), `ui/hooks/useEvent.ts` (the `conflict` state), locales (`workflow.*`, `history.*`, `conflict.*`)
- Test: `ui/page-tests/Workflow.test.tsx`, `ui/page-tests/Conflict.test.tsx`

**Interfaces:**
- `WorkflowBar` shows only the actions allowed for `status`, `scheduled`, `can_write` and `can_publish` (ruling 17). Approve opens `ScheduleDialog` ("Publish now" or a date and time in the event's timezone). Reject needs a note. A locked event without `can_publish` shows a read-only banner ("Published: only a publisher can change it") and disables the form.
- `RevisionHistory`: a drawer listing number, action, actor (the display name when the API gives one, else "System" for `null`), time and note. "View" shows the snapshot's title, times and status. There is no restore (ruling 18).
- `ConflictPanel`: on 409 `stale` the hook re-GETs the event and keeps the unsaved form. The panel names the fields that differ between "yours" and "theirs" and offers "Load their version" (discard mine) or "Save mine over theirs" (resend with the new `expected_revision`, one explicit click). It never retries silently.

- [ ] **Step 1: Write the failing tests:**
  - `Workflow.test.tsx`:
    - `actions per status` (a table over draft, in_review, scheduled and published × publisher or not).
    - `approve later sends publish_at_local as typed`.
    - `reject requires note`.
    - `locked banner disables form for non-publisher`.
    - `history lists revisions newest first`.
  - `Conflict.test.tsx`:
    - `409 stale shows panel with differing fields`.
    - `load theirs discards`.
    - `save mine resends with new revision`.
    - `no silent retry`: one PATCH until the click.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/Workflow.test.tsx modules/events/sm_events/ui/page-tests/Conflict.test.tsx`: fails.
- [ ] **Step 3: Implement.** The schedule dialog sends the wall-clock time it shows; the client never converts to UTC (ruling 1).
- [ ] **Step 4: Run** vitest, tsc and biome: all pass.
- [ ] **Step 5: Commit** `feat(events): workflow actions, revision history and conflict panel`.

### Task 23: Docs and branch verification

**Files:**
- Modify: `modules/events/README.md` (Usage: the event screens and the API table from Task 15; status: PR 2 of 10)
- Modify: `modules/events/docs/index.md`. Add sections "Events and texts", "Times and all-day", "Recurrence" (the allow-list and the bounds), "Overrides", "The occurrences read" (bounds, ordering, truncation, key), "Workflow" (the transition table), "Revisions and conflicts", "Bus events" and "Scheduled publishing (needs beat)". Add a status row.
- Modify: `CHANGELOG.md` (0.0.16 Added: events, recurrence, occurrences, workflow, the editor; the `events` worker queue)
- Modify: `CLAUDE.md`, in the events paragraph only:
  - events read through `core/access/events.py`, with drafts only for `write_events`;
  - locked events need `events.publish`;
  - every write is `claim_revision` first;
  - expansion only inside `calendar/occurrences.py`, never without an `until`;
  - `make worker` serves the `events` queue.
- Modify: `docs/module-layout.md` (the events row counts).
- Modify: the spec's "Amendments" (add "Amendments (PR 2)" listing rulings 1, 5, 6, 9, 13, 16, 18 (the note column), 20 and 29).

- [ ] **Step 1: Lint set** (headroom first), from the root:
  - `uv run ruff check modules/events scripts host`
  - `uv run ruff format --check <files touched>`
  - `uv run basedpyright`
  - `npx biome check modules/events`
  - `npx tsc --noEmit -p modules/events/tsconfig.json`
  - `uv run python scripts/check_metadata.py`, `check_rules.py`, `check_sibling_contracts.py`, `moved_paths.py --check`, `check_ts_imports.py`, `check_readmes.py`, `check_hardcoded_strings.py`, `check_file_size.py` (no WARNING under `modules/events`), `check_locales.py`, `check_migration_heads.py` and `bump_version.py --check-current`

  All pass.
- [ ] **Step 2: Targeted suites, one at a time:**
  1. `cd modules/events && uv run pytest -q -n 8` on SQLite.
  2. The same on `smpy_events_test` on Postgres.
  3. From the root: `uv run pytest -q -n 8 scripts/tests host/tests/test_tenancy_parity.py host/tests/test_events_wiring.py host/tests/test_menu_labels.py host/tests/test_host_boots.py`.
  4. `npx vitest run modules/events`.

  All pass. Do not run other modules' suites.
- [ ] **Step 3: Fresh-import check** for every `modules/events/sm_events/**/*.py`.
- [ ] **Step 4: Commit** `docs(events): events, recurrence, occurrences and workflow`.
- [ ] **Step 5: Hand over to `/ship`.** Browser QA:
  - create a weekly event in Europe/Vienna that crosses 29 March, and check the preview keeps 10:00;
  - skip one occurrence and move another;
  - change the rule and confirm the orphan dialog;
  - add a German text and rename its slug;
  - submit, then reject with a note, then approve for a future time;
  - as a writer without publish, see the locked banner;
  - force a stale save from two tabs and use the conflict panel;
  - filter the list.

  Screenshots of the list, the editor (texts tabs, recurrence with preview), the orphan dialog and the conflict panel go in the PR.

## Verification checklist (before `/ship`)

- Task 23 Step 1's lint set passes, including `basedpyright` with events' contracts included.
- The events pytest passes on SQLite and Postgres; `scripts/tests` and the four host tests pass; `npx vitest run modules/events` passes.
- `alembic check` is clean on SQLite and Postgres after upgrade, downgrade and upgrade. `check_migration_heads.py` reports one head, the note revision.
- No file under `modules/events` is at 280 lines or more.
- `git diff --stat feat/events-pr1-scaffold` touches only `modules/events/**`, `host/migrations/versions/<rev>_events_revision_note.py`, `host/tests/test_events_wiring.py`, `host/tests/test_menu_labels.py`, `Makefile`, `.github/workflows/ci.yml`, the root `pyproject.toml`, `uv.lock`, `README.md` (only if the module row's wording changes), `CHANGELOG.md`, `CLAUDE.md`, `docs/module-layout.md`, the spec and this plan.
- The Review Focus tests exist and pass: grep for each test name listed there.

## Open points

1. **The framework bump #412** chains off `541bfbe29a28` as PR 1 did. Re-check the head in Task 7. If #412 lands first, the base gains a merge revision, and this PR's revision chains off it.
2. **No bus in a worker.** `events.publish_due` runs in Celery without the app, so a scheduled publish emits no `EventPublished`. Subscribers (newsletter cards, PR 8 reminders) only see immediate publishes. Options: a framework cross-process bus (file it upstream in `simple_module_python`), or PR 8 polling `published_at`. My recommendation is the upstream issue plus a doc note now. File it as an issue when this PR opens.
3. **Reinstating, unpublishing and skipping emit no bus event.** PR 8 (reminders) computes its schedule from current state, so it does not need them. A cache consumer would. Decide in PR 6 when the plugin guide fixes the event list.
4. **The tzdata drift.** An override's `original_start` is a UTC instant. If a tzdata update changes a zone's rules, future instances shift and their overrides orphan silently. This is rare. A later follow-up could store the local original start too.
5. **`RichTextField` is ours.** If the framework's `@simple-module-py/ui` gains a rich-text field, swap to it. This is an upstream issue, not a blocker.
6. **The ★ rulings** most likely to change are: local wall-clock input (1), the RRULE allow-list sizes (5), start-in-rule (6), sub-events vs recurrence (9), "moved" changing only times (10), truncation by series cap (13), scheduled = locked (16), the revision `note` migration (18), the required default-locale text (20), `h2`/`h3` in the allow-list (22) and the hand-rolled editor (29).
