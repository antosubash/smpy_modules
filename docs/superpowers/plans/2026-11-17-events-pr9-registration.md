# Events PR 9: registration through records. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An anonymous visitor registers for a public, published event, or for one occurrence of a series. Registration has a capacity and an opening and closing time. The visitor gets a confirmation mail with the event's date, time and place, a link to the `.ics` and a cancel link. A registrant is reminded before the occurrence. A signed-in user sees "My registrations". Organisers see and export the attendees in records. Seats are never oversold, and every path that deletes or cancels a registration frees its seat.

**Architecture:** Each module keeps what it already owns. **Events owns the seats**: the registration settings on the event, a counter row and one seat row per holder in its own tables, and the contract `sm_events.contracts.registration` (`describe`, `admit`, `release`, …). That contract runs in the caller's transaction, pins the tenant twice and never commits. **Records owns the people**: a new record type kind `registration`, whose records are the registrations, reached through records' existing anonymous submission pipeline (origin check, signed form token, captcha, consent, rate limits, retention, confirmation mail). Records calls events' contract from inside its submit transaction, under the lock order *records type lock, then events counter row*. Events never imports records. It learns that a "registration provider" exists through PR 6's extension registry, as it learns about sources, and asks that provider for recipients when it sends registrant reminders through PR 8's pipeline. On the frontend, records registers an editor section and a public panel through PR 6's lazy `events-extensions.ts`, so the event page never imports records code.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy async (dialect `insert … on_conflict_do_nothing`, `UPDATE … RETURNING`), the framework's `simple_module_core.mail` (`MailMessage(to, subject, text, html=None)`, **no attachments at 0.0.44**), records' public-submissions machinery, events' PR 6 registry and PR 8 reminder pipeline, pytest (SQLite plus opt-in Postgres through `tests/pg_support.py`), React 19 + Inertia, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-17-events-module-design.md`, Delivery row 9. It draws on "Integrations" → records ("registration with a capacity limit and a closing date, a confirmation mail with the `.ics` attached, reminders to registrants and 'my registrations'. It needs a new records contract; that PR starts with its own short design note."), Non-goals ("payments and waitlists"), Anti-goals ("an internal or private event reaching the public", "a reminder sent twice", "leaking across tenants"), "Reminders" and "Extension points". Precedent plans: PR 2 (`2026-11-17-events-pr2-events.md`: Ruling 1 wall clock, 12 occurrence keys, 11 orphaned overrides, 16 locks, 19 the stale guard), PR 4 (public gate, `?date=`, caching, `.ics`), PR 6 (registry, Rulings 1–3, 31–32, the frontend Rulings 25–27), PR 8 (Rulings 2, 9, 13–22, 26). Precedent code to read in full first: `modules/records/sm_records/public_submissions/` (`submit.py`, `subscribe.py`, `definition.py`, `tokens.py`, `links.py`, `opt_in.py`, `confirmation.py`, `delivery.py`, `retention.py`, `row_lock.py`, `spec.py`, `config.py`, `actions.py`), `records/services/delete/` (`_lifecycle.py`, `_empty_trash.py`, `_forget_deliveries.py`), `records/services/_lock.py`, `contracts/newsletter.py` (the shape of a careful contract), `web/endpoints/api/public_submissions_public.py`, and `ui/components/public_submissions/form/`.

---

## Design note: where registrations live and who owns the public write

**Decision: Option 1.** Registrations are records of a records type of the new kind `registration`. The public write stays records' anonymous submission route, and records calls an events contract inside that transaction to admit a seat. Events holds the seat counts and the lock, and records holds the people.

**Why it holds.**
- **Everything the anonymous write needs already exists in records** and has been reviewed hard (#101, #348, #350): the `Origin` and content-type guard, the stateless signed form token with a digest of what was shown, the captcha, the consent snapshot, the per-IP and per-type rate limits, the per-address mail budget, after-commit mail with per-recipient claims, signed confirm links with a nonce, retention sweeps and `forget_deliveries` on every purge path.
- **Organisers get an attendee list for free.** It has admin-defined extra fields, filters, export, revisions and the trash, because it is records' list view.
- **The dependency direction is PR 6's.** Records may import `sm_events.contracts.*` behind its optional `events` extra, and events imports nothing from records. Seats are a calendar fact (capacity per occurrence, closing times, cancelled occurrences, series keys), so the rule lives with the data that defines it, in events. People are personal data with consent and retention, so they live in records.
- **The seat check runs in the same transaction as the record write**, so a refused seat leaves no record, and a record never exists without its seat. The lock order is fixed: records' type lock (taken by `create_record`), then events' counter row. Events never calls records, so no transaction takes them the other way round.
- **Events still never reads records' tables.** It stores an opaque holder (the record's uuid) per seat. Reminders resolve holders to addresses through a provider that records registers in PR 6's registry.

**Option 2, an `events_registration` table and an events-owned anonymous route: rejected.** It would duplicate records' token, captcha, consent, rate-limit, confirmation, delivery-claim, retention and erasure machinery: roughly 2,000 reviewed lines, each a place to get personal data wrong. Organisers would also get a second, poorer attendee screen without fields, filters or export. And a second anonymous write surface doubles the CSRF and abuse review for every later change.

**Option 3, `registration_url` only (the status quo): kept as a mode, but not enough on its own.** The spec asks for capacity, a closing date, a confirmation, reminders to registrants and "my registrations". An external URL can do none of these, and a site would need a second product for every event with seats. `registration_url` stays as `registration_mode = "external"`.

**What this costs.** There is a new contract surface in both directions: records calls `sm_events.contracts.registration`, and events calls a registered provider. The seat hooks in four records purge paths must stay complete, so reconciliation backs them up. The cancel and confirm links inherit #366 (signed links break on an `SM_SECRET_KEY` rotation) until that issue lands.

---

## Depends on PRs 2–8 and on records

Before Task 1, rebase onto the finished `feat/events-pr8-reminders` (PR 8 → 7 → … → 1). The implementer of each batch **first re-checks every symbol below against the real code**. Where a name differs, correct this plan's task text; never rename earlier PRs' code. Stop and report if a *behaviour* differs, in particular:
- `public_events()` returns an event of a non-public calendar or a non-published event;
- no function resolves an occurrence key or a `?date=` to one instance with overrides applied;
- records' `PublicErrorRoute` does **not** roll back a refused write;
- some records path hard-deletes or trashes records without going through `_trash`, `_purge_ids` or `purge_type_records`.

| Area | Symbols relied on |
|---|---|
| Events models (PR 1–2) | `Event` (`registration_url`, `status`, `cancelled`, `starts_at`, `ends_at`, `timezone`, `all_day`, `rrule`, `revision`, `venue_name`, `address`, `online_url`, `attendance_mode`, soft delete), `EventText`, `OccurrenceOverride`, `models/_cols.py` |
| Events access (PR 2, 4) | `core/access/public.ANONYMOUS`, `public_events()`, `public_calendars()`; `core/access/events.load_event`, `event_rights`; Ruling 16's locked-event rule |
| Events time (PR 2, 4) | occurrence key shapes (PR 2 Ruling 12); `calendar/expand.instances`; the override application; PR 4's `?date=` resolution in `content/public_read.py`; `calendar/times.localize`, `to_span`/`to_local` |
| Events writes (PR 2, 6) | `content/events_write.create_event`, `update_event`, the CAS (Ruling 19), the series preview and `overrides_orphaned` (Ruling 11), `web/schemas/events_in.EventCreate`/`EventPatch`, `web/services/events_out.EventOut`, `EventUpdated(changed)` |
| Events registry (PR 6) | `calendar/registry.py` (`add_source`, `add_type`, freeze, `ensure_loaded`), `calendar/extensions.Registrar` and namespacing (Ruling 2), `calendar/extension_types.py`, `sm_events.contracts.extensions.__all__`; TS `ui/extensions/registry.ts`, `load.ts`, `PluginBoundary`, `LazyComponent` |
| Events public (PR 4) | `pages/PublicEvent.tsx`, `web/endpoints/public/_event_props.py`, `_urls.event_path(slug, locale, date)`, `_urls.absolute`, the `{slug}.ics` route, `_cache.py`, `tests/web/public/test_leaks.py` |
| Events reminders (PR 8) | `reminders/` `due.py`, `candidates.py` (`Candidate`), `claim.py` (guard), `send.py`, `message.py`, `strings.py`, `availability.availability`, `runtime.ReminderRuntime`, `events_reminder_sent` (`recipient_id` str 64), `REMINDER_LEADS` |
| Events tenancy | `core/tenancy.tenant_scope`, `bound_tenant`, `all_tenants`, `TENANT_RE` |
| Records submissions | `submit.submit`, `_check_token`, `visitor_data`, `_system`; `definition.accepting_type`, `definition`, `form_digest`, `consent_text`, `page_locale`, `ACCEPTED_KINDS`, `EMAIL_KEY`; `tokens._mac`, `host_secret`, `public_base_url`, `TokenError`; `links.sign/parse/matches/url`, `CONFIRM`; `opt_in.confirm`; `confirmation.budget_wait`, `queue_confirmation`, `recipient_key`; `delivery.claim`/`mark_sent`; `mail_runner.queue`, `queue_notification`, `ui_locale`; `transition.transition`; `row_lock.lock_record`; `system.system_update`; `strings`; `spec.system_fields`/`_field`; `config.settle`, `check_change`, `kind_of`, `default_display`; `retention.sweep`, `retention_rules`; `actions.require_form`/`require_subscription`; `errors.SubmissionRefused` |
| Records services | `records.create_record`, `soft_delete_record`, `restore_record`, `hard_delete_record`, `purge_type_records`, `_empty_trash._purge_ids`, `_lifecycle._trash`, `_lock.lock_type`, `index.query.exists_query`/`Filter`/`FilterOp`, `services.types.create_type`/`get_type`/`list_types` |
| Records contracts | `contracts/public_submissions.py` (`KIND_*`, `SubmissionKind`, `PublicSubmissionsConfig`), `public_submissions_api.py` (`SubmitBody`, `SubmissionDefinition`, `MAX_TOKEN_LEN`), `contracts/newsletter.py` (`_checked_tenant`) |
| Records web | `web/endpoints/api/public_submissions_public.py` (`SubmissionRoute`, `router`), `public_submissions_links.py`, `web/endpoints/public_submissions_views.py`, `_error_table_submissions.py`, `web/menu.py`, `web/deps.request_db`; constants `PUBLIC_SUBMISSIONS_API_PREFIX`, `VIEW_PREFIX`, `PERM_VIEW`, `PERM_MANAGE_TYPES` |
| Records + events glue (PR 6) | `sm_records/events_extensions.py`, `sm_records/integrations/events/`, the `events` extra and its `# floor:` comment, `events-extensions.ts`, `package.json` optional peer, the test that `import sm_records.events_extensions` leaves `sm_events` out of `sys.modules` |
| Records UI | `ui/components/public_submissions/form/RecordFormRender.tsx` (`RecordFormRenderProps`), `RecordFormFields.tsx`, `CaptchaWidget.tsx`, `ui/utils/submissions-form-api.ts` (`fetchDefinition`, `submitForm`, `SubmitResult`), `pagebuilder-blocks.ts` (the `RecordForm` type picker) |
| Framework | `simple_module_core.mail.MailMessage` (fields `to, subject, text, html`), `resolve_mail_sender`; `simple_module_test.mail.captured_mail`; the user directory's `email`/`email_verified` |

