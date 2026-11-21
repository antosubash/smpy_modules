# Events PR 8: reminders. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user who can see a published event clicks "Remind me", picks one or more lead times, and gets one plain-text email per occurrence and lead before it starts. Nothing is ever sent twice, and nothing is sent for a cancelled, skipped, unpublished, trashed or no-longer-visible occurrence. Managers see on one screen whether reminders can be delivered, and what was sent, what failed and what never finished in the last 30 days.

**Architecture:** Everything lives in `sm_events/reminders/`. `follows.py` is the request-side service: follow, unfollow, list, limits and existence hiding. Behind the beat task `events.reminders` sit six steps:

1. `due.py`: pure maths. A narrow start window per lead time, the catch-up and stale rules, all-day starts and DST.
2. `candidates.py`: one SQL prefilter per lead for followed events only, then PR 2's bounded expansion over that narrow window, applying overrides.
3. `recipients.py`: the send-time access re-check. It goes through a `ReminderRuntime` that supplies the user directory, membership, permissions and `public_base_url`. In the web process the runtime is the live app. In a Celery worker it is a headless app built once per process, a stopgap until the framework ships an offline principal.
4. `claim.py`: insert-or-nothing into `events_reminder_sent`, committed before any SMTP.
5. `send.py`: the framework mail sender under a per-tick budget, a wall-clock budget, a timeout and a breaker. It writes `sent` or `failed` with a stable code and never retries.
6. `message.py`: the localized text.

`cleanup.py` removes follows on membership or user removal and prunes the ledger from PR 5's janitor. The console gets a `RemindMe` control (calendar popover and event editor), a Reminders page ("My reminders" plus a managers' "Delivery" card) and per-calendar default lead times.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy async (dialect `insert … on_conflict_do_nothing`), `zoneinfo`, `babel.dates` (already locked through `simple_module_core`), `string.Template`, `simple_module_core.mail` (`resolve_mail_sender`, `mail_transport_installed`, `MailMessage`), the framework's `background_tasks` (Celery beat), `simple_module_test.mail.captured_mail`, pytest (SQLite, plus Postgres opt-in through `tests/pg_support.py`), React 19 + Inertia, `@simple-module-py/ui`, vitest.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`. This plan covers Delivery row 8 and draws on "Reminders", the anti-goal "a reminder sent twice, or sent for a cancelled or skipped occurrence", "Settings" (`reminders_enabled`, `default_reminder_minutes`), "Background work" and "Access". Precedent plans: PR 2 (`2026-11-17-events-pr2-events.md`: occurrences, overrides, the worker runtime, the beat, the bus), PR 4 (public URLs), PR 5 (`core/access/offline.py`, the cleanup handlers and the janitor) and PR 6 (durable bus). Precedent code to read in full before starting: `modules/records/sm_records/public_submissions/mail.py`, `mail_runner.py`, `delivery.py`, `sending.py`, `strings.py`, `templates/notify.txt` and their tests; `modules/newsletter/sm_newsletter/sending/` (claim before send, the budget; do **not** copy its SMTP transport); `modules/images/sm_images/jobs/reconcile.py` (`simple_module_db.all_tenants()` around the tagged enumeration); and the framework's `simple_module_core/mail.py`, `simple_module_core/user_directory.py`, `simple_module_core/tenancy.py` (`tenant_member_ids`), `simple_module_hosting/permissions.py` (`resolve_principal_permissions`), `background_tasks/outbox/worker.py` and `mail/module.py` (the resolver is installed in `register_event_handlers`).

## Depends on PRs 2–7

Before Task 1, rebase onto the finished `feat/events-pr7-integrations`. The batch A implementer then **re-checks every name below against the real code first**. Where a name differs, correct the task text of this plan; never rename PR 2–7 code. Stop and report if a *behaviour* differs, in particular:
- `visible_events(who, include_unpublished=False)` returns a non-published event;
- no function applies overrides to a series' instances outside the occurrences read;
- PR 5's offline principal cannot take several user ids or does not return the directory user.

| Area | Symbols relied on |
|---|---|
| Models (PR 1–2) | `Calendar` (`visibility`, `owner_id`, `default_timezone`, soft delete), `Event` (`status`, `cancelled`, `all_day`, `starts_at`, `ends_at`, `timezone`, `rrule`, `recurrence_until`, `revision`, `online_url`, `venue_name`, `address`, `attendance_mode`, soft delete), `EventText`, `OccurrenceOverride` (`original_start`, `kind`, `starts_at`, `ends_at`), `models/_cols.py` helpers |
| Access (PR 1–2, 5) | `core/access`: `POLICY`, `visible_calendars`, `ACTION_WRITE_EVENTS`; `core/access/events.py`: `visible_events`, `load_event`, `event_rights`; `core/access/offline.py`: `OfflineUser`, `feed_principal(app, db, *, user_id, tenant_id, request)` |
| Time (PR 2) | `calendar/times.py` (`Span`, `localize`, `all_day_dates`), `calendar/rrule.py` (`parse`, `Rule`), `calendar/expand.py` (`instances`, `Instance`), the override application inside `calendar/sources.py`/`window.py`, the occurrence key shapes (PR 2 Ruling 12), `MAX_SERIES_EVENT_DAYS` |
| Content (PR 2) | the text fallback rule (locale, then default content locale, then the first), `content/bus.py` (`attach`, `emit`, `commit`, `rollback`), `web/endpoints/deps.event_db` |
| Worker (PR 2, 5, 6) | `core/worker.py` (`run_platform`, `reset_worker_runtime`), `tasks.py`, `task_config.py` (`QUEUE_DEFAULT`, `BEAT_SCHEDULE`, `TASK_ROUTES`), `content/publish_due.py` (the enumeration pattern), PR 5's `events.janitor` and its per-tenant steps, PR 6's `registry.ensure_loaded()` in the worker runtime |
| Cleanup (PR 5) | `feeds/tokens/cleanup.py` handlers and their guarded subscription in `module.py` (`UserDeleted`, `MembershipRemoved`, `TenantDeleted`) |
| URLs (PR 4) | `web/endpoints/public/_urls.py`: `configured_origin(app)`, `event_path(slug, locale, date)`; constants `EVENT_EDIT_URL`, `VIEW_PREFIX`; PR 3's console calendar deep link, if it has one (`?date=`) |
| Calendar API (PR 1) | `web/schemas/calendars.py` (`CalendarPatch`, `CalendarOut`), `calendar/calendars.py` update path |
| UI (PR 1–3, 6) | `ui/utils/api.ts` (`ApiError`, `errorText`), `ui/utils/i18n.ts` (`keys`, `t`), `ui/calendar/DetailPopover.tsx` and its slot props, `pages/EventEditor.tsx`, `pages/Calendars.tsx` and its edit dialog, `ui/page-tests/test-dom.tsx` |
| Tests | `tests/support/app.py` (`build_app`, `as_user`, the fake `Directory`, `client`, `multi_client`, `csrf_client`), `tests/support/access.py` (`principal`, `seed_calendars` with `P`/`I`/`U`, the principals `M`, `O`, `SV`, `SE`, `E`, `V`, `N`, `A`), `tests/support/calendars.py` (`seed_event`), the `unbound_tenant` marker, `tests/pg_support.py`, PR 2's `worker_db` fixture in `tests/core/test_worker.py` |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**Data**
1. **`events_follow`**: `id` (UUID PK), `tenant_id` (`MultiTenantMixin`), `user_id` (str 64), `event_id` (FK `events_event.id` `ON DELETE CASCADE`), `lead_minutes` (int), `locale` (str `LOCALE_MAX`), `created_at`.
   - Unique `uq_events_follow (tenant_id, user_id, event_id, lead_minutes)`; indexes `ix_events_follow_event (tenant_id, event_id)` and `ix_events_follow_user (tenant_id, user_id)`.
   - No soft delete: unfollowing deletes the row.
   - ★ **A follow is on the whole event.** For a series that means every occurrence; a single occurrence cannot be followed. Per-occurrence follows would need an `original_start` on the follow and a second key everywhere, for a case the console has no screen for. Open point 4.
