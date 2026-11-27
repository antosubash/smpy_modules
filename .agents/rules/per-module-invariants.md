---
trigger: model_decision
description: Per-module invariants for records, events, newsletter, billing, images, and ai in smpy_modules.
---

## Per-module invariants

- **records, submissions (#101)** are anonymous writes: the type
  (`RecordType.public_submissions`) is the trust anchor, never the `RecordForm`
  props; `sm_*` fields are written only via `system=`; no `RequiresCsrf` on
  purpose (JSON, `Origin`, signed form token). Purges go only through
  `hard_delete_record`, `empty_trash` or `purge_type_records` (`forget_deliveries`).
  [architecture](../../modules/records/docs/architecture.md#public-submissions-and-system-fields),
  [API](../../modules/records/docs/api-reference.md#website-submissions).
- **records, secret fields** are `SealedSecret`, never `str` (captcha secret, #350;
  provider installed in `core/boot.register_settings` for headless scripts).
  [operations](../../modules/records/docs/operations.md#website-forms-and-newsletters).
- **records, registration**: events owns the seats, records the person; they meet
  only in `sm_events.contracts.registration` (caller's transaction, never commits).
  Lock order: records' type and row locks, the event row (`FOR SHARE`, admit only),
  counter rows in ascending id (`FOR UPDATE`), seats; contention is `SeatsBusy`. A
  registration token is records' form-token surface (the first documented
  exception). `sm_records.contracts.dated` serves events' `records:dates` under the
  caller's own access; `integrations/events/` alone imports `sm_events`
  ([registration](../../modules/records/docs/registration.md#for-contributors)).
- **events** ([rules](../../modules/events/docs/rules.md)):
  - Access goes through `core.access.POLICY`; a change to an existing event starts
    with `claim_revision`; recurrence never expands without an `until`; the API
    takes a wall clock plus an IANA zone, never UTC
    ([access](../../modules/events/docs/rules.md#access)).
  - FullCalendar is imported only under `ui/calendar/adapter/` (MIT packages on the
    allow-list); grid changes convert through `ui/calendar/time/zones.ts`
    ([calendar](../../modules/events/docs/rules.md#the-calendar-fullcalendar-7)).
  - Everything anonymous goes through `core/access/public.py` and answers "not
    here" one way; a new public route joins `tests/web/public/leaks.py`; production
    sets `public_base_url`. `contracts.cards` and the blocks' routes are the same
    projection, fetched live ([public](../../modules/events/docs/rules.md#the-public-surface)).
  - Private feeds and `.ics` import: one padded 404; store only SHA-256 hashes of
    feed tokens; `scan.py` is the only parser, and a private item stays a draft
    ([feeds](../../modules/events/docs/rules.md#private-feeds-and-the-ics-import)).
  - Subscription URLs are fetched only through `feeds.subscriptions.fetch`, stored
    only as `enc:v2:` (`url_enc`), and a fetch `Policy` comes only from
    `policy.effective` ([subscriptions](../../modules/events/docs/rules.md#subscriptions)).
  - Reminders are at most once: claim in `events_reminder_sent`, commit, then send
    ([reminders](../../modules/events/docs/rules.md#reminders-are-at-most-once)).
  - Plugins register from `events_extensions.py`, never `on_startup`, installed in
    the web and every worker image; plugin settings are never secret
    ([plugins](../../modules/events/docs/rules.md#plugins)).
- **newsletter**:
  - HTML only from `sm_newsletter.content.render`; cards only via
    `content/integrations/` (news, pagebuilder and `sm_events.contracts.cards`; an
    event card is a snapshot of a published event of a public calendar, frozen at
    scheduling, its id never printed); writes guarded by `expected_revision` ([content](../../modules/newsletter/docs/content.md)).
  - Test sends go only to vouched-for addresses, under the dispatch lock and
    budget; a refusal writes no row ([test sends](../../modules/newsletter/docs/sending.md#test-sends)).
  - Suppressions are tenant-wide; only a double-opt-in confirmation or an admin
    lift (never `complaint`, under records' `lock_confirmation`, which every new
    unsubscribe path takes) clears one ([suppressions](../../modules/newsletter/docs/audience.md#suppressions)).
  - The Mailchimp import never clears or confirms a pending signup, publishes no
    events and keeps `lock_import_batch`'s lock order ([import](../../modules/newsletter/docs/import.md)).
  - Only the `newsletter.dispatch` beat sends, from the render snapshot;
    `/newsletter/u/`, `/o/`, `/c/` answer forged tokens like real ones
    ([sending](../../modules/newsletter/docs/sending.md), [tracking](../../modules/newsletter/docs/tracking.md)).
  - The SMTP password is written only through `PUT /api/newsletter/settings/smtp-password`
    (`newsletter.manage` and `settings.edit`); workers refuse a plaintext one
    ([secret](../../modules/newsletter/docs/operations.md#the-secret)). A settings write that
    changes the SMTP host, port, security or username clears it, and the generic Settings
    screen refuses newsletter writes ([settings](../../modules/newsletter/docs/index.md#settings)).
- **billing commits outside a request with `finalize_session`, never
  `commit()`** (`tests/core/test_commit_sites.py`, empty allow-list since #340;
  [transactions](../../modules/billing/docs/architecture.md#transactions--the-rule-that-bites)).
  State comes only from `sync.resync`/`apply_snapshot`, never a webhook payload;
  `PlanOut` never inherits input bounds ([architecture](../../modules/billing/docs/architecture.md)).
  `subject_mode = user` is restart-only and refused on a multi-tenant host; images
  replays the subject recorded per hold ([subjects](../../modules/billing/docs/subjects.md)).
- **images**: plugins register from `images_extensions.py`, never `on_startup`,
  installed identically in the web and every worker image
  ([plugins](../../modules/images/docs/writing-a-plugin.md#registration)). `[anonymize]`
  is never installed by default (its tests use a fake detector; only
  `images-models.yml` runs the real ones) and has no AGPL code or weights (user
  decision, 2026-10-29: no torch, ultralytics or ultralytics-trained checkpoint;
  [licences](../../modules/images/docs/index.md#anonymize-models-and-licences)).
- **ai** is SYSTEM-scope (one provider config and key per slot for all tenants)
  and reads `SM_SECRET_KEY`, `SM_SECRET_KEY_PREVIOUS` and, for `consume_requests`
  without a `session_factory` while billing is installed, `SM_DATABASE_URL`, as
  `BootstrapSettings` locates `.env`, never cwd-relative (#124;
  [settings](../../modules/ai/docs/operations.md#settings)).