## Rulings

Each ruling below is **my call** unless it cites the spec. The maintainer may overrule any of them, and the ones most likely to be overruled are marked ★.

**Where things live**
1. **Option 1 of the design note.** Events owns seats and the rule, and records owns registrants and the public write. Events never imports `sm_records` (PR 6 Ruling 31's string test covers this PR's files).
2. ★ **An event points at a registration form; it does not get one each.** A records type of kind `registration` can serve many events, and `sm_event_id`/`sm_occurrence_key` say which event and occurrence each record belongs to. The event stores `registration_provider = "records:registration"` and `registration_target = <type key>`, which events treats as opaque. The event editor offers "Create a registration form" (one call; the key is `event-registrations`, deduplicated `-2`, `-3`, …) or picking any existing registration-kind type, so events that need different questions use different types. Rejected alternatives: one type per tenant, which cannot ask different questions per event, and one type per event, which means dozens of types and a schema editor per event.
3. **Capacity is per occurrence.** A one-off has one occurrence (key `"{event_id}"`). A series has `capacity` seats for **each** occurrence, keyed by PR 2's stable key, so a moved occurrence keeps its seats. `capacity = NULL` means unlimited (the counter still counts). Each registration takes one seat. A party size is an open point, and waitlists are a spec non-goal.
4. **The window.** `registration_opens_at` and `registration_closes_at` are optional UTC instants, entered as local wall clock in the event's timezone (PR 2 Ruling 1), with `opens < closes` (422 `invalid_registration`). Registration for an occurrence also always closes when that occurrence starts. For a series the absolute window applies to every occurrence.
5. ★ **Seats left are public only when the event says so** (`registration_show_seats`, default false). `describe` returns `seats_left` only then. `open` and `full` are public either way, since a refusal says so.

**Events data**
6. **Columns on `events_event`:**
   - `registration_mode` (str 16, `none` | `external` | `builtin`, default `none`; the migration sets `external` where `registration_url` is set);
   - `registration_provider` (str 64, null);
   - `registration_target` (str `REGISTRATION_TARGET_MAX = 100`, null);
   - `registration_capacity` (int null, 1–`REGISTRATION_CAPACITY_MAX = 100_000`);
   - `registration_opens_at`, `registration_closes_at` (timestamptz null);
   - `registration_show_seats` (bool, default false);
   - `registration_reminder_minutes` (int null, one of PR 8's `REMINDER_LEADS`).

   `builtin` needs a registered provider (otherwise 422 `registration_unavailable`) and a target that the provider's `check_target` accepts (otherwise 422 `unknown_registration_target`). `external` needs `registration_url` (PR 2's `http`/`https` rule). Changing a published event's registration needs `events.publish` like any other change to it (PR 2 Ruling 16), and emits `EventUpdated(changed=("registration",))`.