2. **`events_reminder_sent`** (the ledger): `id` (BigInteger PK), `tenant_id`, `event_id` (FK `ON DELETE CASCADE`), `occurrence_key` (str 80, PR 2 Ruling 12's key: `"{event_id}"` or `"{event_id}:{original_start}"`), `starts_at` (UTC, the start this reminder announced), `recipient_id` (str 64), `lead_minutes`, `state` (`sending` | `sent` | `failed`), `code` (str 32, nullable), `claimed_at`, `sent_at` (nullable).
   - ★ **Unique `uq_events_reminder_sent (tenant_id, event_id, occurrence_key, starts_at, recipient_id, lead_minutes)`.** This refines the spec's `(event, occurrence start, recipient, lead)`: "occurrence start" is split into *which* occurrence (`occurrence_key`, stable across a move) and *when* (`starts_at`). The consequences:
     - A moved or rescheduled occurrence that has not been reminded yet is reminded once, at its new time.
     - The old slot no longer exists in the expansion, so it cannot also fire: a moved override never produces two reminders for one start.
     - An occurrence rescheduled *after* its reminder went out is reminded again for the new start, which is the only notice of the new time until #401 sends change notices.
     - Moving it back to the old start finds the old row and sends nothing.
   - Index `ix_events_reminder_sent_claimed (tenant_id, claimed_at)` for the counts and the janitor.
3. ★ **Default lead times exist at two levels.** The setting `default_reminder_minutes: tuple[int, ...] = (60,)` is install-wide. A new nullable JSON column `events_calendar.default_reminder_minutes` overrides it per calendar, and `NULL` means "use the setting". Calendar editors (`ACTION_EDIT`) set it through PR 1's calendar `PATCH`. Defaults only preselect the control; nobody is followed automatically.
4. **Settings** (spec, DB-backed, SYSTEM scope, runtime, no validators, as PR 1's docstring requires):
   - `reminders_enabled: bool = True`;
   - `default_reminder_minutes: tuple[int, ...] = (60,)`.

   Stored values outside `REMINDER_LEADS` are dropped where they are read (`reminders/leads.effective_defaults`), never rejected.
5. **One migration** chained off the single head at implementation time. It creates both tables and adds the calendar column.

**Following**
6. **Lead times come from a fixed list.** `REMINDER_LEADS = (15, 60, 1440, 10080)` minutes (15 min, 1 h, 1 day, 1 week), with `MAX_LEAD_MINUTES = 10080`. Anything else is 422 `invalid_lead`. A follow request names a set of leads and replaces the user's leads on that event, so setting the empty set unfollows.
7. **Who may follow.** The caller needs `events.view`, and the event must be in `visible_events(who, include_unpublished=False)`. Otherwise:
   - 404 `not_found`, so an invisible event cannot be followed or probed, and an invisible event and a missing one answer the same;
   - a writer who sees an unpublished event gets 409 `not_published`. They can see it anyway, so nothing leaks.

   While reminders are unavailable (Ruling 9), every write that would start or change reminders is 503 `reminders_unavailable`, so nobody is promised mail that cannot arrive. Reads still answer, and stopping never fails: `DELETE`, and `PUT` with an empty set, succeed.
   - *Amended (decision 2): the sentence used to say "every write". Why: a user must always be able to stop following, or an outage strands follows that resume when mail comes back.*
8. **Limits.** `FOLLOWS_PER_USER = 200` distinct followed events per user per tenant; one more is 409 `follow_limit`. Re-saving an event already followed does not count again. The follow routes get `RateLimitRule("30/minute", key="user")`.
9. **Availability is one function**, `reminders/availability.py: async def availability(app, db) -> Availability(available: bool, reason: str | None)`. It checks in this order:
   - `disabled`: the setting is off;
   - `no_public_base_url`: the host's `public_base_url` is unset, so links would be relative;
   - `no_mail_transport`: `mail_transport_installed()` is false;
   - `console_mail`: `(await resolve_mail_sender(db)).delivers_email` is false;
   - `worker_access_unavailable`: `worker_runtime_supported()` (Ruling 18) is false.

   ★ Every signed-in caller gets `available`, and only `events.manage` also gets `reason`. While unavailable the control is hidden (spec).
10. ★ **The control lives in the console only**: in PR 3's detail popover and in PR 2's event editor, for published events. There is no per-row control on the Events list (a bell on every row is noise) and none on the **public** event page. PR 4's public pages are cacheable and must not vary by session. Adding a signed-in state there would turn every page `private` for signed-in visitors and add a second CSRF surface to a public router. A signed-in visitor opens the event in the console.
11. **"My reminders"** is `GET /api/events/reminders/mine` (paged by `page`/`page_size`, 1–100, default 50). It lists the caller's follows on events visible to them **now**, each with its leads, the event's title in the request locale (PR 2's fallback), its calendar and the next start. Follows on events the caller can no longer see are counted as `hidden` and never named.
12. **The follow's locale** is the request's console locale when the follow is written, using the same helper PR 5 uses for a token's default locale. A locale outside events' message catalogues (`en`, `de`) falls back to `en` when the mail is rendered. The framework exposes no per-user language preference (open point 5), so the language the user was using when they clicked is the best signal available, and nothing is guessed later.

**The beat**
13. **`events.reminders`** runs from beat every `REMINDER_TICK_SECONDS = 60` on queue `events` (`expires` 55). The tick:
    - Enumerates tenants once: `with simple_module_db.all_tenants():`, a statement tagged with events' `tenancy.all_tenants(...)` selecting `distinct(EventFollow.tenant_id)`. Both are needed, because the tag alone is refused under strict isolation (PR 2 review finding; images' `reconcile.py` does the same).
    - Then works each tenant in its own session under `tenant_context(t)`.
    - Reads `EventsSettings` with `background_tasks.settings_for(EventsSettings, PACKAGE, ttl=30)`.
    - Does nothing at all while `reminders_enabled` is false or Ruling 9's checks fail in the worker.
14. **The due rule** (`due.py`, pure):
    - A reminder for an occurrence starting at `start` with lead `L` is due at `due = start − L`, where `L` is an exact duration in UTC.
    - ★ **All-day start**: an all-day occurrence "starts" at local midnight of the event's timezone, which is its stored `starts_at` (PR 2 Ruling 2). So a 1-day lead on a 6 July all-day event fires at 00:00 local on 5 July. Open point 6 offers a 09:00-local alternative.
    - **DST**: a 1-day lead across a DST change is exactly 24 h, so its wall-clock time differs by an hour from the event's. This is pinned by tests and documented.
    - A tick at `now` sends when `now − catchup(L) ≤ due < now + REMINDER_EARLY` and `now < start`, with `REMINDER_EARLY = 60 s` (one tick: a punctual beat is never late, at most one tick early).
    - ★ `REMINDER_CATCHUP = {15: 5 min, 60: 15 min, 1440: 6 h, 10080: 6 h}` is the lateness cut-off. A reminder later than that, or one whose occurrence has started, is **stale** and is never sent. Stale reminders write no row, are counted in the tick's log line and are recomputed and refused again on every tick until they leave the window.
    - A follow created too late for a lead (its due already older than the catch-up) therefore never fires; the follow response says so (`next_due: null` for that lead).
15. **Candidates without expanding the world** (`candidates.py`). For each lead `L` that has follows in the tenant, the start window is `W_L = [now + L − catchup(L), now + L + REMINDER_EARLY)`, at most 6 h 1 min wide. One query per lead (so at most four per tenant per tick):
    - It joins `events_follow (lead = L)` to events that are `published`, not trashed, not `cancelled`, whose calendar is not trashed;
    - and that are either one-offs with `starts_at ∈ W_L`, or series passing PR 2's prefilter (`starts_at < end(W_L)`, `recurrence_until IS NULL OR > start(W_L)`).

    Each distinct series is expanded **once per lead window** with PR 2's `expand.instances` (window `W_L`, its `until` always set), and PR 2's override application then:
    - drops `skipped`;
    - drops `cancelled` (the spec: a cancelled occurrence is not reminded);
    - places `moved` at its new time, with overrides read over `W_L` widened by `MAX_SERIES_EVENT_DAYS` as PR 2's read does, so an instance moved *into* the window is found.

    Only instances whose `start ∈ W_L` are kept. The result is a list of `Candidate(event_id, revision, occurrence_key, start, end, lead, user_id, locale)` sorted by `due` ascending, the closest to stale first. The cost per tick is at most 4 indexed queries plus one narrow expansion per followed series. The cap is `REMINDER_CANDIDATES_MAX = 5000` per tenant per tick. More than that are left for the next tick (still inside the catch-up) and counted as `deferred`.
16. **Plugin sources and external items are never reminded.** Only events' own events can be followed (Ruling 7).

**Access at send time**
17. **Re-checked for every candidate before its claim, failing closed.** The recipient is resolved through `ReminderRuntime.recipients(db, tenant_id=…, user_ids=…)`, one batch per tenant per tick. A user is dropped (counted `denied`, no row written, the follow kept) unless every one of these holds:
    - the directory knows them and `is_active` is true;
    - `email` is non-empty, and `email_verified` is not `False`;
    - on a multi-tenant host they are a member of the tenant (`tenant_member_ids`; `None` fails closed);
    - their resolved permissions include `events.view`;
    - the event is in `visible_events(principal, include_unpublished=False)`, through one query per user over that user's candidate event ids.

    Any exception in the resolver denies the whole tenant for that tick and is logged by exception class. Because the check reads current state on every tick, a share removed, a visibility narrowed, a role edited, a user disabled or a membership ended stops reminders from the next tick. Cleanup (Ruling 27) only tidies rows.
18. ★ **The offline principal in a worker: a headless app, gated by "never more than a request".** A Celery worker builds no app, so it has no user directory, no membership store and no permission registry (PR 5 open point 1; upstream simple_module_python #1005). `reminders/runtime.py` defines:

    ```python
    class ReminderRuntime(Protocol):
        public_base_url: str
        async def recipients(self, db, *, tenant_id: str, user_ids: Collection[str]) -> dict[str, Recipient]: ...
    ```

    - `web_runtime(app)` is the live app (tests, eager runs, and the request-side check below). It goes through PR 5's offline principal, extended to a batch (`offline_accounts`).
    - `worker_runtime(db)` probes the framework for an offline resolver first (none exists in 0.0.44). Otherwise it builds the host's app with the framework's own `create_app(merge_host_settings())`, **without its lifespan**, once per worker process and again after `REMINDER_RUNTIME_TTL = 600 s`, and replays the DB role overlay through the permissions module's own `PermissionService.load_all_into_registry` once per call (one per tick). It never provisions a secret key (no key: refuse), and any failure answers `None`, turns `worker_runtime_supported()` false for 60 s and is logged once by class.
    - **The gate is "never more than":** the worker's principal must never grant more than a request principal for the same user, on every fixture (users x calendars x event states), and where it cannot establish a right it grants none. It can grant less: a user whose only right is the membership role (`tenant:<role>`, no public read, #1005) gets no reminder. That is a documented limit, never a silent one.
    - **Told, not silent:** the same send-time check runs in the *request* (`reminders/access.py`, through the live app) when a follow is read or written and for each row of "My reminders". When it would refuse the user, the follow is still stored but the response carries `deliverable: false` and the code `reminders_no_access` ("Reminders cannot be sent for this event with your current access"), so nobody waits for mail that will never come.
    - *Amended (decision 1): the gate used to be "grants exactly what a request principal holds", with a fall back to `worker_access_unavailable` when parity failed. Why: parity cannot hold while #1005 is open (the membership role is unreadable), but "never more" is what matters for safety; the narrower grant is fail-closed and is now reported to the affected user.*
    - Measured on the demo host: the first build takes about 16 s and 200 MB, then nothing for the TTL. Web and worker images must be installed identically.
19. **Links** use `runtime.public_base_url`, the host setting:
    - The event link is the console URL (PR 3's calendar deep link at the occurrence's date if PR 3 has one, else PR 2's `/admin/events/edit/{id}`, which a viewer opens read-only).
    - It becomes PR 4's public `event_path(slug, locale, date)` when the calendar is `public` **and** the host is single-tenant. On a multi-tenant host a tenant's public origin is a request property (PR 4 `configured_origin` is `""` there), so the console link is used.
    - The "Manage reminders" link is `/admin/events/reminders`.

**Claim, send, never retry**
20. **The claim** (`claim.py`) runs in its own short session finished with `finalize_session`, **before** any SMTP. It is one statement, `INSERT … SELECT … WHERE EXISTS (guard) ON CONFLICT DO NOTHING RETURNING id`, using the dialect `insert`. It carries its own `tenant_id` predicates, and the guard re-reads the event row (`id`, `tenant_id`, `revision = :rev`, `status = 'published'`, `cancelled = false`, not trashed).
    - A conflict or a failed guard returns `None`: someone else has it, or the event changed since the candidate was computed. The next tick recomputes.
    - *Amended (decision for batch B): the ledger has a fourth state. A claim is `claimed` (committed before anything is attempted, with a 2-minute lease), `begin_send` moves it to `sending` just before the transport is called, then `sent` or `failed`. An expired `claimed` row provably sent nothing and may be reclaimed (only by an exact-`claimed_at` match, so a slow first holder cannot also send); a `sending` row never is. Why: it recovers a crash in the one window where nothing was handed to the transport, without ever risking a duplicate.*
    - On Postgres the guard locks the event row `FOR SHARE`, so a concurrent cancel or reschedule serialises with the claim.
    - The window between the claim's commit and the SMTP call (one send long) can still send for an occurrence cancelled in that instant. This is documented.
21. **The send** (`send.py`) happens after the claim committed:
    - `asyncio.wait_for(sender.send(message), REMINDER_SEND_TIMEOUT = 30 s)`, with `sender = await resolve_mail_sender(db)` resolved once per tick (records' rule: a resolver host has no installed sender).
    - On success, a conditional `UPDATE … SET state='sent', sent_at WHERE id = :id AND state = 'sending'` in its own session.
    - On an exception or a timeout, `state='failed'` with `code` `send_timeout` or `send_failed`.
    - The log line names the tenant, the event id, the recipient **user id** and the exception **class**, never the address, the subject or the exception message (which can echo the address).
    - ★ **No retry, ever** (spec: at most once). A failed or unfinished row is final.
    - A crash after the claim leaves `sending` forever. It counts as **unfinished** once `claimed_at` is older than `REMINDER_UNFINISHED_AFTER = 5 min`.
22. **Bounded ticks.**
    - `REMINDER_SEND_BUDGET = 300` sends per tick install-wide, of which at most `REMINDER_TENANT_BUDGET = 100` per tenant.
    - A wall-clock budget of `REMINDER_TICK_BUDGET = 45 s`, after which nothing new is claimed.
    - A breaker: after `REMINDER_BREAKER_FAILURES = 3` consecutive send failures the tick stops claiming, because the transport is install-wide.

    Whatever was not claimed stays as a candidate for the next tick (still inside the catch-up) and is counted `deferred`. So a mail outage writes at most three `failed` rows per tick, and a huge follow list cannot stall the beat.
23. **Concurrency.** Two workers running the same tick, a redelivered beat message or an overlapping late tick can all compute the same candidates. The claim's unique key makes exactly one of them send. There is no tick lock: claims are the only arbiter, so there is nothing to leak.
24. **Eager hosts.** `events.reminders.apply()` runs the same body with `web_runtime(app)`. A host without beat never sends reminders, and this is documented with publish_due's note.

**The message**
25. **Plain text** (`MailMessage(to, subject, text)`, no HTML, no `Reply-To`), from `reminders/templates/reminder.txt` (`string.Template`). Strings come from events' own catalogue, `locales/<locale>.json` under `reminders.mail.*`, read by `reminders/strings.py` (a copy of records' `public_submissions/strings.py`, English fallback). The body has:
    - the title in the follow's locale, else the default content locale, else the first text (PR 2);
    - the date and time in the **event's** timezone with its abbreviation, through `babel.dates.format_date(…, "full")` and `format_time(…, "short")` in the follow's locale, and `tzname()` (`CEST`). Nothing is said about the recipient's own zone;
    - all-day events as dates only ("Monday, 6 July 2026 (all day)");
    - multi-day events as start – end;
    - the place: `venue_name`, `address`, and `online_url` when the attendance mode is `online`/`hybrid`. The recipient passed Ruling 17's visibility check, which is exactly who the console shows `online_url` to;
    - the event link and "Manage reminders" (Ruling 19);
    - a footer naming the site's host.

    Subject: `reminders.mail.subject` with the title and the date. It is sanitised: control characters, line and paragraph separators removed, whitespace collapsed, capped at `REMINDER_SUBJECT_MAX = 200`, even though titles are single-line already.
26. ★ **Cancel and reschedule notices are out of scope** and tracked for #401. A cancelled occurrence simply gets no reminder, and a rescheduled one gets its reminder at the new time (Ruling 2).

**Changes to events, users and access**
27. **What happens when:**

    | Change | Reminders | Rows |
    |---|---|---|
    | occurrence moved earlier or later, one-off rescheduled, series rule or start changed | computed from current state; reminded at the new start (Ruling 2) | none |
    | occurrence cancelled or skipped, event `cancelled` | not reminded | follows kept (un-cancelling resumes) |
    | event unpublished, trashed, calendar trashed | not reminded (candidate filter, claim guard) | follows kept (republish or restore resumes) |
    | event or calendar hard-deleted | n/a | FK `ON DELETE CASCADE` removes follows and ledger |
    | share removed, visibility narrowed, `events.view` lost, user disabled | refused per tick (Ruling 17) | follows kept (a re-grant resumes) |
    | membership removed (`MembershipRemoved`) | refused per tick | bus handler deletes that user's follows in that tenant |
    | user deleted (`UserDeleted`, when the framework has it) | refused per tick | bus handler deletes that user's follows everywhere (one narrow `all_tenants()` DELETE with its own `user_id` predicate) |
    | tenant deleted (`TenantDeleted`) | n/a | bus handler deletes that tenant's follows and ledger |

    The handlers subscribe beside PR 5's, guarded the same way.
28. **The ledger is pruned** by PR 5's `events.janitor`: rows whose `starts_at` is older than `REMINDER_LEDGER_DAYS = 90`. Only rows whose occurrence has started are ever deleted, and Ruling 14 never sends after the start, so deleting a row can never re-enable a send.

**Console**
29. The **Reminders page** is `/admin/events/reminders` (`events.view`; menu entry "Reminders", after Calendars).
    - "My reminders" (Ruling 11), with remove.
    - For `events.manage`, a "Delivery" card: enabled, available or the reason in words, the effective defaults, a link to the framework Settings screen for the two fields, and the 30-day counts from `GET /api/events/reminders/delivery`: `sent`, `failed` by code, `unfinished` (Ruling 21).
30. **The `RemindMe` control**, with its states:
    - hidden: unavailable, or not published;
    - "Remind me": not following;
    - "Reminding: 1 h before" (the leads summarised): following;
    - saving;
    - error: `follow_limit`, or a 404 that closes it.

    It opens a popover of lead checkboxes, preselecting the calendar's effective defaults when not following, with Save and "Stop reminding". For each chosen lead it shows the next due time, or "too late for the next occurrence".
31. **Errors** (`{"detail","code"}` envelope):
    - 409 `follow_limit`, `not_published`;
    - 422 `invalid_lead`;
    - 503 `reminders_unavailable`.

    Ledger codes are `send_failed` and `send_timeout`.
32. ★ **No e2e spec.** Records' e2e specs do not observe mail either (they assert `sm_notified_at`). A module test with `captured_mail` covers delivery more precisely than a browser could, and the e2e host runs the console transport, which hides the control. `/ship`'s browser QA exercises the control and the Reminders page against a local mail container instead (Task 18).

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, alembic or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. Use `/usr/bin/ps`, never `ps`.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr8` on branch `feat/events-pr8-reminders`, stacked on `feat/events-pr7-integrations` → pr6 → pr5 → pr4 → pr3 → pr2 → pr1. Before Task 1, rebase onto the finished PR 7 branch and run the "Depends on" check. Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points from the worktree root, and module tests from the module directory: `cd modules/events && uv run pytest …`.
- Implementers are Claude subagents. Each runs pytest in the foreground, commits its own tasks (one commit per task) and never pushes.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- Names: package `sm_events`, npm `@simple-module-py/events`, locale namespace `events`, API prefix `/api/events`, view prefix `/admin/events`, tables `events_follow` and `events_reminder_sent`, task `events.reminders`, queue `events`, page `Events/Reminders`.
- Version stays what the base has (`uv run python scripts/bump_version.py --check-current`).
- One new direct dependency: `babel>=2.14,<3` (already in `uv.lock` through `simple_module_core`). Pins stay ranges.
- Settings stay DB-backed with no environment reads. The two new fields go in `EventsSettings`, never in `.env.example`.
- Every query on an events table runs with a tenant bound. Core statements (the claim, the marks, the cleanup deletes) carry their own `tenant_id` predicate. `simple_module_db.all_tenants()` together with events' `all_tenants` tag is used in this PR only for the tick's tenant enumeration and the `UserDeleted` follow cleanup; extend PR 5's grep test with both.
- Do not edit `sm_events/core/tenancy/*` (parity family).
- A recipient's address, the subject, the body and an exception's message never appear in a log line, a ledger `code` or an API error. Log user ids, event ids, counts and exception class names.
- Mail goes out only through `simple_module_core.mail` (`resolve_mail_sender`). Never import newsletter's transport or open SMTP yourself.
- 300-line cap; keep every `.py`/`.ts`/`.tsx` under 280 lines. The split is fixed in the File structure below.
- No literal permission, page, module-name or error-code strings outside `core/constants.py` (`scripts/check_hardcoded_strings.py`). Numeric bounds named in the Rulings live in `reminders/limits.py`. If `core/constants.py` would pass 260 lines, follow whatever split PRs 5–7 established for it.
- Only real Inertia pages go under `sm_events/pages/`: `Reminders.tsx` in this PR.
- `en.json` and `de.json` keep identical key trees and placeholders (`scripts/check_locales.py`), and that includes the server-side `reminders.mail.*` keys. UI strings go through `t(keys.events.…)`.
- Postgres checks use dev-services' Postgres and scratch databases (`smpy_events_check` for alembic, `smpy_events_test` for pytest). Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **Double sends.** Two concurrent ticks, a redelivered beat message, a tick that overlaps the next, a moved override and its original slot, a reschedule back to the original time: each must send at most one mail per `(occurrence, start, recipient, lead)`. Pinned by Task 10 (`test_claim_once_under_race` on Postgres, `test_moved_override_one_reminder`, `test_move_back_sends_nothing`) and Task 13 (`test_two_ticks_concurrently_send_once`, `test_redelivered_tick_sends_nothing`).
2. **Reminders for cancelled, skipped, unpublished, trashed or invisible events.** A cancelled override, a skipped override, `cancelled=True`, unpublish, trash, a trashed calendar, an event cancelled between the candidate read and the claim (revision guard), a share removed, `internal` → `private`: none sends. Pinned by Task 7 (`test_candidate_filters`), Task 10 (`test_guard_refuses_changed_event`) and Task 13 (`test_access_matrix_at_send`).
3. **The offline access check failing open.** An unknown user, an inactive user, an unverified email, a non-member on multi, a lost `events.view`, a role edited on the permissions screen, a directory that raises, and a membership store that is missing on multi must each deny; a resolver exception denies the whole tenant. Pinned by Task 8 (`test_recipients_fail_closed`), Task 9 (`test_worker_runtime_parity`, `test_role_overlay_removal_denies`) and Task 13.
4. **Unbounded per-tick work.** 10,000 follows on one endless daily series, 3,000 followed series, a mail outage (sender always raises) and a slow sender (each send takes 2 s) must each finish the tick within its budgets. They write at most 3 `failed` rows per tick in an outage, and leave the rest `deferred`. Pinned by Task 7 (`test_expansion_is_window_bounded`, `test_candidates_cap`) and Task 12 (`test_outage_breaker`, `test_wall_clock_budget`, `test_send_budget_per_tenant`).
5. **Tenant binding in the worker under strict isolation.** The tick on a `tenant_strict=True` worker engine must enumerate tenants through `simple_module_db.all_tenants()` and work each one under `tenant_context`; tenant B's follows never produce mail in tenant A's pass. Pinned by Task 13 (`test_tick_under_strict_isolation`, `test_per_tenant_isolation`).
6. **Addresses in logs.** A failing send, a timeout, a denied recipient and the tick summary must log no address, subject or exception message. Pinned by Task 12 (`test_failure_log_has_no_address`, using `caplog` over every record's message and args).
7. **DST and all-day due times.** A 1-day lead on a Vienna 10:00 event on 29 March fires at 08:00Z on 28 March (09:00 local), and on 25 October at 09:00Z on 24 October. An all-day event on 6 July in Vienna with a 1-day lead fires at 2026-07-04T22:00Z. A 15-minute lead on an instance in the spring gap uses the shifted start. Pinned by Task 6.

---

## File structure

| File | Responsibility | ≈ lines |
|---|---|---|
| `models/reminders.py` | `EventFollow`, `ReminderSent` | 90 |
| `reminders/__init__.py` | docstring: the at-most-once contract | 30 |
| `reminders/limits.py` | the numeric bounds of the Rulings | 50 |
| `reminders/leads.py` | `REMINDER_LEADS` validation, `effective_defaults(settings, calendar)` | 60 |
| `reminders/availability.py` | Ruling 9 | 100 |
| `reminders/follows.py` | set/get/delete a follow, limits, `next_due` | 220 |
| `reminders/mine.py` | "My reminders" listing | 120 |
| `reminders/due.py` | pure: windows, catch-up, stale, due | 120 |
| `reminders/candidates.py` | per-lead SQL and expansion → `Candidate` | 230 |
| `reminders/runtime.py` | `Recipient`, `ReminderRuntime`, `web_runtime` | 120 |
| `reminders/worker_app.py` | the headless-app stopgap, TTL, overlay replay, `worker_runtime_supported` | 200 |
| `reminders/recipients.py` | Ruling 17's checks over a runtime | 160 |
| `reminders/claim.py` | claim and the two marks | 150 |
| `reminders/send.py` | budgets, timeout, breaker, logging | 200 |
| `reminders/strings.py`, `reminders/formatting.py`, `reminders/message.py`, `reminders/templates/reminder.txt` | catalogue reader; Babel dates; `build_message` | 70 / 120 / 150 |
| `reminders/tick.py` | `reminders_async`: enumeration and the per-tenant pass | 220 |
| `reminders/cleanup.py` | bus handlers, `prune_ledger` | 140 |
| `reminders/stats.py` | 30-day counts | 80 |
| `web/schemas/reminders.py`, `web/endpoints/reminders_api.py` | API | 120 / 200 |
| `ui/utils/api-reminders.ts`, `ui/reminders/useFollow.ts`, `ui/reminders/RemindMe.tsx`, `ui/reminders/leadText.ts` | client and control | 80 / 120 / 220 / 60 |
| `pages/Reminders.tsx`, `ui/components/reminders/MyReminders.tsx`, `ui/components/reminders/DeliveryCard.tsx`, `ui/components/calendars/ReminderDefaultsField.tsx` | screens | 120 / 200 / 160 / 100 |

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events suite green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: tables, follows API, settings** | 1–5 | constants and limits; the migration and models; settings, defaults and availability; the follow service; the API and views |
| **B: due computation, claim, send, the beat, cleanup** | 6–14 | due maths; candidates; recipients and the offline batch; the worker runtime gate; claim; message; send; the tick and beat; cleanup and janitor |
| **C: console UI, docs, verification** | 15–18 | API client and the control; the Reminders page and calendar defaults; docs; verification |

---

### Task 1: Constants, limits and error codes

**Files:**
- Modify: `sm_events/core/constants.py` (codes `FOLLOW_LIMIT`, `NOT_PUBLISHED`, `INVALID_LEAD` and `REMINDERS_UNAVAILABLE`, each with a `*_DETAIL`; ledger codes `REMINDER_SEND_FAILED`, `REMINDER_SEND_TIMEOUT`; states `REMINDER_STATES = ("sending", "sent", "failed")`; availability reasons `AVAILABILITY_REASONS` (Ruling 9's five); page and URL constants `_PAGE_REMINDERS`, `REMINDERS_URL = f"{VIEW_PREFIX}/reminders"`, menu label and key, icon `bell`; task name in `task_config.py` only)
- Create: `sm_events/reminders/__init__.py` (docstring: Rulings 20–21 in three sentences), `sm_events/reminders/limits.py` (every numeric bound of Rulings 6, 8, 14, 15, 18, 21, 22, 25, 28)
- Modify: `sm_events/core/errors.py` (`FollowLimit` 409, `NotPublished` 409, `InvalidLead` 422, `RemindersUnavailable` 503)
- Test: `tests/core/test_errors.py`, `tests/reminders/__init__.py`, `tests/reminders/test_limits.py`

**Interfaces:** `limits.REMINDER_CATCHUP: Mapping[int, timedelta]` with a key for every `REMINDER_LEADS` entry.

- [ ] **Step 1: Write the failing tests.**
  - `test_errors.py::test_reminder_codes`: parametrized `(cls, status, code)` over the four classes, each rendering exactly `{"detail","code"}`.
  - `test_limits.py::test_catchup_covers_every_lead`: the keys equal `REMINDER_LEADS`, and every catch-up is shorter than its lead.
  - `test_limits.py::test_budgets_consistent`: `REMINDER_TENANT_BUDGET <= REMINDER_SEND_BUDGET`, and `REMINDER_SEND_TIMEOUT < REMINDER_UNFINISHED_AFTER`.
- [ ] **Step 2: Run** `cd modules/events && uv run pytest -q tests/core/test_errors.py tests/reminders/test_limits.py`. Expected: ImportError.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same (passes), then from the root `uv run python scripts/check_hardcoded_strings.py` (passes).
- [ ] **Step 5: Commit** `feat(events): reminder codes and bounds`.

### Task 2: Tables, calendar defaults column and the migration

**Files:**
- Create: `sm_events/models/reminders.py`; modify `models/__init__.py` (export both), `models/calendar.py` (`default_reminder_minutes: list[int] | None`, JSON, nullable)
- Create: `host/migrations/versions/<rev>_events_reminders.py`
- Test: `tests/models/test_reminder_models.py`

**Interfaces:** `EventFollow` and `ReminderSent` exactly as Rulings 1–2, `MultiTenantMixin`, through PR 1's `_cols.py` helpers (UTC datetimes).

- [ ] **Step 1: Write the failing tests.**
  - `test_follow_unique_per_lead`: the same `(tenant, user, event, lead)` twice raises `IntegrityError`, and two leads do not.
  - `test_ledger_unique_key`: the six-column key collides, and a different `starts_at` does not.
  - `test_cascade_on_event_delete` (Postgres, and SQLite with foreign keys on): deleting the event row removes follows and ledger rows.
  - `test_calendar_defaults_nullable`.
- [ ] **Step 2: Run** `uv run pytest -q tests/models/test_reminder_models.py`. Expected: FAIL.
- [ ] **Step 3: Check the head first.** Run `uv run python scripts/check_migration_heads.py`, and if it prints two heads, stop and report. Autogenerate against a scratch SQLite file as PR 2 Task 7 does (`make migration msg="events reminders"`). The revision must create only the two tables with their indexes and add the calendar column (`batch_alter_table` on SQLite), and it gets a docstring. Run `upgrade`, `check`, `downgrade -1`, `upgrade` and `check`, then delete the file.
- [ ] **Step 4: Postgres.** On `smpy_events_check`: `upgrade heads`, `check`, `downgrade <parent>`, `upgrade heads`, `check`; drop the database. Then run the Step 2 tests on SQLite and Postgres (pass), and `check_migration_heads.py` (one head).
- [ ] **Step 5: Commit** `feat(events): follow and reminder ledger tables`.

### Task 3: Settings, effective defaults and availability

**Files:**
- Modify: `sm_events/core/settings/__init__.py` (Ruling 4's two fields with attribute docstrings), `modules/events/pyproject.toml` (`babel>=2.14,<3`), `uv.lock`
- Create: `sm_events/reminders/leads.py`, `sm_events/reminders/availability.py`
- Modify: `web/schemas/calendars.py` and PR 1's calendar update (accept and return `default_reminder_minutes: list[int] | None`; each value in `REMINDER_LEADS`, no duplicates, else 422 `invalid_lead`; needs `ACTION_EDIT`, which it already has)
- Test: `tests/reminders/test_leads.py`, `tests/reminders/test_availability.py`, `tests/web/test_calendars_api.py` (additions)

**Interfaces:**

```python
def validate_leads(values: Iterable[int]) -> tuple[int, ...]          # sorted, deduped; InvalidLead
def effective_defaults(settings: EventsSettings, calendar: Calendar) -> tuple[int, ...]
    # calendar column if set, else the setting; stored values outside REMINDER_LEADS dropped
@dataclass(frozen=True)
class Availability: available: bool; reason: str | None
async def availability(app, db) -> Availability   # Ruling 9 order
def public_base_url(app) -> str                    # host setting, rstrip("/"), "" when unset
```

- [ ] **Step 1: Write the failing tests.**
  - `test_leads.py`: `test_validate` (`[60, 15, 60]` → `(15, 60)`; `[30]` raises), `test_effective_prefers_calendar`, `test_stored_garbage_dropped` (setting `(60, 7)` → `(60,)`).
  - `test_availability.py`, with `captured_mail` and the reset fixture: parametrized over each reason in Ruling 9's order:
    - `disabled`;
    - no `public_base_url`;
    - nothing installed (`reset_mail_sender`);
    - a sender with `delivers_email=False`;
    - `worker_runtime_supported` monkeypatched false;

    and with everything satisfied, `available=True`. Also `test_resolver_only_host`: only `install_mail_resolver` with a delivering sender is `available`.
  - `test_calendars_api.py::test_reminder_defaults_round_trip` and `test_reminder_defaults_invalid_lead_422`.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_leads.py tests/reminders/test_availability.py tests/web/test_calendars_api.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Until Task 9 lands, `availability.py` imports `worker_runtime_supported` from a stub in `reminders/worker_app.py` that returns `False`. Run `uv sync --all-packages --all-extras --no-extra anonymize` from the root (headroom first).
- [ ] **Step 4: Run** the same: passes.
- [ ] **Step 5: Commit** `feat(events): reminder settings, calendar defaults and availability`.

### Task 4: The follow service

**Files:**
- Create: `sm_events/reminders/follows.py`, `sm_events/reminders/mine.py`
- Test: `tests/reminders/test_follows.py`, `tests/reminders/test_mine.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class FollowState:
    leads: tuple[int, ...]; defaults: tuple[int, ...]
    next_due: dict[int, datetime | None]            # per chosen lead, from due.next_due (Task 6)
async def get_follow(db, who, event_id, *, settings, now) -> FollowState   # NotFound per Ruling 7
async def set_follow(db, who, event_id, leads: Iterable[int], *, locale: str,
                     settings, now) -> FollowState
    # Ruling 7 checks (NotFound / NotPublished), validate_leads, FollowLimit (counted with the row
    # lock: SELECT count FOR UPDATE on the user's follows on Postgres), replace rows; empty = delete
async def delete_follow(db, who, event_id) -> None   # idempotent; NotFound when invisible
async def my_reminders(db, who, *, locale, page, page_size, now) -> MinePage
    # items: event_id, title, lang, calendar {id, name, color}, leads, next_start; hidden: int
```

`next_due` uses Task 6's pure `next_due(start_iter, lead, now)`. Until then it is stubbed to return `None`, and Task 6 wires the real one through `candidates.next_start(db, event, now)` (one bounded expansion over `[now, now + MAX_LEAD_MINUTES + 1 day]`).

- [ ] **Step 1: Write the failing tests.**
  - `test_follows.py`:
    - `test_follow_and_replace_leads`;
    - `test_empty_set_unfollows`;
    - `test_invisible_is_404_and_writes_nothing`: `V` on `P`'s published event; `A`; another tenant's id under `unbound_tenant`;
    - `test_draft_for_writer_is_not_published` (`SE` on `P`'s draft: 409) and `test_draft_for_viewer_is_404`;
    - `test_needs_events_view` (`O-`, an owner without `events.view`, on their own published event: 404);
    - `test_limit_200`: the 201st event raises `FollowLimit`, and re-saving the 200th does not;
    - `test_invalid_lead`;
    - `test_locale_recorded`;
    - `test_defaults_from_calendar`.
  - `test_mine.py`: `test_lists_visible_only_and_counts_hidden` (a share removed after following → `hidden == 1`, and the title is absent from the body); `test_paging_bounds`; `test_title_fallback`.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_follows.py tests/reminders/test_mine.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Services never commit.
- [ ] **Step 4: Run** the same on SQLite and Postgres: passes.
- [ ] **Step 5: Commit** `feat(events): follow an event for reminders`.

### Task 5: The reminders API, view and menu

**Files:**
- Create: `sm_events/web/schemas/reminders.py`, `sm_events/web/endpoints/reminders_api.py`
- Modify: `web/endpoints/__init__.py` (include the router), `web/endpoints/views.py` (`GET /reminders` renders `_PAGE_REMINDERS` with `{**view_props, "is_manager": bool, "settings_url": str}`), `web/endpoints/menu.py` (the entry after Calendars), the rate-limit registration (PR 4/5's place: `RateLimitRule("30/minute", key="user")` on `PUT`/`DELETE …/follow`), locales (`menu.reminders`)
- Modify: `host/tests/test_events_wiring.py` (the new paths), `host/tests/test_menu_labels.py` (item count +1)
- Test: `tests/web/test_reminders_api.py`, `tests/web/test_views.py` (addition)

**Interfaces.** Every route requires `events.view`, sits under `bind_admin` and CSRF, and finishes with `bus.commit`:

| Method and path | Body / query | Success | Errors |
|---|---|---|---|
| `GET /api/events/reminders/status` | none | 200 `{available, reason?, leads: REMINDER_LEADS}` (`reason` only for managers) | none |
| `GET /api/events/events/{id}/follow` | none | 200 `FollowOut {leads, defaults, next_due}` | 404 |
| `PUT /api/events/events/{id}/follow` | `{leads: list[int]}` | 200 `FollowOut` | 404, 409 `follow_limit`/`not_published`, 422 `invalid_lead`, 503 `reminders_unavailable` |
| `DELETE /api/events/events/{id}/follow` | none | 204 | 404 |
| `GET /api/events/reminders/mine` | `page`, `page_size`, `locale` | 200 `MinePage` | 422 |
| `GET /api/events/reminders/delivery` | none (`events.manage`) | 200 `{enabled, available, reason, defaults, window_days: 30, counts: {sent, failed: {code: n}, unfinished}}` | 403 |

The `delivery` counts come from Task 14's `stats.py`; this task ships the route with a stub returning zeros, and Task 14 wires it.

- [ ] **Step 1: Write the failing tests.**
  - `test_round_trip`.
  - `test_unavailable_blocks_writes_not_reads`: with `availability` monkeypatched unavailable, `PUT` gives 503 and `GET` 200.
  - `test_reason_only_for_managers`.
  - `test_invisible_404_everywhere`: each route with an invisible event id and with a random UUID gives byte-identical bodies.
  - `test_writes_need_csrf`.
  - `test_delivery_needs_manage`.
  - `test_error_envelope`: one request per new code.
  - `test_tenant_isolation` (multi).
  - `test_views.py::test_reminders_page_props`.
  - `test_events_wiring` gains `/admin/events/reminders`.
- [ ] **Step 2: Run** `uv run pytest -q tests/web/test_reminders_api.py tests/web/test_views.py`, then from the root `uv run pytest -q host/tests/test_events_wiring.py host/tests/test_menu_labels.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep handlers thin.
- [ ] **Step 4: Run** the same (passes), plus `check_hardcoded_strings.py` and `check_locales.py`.
- [ ] **Step 5: Commit** `feat(events): reminders API and page route`.

**End of batch A.** Run `cd modules/events && uv run pytest -q -n 8` (headroom first), `check_file_size.py` (no WARNING under `modules/events`), `check_hardcoded_strings.py` and `ruff check modules/events`.

---

### Task 6: Due maths

**Files:**
- Create: `sm_events/reminders/due.py` (pure)
- Test: `tests/reminders/test_due.py`

**Interfaces:**

```python
def start_window(now: datetime, lead: int) -> tuple[datetime, datetime]
    # [now + lead - catchup(lead), now + lead + REMINDER_EARLY)
def is_due(*, start: datetime, lead: int, now: datetime) -> bool
    # now - catchup <= start - lead < now + REMINDER_EARLY and now < start
def is_stale(*, start: datetime, lead: int, now: datetime) -> bool   # past the catch-up, or started
def due_at(start: datetime, lead: int) -> datetime                    # start - timedelta(minutes=lead)
def next_due(starts: Iterable[datetime], lead: int, now: datetime) -> datetime | None
    # the first due >= now - catchup among ascending starts; None when none in the iterable
```

- [ ] **Step 1: Write the failing tests:**
  - `test_due_edges`: for each lead, `due == now - catchup` is due, `now - catchup - 1 s` is stale, `now + 59 s` is due and `now + 60 s` is not yet.
  - `test_never_after_start`.
  - `test_one_day_lead_across_spring_dst`: Vienna 2026-03-29 10:00 (08:00Z), lead 1440 → due `2026-03-28T08:00Z`.
  - `test_one_day_lead_across_autumn_dst`: 2026-10-25 10:00 (09:00Z) → due `2026-10-24T09:00Z`.
  - `test_all_day_start_is_local_midnight`: an all-day event on 2026-07-06 Vienna stored by PR 2's `to_span` → lead 1440 → due `2026-07-04T22:00Z`.
  - `test_gap_instance_uses_shifted_start`: daily 02:30 Vienna; the 29 March instance (01:30Z) with lead 15 → due `01:15Z`.
  - `test_window_width`: every `start_window` is at most 6 h 1 min wide.
  - `test_next_due`: a series whose next instance is too close for 1 week gives the following one.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_due.py`. Expected: FAIL.
- [ ] **Step 3: Implement**, then wire `next_due` into `follows.py` as Task 4's note says.
- [ ] **Step 4: Run** it plus `tests/reminders/test_follows.py`: passes.
- [ ] **Step 5: Commit** `feat(events): reminder due times across DST and all-day`.

### Task 7: Candidates

**Files:**
- Create: `sm_events/reminders/candidates.py`
- Modify (only if PR 2's override application is private to the occurrences read): extract it into `calendar/series.py` as `apply_overrides(instances, overrides) -> Iterator[Instance & status]` with no behaviour change, and make `sources.py` call it. PR 2's occurrences tests must still pass unchanged.
- Test: `tests/reminders/test_candidates.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Candidate:
    event_id: uuid.UUID; revision: int; occurrence_key: str
    start: datetime; end: datetime; lead: int; user_id: str; locale: str
    @property
    def due(self) -> datetime
async def candidates(db, *, now: datetime, cap: int = REMINDER_CANDIDATES_MAX) -> tuple[list[Candidate], int]
    # (sorted by due, then event_id, user_id), deferred count; bound tenant; Ruling 15
async def next_start(db, event: Event, *, now: datetime) -> list[datetime]   # for follows.next_due
```

- [ ] **Step 1: Write the failing tests** (rows through `seed_event` and direct follow/override inserts; `now` fixed):
  - `test_one_off_due_per_lead`: an event starting in 60 min with leads 15 and 60 gives one candidate (60) now and the other after advancing `now` by 45 min.
  - `test_series_instance_key`: a weekly series gives the PR 2 key for the right instance.
  - `test_candidate_filters`: parametrized over a `cancelled` override, a `skipped` override, `event.cancelled`, a draft, `in_review`, scheduled-but-unpublished, trashed and a trashed calendar: no candidate.
  - `test_moved_into_window`: an instance moved from next week into `W_60` is a candidate at its new start with its original key.
  - `test_moved_out_of_window_not_at_old_time`.
  - `test_expansion_is_window_bounded`: an endless daily series with 10,000 follows (bulk insert) finishes in under 3 s on SQLite, gives 10,000 candidates capped to `cap` with the rest `deferred`, and expands at most 2 instances per lead window (spy on `expand.instances`).
  - `test_candidates_cap`: 3,000 followed series with instances in the window give `cap` candidates sorted by due, and `deferred == total - cap`.
  - `test_other_tenant_follows_ignored` (`unbound_tenant`).
  - `test_impossible_rule_terminates` (a stored `BYMONTHDAY=30;BYMONTH=2` row) in under 1 s.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_candidates.py tests/calendar`. Expected: the new tests FAIL and PR 2's pass.
- [ ] **Step 3: Implement.** One query per lead in use (`select distinct(lead_minutes)` first). Texts are not loaded here.
- [ ] **Step 4: Run** the same on SQLite and Postgres: passes.
- [ ] **Step 5: Commit** `feat(events): due reminder candidates without unbounded expansion`.

### Task 8: Recipients: the batch offline check

**Files:**
- Modify: `sm_events/core/access/offline.py` (add `async def offline_accounts(app, db, *, user_ids: Collection[str], tenant_id: str, request) -> dict[str, OfflineAccount]`, with `OfflineAccount(user: DirectoryUser, principal: ResourcePrincipal)`, built on one `get_many(…, with_roles=True)` and one `tenant_member_ids`; make `feed_principal` a one-id call of it, with PR 5's tests unchanged)
- Create: `sm_events/reminders/runtime.py`, `sm_events/reminders/recipients.py`
- Test: `tests/reminders/test_recipients.py`; PR 5's `tests/core/access/test_offline.py` must pass unchanged

**Interfaces:**

```python
@dataclass(frozen=True)
class Recipient: user_id: str; email: str; principal: ResourcePrincipal
class ReminderRuntime(Protocol): ...            # Ruling 18
def web_runtime(app) -> ReminderRuntime          # offline_accounts with a minimal Request on app
async def eligible(db, runtime, *, tenant_id: str,
                   wanted: Mapping[str, set[uuid.UUID]]) -> dict[str, tuple[Recipient, set[uuid.UUID]]]
    # user_id -> (recipient, visible event ids ⊆ wanted[user]); Ruling 17; raises nothing:
    # a resolver exception returns {} and logs the class
```

- [ ] **Step 1: Write the failing tests.**
  - `test_recipients_fail_closed`: parametrized over:
    - unknown id;
    - `is_active=False`;
    - `email=""`;
    - `email_verified=False` (and `None` passes);
    - `roles=None`;
    - multi mode with the user not a member;
    - multi mode with no membership store;
    - a role without `events.view`;
    - a share removed;
    - visibility `internal` → `private` for a non-owner.

    Each case drops the user, or only that event.
  - `test_resolver_raises_denies_tenant`.
  - `test_batch_one_directory_call`: a spy shows one `get_many` for 50 users.
  - `test_manager_sees_private`.
  - `test_visible_only_published`: a writer's draft id in `wanted` is not returned.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_recipients.py tests/core/access/test_offline.py`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite and Postgres: passes.
- [ ] **Step 5: Commit** `feat(events): re-check a reminder's recipient at send time`.

### Task 9: The worker runtime and its parity gate

**Files:**
- Create: `sm_events/reminders/worker_app.py` (replaces Task 3's stub)
- Test: `tests/reminders/test_worker_runtime.py`

**Interfaces:**

```python
def worker_runtime_supported() -> bool           # upstream resolver present, or the stopgap proven (see Step 0)
async def worker_runtime(db) -> ReminderRuntime | None
    # upstream principal_for if present; else the headless app, built once per process,
    # rebuilt after REMINDER_RUNTIME_TTL, role overlay replayed at most once per tick; None on any failure
def reset_worker_app() -> None                   # worker_process_init and tests
```

- [ ] **Step 0: Look upstream and spike.**
  1. Probe: `grep -rn "def principal_for\|def offline_principal\|def worker_services" $(uv run python -c "import simple_module_hosting,simple_module_core,background_tasks,os;print(*[os.path.dirname(m.__file__) for m in (simple_module_hosting,simple_module_core,background_tasks)])")`. If a resolver exists, wrap it, skip the headless app and say so in the commit.
  2. Otherwise, in a scratch script under the scratchpad, build `create_app(merge_host_settings())` without a lifespan against a scratch SQLite host database. Confirm `get_user_directory(app)` is not the null directory, that `app.state.tenant_members` is set on multi, and that `app.state.sm.permissions` holds the code role map. Then find how the permissions module replays its DB overlay (`permissions/core/_registry_sync.py`, `service.py`): the public seam it exposes, or its module `on_startup`. Measure the build time and RSS.
  3. Record the findings in the commit message. If any piece is missing without a lifespan and has no public seam, implement `worker_runtime_supported() -> False` with a comment naming the gap, keep the tests below that assert fail-closed behaviour, and **stop and report** before Task 10. The rest of batch B still lands; it just sends nothing.
- [ ] **Step 1: Write the failing tests** (the module's test app plays the host: `build_app` from `tests/support/app.py`; `create_app` is monkeypatched to return it):
  - `test_worker_runtime_parity`: for every PR 5 principal fixture, `worker_runtime(db).recipients` grants the same `events.view`/`events.manage` and the same visible ids as `web_runtime(app)`.
  - `test_role_overlay_removal_denies`: a permission removed from a role through the permissions service after the runtime was built is denied on the next tick (the overlay replay).
  - `test_build_failure_fails_closed`: `create_app` raises, so `worker_runtime` gives `None` and `worker_runtime_supported()` gives `False`; logged once by class.
  - `test_ttl_rebuild`: advancing the clock past the TTL builds again.
  - `test_reset_on_fork`: `reset_worker_app` forgets the app.
  - `test_public_base_url_from_host`.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_worker_runtime.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Add `reset_worker_app` to the existing `worker_process_init` handler in `tasks.py`.
- [ ] **Step 4: Run** it: passes.
- [ ] **Step 5: Commit** `feat(events): resolve reminder recipients in a worker (stopgap until upstream)`.

### Task 10: The claim and the marks

**Files:**
- Create: `sm_events/reminders/claim.py`
- Test: `tests/reminders/test_claim.py`

**Interfaces:**

```python
async def claim(factory: SessionFactory, c: Candidate, *, tenant_id: str, now: datetime) -> int | None
    # Ruling 20; own session; finalize_session; None on conflict or failed guard
async def mark_sent(factory, tenant_id: str, row_id: int, *, now: datetime) -> bool
async def mark_failed(factory, tenant_id: str, row_id: int, code: str) -> bool
    # both: UPDATE ... WHERE tenant_id AND id AND state = 'sending'
```

- [ ] **Step 1: Write the failing tests.**
  - `test_claim_once`: a second claim of the same candidate gives `None`.
  - `test_moved_override_one_reminder`: claim the moved instance at its new start; the original start is not a candidate (Task 7), and a direct claim of the original key at the new start conflicts.
  - `test_move_back_sends_nothing`: claim for start S1, reschedule to S2 and claim, move back to S1: `None`.
  - `test_guard_refuses_changed_event`: parametrized over a bumped revision, unpublish, `cancelled`, trash: `None` and no row.
  - `test_marks_conditional`: `mark_sent` on a `failed` row gives `False`.
  - `test_claim_commits_before_return`: a fresh session sees the `sending` row.
  - Postgres only, `test_claim_once_under_race`: 20 concurrent `claim` calls on the same candidate through separate sessions give exactly one id.
  - Postgres only, `test_guard_serialises_with_cancel`: a cancelling transaction holding the event row makes the claim wait, and after the cancel commits the claim gives `None`.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_claim.py`. Expected: FAIL.
- [ ] **Step 3: Implement** with `sqlalchemy.dialects.postgresql.insert`/`sqlite.insert` chosen by `db.bind.dialect.name`. If `INSERT … SELECT … ON CONFLICT` is awkward in one dialect, use a guard `SELECT … FOR SHARE` plus the insert in the same transaction; the tests stay the same.
- [ ] **Step 4: Run** it on SQLite and Postgres: passes.
- [ ] **Step 5: Commit** `feat(events): claim a reminder before it is sent`.

### Task 11: The message

**Files:**
- Create: `sm_events/reminders/strings.py`, `sm_events/reminders/formatting.py`, `sm_events/reminders/message.py`, `sm_events/reminders/templates/reminder.txt`
- Modify: `locales/en.json`, `de.json` (`reminders.mail.{subject, intro, when_all_day, where, online, open, manage, footer}`)
- Modify: `modules/events/pyproject.toml` package data, if the templates folder is not already included (check how records ships `templates/`)
- Test: `tests/reminders/test_message.py`, `tests/reminders/golden/{en_timed,de_timed,en_all_day_multi,de_series_online}.txt`

**Interfaces:**

```python
def format_when(*, start: datetime, end: datetime, all_day: bool, timezone: str, locale: str) -> str
def clean_subject(text: str) -> str                    # Ruling 25
def build_message(*, to: str, event: Event, texts: Mapping[str, EventText], calendar: Calendar,
                  occurrence_start: datetime, occurrence_end: datetime, locale: str,
                  default_locale: str, event_url: str, manage_url: str, site: str) -> MailMessage
def event_url(runtime, *, event, calendar, text: EventText | None, start: datetime, single_tenant: bool) -> str   # Ruling 19
```

- [ ] **Step 1: Write the failing tests.**
  - `test_golden`: parametrized over the four golden files; exact text, `html is None`.
  - `test_zone_abbreviation`: CEST in July and CET in January, for Vienna.
  - `test_title_fallback`: a `de` follow with only an `en` text gives the `en` title.
  - `test_unknown_locale_falls_back_to_en`.
  - `test_subject_sanitised`: a title containing `\r\nBcc: x`, U+2028, U+202E and 400 characters gives one line of at most 200 characters with no control or direction characters.
  - `test_online_url_only_when_online_or_hybrid`.
  - `test_links`: the public URL for a public calendar on single-tenant; the console URL on multi and for internal; the manage URL.
  - `test_catalogue_keys_parity`: every `reminders.mail.*` key exists in both catalogues (also enforced by `check_locales`).
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_message.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it plus `check_locales.py`: passes.
- [ ] **Step 5: Commit** `feat(events): plain-text reminder mail in the follower's language`.

### Task 12: Sending under budgets

**Files:**
- Create: `sm_events/reminders/send.py`
- Test: `tests/reminders/test_send.py`

**Interfaces:**

```python
@dataclass
class Budget:
    remaining: int; tenant_remaining: int; deadline: float; failures_in_row: int = 0
    def open(self) -> bool                 # remaining, tenant budget, deadline, breaker
@dataclass
class SendCounts: sent: int = 0; failed: int = 0; denied: int = 0; taken: int = 0; deferred: int = 0; stale: int = 0
async def send_tenant(db, factory, *, tenant_id, candidates: Sequence[Candidate], eligible, sender: MailSender,
                      budget: Budget, render: Callable[[Candidate, Recipient], MailMessage], now) -> SendCounts
    # per candidate: denied (no recipient or event not visible) -> next; budget closed -> deferred;
    # build the message (a failure counts failed, no claim); claim; send with timeout; mark
```

The message is built **before** the claim: a rendering bug must not burn a claim, which records' `deliver` also guards against.

- [ ] **Step 1: Write the failing tests** (`captured_mail`; fake senders):
  - `test_sent_and_marked`.
  - `test_failure_marks_failed_no_retry`: a raising sender gives `failed`/`send_failed`, and a second `send_tenant` over the same candidate sends nothing (`taken`).
  - `test_timeout_code`: a sender sleeping past a patched 0.1 s timeout gives `send_timeout`.
  - `test_outage_breaker`: an always-raising sender over 50 candidates gives exactly 3 `failed` rows and 47 `deferred`.
  - `test_wall_clock_budget`: a 2 s sender with a 5 s deadline sends about 2–3, and the rest are `deferred` with no rows.
  - `test_send_budget_per_tenant`.
  - `test_crash_after_claim_is_unfinished`: a sender raising `BaseException` (`KeyboardInterrupt` stand-in) leaves `sending`, and the next call sends nothing.
  - `test_render_failure_burns_no_claim`.
  - `test_failure_log_has_no_address`: over every record in `caplog`, neither the address nor the subject appears in `getMessage()` or `args`.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_send.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and Postgres: passes.
- [ ] **Step 5: Commit** `feat(events): send reminders under a budget, at most once`.

### Task 13: The tick and the beat

**Files:**
- Create: `sm_events/reminders/tick.py`
- Modify: `sm_events/task_config.py` (`REMINDERS = "events.reminders"`, route, `BEAT_SCHEDULE["events-reminders"] = {"task": REMINDERS, "schedule": 60.0, "options": {"queue": "events", "expires": 55}}`), `sm_events/tasks.py` (`@shared_task(name=REMINDERS) def reminders() -> dict[str, int]`, which runs `run_platform(lambda f: reminders_async(f, runtime_factory=worker_runtime, now=utcnow()))` and logs `"events.reminders: %d tenant(s), %d sent, %d failed, %d denied, %d deferred, %d stale"`), `Makefile` and `.github/workflows/ci.yml` comments (add `events.reminders`)
- Modify: the PR 5 grep test for `all_tenants` (the two new sites)
- Test: `tests/reminders/test_tick.py`, `tests/core/test_task_discovery.py` (the beat entry)

**Interfaces:**

```python
async def reminders_async(factory, *, runtime_factory: Callable[[AsyncSession], Awaitable[ReminderRuntime | None]],
                          now: datetime) -> dict[str, int]
    # settings (settings_for); enumeration under simple_module_db.all_tenants() + events' tag;
    # sender resolved once; availability re-checked in the worker (transport, delivers_email, base URL);
    # per tenant: tenant_context, candidates, eligible, send_tenant; one tenant's exception logged by class,
    # counted, rolled back, the others continue
```

- [ ] **Step 1: Write the failing tests:**
  - `test_end_to_end_one_mail` (web runtime, `captured_mail`): one follow, an event due now, one mail to the follower and one `sent` row.
  - `test_access_matrix_at_send`: parametrized over Ruling 27's rows that refuse, each giving no mail.
  - `test_disabled_or_unavailable_sends_nothing`: `reminders_enabled=False`, no transport, the console sender, no base URL and `runtime_factory → None` each give no rows and no mail.
  - `test_two_ticks_concurrently_send_once` (Postgres): `asyncio.gather` of two `reminders_async` with a 0.5 s sender over 30 due candidates gives 30 mails.
  - `test_redelivered_tick_sends_nothing`: a second run at the same `now` sends nothing.
  - `test_late_beat_catchup_then_stale`: a tick 10 min late sends a 1 h reminder, and a tick 20 min late does not.
  - `test_tick_under_strict_isolation`: on PR 2's `worker_db` with `tenant_strict=True` and two tenants, each tenant's follower gets their own mail, nothing raises `TenantUnbound`, and removing the `simple_module_db.all_tenants()` wrapper (monkeypatched to a null context) makes the enumeration fail. That last part proves the test exercises it.
  - `test_per_tenant_isolation`: tenant B's follow with A's event id produces nothing.
  - `test_failing_tenant_does_not_stop_others`.
  - `test_eager_task_runs`: `reminders.apply()` under `task_always_eager` with the runtime factory patched to `web_runtime`.
  - `test_task_discovery`: the beat entry and its route.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_tick.py tests/core/test_task_discovery.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the tests on SQLite and Postgres (passes), and from the root `uv run pytest -q host/tests/test_host_boots.py host/tests/test_events_wiring.py`.
- [ ] **Step 5: Commit** `feat(events): the events.reminders beat`.

### Task 14: Cleanup, ledger pruning and delivery counts

**Files:**
- Create: `sm_events/reminders/cleanup.py`, `sm_events/reminders/stats.py`
- Modify: `sm_events/module.py` (subscribe the follow handlers next to PR 5's, guarded the same way), PR 5's janitor (call `prune_ledger` per tenant; add its count to the log line), `web/endpoints/reminders_api.py` (wire `delivery` to `stats.counts`)
- Test: `tests/reminders/test_cleanup.py`, `tests/reminders/test_stats.py`

**Interfaces:**

```python
async def on_membership_removed(event) -> None     # tenant_scope; DELETE follows WHERE tenant_id AND user_id
async def on_user_deleted(event) -> None           # all_tenants(); DELETE follows WHERE user_id (own predicate)
async def on_tenant_deleted(event) -> None         # tenant_scope; follows and ledger
async def prune_ledger(db, *, now) -> int          # starts_at < now - REMINDER_LEDGER_DAYS, bound tenant
async def counts(db, *, now, days: int = 30) -> DeliveryCounts   # sent, failed by code, unfinished
```

Each handler opens its own session, finishes with `finalize_session`, and logs a count, or the exception class on failure, never re-raising into the bus (PR 5's pattern).

- [ ] **Step 1: Write the failing tests:**
  - `test_membership_removed_only_that_tenant`.
  - `test_user_deleted_everywhere` (`unbound_tenant`).
  - `test_tenant_deleted`.
  - `test_handler_failure_swallowed`.
  - `test_user_disabled_keeps_follows` (no handler; the next tick denies).
  - `test_prune_only_started`: a row for a start 91 days ago goes, and a row for a start tomorrow with `claimed_at` 100 days ago stays (impossible in practice, but it pins that the predicate is on `starts_at`).
  - `test_counts_window_and_unfinished`: `sending` rows 4 min old are not unfinished, 6 min old are, and rows from 31 days ago are excluded.
  - `test_delivery_route_counts`.
  - `test_subscriptions_registered`.
- [ ] **Step 2: Run** `uv run pytest -q tests/reminders/test_cleanup.py tests/reminders/test_stats.py tests/web/test_reminders_api.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same on SQLite and Postgres: passes.
- [ ] **Step 5: Commit** `feat(events): reminder cleanup, ledger pruning and delivery counts`.

**End of batch B.** Run the module suite (`-n 8`), `check_file_size.py`, `check_hardcoded_strings.py`, `check_sibling_contracts.py`, `basedpyright` and `ruff check modules/events`.

---

### Task 15: The API client and the `RemindMe` control

**Files:**
- Create: `sm_events/ui/utils/api-reminders.ts` (`reminderStatus()`, `getFollow(id)`, `setFollow(id, leads)`, `deleteFollow(id)`, `myReminders(query)`, `deliveryStatus()`), `ui/reminders/useFollow.ts`, `ui/reminders/RemindMe.tsx`, `ui/reminders/leadText.ts` (`"15 minutes" / "1 hour" / "1 day" / "1 week"` and the summary, through `t()`)
- Modify: `ui/utils/api.ts` (`errorText` for the four codes), `ui/calendar/DetailPopover.tsx` or its console slot (mount `RemindMe` for `event_status === 'published'` occurrences of the `events` source), `pages/EventEditor.tsx` (in the header for published events, for anyone who can view), locales (`reminders.control.*`, `reminders.leads.*`)
- Test: `ui/page-tests/RemindMe.test.tsx`

**Interfaces:** `<RemindMe eventId calendarDefaults? />` reads `reminderStatus()` once per page (a module-level cached promise) and renders nothing unless `available`.

- [ ] **Step 1: Write the failing tests:**
  - `hidden when unavailable`.
  - `preselects calendar defaults when not following`.
  - `saves leads and shows the summary`.
  - `stop reminding sends DELETE`.
  - `too late shows the hint for a lead with next_due null`.
  - `follow_limit shows the message`.
  - `404 closes and hides`.
  - `hidden for a draft in the popover`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/RemindMe.test.tsx` (headroom first). Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, `npx tsc --noEmit -p modules/events/tsconfig.json` and `npx biome check modules/events`: all pass.
- [ ] **Step 5: Commit** `feat(events): Remind me control in the calendar and editor`.

### Task 16: The Reminders page and calendar defaults

**Files:**
- Create: `sm_events/pages/Reminders.tsx`, `ui/components/reminders/MyReminders.tsx`, `ui/components/reminders/DeliveryCard.tsx`, `ui/components/calendars/ReminderDefaultsField.tsx`
- Modify: PR 1's calendar edit dialog (the defaults field, shown to editors), locales (`reminders.page.*`, `reminders.delivery.*` including one sentence per availability reason, `calendars.reminder_defaults.*`)
- Test: `ui/page-tests/Reminders.test.tsx`, `ui/page-tests/ReminderDefaults.test.tsx`

**Interfaces:**
- `MyReminders`: a table of title (with a `lang` badge on fallback), calendar swatch, next start in the event's timezone, leads, and Remove; paging; "N reminders are on events you can no longer see" when `hidden > 0`.
- `DeliveryCard` (only when `is_manager`): enabled, available or the reason sentence, defaults, the counts with failed broken down by code, the sentence "Unfinished: claimed but never confirmed sent. They are not retried.", and a link to `settings_url`.
- `ReminderDefaultsField`: checkboxes over the four leads plus "Use the site default".

- [ ] **Step 1: Write the failing tests:**
  - `lists reminders and removes one`.
  - `hidden count sentence`.
  - `delivery card only for managers`.
  - `each reason has a sentence` (a table over the five reasons).
  - `counts rendered`.
  - `defaults field sends null for site default and a list otherwise`.
- [ ] **Step 2: Run** `npx vitest run modules/events/sm_events/ui/page-tests/Reminders.test.tsx modules/events/sm_events/ui/page-tests/ReminderDefaults.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** vitest, tsc, biome and `uv run python scripts/check_rules.py`: all pass.
- [ ] **Step 5: Commit** `feat(events): Reminders page and calendar default lead times`.

### Task 17: Docs

**Files:**
- Create: `modules/events/docs/reminders.md`, covering:
  - the user guide: following, lead times, defaults, "My reminders";
  - operations:
    - it needs `make worker` serving `events` and `make beat`;
    - it needs a mail transport whose sender delivers, and `public_base_url`;
    - at most once: claim before send, never retried, what "unfinished" means and that a crash loses that one reminder;
    - the catch-up table and "never after the start";
    - the per-tick budgets and the breaker;
    - DST and all-day due times;
    - the links on multi-tenant hosts;
    - the worker stopgap (Ruling 18): its cost and that worker and web images must be installed identically;
    - what Ruling 27's table does;
    - the 90-day ledger.
- Modify: `modules/events/README.md` (a Reminders section; status: PR 8 of 10), `modules/events/docs/index.md` (link, settings rows, the status row), `CHANGELOG.md` (Added: reminders), `docs/module-layout.md` (the events row: `reminders/`)
- Modify: `CLAUDE.md`, the events paragraph only, adding: "**Events reminders are at most once.** `events.reminders` claims a row in `events_reminder_sent` (unique per event, occurrence, start, recipient and lead) and commits it before the send; a failed or unfinished claim is never retried. Access is re-checked for every recipient at send time and fails closed (`reminders/recipients.py`), and mail goes only through `simple_module_core.mail`."
- Modify: the spec's Amendments: add "Amendments (PR 8)" listing Rulings 1 (whole-event follows), 2 (the key with `occurrence_key` and `starts_at`), 3 (calendar defaults column), 10 (console only), 14 (all-day midnight, catch-up), 18 (the worker stopgap), 26 (no notices) and 32 (no e2e).

- [ ] **Step 1: Write** the docs.
- [ ] **Step 2: Run** `uv run python scripts/check_readmes.py` and `check_metadata.py`: both pass.
- [ ] **Step 3: Commit** `docs(events): reminders`.

### Task 18: Branch verification

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

  All pass.
- [ ] **Step 3: Fresh-import check** for every `modules/events/sm_events/reminders/*.py`.
- [ ] **Step 4: Hand over to `/ship`.** Browser QA against a local mail container (mailpit, with the mail module's SMTP pointed at it, and `public_base_url` set):
  - open an event in the calendar popover and in the editor and follow it with two leads;
  - see it in "My reminders";
  - as a manager, see the Delivery card;
  - switch the mail backend to console and see the control disappear and the reason appear;
  - with `make worker` and `make beat` running, create an event 16 minutes ahead with a 15-minute follow and receive exactly one mail in mailpit (en and de);
  - cancel a second event's occurrence and receive nothing;
  - stop the worker afterwards.

  Screenshots of the control, the page and both mails go in the PR. Stop every server when done.

## Verification checklist (before `/ship`)

- Task 18's lint set and suites pass on SQLite and Postgres. `alembic check` is clean on both after upgrade, downgrade and upgrade, and `check_migration_heads.py` reports one head.
- No file under `modules/events` is at 280 lines or more.
- `git diff --stat feat/events-pr7-integrations` touches only `modules/events/**`, `host/migrations/versions/<rev>_events_reminders.py`, `host/tests/test_events_wiring.py`, `host/tests/test_menu_labels.py`, `Makefile`, `.github/workflows/ci.yml`, `uv.lock`, `CHANGELOG.md`, `CLAUDE.md`, `docs/module-layout.md`, the spec and this plan.
- The Review Focus tests exist and pass: grep for each name listed there.
- Task 9's Step 0 outcome is stated in the PR body: whether worker sends are enabled (stopgap proven, or upstream present) or fail closed.

## Open points

1. **No offline principal in the framework** (PR 5 open point 1, now blocking for workers). File upstream in `simple_module_python` when this PR opens, with a reproduction from Task 9's tests. The ask: a worker-usable `principal_for(db, user_id, tenant_id) -> (DirectoryUser, permissions) | None`, covering the directory, membership, the tenant role, the DB role overlay and grant sources without a request, plus a worker-readable `public_base_url`. When it ships, `worker_app.py`'s probe picks it up and the headless app is deleted. If the maintainer prefers not to build the host app in a worker at all, the alternative is to ship with `worker_runtime_supported() = False`, so reminders stay hidden until upstream lands. That is a one-line change.
2. **The claim-to-send window.** An occurrence cancelled after the claim committed but before the SMTP call is still reminded. That window is one send long, and only #401's change notices could correct it.
3. **The tenant role** (`tenant:<role>`) is not counted by the stopgap, as in PR 5. On a multi-tenant host, a member whose `events.view` comes only from their tenant role is denied, which fails closed. It is fixed upstream with point 1.
4. **Per-occurrence follows** (Ruling 1) would need `original_start` on the follow. Add them only if a site asks.
5. **No per-user language.** Mail uses the console locale at follow time (Ruling 12). A framework user preference would replace it.
6. **All-day reminders fire at local midnight** (Ruling 14, the lead's suggestion). A friendlier alternative is 09:00 local on the day before for leads of a day or more. It is a constant and a test change if the maintainer prefers it.
7. **Notifications module #401**: delivery, cancel and reschedule notices and per-user channels move there. The ledger and the claim stay.
8. **The ★ rulings** most likely to change are: whole-event follows (1), the ledger key with `starts_at` (2), calendar defaults as a column (3), the reason shown only to managers (9), console only with no public control (10), all-day midnight and the catch-up table (14), the worker stopgap (18), no retry (21), no cancel or reschedule notices (26) and no e2e (32).