7. **`events_registration_count`**: `id` (BigInteger PK), `tenant_id`, `event_id` (FK `ON DELETE CASCADE`), `occurrence_key` (str 80), `taken` (int ≥ 0), `updated_at`. Unique `uq_events_registration_count (tenant_id, event_id, occurrence_key)`. This row is the lock target.
8. ★ **`events_registration_seat`**, one row per holder: `id` (BigInteger PK), `tenant_id`, `event_id` (FK cascade), `occurrence_key`, `provider` (str 64), `target` (str 100), `holder` (str `REGISTRATION_HOLDER_MAX = 64`, records' uuid), `created_at`. Unique `uq_events_registration_seat (tenant_id, provider, holder)`, index `ix_events_registration_seat_occ (tenant_id, event_id, occurrence_key)`. The brief asked for a counter only. Seat rows make `release` idempotent (a holder released twice frees one seat), let reconciliation be exact instead of estimated, and let reminders find registrants without reading records. A seat row holds an opaque uuid only, never personal data.
9. **One migration** chained off the single head at implementation time: the eight columns, the backfill and the two tables. Records needs no migration, because its config is JSON and its system fields are part of the type's JSON fields.

**The contract `sm_events.contracts.registration`** (all of it in the caller's session and transaction; it never commits or flushes beyond its own statements; it binds `tenant_scope(tenant_id)` itself and puts `tenant_id` in every Core statement; a malformed argument raises `ValueError` before any query)
10. **`describe(db, *, tenant_id, event_id, occurrence_key, provider, target, locale, now=None) -> Availability`**, with `Availability(state, seats_left: int | None, opens_at, closes_at, event: RegistrationEvent | None)`. `state` is one of:
    - `unavailable`: one answer for an unknown event, another tenant's, a draft, scheduled or trashed event, an internal or private calendar (through `public_events()` only), mode not `builtin`, a provider or target other than the caller's, or an occurrence key that is not an occurrence of the event (a skipped one included). `event` is `None`.
    - `cancelled`: the event, or this occurrence, is cancelled.
    - `not_open_yet`, `closed` (the window has passed or the occurrence has started), `full` and `open`.

    `RegistrationEvent` holds `event_id, occurrence_key, title, starts_at, ends_at, all_day, timezone, when_text, venue_name, address, online_url, page_path, ics_path, lang`. `when_text` is the occurrence's date and time in the **event's** timezone in `locale`, through PR 8's `message.py` formatter, because events owns time rendering (anti-goal 2). `page_path` and `ics_path` come from PR 4's `event_path(slug, lang, date)` and its `.ics` sibling, relative.
11. **`admit(db, *, tenant_id, event_id, occurrence_key, provider, target, holder, admin=False, now=None) -> Admission`**, with `Admission(admitted: bool, code: str | None, event: RegistrationEvent | None)`. It:
    1. re-reads the event through `public_events()`, locked `FOR SHARE` on Postgres, so it serialises with PR 2's CAS on an unpublish or cancel;
    2. applies `describe`'s rules (with `admin=True` the window and "already started" checks are skipped, but availability and capacity never are);
    3. inserts the counter row `ON CONFLICT DO NOTHING`;
    4. inserts the seat row `ON CONFLICT DO NOTHING RETURNING id`. No row back means this holder already holds a seat, which is idempotent and answers admitted;
    5. runs one statement, `UPDATE events_registration_count SET taken = taken + 1, updated_at = :now WHERE tenant_id = :t AND event_id = :e AND occurrence_key = :k AND (:cap IS NULL OR taken < :cap) RETURNING taken`. On Postgres the `UPDATE` takes the row lock and re-evaluates its `WHERE` after a wait, so N concurrent admits for the last seat admit exactly one. On SQLite the caller's records type lock (a `RESERVED` write) already serialises the writers;
    6. if no row comes back, deletes its own seat row and answers `registration_full`.

    Codes are `registration_full` (state `full`), `registration_closed` (`not_open_yet`, `closed` or `cancelled`) and `event_unavailable` (`unavailable`).
12. **`release(db, *, tenant_id, provider, holders: Sequence[str]) -> int`** deletes those seat rows (1–`SEAT_RELEASE_MAX = 1000` holders per call) and sets each affected counter to `(SELECT count(*) FROM seats …)` in one `UPDATE` per affected key. That is exact and self-healing, and it takes the same row lock admit takes. An unknown holder is a no-op. **`release_target(db, *, tenant_id, provider, target) -> int`** does the same for every seat of a target, for a deleted type. **`seat_holders(db, *, tenant_id, provider, after: str | None, limit) -> list[SeatRef(holder, event_id, occurrence_key)]`** pages by holder (1–500) for reconciliation. **`summaries(db, *, tenant_id, refs, locale) -> dict[(event_id, occurrence_key), RegistrationEvent | None]`** answers "My registrations" (≤ 200 refs), `None` for anything `describe` would call `unavailable`.
13. **`counts(db, *, tenant_id, event_id) -> list[(occurrence_key, taken)]`** is the editor's read, events-internal and behind `GET /api/events/events/{id}/registrations` (write right on the event; Ruling 32).

**The provider** (events' side of the other direction)
14. **PR 6's registry gains `add_registration_provider(RegistrationProvider)`**, namespaced like sources (`records:registration`) and frozen with the rest. `RegistrationProvider` is a frozen dataclass with:
    - `id`;
    - `label_key`;
    - `async check_target(ctx: RegistrationContext, target: str) -> RegistrationTargetInfo(label: str, admin_url: str | None, attendees_url: str | None)`, which raises `RegistrationTargetError(message)`;
    - `async recipients(ctx: RegistrationContext, holders: Sequence[str]) -> Mapping[str, Registrant(email, name, locale)]`, returning only holders whose registration is **confirmed** right now.

    `RegistrationContext` is `(tenant_id, db)`. Each call runs in a savepoint with `SOURCE_TIMEOUT_SECONDS` (PR 6 Ruling 7's isolation, reused). A timeout or an unexpected exception is 503 `registration_unavailable` on save, and skips that tenant's registrant reminders for the tick. All of it is exported from `sm_events.contracts.extensions`. The frontend twin is `registerRegistration({id, EditorSection, PublicPanel})` (Ruling 27).
15. ★ **`check_target` checks existence and kind, not the editor's records rights.** Pointing an event at a form exposes no attendee. Seeing attendees needs records' own grants on that type (Ruling 31).

**Records: the kind**
16. **`KIND_REGISTRATION = "registration"`** joins `SubmissionKind`. The config gains `pending_hold_hours: int = 24` (1–168, registration only). It reuses `double_opt_in` (default true; off requires `consent.required`, as for subscription), `public_fields` (admin-defined extra questions), `notify_to` (staff notification, through `queue_notification` unchanged), `consent` and `retention_days` (Ruling 23). A registration kind can be created only while `sm_events.contracts.registration` imports (otherwise 422 `events_unavailable`). `check_change` keeps "kind is set once". `display_field` defaults to `sm_name`.
17. **System fields of the kind** (`spec.py`), all `readonly` except `sm_nonce`:
    - `sm_email` (EMAIL, required, indexed, **not** unique: one address registers for many events);
    - `sm_name` (TEXT, required, max 200);
    - `sm_event_id` (TEXT 36, indexed);
    - `sm_occurrence_key` (TEXT 80, indexed);
    - `sm_occurrence_start` (DATETIME, indexed);
    - `sm_event_title` (TEXT 300, a snapshot for the list and the export);
    - `sm_status` (SELECT `pending` | `registered` | `cancelled`, indexed);
    - `sm_locale`, `sm_source_page`, `sm_consent_text`, `sm_consent_at`, `sm_confirmed_at`, `sm_cancelled_at`, `sm_confirm_sent_at`, `sm_ip_hash`;
    - `sm_nonce` (`internal`, 32).

    The visitor fills `sm_email` and `sm_name` (popped from `data` as `EMAIL_KEY` is today). Everything else is written only through `system=`.
18. **The `RecordForm` block and `GET /api/records/submissions/{type}` never serve a registration type** (`ACCEPTED_KINDS` stays `{form, subscription}` for that route, and the block's type picker filters the kind out). A registration form exists only with an event bound by the server (Ruling 19). Otherwise a visitor could submit with no event, or with an event id of their choosing.

**Records: the token and the public routes**
19. ★ **The registration token binds the event and the occurrence.** Its format is `{digest}.{issued}.{nonce}.{event_id}.{occurrence_key}.{mac}`, with `mac = HMAC-SHA256(secret_key, "registration|tenant|type_key|digest|issued|nonce|event_id|occurrence_key")`, base64url. A different purpose label from the form token's `"form"` means neither can be turned into the other, and their part counts (6 against 4) differ too. `event_id` must match the UUID pattern and `occurrence_key` must match `^[0-9a-f-]{36}(:\d{8}T\d{6}Z)?$` before the MAC is computed, so no dot or separator can be smuggled in. The submit route takes the event **only** from the verified token: `SubmitBody` gains no event field, and an `event`/`occurrence` key in `data` is a 422 `unknown_field` like any other. Age and `min_fill` are the form token's settings. Replaying a token for another event fails the MAC. Replaying it for the same event is a second registration attempt, which the per-address de-duplication (Ruling 21) and the rate limits bound.
20. **`GET /api/records/submissions/{type_key}/registration?event=&occurrence=&locale=`** (anonymous, under the existing prefix, so the same auth exemption, `bind_public`, `abuse.guard` and the 60/min GET rule apply; `no-store` through `SubmissionRoute`) returns `RegistrationView{availability: {state, seats_left, opens_at, closes_at}, event: {when_text, title, venue_name, address} | null, definition: SubmissionDefinition | null}`. The definition, with a registration token, is present only when `state == "open"` **and** the type is enabled and of kind `registration`. A disabled type is reported as `closed`. An unknown type, or any `unavailable`, gets the shared 404 body. This is the uncached availability read the publicly cached event page calls (Ruling 29).

**Records: the write**
21. **`registration.register(...)`**, the submit branch for the kind, follows `submit.submit`'s checks unchanged (rate limits, honeypot, token, type budget, captcha, consent, patterns), then:
    1. takes `lock_type(db, rtype)`;
    2. looks up a live record with the same `sm_email`, `sm_event_id` and `sm_occurrence_key` and status `pending` or `registered`. If it finds one: when `pending`, the confirmation goes out again within the address budget; when `registered`, nothing is sent. Either way it answers the same 202, so the form is no oracle for who registered;
    3. otherwise calls `create_record(…, status=DRAFT, actor=None, system=…)` (status `pending` with double opt-in, else `registered`);
    4. calls `admit(…, holder=record.uuid)`. On refusal it raises `SubmissionRefused(code)` with 409, and records' error route rolls the record back (Task 9 proves it).

    Lock order: **records type, then events counter**. No events path takes a records lock.
22. ★ **Double opt-in by default, and the seat is held while pending.** A pending registration holds its seat for `pending_hold_hours` (default 24). The retention sweep then trashes and purges it through the normal paths, which release the seat (Ruling 24). The confirm link expires at `min(confirm_ttl_hours, pending_hold_hours)`. Without double opt-in the registration is `registered` at once, and the mail is a confirmation with a cancel link. Someone can register another person's address either way; that person's cancel link undoes it, and the per-address budget bounds the mail.
23. **Retention.** `retention_days` counts from `sm_occurrence_start` for this kind (0 keeps), so attendee data goes a fixed time after the event. Pending purge is by `sm_consent_at + pending_hold_hours`. Both go through `soft_delete_record` and then `hard_delete_record`.

**Records: seats follow every path**
24. **Seat hooks** in `public_submissions/registration/seats.py`, each a no-op unless the type's kind is `registration`:
    - `on_trashed(db, pairs)` from `_lifecycle._trash` (single trash, cascade, bulk, spam, the retention sweep) releases;
    - `on_restored(db, rtype, record)` from `restore_record` re-admits with `admin=True`. A refusal raises records' `Conflict` with code `registration_full` or `event_unavailable`, and the restore is refused (★: a restore never overbooks);
    - `on_purged(db, rtype, uuids)` from `_purge_ids` releases again (idempotent, for rows trashed before this PR or on a host without events);
    - `on_type_purged(db, rtype)` from `purge_type_records` calls `release_target`.

    A cancelled or pending-then-expired registration releases through cancel (Ruling 25) or the trash. Without the events extra, release is a no-op that logs once, and a restore is refused with `event_unavailable`.
25. **Cancel.** The new link action `CANCEL` (`links.py`) has the form `{tenant}.{type}.{uuid}.{gate}.{mac}`, with no expiry, killed by the nonce. `GET /records/submissions/cancel?t=` shows a page with a button, and `POST /api/records/submissions/cancel` acts, so mail scanners do nothing. Under `lock_record`, a `pending` or `registered` record becomes `cancelled` (`sm_cancelled_at`, nonce rotated, `system_update` under `events.muted`) and `release` runs in the same transaction. Every outcome (forged, expired, already cancelled, the occurrence already started) answers the same page. The admin action "Cancel registration" (`actions.py`, `409 wrong_kind` on other kinds) calls the same function. ★ The record is **kept** with status `cancelled` until retention, so the organiser sees who cancelled.
26. ★ **The confirmation mail links to the `.ics`; it does not attach it.** At the pinned framework (0.0.44) `MailMessage` has `to, subject, text, html` and nothing else. The mail (`templates/registration.txt`, strings `public_submissions.registration.mail.*` in en/de, in the registration's `sm_locale`) carries the title, `when_text`, the place, the online link when there is one, the event page and `.ics` links, the confirm link (pending only), the cancel link, and why the address received it. Event links are absolute through `public_base_url` on a single-tenant host. ★ On a multi-tenant host they use the submit request's `Origin`, which `abuse.guard` has already accepted as this host's: the tenant's public origin is a request property there (PR 8 Ruling 19), and the records confirm and cancel links stay on `public_base_url` with the tenant in the token, as today. It is queued after commit through `mail_runner.queue` with per-recipient delivery claims (`recipient_key`), exactly as the newsletter confirmation is. A framework attachment API is an open point (upstream).
27. **#366 is inherited, not solved.** Confirm and cancel links are records' HMAC links, so an `SM_SECRET_KEY` rotation kills those already sent, as for newsletter confirmations. `docs/secret-key-rotation.md` lists them. When #366 lands, they verify against `SM_SECRET_KEY_PREVIOUS` with the rest. "My registrations" (Ruling 30) is a cancel path that needs no link.
28. **Reconciliation.** The retention sweep gains a per-tenant step: page `seat_holders(provider="records:registration")` and `release` every holder that is not a live (untrashed) registration record with status `pending` or `registered`. It catches seats left by a path outside the hooks, and a host where events was installed later than records. It never admits, so a registration record without a seat (its event hard-deleted) is left alone, and `describe` reports it `unavailable`.

**Public page, console and "My registrations"**
29. ★ **The event page stays publicly cacheable.** PR 4's props gain `registration: {mode, url, provider, target, occurrence_key} | null`, which is static per event and occurrence and carries no counts. `occurrence_key` is the `?date=` occurrence's, `null` for a series page without `?date=`. The page renders `RegistrationSlot`:
    - `external` shows PR 4's button;
    - `builtin` renders the registered provider's lazy `PublicPanel` with `{typeKey: target, eventId, occurrenceKey, locale}`;
    - a series without `?date=` lists its next `REGISTRATION_UPCOMING = 5` occurrences as `?date=` links ("Choose a date") instead;
    - a cancelled event shows no panel (PR 4 Ruling 16).

    The panel fetches Ruling 20's route, which is `no-store`, and renders open (the records form), not yet open, closed, full ("This event is fully booked") or cancelled. An `unavailable`/404 renders nothing. No attendee data and no counts beyond `seats_left` (Ruling 5) ever reach the page.
30. ★ **"My registrations"** is a records console page, `/admin/records/my-registrations`, with a menu entry for every signed-in member while the events extra is installed. `GET /api/records/registrations/mine` lists the bound tenant's registration records whose `sm_email` equals the caller's directory email **only when `email_verified is True`** (otherwise an empty list with `verified: false`, so an unverified account cannot read someone else's registrations). It covers statuses `pending` and `registered` with an upcoming `sm_occurrence_start`, at most 200, each with `summaries(…)` for the title and date (falling back to the `sm_event_title` snapshot and "no longer available"). `POST /api/records/registrations/{uuid}/cancel` (`RequiresCsrf`) re-checks the email match and runs Ruling 25's cancel. Matching by verified email, not by a stored user id, is deliberate: the public submit reads no session (records' rule), and someone registered before they had an account still sees it.
31. **The attendee list is records' list view**: `{VIEW_PREFIX}/{type_key}?filter=sm_event_id:eq:{event_id}` (re-check the grammar), filterable by occurrence and status, with records' export and records' grants. `check_target` returns it as `attendees_url`, and the event editor shows it only to someone who has records access to the type (the provider's editor section asks records' API, Ruling 33).
32. **The events editor** gets a "Registration" section: mode, URL, capacity, window, "show seats left", reminder lead, and the provider's `EditorSection` for the target. `GET /api/events/events/{id}/registrations` (write right) returns `{items: [{occurrence_key, start, taken, capacity}], total}` for the occurrences holding seats (≤ 100, upcoming first). ★ A series change (rule, start, timezone, all-day) that would orphan an occurrence key **holding seats** is 409 `registrations_orphaned`, with no override flag: "cancel those occurrences instead". Changing provider or target, or setting mode `none`/`external`, while seats are held is 409 `registration_has_seats`.
33. **Records' editor section** (`records:registration`'s `EditorSection`): a type select fed by `GET /api/records/registration-forms` (registration-kind types the caller may view, `records.view` plus type grants), "Create a registration form" through `POST /api/records/registration-forms` (`records.manage_types`, Ruling 2's defaults: consent required with an empty text the admin fills, double opt-in on, enabled) shown only with that permission, and the attendee link (Ruling 31).

**Reminders and lifecycle**
34. ★ **Registrants are reminded through PR 8's pipeline, not by a records beat.** A second candidate source, `reminders/registrants.py`, finds seat rows of `builtin` events with `registration_reminder_minutes = L`, published and not cancelled, whose occurrence (overrides applied, cancelled and skipped dropped, moved placed) starts in PR 8's window `W_L`. The provider's `recipients` resolves holders in one batch per tenant per tick, returning confirmed registrations only. The ledger's `recipient_id = "reg:" + holder` keeps PR 8's at-most-once claim, and the claim guard adds `EXISTS seat(holder)`, so a cancel between candidate and claim sends nothing. Availability is PR 8 Ruling 9's checks unchanged. The mail is PR 8's message with a registrant variant: public event link and `.ics` link, no "Manage reminders". ★ It has **no cancel link**, because the worker has no `secret_key` to mint one (open point). Rejected alternative: records' own beat over `contracts.occurrences`, which would duplicate the ledger, the due maths and the cancelled/moved rules.
35. **Lifecycle** (what happens when):

    | Change | Registration | Seats / records |
    |---|---|---|
    | event or occurrence cancelled | `describe` → `cancelled`; no reminders | kept (reinstating resumes) |
    | event unpublished, trashed, calendar made non-public or trashed | `unavailable`; no reminders | kept (republish resumes) |
    | event or calendar hard-deleted | n/a | seats cascade; records kept (orphaned, Ruling 28) |
    | occurrence moved | keeps its key and seats; reminded at the new time (PR 8 Ruling 2) | kept |
    | series change orphaning keys with seats | refused, 409 `registrations_orphaned` (Ruling 32) | — |
    | capacity lowered below `taken` | allowed; `full` until seats free; nobody removed | kept |
    | closed early (`closes_at` = now) | `closed` | kept |
    | provider, target or mode changed with seats | refused, 409 `registration_has_seats` | — |

    ★ **Cancellation and reschedule notices to registrants are deferred to #401**, consistent with PR 8 Ruling 26. The data they need (seats, addresses, ledger) is kept. Open point 2 describes the drop-in.

**Errors**
36. Events: 422 `invalid_registration`, `registration_unavailable` (503 when the provider times out), `unknown_registration_target`; 409 `registrations_orphaned`, `registration_has_seats`. Contract codes: `registration_full`, `registration_closed`, `event_unavailable`, as constants exported from `sm_events.contracts.registration`. Records: 409 `registration_full`, `registration_closed`, `event_unavailable` on submit and restore; 422 `events_unavailable` on creating the kind; 409 `wrong_kind` on the admin cancel. All use the `{"detail","code"}` envelope and the records error tables.

## Global Constraints

- Machine load: run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest, tsc, alembic or `uv sync`/`npm install` run, and stop and report if it exits 1. Use `-n 8` (`PYTEST_WORKERS=8`) at most, and run pytest in the **foreground**. Run **targeted tests only**, never `make test-py` or a full suite: `/ship` runs those once. Use `/usr/bin/ps`, never `ps`. No dev server, no browser here; the e2e spec is written and run once at the end of batch D by the batch D implementer after the headroom check, then the server is stopped.
- Work only in `/home/anto/Repos/smpy_modules/.claude/worktrees/events-pr9` on branch `feat/events-pr9-registration`. Before Task 1, rebase onto the finished `feat/events-pr8-reminders`. Never touch `/home/anto/Repos/smpy_modules` itself or any other worktree. Run Python entry points from the worktree root, and module tests from the module directory (`cd modules/events && uv run pytest …`, `cd modules/records && uv run pytest …`).
- Implementers are Claude subagents. Each one commits its own tasks, one commit per task, and never pushes.
- Never run `ruff format` repo-wide. Run `uv run ruff format <files touched>` and `uv run ruff check <paths>`. Never commit `.env*`.
- **Events never imports `sm_records`** (PR 6's string test must stay green). Records imports only `sm_events.contracts.*`, and only from `sm_records/integrations/events/` and the one seam `public_submissions/registration/seats.py`'s lazy import of that package (`scripts/check_sibling_contracts.py`, boundary #336).
- Records' `events` extra: keep `simple_module_events>=0.0.16,<0.1`, and extend its `# floor:` comment to `0.0.16: sm_events.contracts.extensions (the plugin registry) and sm_events.contracts.registration first ship in 0.0.16`. Version stays `0.0.15` (`uv run python scripts/bump_version.py --check-current`). Pins are ranges, never `==`.
- Settings stay DB-backed, with no environment reads. No new events or records settings field: the registration knobs live on the event and on the type's config.
- Every query on an events table runs with a tenant bound, and Core statements carry their own `tenant_id`. The contract binds `tenant_scope(tenant_id)` itself. A records contract call binds records' `tenant_scope` the same way.
- The submit path never reads `request.state.user` (records' public rule). "My registrations" is a separate, signed-in router.
- Logs never contain an address, a name, a token or a link: only tenant, type key, record uuid, event id, occurrence key and exception class.
- 300-line cap. Keep every `.py`/`.ts`/`.tsx` under 280 lines. `records/services/delete/_lifecycle.py` (277) and `public_submissions/retention.py` (268) are split **moves-only first** (Tasks 11 and 12), never trimmed.
- No literal permission, page, module-name or error-code strings outside each module's `core/constants.py` (`scripts/check_hardcoded_strings.py`).
- Only real Inertia pages under `*/pages/`: `sm_records/pages/MyRegistrations.tsx` is the one new page.
- `en.json` and `de.json` keep identical key trees in both modules (`scripts/check_locales.py`).
- Postgres checks use dev-services' Postgres with scratch databases `smpy_events_check` (alembic) and `smpy_events_test` (pytest). Drop them afterwards and say so.
- Commits use conventional messages, each ending with the line `Claude-Session: https://claude.ai/code/session_01FXHA3d9EHjqP27BBDqPnu8`.

## Review Focus

1. **Overselling under concurrency.** 20 parallel submits for the last seat on Postgres admit exactly one, and the other 19 get 409 `registration_full` with no record stored. The same holds with a pending purge, a cancel and a restore racing an admit. Covered by Task 5 (`test_admit_last_seat_parallel_pg`) and Task 9 (`test_parallel_submits_one_seat_pg`).
2. **A forged or replayed event id.** A token minted for event A used to post for event B, a form token (4-part) on a registration type, a registration token on a form type, an `event_id`/`occurrence_key` put in `data`, an occurrence key of a skipped date, and a token from tenant `a` used on tenant `b` all fail with `form_expired`, `unknown_field` or `event_unavailable`, and nothing is stored. Covered by Task 8 (`test_token_binds_event_and_occurrence`, `test_purpose_labels_differ`) and Task 9 (`test_event_never_from_body`).
3. **Seats leaking.** Single trash, cascade trash, bulk trash, spam, empty trash, hard delete, type deletion, the pending-expiry purge, the retention purge, cancel by link, cancel by admin and cancel from "My registrations" each leave `taken` equal to the number of live seats. Restoring past capacity is refused. Covered by Task 11's parametrized `test_every_path_releases` and Task 12's `test_reconcile_frees_leaked`.
4. **Private or unpublished events accepting registrations.** Drafts, scheduled, in-review and trashed events, internal and private calendars, a trashed calendar, another tenant's event and a mode-`external` event all get `unavailable` from `describe`, 404 from the registration route and `event_unavailable` from a submit carrying an old valid token. Covered by Task 4 (`test_unavailable_truth_table`) and Task 9.
5. **The dependency direction and the optional extra.** `sm_events` contains no `sm_records` string. Records without `sm_events` importable still serves forms and lists, refuses the kind with 422 `events_unavailable`, and its trash and purge paths still work. Covered by Task 6 and Task 7 (`test_without_events_installed`).
6. **PII exposure.** No address, name or count beyond `seats_left` in any public prop, cached answer or log line. "My registrations" is empty for an unverified email. A seat row holds only a uuid. Covered by Task 15 (`test_props_cache_safe`), Task 17 (`test_mine_requires_verified_email`) and Task 10 (`test_logs_carry_no_address`).

---

## Implementation batches

Hand each batch to one implementer agent, in order. Each batch leaves the events and records suites green.

| Batch | Tasks | Delivers |
|---|---|---|
| **A: events seats and contract** | 1–6 | constants, errors, migration; registration settings and their guards; the provider registry; `describe`; `admit`/`release` with the lock; the contract surface and the counts endpoint |
| **B: records kind, submit, mail, purge hooks** | 7–12 | the `registration` kind and its seam; the bound token and availability route; the submit branch; confirmation, cancel and the mail; seat hooks on every purge path; retention, reconciliation, the provider and the registration-forms API |
| **C: public panel and console** | 13–17 | events' frontend registry and editor section; records' editor section; public props and the slot; records' public panel; "My registrations" |
| **D: reminders, e2e, docs** | 18–20 | registrant reminders; `tests/e2e/events-registration.spec.ts`; docs, CHANGELOG, README, CLAUDE.md |

Each source file this plan creates stays under 280 lines; the expected sizes are in each task.

---

### Task 1: Constants, errors, columns, tables and the migration

**Files:**
- Modify: `modules/events/sm_events/core/constants.py`, `core/errors.py`, `models/event.py`, `models/__init__.py`
- Create: `modules/events/sm_events/models/registration.py` (~70 lines: `RegistrationCount`, `RegistrationSeat`)
- Create: `host/migrations/versions/<rev>_events_registration.py`
- Test: `modules/events/tests/models/test_registration_models.py`, `tests/core/test_errors.py`

**Interfaces:**
- Constants: `REGISTRATION_MODES = ("none", "external", "builtin")`, `REGISTRATION_MODE_NONE/EXTERNAL/BUILTIN`, `REGISTRATION_TARGET_MAX = 100`, `REGISTRATION_HOLDER_MAX = 64`, `REGISTRATION_CAPACITY_MAX = 100_000`, `SEAT_RELEASE_MAX = 1000`, `SEAT_HOLDERS_MAX = 500`, `SUMMARIES_MAX = 200`, `REGISTRATION_COUNTS_MAX = 100`, `REGISTRATION_UPCOMING = 5`, `OCCURRENCE_KEY_MAX = 80`; codes and details for Ruling 36.
- Errors: `InvalidRegistration` (422), `RegistrationUnavailable` (422; raised with status 503 on a provider timeout), `UnknownRegistrationTarget` (422), `RegistrationsOrphaned` (409), `RegistrationHasSeats` (409).

- [ ] **Step 1: Write the failing tests.** `test_new_codes` (parametrized `(cls, status, code)`, body exactly `{"detail","code"}`); `test_registration_tables`: the unique constraints `uq_events_registration_count` and `uq_events_registration_seat` exist, a second seat for the same `(tenant, provider, holder)` raises `IntegrityError`, deleting the event cascades both (Postgres variant under `pg_support`); `test_event_registration_defaults`: a new `Event` has `registration_mode == "none"`, `registration_show_seats is False` and the rest `None`.
- [ ] **Step 2: Run** `~/.claude/bin/wait-for-headroom`, then `cd modules/events && uv run pytest -q tests/models/test_registration_models.py tests/core/test_errors.py`. Expected: ImportError.
- [ ] **Step 3: Implement** the models (`MultiTenantMixin`, FK `ON DELETE CASCADE`) and the migration (columns, the backfill `UPDATE events_event SET registration_mode = 'external' WHERE registration_url IS NOT NULL`, both tables), chained off `alembic heads` (exactly one head).
- [ ] **Step 4: Run** the tests (pass); `uv run python scripts/check_migration_heads.py`; `alembic upgrade heads` then `alembic check` on SQLite and on Postgres (`smpy_events_check`), and `alembic downgrade -1`/`upgrade heads` once. Expected: no diff, one head.
- [ ] **Step 5: Commit** `feat(events): registration columns, seat and counter tables`.

### Task 2: Registration settings on an event, and their guards

**Files:**
- Create: `sm_events/registration/__init__.py`, `sm_events/registration/settings.py` (~170 lines: validation, wall clock ↔ UTC, the guards)
- Modify: `web/schemas/events_in.py` (`RegistrationIn` on `EventCreate`/`EventPatch`), `web/services/events_out.py` (`RegistrationOut`), `content/events_write.py` (one call each in create and update), the series-change path of Ruling 11 (one call)
- Test: `tests/registration/test_settings.py`, `tests/web/test_events_api_registration.py`

**Interfaces:**
- Consumes: Task 1; PR 2 `to_span`/`to_local`, CAS, `EventUpdated`.
- Produces:
```python
class RegistrationIn(BaseModel):   # extra="forbid"
    mode: Literal["none", "external", "builtin"] = "none"
    url: str | None = None                     # external; replaces top-level registration_url (still accepted, mapped)
    provider: str | None = None
    target: str | None = None
    capacity: int | None = None                # 1..REGISTRATION_CAPACITY_MAX
    opens_at_local: str | None = None          # wall clock in the event's timezone
    closes_at_local: str | None = None
    show_seats: bool = False
    reminder_minutes: int | None = None        # in REMINDER_LEADS
async def apply_registration(db, event, reg: RegistrationIn, *, viewer) -> RegistrationTargetInfo | None
async def guard_seats(db, event, *, new: RegistrationIn | None, orphaned_keys: Collection[str]) -> None
```

- [ ] **Step 1: Write the failing tests:**
  - `test_builtin_needs_provider`: with no provider registered, 422 `registration_unavailable`.
  - `test_target_checked`: with a fake provider whose `check_target` raises, 422 `unknown_registration_target`; a timeout gives 503 `registration_unavailable`.
  - `test_window_wall_clock`: `opens_at_local="2026-07-01T09:00"` in Vienna stores `07:00Z`, and the response echoes the local value; `opens >= closes` gives 422 `invalid_registration`.
  - `test_external_keeps_url`: an old body with a top-level `registration_url` still sets mode `external`.
  - `test_published_change_needs_publish`: a writer without `events.publish` gets 403 `publish_required` on a published event, and `EventUpdated(changed=("registration",))` is emitted for one who has it.
  - `test_has_seats_guard`: with one seat held, changing target or mode gives 409 `registration_has_seats`.
  - `test_orphan_guard`: a series with a seat on the 8 July occurrence; changing `BYDAY` gives 409 `registrations_orphaned`, and a change that keeps 8 July passes.
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement.** The orphan guard reuses Ruling 11's orphan computation over the occurrence keys that hold seats (`SELECT DISTINCT occurrence_key FROM seats WHERE event_id`). It runs before the CAS, so a refusal writes nothing.
- [ ] **Step 4: Run** them, and PR 2's `tests/web/test_events_api*.py`: pass.
- [ ] **Step 5: Commit** `feat(events): registration settings on events, with seat guards`.

### Task 3: The registration provider in the registry

**Files:**
- Modify: `calendar/extension_types.py` (+~50 lines), `calendar/registry.py`, `calendar/extensions.py` (`Registrar.add_registration_provider`), `contracts/extensions.py`
- Create: `sm_events/registration/provider_call.py` (~80 lines: savepoint and timeout around `check_target`/`recipients`, after PR 6's `plugin_runner`)
- Test: `tests/calendar/test_registry_registration.py`, `tests/registration/test_provider_call.py`

**Interfaces:**
- Produces: `RegistrationProvider`, `RegistrationContext`, `RegistrationTargetInfo`, `Registrant`, `RegistrationTargetError` (Ruling 14); `registry.registration_provider(id) -> RegistrationProvider | None`, `registration_providers() -> list`; `async check_target(provider, *, db, tenant_id, target) -> RegistrationTargetInfo`; `async recipients(provider, *, db, tenant_id, holders) -> Mapping[str, Registrant]`.

- [ ] **Step 1: Write the failing tests:** `test_namespaced` (`records:registration` from namespace `records` passes; `other:registration` from `records` raises `InvalidExtensionId`); `test_duplicate` (`DuplicateExtension`); `test_frozen` (`RegistryFrozenError` after load); `test_check_target_timeout` (a provider sleeping past `SOURCE_TIMEOUT_SECONDS` raises `RegistrationUnavailable`, and the savepoint is rolled back); `test_provider_write_refused` (a provider that adds a row is refused as PR 6 Ruling 7 refuses a source); `test_contract_surface` (`contracts.extensions.__all__` gains exactly the five names).
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, and PR 6's registry tests: pass.
- [ ] **Step 5: Commit** `feat(events): registration providers in the extension registry`.

### Task 4: `describe`: availability of one occurrence

**Files:**
- Create: `sm_events/registration/availability.py` (~200 lines; if it passes 250, split `occurrence.py` out with the key resolution)
- Test: `tests/registration/test_availability.py`

**Interfaces:**
- Consumes: `public_events()`, PR 4's occurrence resolution, PR 8's `when` formatter, `_urls.event_path`.
- Produces: `Availability`, `RegistrationEvent` (Ruling 10), `async describe(db, *, tenant_id, event_id, occurrence_key, provider, target, locale, now=None) -> Availability`, `def resolve_key(event, overrides, key) -> ResolvedOccurrence | None` (start, end, cancelled).

- [ ] **Step 1: Write the failing tests:**
  - `test_unavailable_truth_table`: parametrized over draft, in_review, scheduled, trashed event, trashed calendar, internal calendar, private calendar, another tenant's event (`unbound_tenant`, tenant `b`), mode `external`, a wrong provider, a wrong target, an unknown uuid, the key of a skipped date, a key not in the rule and a malformed key (`ValueError` before any query). Each is `unavailable` with `event is None`, except the malformed key.
  - `test_states`: `cancelled` (event flag, then a cancelled override on that date only), `not_open_yet`, `closed` (after `closes_at`, and at the occurrence's start), `full`, `open`.
  - `test_seats_left_only_when_shown`: `seats_left` is `None` unless `show_seats`; with capacity 3 and 1 taken it is 2.
  - `test_moved_occurrence`: a moved occurrence keeps its key, and `starts_at`/`when_text` are the new time.
  - `test_when_text`: a 10:00 Vienna event in `de` reads with `CEST`; all-day as a date only.
  - `test_tenant_pinned`: called with `tenant_id="b"` while `a` is bound raises `TenantIsolationError`.
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement.** Compose `public_events()` with `id == event_id`. Never build a status or visibility predicate yourself (PR 4 Ruling 1).
- [ ] **Step 4: Run** them: pass.
- [ ] **Step 5: Commit** `feat(events): registration availability of an occurrence`.

### Task 5: `admit`, `release`, `release_target`, `seat_holders`

**Files:**
- Create: `sm_events/registration/seats.py` (~220 lines)
- Test: `tests/registration/test_seats.py`, `tests/registration/test_seats_pg.py`

**Interfaces:**
- Consumes: Task 4's `describe`.
- Produces: `Admission`, `SeatRef`, `admit`, `release`, `release_target`, `seat_holders`, `counts` (Rulings 11–13), all `async` and in the caller's session.

- [ ] **Step 1: Write the failing tests:**
  - `test_admit_until_full`: capacity 2: two holders admitted (`taken == 2`), the third `registration_full` with no seat row left behind.
  - `test_admit_idempotent`: the same holder twice gives one seat and `taken == 1`.
  - `test_release_exact`: releasing a holder twice gives `taken == 0`, not −1; an unknown holder is a no-op.
  - `test_release_target`: deletes every seat of the target, and the counters become 0.
  - `test_admin_skips_window`: after `closes_at`, `admit(admin=True)` admits and `admit()` refuses `registration_closed`; with `admin=True` on a full occurrence it is still `registration_full`.
  - `test_capacity_lowered`: capacity 3 with 3 taken, lowered to 1: still `full` until two release.
  - `test_never_commits`: after `admit`, `db.in_transaction()` is true and a rollback leaves no seat.
  - `test_seat_holders_pages`: 7 holders with `limit=3` come in three pages, in holder order.
  - `test_admit_last_seat_parallel_pg` (Postgres, 20 sessions via `asyncio.gather`, each in its own transaction, capacity 1): exactly one `admitted`, nineteen `registration_full`, one seat row, `taken == 1`.
  - `test_release_races_admit_pg`: capacity 1 and held; a release and an admit concurrently end with one seat and `taken == 1`.
- [ ] **Step 2: Run** them (Postgres with `SM_TEST_PG=…smpy_events_test`): they fail.
- [ ] **Step 3: Implement** with the dialect `insert(...).on_conflict_do_nothing(index_elements=…)` and the single conditional `UPDATE … RETURNING` of Ruling 11. `FOR SHARE` on the event read is Postgres only.
- [ ] **Step 4: Run** them: pass.
- [ ] **Step 5: Commit** `feat(events): seat admission under the counter lock, exact release`.

### Task 6: The contract surface, the counts endpoint and the boundary tests

**Files:**
- Create: `sm_events/contracts/registration.py` (~120 lines: argument checks, `tenant_scope`, re-exports, `summaries`)
- Create: `sm_events/web/endpoints/registrations_api.py` (~70 lines)
- Modify: root `pyproject.toml` `[tool.pyright] include` (the new contract), `module.py` (router)
- Test: `tests/contracts/test_registration_contract.py`, `tests/web/test_registrations_api.py`, PR 6's `test_no_sibling_imports`

**Interfaces:**
- Produces: `sm_events.contracts.registration.__all__ = ["Admission", "Availability", "EVENT_UNAVAILABLE", "REGISTRATION_CLOSED", "REGISTRATION_FULL", "RegistrationEvent", "SeatRef", "admit", "describe", "release", "release_target", "seat_holders", "summaries"]`; `GET /api/events/events/{id}/registrations`.

- [ ] **Step 1: Write the failing tests:** `test_contract_surface` (`__all__` exactly as above); `test_arguments_checked` (a bool `limit`, an empty holder, 1,001 holders, a non-UUID event id and a tenant failing `TENANT_RE` each raise `ValueError`, with zero statements counted by an `after_cursor_execute` listener); `test_binds_its_tenant` (unbound session plus a `tenant_id`: works; the guard does not raise); `test_summaries` (an unavailable ref maps to `None`); `test_counts_api` (write right: items with `taken`/`capacity`; view-only: 404); `test_no_sibling_imports` still passes with the new files.
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, then `uv run basedpyright` over the include list (repo root): pass.
- [ ] **Step 5: Commit** `feat(events): sm_events.contracts.registration and the seat counts endpoint`.

### Task 7: The `registration` kind, its system fields and the events seam

**Files:**
- Modify: `modules/records/sm_records/contracts/public_submissions.py` (`KIND_REGISTRATION`, `pending_hold_hours`), `public_submissions/spec.py` (`_REGISTRATION`), `public_submissions/config.py` (settle rules, `default_display`), `public_submissions/definition.py` (`ACCEPTED_KINDS` unchanged; a `REGISTRATION_KINDS` constant), `pagebuilder-blocks.ts` type picker filter
- Create: `sm_records/public_submissions/registration/__init__.py`, `registration/seats.py` (~90 lines: the seam; Ruling 24 hooks as stubs, filled in Task 11), `sm_records/integrations/events/registration.py` (~100 lines: thin calls to `sm_events.contracts.registration`, `available() -> bool`)
- Modify: `modules/records/pyproject.toml` (floor comment)
- Test: `tests/public_submissions/registration/test_kind.py`, `tests/public_submissions/registration/test_without_events.py`

**Interfaces:**
- Produces: `KIND_REGISTRATION`; `seats.available() -> bool`; `integrations.events.registration.describe/admit/release/release_target/seat_holders/summaries`, keyword arguments as the contract, with `provider` fixed to `PROVIDER_ID = "records:registration"` (a records constant).

- [ ] **Step 1: Write the failing tests:**
  - `test_kind_fields`: a created registration type carries exactly Ruling 17's system fields, `sm_email` is not unique, and `display_field == "sm_name"`.
  - `test_kind_rules`: `double_opt_in=False` without required consent gives 422; `pending_hold_hours=0` and `169` give 422; changing the kind gives 409.
  - `test_form_route_refuses_kind`: `GET /api/records/submissions/{reg_type}` is the shared 404.
  - `test_without_events_installed`: with `sys.modules["sm_events"] = None` (monkeypatch), creating the kind is 422 `events_unavailable`, a form type still creates, submits and trashes, and `seats.available()` is false. Skip the rest of the module under `pytest.importorskip("sm_events")` (PR 6 pattern).
  - The PR 6 test that `import sm_records.events_extensions` leaves `sm_events` out of `sys.modules` still passes, and `import sm_records.public_submissions.registration.seats` does too.
- [ ] **Step 2: Run** `cd modules/records && uv run pytest -q tests/public_submissions/registration/`: fails.
- [ ] **Step 3: Implement.** The seam imports `sm_records.integrations.events.registration` inside each function, catching `ImportError` once.
- [ ] **Step 4: Run** them, `uv run python scripts/check_sibling_contracts.py` and `scripts/check_rules.py`: pass.
- [ ] **Step 5: Commit** `feat(records): the registration record type kind`.

### Task 8: The event-bound token and the availability route

**Files:**
- Create: `sm_records/public_submissions/registration/tokens.py` (~80 lines), `registration/view.py` (~110 lines: `RegistrationView` assembly)
- Modify: `contracts/public_submissions_api.py` (`RegistrationView`, `RegistrationAvailability`), `web/endpoints/api/public_submissions_public.py` (one route, declared **before** `/{type_key}`), `_error_table_submissions.py`
- Test: `tests/public_submissions/registration/test_tokens.py`, `tests/web/test_registration_route.py`

**Interfaces:**
- Produces: `sign_registration(secret, tenant, type_key, digest, event_id, occurrence_key, *, now=None) -> str`; `verify_registration(secret, token, tenant, type_key, *, min_fill, max_age, now=None) -> RegistrationToken(digest, issued, event_id, occurrence_key)` (raises `TokenError`); `GET /api/records/submissions/{type_key}/registration`; `SubmissionDefinition` gains `double_opt_in: bool | None = None`, set only for the registration kind (Task 16 uses it to choose its success text).

- [ ] **Step 1: Write the failing tests:**
  - `test_token_binds_event_and_occurrence`: changing any of tenant, type, event, occurrence, digest or issued fails the MAC.
  - `test_purpose_labels_differ`: a 4-part form token fails `verify_registration`, a 6-part registration token fails `verify_form`, and a token re-signed with `"form"` over the same parts fails.
  - `test_key_shapes`: an occurrence key with `.`, `|`, a space or non-ASCII fails before the MAC; `isascii` is checked as `verify_form` does.
  - `test_route_open`: an open event gives `definition.token` with six parts, `Cache-Control: no-store`, `availability.state == "open"` and `seats_left is None`.
  - `test_route_states`: `full` and `closed` carry no definition; a disabled type is `closed`; unavailable, an unknown type, a form-kind type and an unknown event are byte-identical 404s.
  - `test_route_tenant`: tenant `b`'s event through tenant `a`'s host is 404.
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement.** The digest is `form_digest` of the type, extended with the event id, the occurrence key and `sm_name`/`sm_email` as the first fields, so the visitor's shown form is pinned.
- [ ] **Step 4: Run** them: pass.
- [ ] **Step 5: Commit** `feat(records): event-bound registration token and availability route`.

### Task 9: The submit branch: register under both locks

**Files:**
- Create: `sm_records/public_submissions/registration/register.py` (~200 lines)
- Modify: `public_submissions/submit.py` (kind dispatch in `_check_token` and `submit`, ~12 lines; split `_check_token` into `submit_token.py` if `submit.py` passes 250)
- Test: `tests/public_submissions/registration/test_register.py`, `test_register_pg.py`

**Interfaces:**
- Consumes: Tasks 7–8; `create_record`, `lock_type`, `exists_query`, `budget_wait`, `queue_confirmation` (Task 10 replaces the mail call; until then a `queue_registration_mail` stub that records the call).
- Produces: `async register(request, db, rtype, data, token: RegistrationToken, body, settings, verdicts) -> None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_registers_pending`: system values as Ruling 17 (`sm_event_title` and `sm_occurrence_start` from `describe`), status `pending`, one seat with holder == uuid, 202.
  - `test_single_opt_in`: status `registered`.
  - `test_refusal_codes`: full gives 409 `registration_full`, closed gives `registration_closed`, an unpublished event (with a token minted before) gives `event_unavailable`; **no record stored** in each case (count rows) and no mail queued.
  - `test_event_never_from_body`: `data={"sm_event_id": other}` gives 422 `unknown_field`; `data={"event": …}` gives 422.
  - `test_duplicate_same_answer`: the same address twice for one occurrence gives one record, one seat and two 202s with identical bodies; a pending duplicate re-queues the confirmation within the budget; a registered duplicate queues nothing.
  - `test_same_address_other_occurrence`: two records, two seats.
  - `test_cross_tenant`: a token from tenant `a` posted on tenant `b` gives `form_expired`.
  - `test_parallel_submits_one_seat_pg`: capacity 1, 10 different addresses in parallel requests through the ASGI client: one 202 with a record, nine 409 `registration_full`, one record in the table.
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement** Ruling 21's order exactly: `lock_type` → duplicate lookup → `create_record` → `admit` → raise on refusal.
- [ ] **Step 4: Run** them, and records' `tests/public_submissions/test_submit*.py`: pass.
- [ ] **Step 5: Commit** `feat(records): registration submits admitted inside the records transaction`.

### Task 10: Confirmation, cancel and the registration mail

**Files:**
- Create: `registration/mail.py` (~170 lines), `registration/cancel.py` (~120 lines), `public_submissions/templates/registration.txt`
- Modify: `public_submissions/links.py` (`CANCEL`), `opt_in.py` (registration branch of `confirm`: `pending → registered`), `actions.py` (`cancel_registration`), `web/endpoints/api/public_submissions_links.py` (`POST …/cancel`), `web/endpoints/public_submissions_views.py` (the cancel page), `locales/en.json`, `locales/de.json`
- Test: `tests/public_submissions/registration/test_mail.py`, `test_cancel.py`, `test_confirm.py`

**Interfaces:**
- Produces: `async queue_registration_mail(db, request, rtype, record, event: RegistrationEvent) -> None`; `async cancel(db, rtype, record, *, settings, now=None) -> bool`; links action `CANCEL`.

- [ ] **Step 1: Write the failing tests** (with `simple_module_test.mail.captured_mail`):
  - `test_pending_mail`: one message to the address. The text contains the title, `when_text`, the venue, an absolute `…/events/<slug>.ics?date=…` link, a confirm link and a cancel link. The subject is sanitised (no CR/LF, ≤ 200). `html is None`.
  - `test_registered_mail`: no confirm link.
  - `test_multi_tenant_origin`: the event links use the request's accepted `Origin`, while the confirm and cancel links use `public_base_url`.
  - `test_confirm`: pending becomes registered and `sm_confirmed_at` is set; a second click is `already_confirmed`; after `pending_hold_hours` the link is 410 `link_expired`.
  - `test_cancel_link`: registered becomes cancelled, `sm_cancelled_at` is set, the nonce rotated, the seat released (`taken` drops) and the record kept. The second click, a forged token, another tenant's token and an occurrence already started all answer the same page, with `taken` unchanged in each.
  - `test_cancel_get_is_inert`: the `GET` page changes nothing.
  - `test_admin_cancel`: the admin action does the same; on a form type it is 409 `wrong_kind`.
  - `test_logs_carry_no_address`: with `caplog`, no record contains the address or the name in any of the above.
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement.** The mail goes through `mail_runner.queue` with the secret in the closure and `delivery` claims keyed by `recipient_key`, as `confirmation.queue_confirmation` does. Cancel takes `lock_record` and then `release` (records type lock, then events counter).
- [ ] **Step 4: Run** them, `scripts/check_locales.py`, and records' `test_opt_in*.py`/`test_links*.py`: pass.
- [ ] **Step 5: Commit** `feat(records): registration confirmation mail, confirm and cancel links`.

### Task 11: Seats follow every purge and restore path

**Files:**
- Modify (moves-only first, its own commit): move `hard_delete_record` and `purge_type_records` from `records/services/delete/_lifecycle.py` to a new `records/services/delete/_purge.py`, re-exported from the same names
- Modify: `_lifecycle._trash` (call `seats.on_trashed`), `_lifecycle.restore_record` (`seats.on_restored`), `_empty_trash._purge_ids` (`seats.on_purged`), `_purge.purge_type_records` (`seats.on_type_purged`), `public_submissions/registration/seats.py` (fill the hooks)
- Test: `tests/public_submissions/registration/test_seat_paths.py`

**Interfaces:**
- Consumes: Task 7's seam, Task 5's `release`/`release_target`/`admit(admin=True)`.
- Produces: `on_trashed(db, pairs: Sequence[tuple[Record, RecordType]])`, `on_restored(db, rtype, record)`, `on_purged(db, rtype, uuids: Sequence[str])`, `on_type_purged(db, rtype)`.

- [ ] **Step 1: Write the failing test** `test_every_path_releases`, parametrized over single trash (API), a cascade trash from a related record, bulk trash, mark as spam, empty trash, hard delete, deleting the type, the cancel link and the admin cancel. Each starts from 2 registered seats on a capacity-2 event, and after the path `taken == live seat count` and the counter equals `count(*)` of seats. Plus `test_restore_readmits` (a seat comes back), `test_restore_refused_when_full` (409 `registration_full`, record still trashed, nothing changed) and `test_non_registration_untouched` (a form type's trash runs no events statement, by the statement counter).
- [ ] **Step 2: Run** it: fails.
- [ ] **Step 3: Implement.** Before the hooks, grep records for every `sa_delete(` on a document table and every `is_deleted` write, and confirm they all reach one of the four hooks. Stop and report if one does not.
- [ ] **Step 4: Run** it, and records' `tests/records/services/delete/` and `tests/public_submissions/test_retention*.py`: pass.
- [ ] **Step 5: Commit** twice: `refactor(records): move purge services out of _lifecycle (moves only)` and `feat(records): registration seats follow every trash, purge and restore`.

### Task 12: Retention, reconciliation, the provider and the registration-forms API

**Files:**
- Modify (moves-only first): move `_due` and `_purge_one` from `public_submissions/retention.py` to `retention_purge.py`
- Modify: `retention_rules.py` (registration: pending by `sm_consent_at + pending_hold_hours`, the rest by `sm_occurrence_start + retention_days`), `retention.py` (one call to the reconcile step per tenant)
- Create: `registration/reconcile.py` (~80 lines), `sm_records/integrations/events/registration_provider.py` (~120 lines: `check_target`, `recipients`), `sm_records/web/endpoints/api/registration_forms.py` (~120 lines)
- Modify: `sm_records/events_extensions.py` (`registry.add_registration_provider(...)`, imported inside `register()`)
- Test: `tests/public_submissions/registration/test_retention.py`, `test_reconcile.py`, `tests/integrations/events/test_registration_provider.py`, `tests/web/test_registration_forms_api.py`

**Interfaces:**
- Produces: `GET /api/records/registration-forms` → `[{key, label, enabled, attendees_url}]` (types the caller may view); `POST /api/records/registration-forms` (`records.manage_types`) → `{key}`; provider `records:registration` (`label_key = "records.events.registration.label"`).

- [ ] **Step 1: Write the failing tests:**
  - `test_pending_expires`: a pending record older than `pending_hold_hours` is purged and its seat released; a confirmed one is kept.
  - `test_retention_from_occurrence`: `retention_days=30`; a record of an occurrence 31 days past is purged, and one 29 days past is kept.
  - `test_reconcile_frees_leaked`: a seat whose holder has no record (inserted directly) and one whose record is `cancelled` are released; a live seat is kept; it pages across 3 pages with `limit=2`.
  - `test_check_target`: an unknown key, a form-kind type and another tenant's type raise `RegistrationTargetError`; a registration type returns its label and attendee URL.
  - `test_recipients`: only `registered`, untrashed holders come back (pending and cancelled do not); the email, name and `sm_locale`.
  - `test_forms_api`: create gives `event-registrations`, then `-2`; without `records.manage_types` 403; the list hides types the caller's role cannot view.
- [ ] **Step 2: Run** them: they fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them: pass.
- [ ] **Step 5: Commit** twice: `refactor(records): move retention purge helpers (moves only)` and `feat(records): registration retention, seat reconciliation and the events provider`.

### Task 13: Events' frontend registry and the editor's Registration section

**Files:**
- Modify: `sm_events/ui/extensions/registry.ts` (`registerRegistration`, `registrationFor(id)`), `index.ts` (exports and types `RegistrationRegistration`, `RegistrationEditorProps`, `RegistrationPanelProps`), `ui/utils/types-events.ts`, `ui/components/editor/EventForm.tsx` (one section)
- Create: `ui/components/editor/RegistrationSection.tsx` (~200 lines), `ui/hooks/useRegistrationCounts.ts` (~50 lines), locale keys `events.registration.*` (en, de)
- Test: `ui/components/editor/RegistrationSection.test.tsx`, `ui/extensions/registry.test.ts`

**Interfaces:**
- Produces: `registerRegistration({id, EditorSection?: LazyComponent<RegistrationEditorProps>, PublicPanel?: LazyComponent<RegistrationPanelProps>})`; `RegistrationEditorProps = {target: string | null, onChange(target: string | null), eventId: string | null, readOnly: boolean, errors: Record<string, string>}`; `RegistrationPanelProps = {typeKey: string, eventId: string, occurrenceKey: string, locale: string}`.

- [ ] **Step 1: Write the failing tests:** the mode radio hides "built-in" when no provider is registered; built-in renders the provider's section inside `PluginBoundary`; the window fields are wall-clock inputs in the event's timezone; the counts table shows `taken/capacity` per occurrence; a 409 `registration_has_seats` and `registrations_orphaned` show their messages; registering an id twice throws.
- [ ] **Step 2: Run** `cd modules/events && npx vitest run ui/components/editor/RegistrationSection.test.tsx ui/extensions/registry.test.ts` (headroom first): fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, `npx tsc --noEmit -p modules/events`, and `scripts/check_locales.py`: pass.
- [ ] **Step 5: Commit** `feat(events): registration section in the event editor and the frontend slot`.

### Task 14: Records' editor section

**Files:**
- Create: `sm_records/ui/integrations/events/RegistrationEditor.tsx` (~170 lines), `ui/utils/registration-forms-api.ts` (~60 lines)
- Modify: `sm_records/events-extensions.ts` (`registerRegistration({id: 'records:registration', EditorSection: () => import(…), PublicPanel: () => import(…)})`; `PublicPanel` is a placeholder until Task 16), locales
- Test: `ui/integrations/events/RegistrationEditor.test.tsx`; PR 6's static-import scan test

**Interfaces:**
- Consumes: Task 12's API, Task 13's props.

- [ ] **Step 1: Write the failing tests:** it lists forms and selecting one calls `onChange(key)`; "Create a registration form" is shown only when the create call is permitted (the list response carries `can_create`) and selects the new key; the attendee link renders only when `attendees_url` is present; `events-extensions.ts` still has no static import beyond `@simple-module-py/events` and type imports.
- [ ] **Step 2: Run** them: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, `tsc`, and `scripts/check_ts_imports.py`: pass.
- [ ] **Step 5: Commit** `feat(records): registration form picker in the event editor`.

### Task 15: Public props and the registration slot

**Files:**
- Modify: `sm_events/web/endpoints/public/_event_props.py` (`registration` prop), `pages/PublicEvent.tsx` (slot)
- Create: `sm_events/ui/public/RegistrationSlot.tsx` (~120 lines)
- Test: `tests/web/public/test_event_props_registration.py`, `ui/public/RegistrationSlot.test.tsx`

- [ ] **Step 1: Write the failing tests:**
  - `test_props_cache_safe`: the props contain exactly `{mode, url, provider, target, occurrence_key}`, with no capacity, taken, seats, address or name; the ETag and `Cache-Control` are unchanged by a seat being taken (take a seat between two GETs: same ETag).
  - `test_series_without_date`: `occurrence_key` is null and `upcoming` lists ≤ 5 `?date=` links of future, non-skipped, non-cancelled occurrences.
  - `test_cancelled_no_panel`.
  - vitest: `external` shows the button; `builtin` with a registered panel renders it lazily with the right props; with none registered it renders nothing.
- [ ] **Step 2: Run** them: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, and PR 4's `tests/web/public/test_leaks.py`: pass.
- [ ] **Step 5: Commit** `feat(events): registration slot on the public event page`.

### Task 16: Records' public registration panel

**Files:**
- Create: `sm_records/ui/integrations/events/RegistrationPanel.tsx` (~200 lines), `ui/utils/registration-api.ts` (~70 lines: `fetchRegistration`)
- Modify: `ui/components/public_submissions/form/RecordFormRender.tsx` (an optional `definition` prop, so a caller can supply one; ~10 lines), `events-extensions.ts`, locales (`public_submissions.registration.panel.*`)
- Test: `ui/integrations/events/RegistrationPanel.test.tsx`

- [ ] **Step 1: Write the failing tests** (with `stubFetch`): `open` renders the name, email, extra fields and consent, and the submit posts to `/api/records/submissions/{type}` with the six-part token and **no** event field in the body; a 202 shows "Check your inbox" (pending) or "You're registered" (single opt-in, from a definition flag `double_opt_in`); 409 `registration_full` swaps to "This event is fully booked" without a reload; `registration_closed` and `event_unavailable` show their texts; `form_expired` refetches once (the existing behaviour); `not_open_yet` shows the opening time; a 404 renders nothing; nothing in the DOM names another registrant.
- [ ] **Step 2: Run** them: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, records' `RecordFormRender.test.tsx`, `tsc` and `check_ts_imports.py`: pass.
- [ ] **Step 5: Commit** `feat(records): public registration panel on event pages`.

### Task 17: My registrations

**Files:**
- Create: `sm_records/web/endpoints/api/registrations_mine.py` (~140 lines), `sm_records/pages/MyRegistrations.tsx` (~170 lines)
- Modify: `web/menu.py` (one entry, only when `seats.available()`), `web/endpoints/views.py` (one view), locales
- Test: `tests/web/test_registrations_mine.py`, `pages/MyRegistrations.test.tsx`

- [ ] **Step 1: Write the failing tests:** `test_mine_requires_verified_email` (`email_verified` `False` or `None` gives `{items: [], verified: false}`); `test_mine_lists` (pending and registered upcoming only, in the bound tenant only, with titles from `summaries` and the snapshot fallback); `test_mine_cancel` (CSRF required; someone else's uuid is 404; it releases the seat); `test_tenant_isolation` (the same email in tenant `b` is not listed for `a`); vitest for the page (list, empty, unverified notice, cancel confirm).
- [ ] **Step 2: Run** them: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, and `scripts/check_rules.py` (pages rule): pass.
- [ ] **Step 5: Commit** `feat(records): my registrations`.

### Task 18: Registrant reminders through the reminder pipeline

**Files:**
- Create: `sm_events/reminders/registrants.py` (~200 lines)
- Modify: `reminders/candidates.py` (merge the second source, sorted by `due`, under the same cap), `reminders/claim.py` (guard `EXISTS seat` for `reg:` recipients), `reminders/message.py` + `templates/registrant.txt` (the registrant variant), `tasks.py` tick (resolve through the provider), locales
- Test: `tests/reminders/test_registrants.py`

**Interfaces:**
- Consumes: Task 3's `recipients(...)`, Task 5's seat table, PR 8's `due`, `claim`, `send`.

- [ ] **Step 1: Write the failing tests** (a fake provider; `captured_mail`):
  - `test_reminded_once`: a registered holder, lead 1440, two ticks and a redelivered tick send one mail, with ledger `recipient_id == "reg:<uuid>"`.
  - `test_not_for_pending_or_cancelled`: the provider returns neither, so no mail and no row.
  - `test_cancelled_skipped_moved`: a cancelled occurrence gives no mail; a skipped one none; a moved one is sent at the new time.
  - `test_cancel_between_candidate_and_claim`: the seat deleted after the candidate is computed makes the claim return `None`, and nothing is sent.
  - `test_no_lead_no_reminder`: `registration_reminder_minutes` null sends nothing.
  - `test_provider_failure_skips_tenant`: a provider that raises skips that tenant and sends the other tenant's.
  - `test_registrant_mail`: the public link and `.ics` link, no "Manage reminders", the registration's locale.
- [ ] **Step 2: Run** them: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them, and PR 8's `tests/reminders/`: pass.
- [ ] **Step 5: Commit** `feat(events): reminders to registrants`.

### Task 19: e2e spec `tests/e2e/events-registration.spec.ts`

**Files:**
- Create: `tests/e2e/events-registration.spec.ts` (~200 lines; it stands alone, seeding everything through the API with `uniqueSlug`)
- Modify: none in `start-test-server.sh` unless `public_submissions_min_fill_seconds` needs lowering for every run (then set it there, suite-wide)

The repo has **no e2e mail capture** for records (only newsletter's opt-in outbox hook), so the spec uses a **single opt-in** type, and the confirm and cancel links are covered by Task 10's pytest with `captured_mail`.

- [ ] **Step 1: Write the spec.** As admin: create a public calendar, create a registration form (Task 12's API), set `double_opt_in=false`, required consent with a text, and publish an event with built-in registration, capacity 1 and `show_seats`. In an anonymous context: open `/events/<slug>`, see "1 seat left", fill name, email and consent, wait `min_fill`, submit, see "You're registered". In a second anonymous context: see "This event is fully booked", and a direct POST with a fresh token gives 409 `registration_full`. As admin: open the attendee link, see exactly one row, run "Cancel registration". Anonymous again: the form is open, and a third address registers. Also assert the event page's response headers are unchanged between the two visits (cache-safe).
- [ ] **Step 2: Run** after `wait-for-headroom`: `npx playwright test tests/e2e/events-registration.spec.ts`, against the e2e server started per `running-the-stack`. Expected: pass. Stop the server.
- [ ] **Step 3: Commit** `test(e2e): events registration through records`.

### Task 20: Docs, CHANGELOG, README, CLAUDE.md

**Files:**
- Modify: `modules/events/docs/index.md` (Registration), `modules/events/docs/writing-a-plugin.md` (registration providers), `modules/records/docs/user-guide.md` and `api-reference.md` (the kind, the routes, cancel, "My registrations", retention), `docs/secret-key-rotation.md` (registration confirm and cancel links), both modules' `CHANGELOG.md`, `README.md` (the integration line), `CLAUDE.md`

- [ ] **Step 1: Write.** The CLAUDE.md paragraph goes in the records website-submission section and has a short twin in the events paragraph: *"Event registration (events PR 9) is a records kind, `registration`. The signed registration token is the trust anchor for the event and occurrence: never take them from the body or a block. Seats are admitted by `sm_events.contracts.registration.admit` inside records' submit transaction, records type lock first, then events' counter row; events never takes a records lock and never imports records. Every trash, purge, restore and cancel path goes through `public_submissions/registration/seats.py`; a new way of deleting registration records must too. The retention sweep reconciles leaked seats."*
- [ ] **Step 2: Run** `scripts/check_rules.py`, `check_locales.py` and `check_file_size.py`: pass.
- [ ] **Step 3: Commit** `docs(events,records): registration through records`.

## Verification checklist

- [ ] Batches A–D committed, one commit per task (plus the two moves-only commits), all ending with the session line.
- [ ] Targeted suites green: `modules/events/tests/registration/`, `tests/reminders/`, `tests/web/public/`, `tests/calendar/test_registry*`; `modules/records/tests/public_submissions/`, `tests/records/services/delete/`, `tests/integrations/events/`; the Postgres variants against `smpy_events_test` (then dropped).
- [ ] `alembic check` clean on SQLite and Postgres, one head (`check_migration_heads.py`); `smpy_events_check` dropped.
- [ ] `make lint`'s checks: `check_rules.py`, `check_sibling_contracts.py` (with tags fetched), `check_ts_imports.py`, `check_locales.py`, `check_file_size.py` (no new file ≥ 280), `check_hardcoded_strings.py`, `moved_paths.py --check`, basedpyright over the include list.
- [ ] No `sm_records` string in `sm_events/`; records' `sm_events` imports only from `integrations/events/` and the seam.
- [ ] Review Focus 1–6 tests named above all exist and pass.
- [ ] The e2e spec passed once; the server is stopped.

## Open points

1. **`MailMessage` has no attachments at framework 0.0.44.** The spec says "the `.ics` attached", and this PR links it instead (Ruling 26). File upstream in `simple_module_python` with a reproduction: `MailMessage(attachments=[(filename, content_type, bytes)])` plus SMTP support. When it ships, attach the single-event `.ics`.
2. **Cancellation and reschedule notices** to registrants are deferred to #401 (Ruling 35, as PR 8 Ruling 26). The drop-in, if the maintainer wants it now: a ledger row with a reserved `lead_minutes = 0` per `(occurrence_key, starts_at, "reg:"+holder)`, a beat step over seats of cancelled occurrences starting in the future, and a guard requiring the occurrence still cancelled. That is about one task.
3. **No cancel link in reminders** (Ruling 34): the worker has no `secret_key`. A stored random per-registration cancel token (hashed, as PR 5's feed tokens, so independent of #366) would fix both this and the rotation problem; it is a records change.
4. **Party size and waitlists.** One seat per registration; waitlists are a spec non-goal.
5. **Signed-in-only registration** for internal events (members registering for an internal workshop) is out: registration is public-only (Ruling 10). It would need a second, authenticated submit path.
6. **#366** (signed links and key rotation) is inherited (Ruling 27).
7. **The ★ rulings** most likely to change are: an event points at a shared form (2), seats left hidden by default (5), seat rows beside the counter (8), `check_target` not checking the editor's records rights (15), the event-bound token format (19), double opt-in holding a seat (22), a restore never overbooking (24), keeping cancelled records (25), the `.ics` link instead of an attachment and the `Origin` on multi-tenant hosts (26), the cache-safe props (29), "My registrations" by verified email (30), the orphan and seats guards (32), reminders through events' pipeline without a cancel link (34) and deferring notices to #401 (35).
