# Newsletter PR 4: sending — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A campaign can be sent now or scheduled. Its audience is frozen into `newsletter_send`
when it starts. One beat-driven dispatcher sends it over SMTP within the daily cap and the
per-minute rate, across days if it has to. Failures are retried only when nothing can have been
delivered. Hard bounces are suppressed. An admin can pause, resume and cancel. Every email
carries a signed, per-recipient unsubscribe link: a confirm page on GET, and an RFC 8058
one-click POST.

**Architecture:**
- **Scheduling (web process).** Scheduling renders the email once and stores it as a
  *render snapshot* (`newsletter_campaign_render`) beside the campaign, while the web app is at
  hand. A Celery worker therefore never needs the app, branding, i18n or the tenants module.
- **The tick (worker).** A beat task, `newsletter.dispatch`, runs every minute. It recovers
  expired leases, freezes due campaigns, then sends in slices of at most 10 recipients under
  PR 3's install-wide `dispatch_lock`. Each slice is admitted by PR 3's rolling budget.
  - Each recipient's `newsletter_send_attempt` row is committed before the SMTP call and closed
    after it.
  - The transport's outcome, which now carries the SMTP stage, is classified into one verdict
    per row.
- **Unsubscribe (web process).** It is an anonymous route under `/newsletter/u/`. Its tenant
  comes from the HMAC-verified token, as records' links do. It calls records' `unsubscribe`
  contract and writes newsletter's suppression row in the same transaction.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic, Celery through
`simple_module_background_tasks` (`settings_for`, `sync_db`), aiosmtplib, aiosmtpd (tests),
stdlib `hmac`, React 19 + Inertia, vitest.

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md`. Its "Amendments"
section overrides the text above it. Also read:
- the roadmap, `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md` (PR 4 row and the
  "Notes for PR 4");
- the PR 3 plan, `docs/superpowers/plans/2026-11-03-newsletter-pr3-campaigns.md`, and its
  ledger, `.superpowers/sdd/2026-11-03-newsletter-pr3-campaigns/progress.md` (rulings C1–C14);
- the stack notes, `.superpowers/sdd/newsletter-stack.md` (the PR 2 carry-over: the worker
  secret four-case test).

## Rulings (decided here; cost if wrong in each)

- **S1. The render is snapshotted when the campaign is scheduled, not in the worker.**
  - `campaigns/snapshot.py` runs PR 3's `render_context` and `render` in the request that
    schedules the campaign.
  - It stores `subject` / `html` / `text` (merge tags left in place), `sender` (formatted
    `From`), `reply_to`, `public_base` and `locale` in a new table, `newsletter_campaign_render`
    (one row per campaign). The row is written in the same transaction as `draft → scheduled`.
  - The worker only personalises. This replaces the roadmap note that "the worker app needs
    `app.state.sm_newsletter.tenancy` and `app.state.tenants`": no app is built in a worker.
  - It also freezes the content when the campaign leaves draft, which the status machine
    already implies.
  - Cost if wrong: a later change to the sender, branding or physical address does not reach a
    campaign that is already scheduled or sending. *Unschedule* and schedule again re-render it,
    and the docs say so.
- **S2. Start is the beat; "send now" means "scheduled for now".**
  - `POST /campaigns/{id}/send` with no `scheduled_at` schedules the campaign at `now`.
  - The next dispatcher tick freezes it (≤ about 60 s). One path serves both cases.
  - There is no immediate `.delay()`: in eager mode it would run `run_platform` on the
    request's loop, which refuses.
  - Scheduling is in this PR because no later PR lists it, and the status `scheduled` exists.
  - Cost if wrong: up to a minute before the first message goes out.
- **S3. The audience stays `all` in PR 4.**
  - `tag:` and `segment:` keep answering 422 `audience_unsupported` until PR 6, which ships
    segments and a tag picker.
  - Freeze takes its filters from `campaigns/audience.py:audience_filters`, the seam PR 6 fills.
  - Fix `AudienceUnsupported`'s docstring and detail, which promise tags in PR 4.
  - Cost if wrong: PR 7's e2e step "send to a tag" depends on PR 6. That is already the stack
    order (team-lead, 2026-11-05).
- **S4. Classification follows the spec, not "every hard 5xx bounces".** One pure function,
  `sending/classify.py:classify`, maps each result to a verdict:

  | Transport result | Verdict | Row | Stops the tick |
  |---|---|---|---|
  | `accepted` | `sent` | `sent`, `sent_at` | no |
  | `unknown` (drop after the body) | `unknown` | `failed`, `error_kind=outcome_unknown`, **never retried** | no |
  | `failed`, stage `auth` | `pause` (`smtp_auth`) | back to `queued` | yes |
  | `failed`, any other stage | `retry` | `queued` + `retry_at`, or `failed/retries_exhausted` | yes |
  | `rejected`, `code is None` (bad header, non-ASCII address) | `fail` | `failed`, `error_kind=invalid_message` | no |
  | `rejected` 4xx | `retry` | as above | only for `421` or enhanced `4.7.x` (a quota reply) |
  | `rejected` 5xx at **RCPT** with enhanced `5.1.x` | `bounce` | `bounced` + tenant-wide `hard_bounce` suppression | no |
  | any other `rejected` (other 5xx at any stage, 5.1.x at MAIL/DATA, no enhanced code, non-4/5 code) | `pause` (`smtp_rejected`) | back to `queued` | yes |

  - Retries: at most `MAX_ATTEMPTS = 3` counted attempts. The backoff is 5 min, then 30 min
    (`retry_at`). A `pause` verdict does not count as an attempt.
  - The brief's "hard 5xx → bounce" is overridden by spec §Sending 4: only 5.1.x is a bounce,
    so a quota or policy refusal never suppresses anyone.
  - Cost if wrong: a relay that answers a bad mailbox with a bare `550` (no enhanced code)
    pauses the campaign instead of bouncing. The admin resumes or cancels.
- **S5. The transport says where it failed.**
  - `DeliveryResult` gains `stage: Stage | None = None`, with
    `Stage = Literal["connect", "tls", "auth", "mail", "rcpt", "data"]`. `data` covers the
    `DATA` command and the final reply.
  - `TransportUnavailable` gains a `stage` attribute.
  - A reconnect failure inside a session returns `failed` with the reconnect's stage.
  - The console transport returns `rejected`/`None` for a bad header, instead of raising
    (smtp already does).
  - Cost if wrong: none beyond one field.
- **S6. The dispatcher holds the lock per slice, not per tick.**
  - A slice is ≤ `SLICE = 10` recipients. Inside `dispatch_lock(holder="dispatcher")` the tick
    calls `current_budget`, sends `min(budget.left, SLICE)`, and releases.
  - A test send therefore waits at most one slice; PR 3 ruling C1's `wait_s=15` holds.
  - The global lock is the "single dispatcher" of amendment 4, so there is no
    `FOR UPDATE SKIP LOCKED`: nothing else can claim inside the lock.
  - Per recipient, the order is (A4):
    1. eligibility, render and compose, with no reservation;
    2. `lock.renew()`;
    3. the reservation, in one transaction: the lock fence (`HeldLock.fence(session)`: on
       SQLite a conditional `UPDATE` requiring `holder = me AND locked_until > now`), the
       conditional row claim (A3) and `open_attempt`, all committed together;
    4. the SMTP call.

    A lost SQLite lease ends the tick with nothing claimed, and a fenced reservation can never
    spend budget another holder counted.
  - One recipient's SMTP work is bounded by `send_deadline = 45 s` (per command 20 s), well
    under the 120 s SQLite lease.
  - A tick stops after `TICK_SECONDS = 50` so ticks rarely overlap. The beat entry also carries
    `expires: 55`.
  - Cost if wrong: one extra query per recipient (30 per minute by default).
- **S7. The lease.**
  - A claimed row is `sending` with `lease_until = now + 10 min` and its attempt row `pending`,
    both committed before the SMTP call.
  - At the start of each tick, `sending` rows whose lease has expired become
    `failed/outcome_unknown`, and their `pending` attempts become `unknown`. They are never
    resent, and they still count against the budget (spec "duplicate guard", amendment 2).
- **S8. Unsubscribe tenancy: the tenant comes from the verified token, not `bind_public`.**
  - Unsubscribe URLs are built on the host's `public_base_url` (ruling C7). On a multi-tenant
    host that is the apex, where no tenant resolves, so `bind_public` would 404 every link.
  - The route follows records' documented exception
    (`sm_records/web/endpoints/api/public_submissions_links.py`):
    1. verify the MAC before any statement runs;
    2. if the request resolved a tenant and it differs from the token's tenant, treat the token
       as forged;
    3. otherwise bind `tenant_scope(token.tenant_id)`.
  - There is no 404 "no tenant" case. Every answer, for a real, forged, `test` or other-tenant
    token, is the same 200 page (spec: "always answers the same way"; R1).
  - This overrides the brief's "bind_public, 404 when no tenant".
  - Cost if wrong: with `bind_public`, every multi-tenant unsubscribe link fails, which breaks
    an anti-goal.
- **S9. The unsubscribe page.**
  - **The page.** Server-rendered HTML with one plain `<form method="post">` and no script, so
    it works in any mail client's browser. It is not an Inertia page (the pages rule is
    untouched). Its language is the host's `i18n_default_locale`, the same as the email footer
    (PR 3 R12). Its strings are `newsletter.unsubscribe_page.*`. GET reads nothing and binds
    nothing.
  - **The POST.** Any body is accepted (the button's empty form, or RFC 8058's
    `List-Unsubscribe=One-Click`). It runs records' `unsubscribe` with
    `unless_confirmed_after = send.sent_at or campaign.started_at`.
  - **The suppression** (`reason=unsubscribed`, the campaign's list, `source=unsubscribe_page`)
    is written in the same transaction (amendment 1) when records wrote. It is also written when
    the subscriber is gone, trashed or already unsubscribed, or when the type stopped being a
    list (`SubscriberFilterError`). It is never written for one who re-confirmed after the
    cutoff, or one who is `pending`.
  - **The count.** `unsubscribe_count` is bumped only when records wrote (amendment 8).
  - **No CSRF, on purpose.** The one-click POST comes from the mailbox provider with no session.
    The signed path token is the capability, and a cross-site forger cannot mint one.
  - **Rate limits.** `register_rate_limits` sets 60/min per IP on GET and 300/min per IP on POST.
    The POST is generous because one-click posts arrive from the providers' shared egress IPs,
    and a refused one loses an opt-out.
  - Cost if wrong: the POST limit is too loose for an attacker. A forged token costs one HMAC
    and no query.
- **S10. One token per send.**
  - Format: `{tenant}.{campaign_id}.{send_id}.{mac}`, where `mac` is the base64url of
    HMAC-SHA256(secret, `"newsletter|send|{tenant}|{campaign}|{send}"`) truncated to 16 bytes
    (128 bits, spec). It is split from the right, because a tenant may contain dots.
  - PR 5 reuses the same token for `/o/` and `/c/`.
  - The secret: in the web process it is `app.state.sm.settings.secret_key`; in a worker,
    `core/secret.py`.
  - Tokens are minted at send time and never stored (spec).
- **S11. What "the four-case worker secret test" means.**
  - The spec's resolver (§Sending, "Secrets in workers"; the ai precedent) takes the *secret
    key* from explicit `SM_SECRET_KEY` (env or the `.env` that `BootstrapSettings` locates),
    else the stored `host.secret_key` settings row, else it refuses.
  - The four cases are those sources:
    1. env and row both present: env wins;
    2. env only: env;
    3. row only: the row;
    4. neither: refuse.
  - Each is asserted by decrypting an `enc:v1:` SMTP password encrypted under the expected
    secret, and by verifying a minted token.
  - A fifth case covers the brief's "never send plaintext": a secret that does not match the
    stored password gives `SmtpPasswordUnreadable`, and the tick is refused before any attempt
    row or connection.
  - The brief's wording, "row" as the password row, does not match the spec. This reading
    follows the spec. Cost if wrong: one more test.
- **S12. A configuration failure refuses the whole tick.**
  - The failures are: no secret, an unreadable password, and `NewsletterSettings` unreadable.
  - Freeze is skipped too. The failure is logged at ERROR, naming the exception class and never
    a value. Campaigns stay as they are.
  - A relay **auth** failure when the tick opens its session pauses every `sending` campaign
    (each in its own tenant scope) with `smtp_auth` (spec: "So does an auth failure").
  - A connect or TLS failure only ends the tick.
  - Cost if wrong: a misconfigured worker is visible only in logs until PR 5's report.
    `docs/operations.md` says so.
- **S13. The paused reason is stored as `"<code>|<detail>"`** in `paused_reason`.
  - The codes are `manual`, `smtp_rejected`, `smtp_auth` and `list_unavailable`. The detail is
    the relay's code and text, clipped to fit 1000.
  - The API splits it into `paused_code` / `paused_detail`. The UI translates the code and shows
    the detail verbatim.
- **S14. The status machine.** Every transition is one conditional Core `UPDATE` pinned to `id`,
  `tenant_id` and the allowed *from* statuses, with `revision = revision + 1`:

  | Action (permission) | From | To | Also |
  |---|---|---|---|
  | send / schedule (`send`) | `draft` (and `expected_revision`) | `scheduled` | render snapshot; `scheduled_at` |
  | unschedule (`send`) | `scheduled` (and `expected_revision`) | `draft` | snapshot deleted; `scheduled_at = NULL` |
  | freeze (worker) | `scheduled` | `sending` | `started_at`, `recipient_count`, `suppressed_count` |
  | freeze, list gone (worker) | `scheduled` | `paused` (`list_unavailable`) | `started_at` stays `NULL` |
  | pause (`send`) / auto-pause | `sending` | `paused` | reason |
  | resume (`send`) | `paused` | `sending` if `started_at` is set, else `scheduled` with `scheduled_at = now` | reason cleared |
  | cancel (`send`) | `scheduled`, `sending`, `paused` | `cancelled` | `finished_at`; remaining `queued` rows → `cancelled` |
  | finish (worker) | `sending` with no `queued`/`sending` rows | `sent` | `finished_at` |

  - Zero rows updated: re-read the campaign.
    - Missing or unreadable: 404.
    - Revision mismatch on send/unschedule: 409 `stale`.
    - Send when it is not a draft: 409 `not_a_draft`.
    - Anything else: 409 `invalid_transition` (new).
  - Rows already `sending` when a cancel lands are finished by the dispatcher. Before each
    recipient it re-reads the campaign status, so nothing after the cancel is sent.
- **S15. `CampaignSent` is deferred.** No consumer exists, and a worker has no `EventBus`. Cost:
  add it with its first consumer.
- **S16. The estimate.**
  - `rate = min(daily_limit, per_minute_limit × 1440)`.
  - The "queue ahead" is the count of `queued` rows of `sending` campaigns started before this
    one, **across tenants**. Like the budget count, it returns only a number, folded into a date
    (the relay is the deployment's).
  - `estimated_finish = start + (ahead + own) / rate days`. `overlaps = ahead > 0`.
  - Cost if wrong: the estimate is approximate, and labelled "about".
- **S17. Progress.**
  - `GET /campaigns/{id}/progress` counts rows by status with one pinned `GROUP BY`.
  - `skipped_unsubscribed` has no denormalised counter.
  - The campaign counters (`sent`, `failed`, `bounced`, `suppressed`, `unsubscribe`) are bumped
    in the same transaction as the row change (spec).
- **S18. Freeze details.**
  - Freeze runs outside the dispatch lock: it spends no budget. It is idempotent
    (`insert_ignore` on `(tenant_id, campaign_id, record_uuid)`), and pages through
    `iter_subscribers` 1000 at a time, one session per page.
  - Suppressed addresses get a row with status `suppressed`, so a re-run is a no-op and the
    count comes from rows.
  - `first_name` is stored on the row (new column) for the worker's merge. `locale` is not
    stored (S9).
  - A campaign cancelled or unscheduled while it is being frozen is handled by the freeze
    fence (A1, A2: one owner per campaign and generation, checked inside every page's
    transaction).
    - The cancel or unschedule bumps the generation and cleans up the rows itself: `cancelled`
      or deleted.
    - The old freezer's next page and its final `scheduled → sending` match nothing, so it
      writes nothing.
- **S19. Send-now validation**, in this order:
  1. `require_campaign` (404);
  2. draft and revision (409);
  3. `check_list` (422/403);
  4. `audience_filters` (422);
  5. `check_sender` (422 `sender_not_configured`, moved from `test_send.py` to
     `campaigns/checks.py`);
  6. header checks (422 `invalid_campaign`);
  7. a blank subject is 422 `invalid_campaign` (`subject: required`);
  8. no blocks is 422 `empty_campaign` (new);
  9. the `relative_urls` warning is 422 `public_base_url_required`;
  10. `scheduled_at` must be aware and within `[now − 60 s, now + 366 days]`, else 422
      `invalid_campaign` (`scheduled_at: out of range`);
  11. A6: on the `smtp` transport, both bases must be `https://`, else 422 `https_required`;
  12. A7: the subject and preheader hold no capability merge field (`{{unsubscribe_url}}`),
      else 422 `invalid_campaign`.
- **S20. Postgres test database.** `create_all` does not add columns to an existing schema.
  After Task 1, recreate `smpy_newsletter_test` (drop and create; only `smpy_newsletter_*`
  names, PR 3 C14).

## Global Constraints

- **Before every run.** Run `~/.claude/bin/wait-for-headroom` before **every** pytest, vitest,
  tsc or alembic run. If it exits 1, stop and report.
- **Targeted tests only.** Run the files the task names. Never a full suite (`/ship` runs them
  once at the end of the stack). Use `-n 8` at most (`PYTEST_WORKERS=8`).
- **Shell.** Use `/usr/bin/ps`, never `ps` (it is aliased to `pnpm start`). One plain command
  per Bash call, with literal paths.
- **Formatting.** Never run a repo-wide `ruff format`; format only the files you touched
  (`uv run ruff format <files>`).
- **Secrets.**
  - Commit no secrets.
  - Never log, return or echo the SMTP password (stored or decrypted), the host secret key, an
    SMTP AUTH exchange, or a full send token.
  - A log line may name a send id, never its token.
- **300-line cap** on every `.py`/`.ts`/`.tsx` (`scripts/check_file_size.py`). At 280+ lines,
  split by responsibility.
- **Layout.** Follow `docs/module-layout.md`:
  - the domain areas are `campaigns/` and `sending/`;
  - shared building blocks go in `core/`;
  - HTTP goes in `web/endpoints|schemas|services`;
  - tests mirror the areas.
- **Pages rule.** Only real Inertia pages go under `sm_newsletter/pages/`. This PR adds none.
- **Locales.**
  - Every new key goes into `en.json` **and** `de.json` in the same commit
    (`uv run python scripts/check_locales.py`).
  - Every new error code gets `errors.<code>`.
  - UI strings use `t(keys.newsletter.…)` with no `defaultValue`.
- **Admin routers.** `Depends(bind_admin)` comes **first**, then `RequiresPermission(PERM_*)`.
  The API is wrapped in `RequiresCsrf()` by `module.py`.
- **Public routes.** They are exempted in `register_public_routes`, carry no `RequiresCsrf`, and
  their tenant comes from the token (S8).
- **Contracts.** Lists, subscribers and unsubscribe go **only** through
  `sm_records.contracts.newsletter`. Records' settings are read from
  `app.state.sm_records.settings` (what the contract's `settings=` argument takes). Never import
  records' tables or services.
- **Tenancy.**
  - Every Core statement over a newsletter table pins `tenant_id`.
  - The deliberate cross-tenant reads return numbers or `(tenant_id, id)` pairs only, under the
    framework's `all_tenants()` plus `tenancy.all_tenants(stmt)`. They are: the budget count, the
    queue-ahead count, the due/sending/expired campaign enumerations, and the auth-failure pause
    enumeration.
  - Per-tenant work runs in `tenant_scope(tenant)` with a fresh session per tenant.
- **Settings.** Newsletter reads no environment variables. Settings are DB-backed;
  `settings_for(NewsletterSettings, constants.PACKAGE)` in the worker. The only environment
  read is the secret key, through `BootstrapSettings` / the process env (`core/secret.py`, as
  `core/crypto.py` already does).
- **Commits outside a request** finish with `simple_module_db.finalize_session(session)`, never
  a bare `commit()`.
- **Migrations.** Exactly one new revision in `host/migrations/versions/`, off the single head
  at execution time (`0fa7184b108f` when this was written; re-check with
  `uv run python scripts/check_migration_heads.py`). No branch label. `alembic check` passes on
  SQLite and Postgres.
- **Python tests.** `uv run --directory modules/newsletter pytest <paths> -q -p no:cacheprovider`.
  - **Postgres:** prefix
    `SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_test`.
  - Tests marked SQLite-only (`sync_db` file databases) skip there.
- **JS.** `npx vitest run <paths>` and `npx tsc --noEmit -p modules/newsletter/tsconfig.json`.

## Review Focus

1. **A worker killed between the relay's 250 and the commit.** The row is `sending` and its
   attempt is `pending`. Expected: the next tick, once the lease has expired, marks the row
   `failed/outcome_unknown` and the attempt `unknown`. Nothing is sent to that address again,
   and the attempt still counts against the cap. Pinned in Task 7,
   `test_crash_between_accept_and_commit_never_resends`.
2. **A quota or policy refusal mid-campaign** (`554 5.4.5`, `550 5.7.1`, `421 4.7.0`).
   Expected:
   - for the 5xx, the campaign is paused with the relay's text, the row stays `queued`, nobody
     is suppressed, and nothing else is sent in this tick;
   - for the 4xx, the row is retried later and the tick stops.
   Pinned in Task 2 (`test_classify`) and Task 7 (`test_pause_class_pauses_and_stops`,
   `test_relay_quota_reply_stops_tick`).
3. **An old campaign's unsubscribe link clicked after the person signed up and confirmed again.**
   Expected: still subscribed, no suppression, `unsubscribe_count` unchanged, and the same page
   as any other click. Pinned in Task 10, `test_old_link_after_resignup_changes_nothing`.
4. **The daily cap shared by two tenants' campaigns and test sends, across a day boundary.**
   Expected: never more than `daily_limit` counted attempts in any rolling 24 h. The
   oldest-started campaign goes first, and the rest continue the next day. Pinned in Task 7:
   - `test_daily_cap_rollover_two_days`
   - `test_test_sends_share_the_budget`
   - `test_oldest_started_first_across_tenants`
   - `test_concurrent_ticks_never_exceed_cap`
5. **Pause or cancel pressed while a tick is mid-slice, then resume.** Expected:
   - no recipient after the change gets mail;
   - cancelled rows end `cancelled`;
   - resume continues with the remaining rows, and no address is mailed twice.
   Pinned in Task 7, `test_cancel_mid_tick` and `test_pause_resume_continues_without_duplicates`.

---

### Task 1: Models, constants and the migration

**Files:**
- Create: `modules/newsletter/sm_newsletter/models/render.py`
- Modify:
  - `modules/newsletter/sm_newsletter/models/__init__.py` (export `CampaignRender`)
  - `modules/newsletter/sm_newsletter/models/send.py`
  - `modules/newsletter/sm_newsletter/core/constants.py`
- Create: `host/migrations/versions/<rev>_newsletter_sending.py`
- Test: `modules/newsletter/tests/core/test_models.py`

**Interfaces (Produces):**
```python
class CampaignRender(Base, MultiTenantMixin, table=True):   # "newsletter_campaign_render"
    campaign_id: int      # PK, FK newsletter_campaign.id ON DELETE CASCADE
    subject: str          # max 300, merge tags in place
    html: str             # sa Text, NOT NULL
    text: str             # sa Text, NOT NULL
    sender: str           # max 600, formatted "Name <addr>"
    reply_to: str | None  # max MAX_EMAIL_LEN
    public_base: str      # max 2048, no trailing slash
    locale: str           # max 16
    rendered_at: datetime # dt_col(nullable=False)
# Send gains:
first_name: str | None = Field(default=None, max_length=200)
retry_at: datetime | None = dt_col()   # a queued row is not due before it
freeze_gen: int = Field(default=0, sa_column_kwargs={"nullable": False, "server_default": "0"})  # A1
# Campaign gains (A1, A2):
freeze_gen: int = Field(default=0, sa_column_kwargs={"nullable": False, "server_default": "0"})
freeze_owner: str | None = Field(default=None, max_length=64)
freeze_until: datetime | None = dt_col()
# core/constants.py gains:
UNSUBSCRIBE_PREFIX = f"{PUBLIC_PREFIX}u/"
PAUSE_MANUAL, PAUSE_SMTP_REJECTED, PAUSE_SMTP_AUTH, PAUSE_LIST_UNAVAILABLE = (
    "manual", "smtp_rejected", "smtp_auth", "list_unavailable")
PAUSE_CODES = (PAUSE_MANUAL, PAUSE_SMTP_REJECTED, PAUSE_SMTP_AUTH, PAUSE_LIST_UNAVAILABLE)
ERROR_OUTCOME_UNKNOWN, ERROR_RETRIES_EXHAUSTED, ERROR_INVALID_MESSAGE, ERROR_HARD_BOUNCE = (
    "outcome_unknown", "retries_exhausted", "invalid_message", "hard_bounce")
SOURCE_SEND, SOURCE_UNSUBSCRIBE_PAGE = "send", "unsubscribe_page"   # both already in SOURCES
```

- [ ] **Step 1: Failing tests** in `tests/core/test_models.py`.
  - Add `newsletter_campaign_render` to the expected table set.
  - `test_render_row_is_tenant_owned_and_cascades`: delete a campaign and its render row goes
    too, on SQLite with foreign keys on and on Postgres.
  - `test_send_has_first_name_and_retry_at`: both are nullable.
  - `test_freeze_columns`: `newsletter_send.freeze_gen` and `newsletter_campaign.freeze_gen`
    are `NOT NULL DEFAULT 0`; `freeze_owner` and `freeze_until` are nullable (A1, A2).
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/core/test_models.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement the models and constants.** The model docstring says why the render
  is stored: the worker never builds the app (S1).
- [ ] **Step 4: Generate the revision** against a scratch SQLite database, never `host/app.db`.
  1. From the root, with `SM_DATABASE_URL=sqlite+aiosqlite:////tmp/newsletter-pr4-mig.db`, run
     `uv run --project host alembic -c host/alembic.ini upgrade heads`.
  2. Run `… revision --autogenerate -m "newsletter sending"`.
  3. Check the file. It must:
     - create `newsletter_campaign_render`;
     - add `newsletter_send.first_name`, `newsletter_send.retry_at` and
       `newsletter_send.freeze_gen`, and `newsletter_campaign.freeze_gen`, `freeze_owner` and
       `freeze_until` (through `batch_alter_table`, as `0fa7184b108f` does, with
       `server_default="0"` on both `freeze_gen` columns);
     - have no branch label;
     - have `down_revision` = the prior single head.
  4. Delete unrelated drift and report it. Write a docstring like `0fa7184b108f`'s.
  5. Run `upgrade heads`, then `check` (expected: "No new upgrade operations detected"), then
     `downgrade <parent>`, `upgrade heads` and `check` again. Delete the scratch file.
- [ ] **Step 5: Postgres.** Use dev-services' Postgres.
  1. Create the scratch database: `PGPASSWORD=postgres createdb -h localhost -U postgres smpy_newsletter_check`.
  2. With `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_check`,
     run `upgrade heads`, `check`, `downgrade <parent>`, `upgrade heads` and `check`.
  3. Drop the database. Recreate `smpy_newsletter_test` (S20).
- [ ] **Step 6: Run** `uv run python scripts/check_migration_heads.py` (one head, the new one).
  Then run the Step 2 test on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 7: Commit** `feat(newsletter): render snapshot table, send retry and freeze-fence columns`.

### Task 2: Transport stage and the verdict classifier

**Files:**
- Modify:
  - `sm_newsletter/sending/transport/base.py`
  - `sm_newsletter/sending/transport/smtp.py`
  - `sm_newsletter/sending/transport/console.py`
  - `sm_newsletter/sending/transport/message.py` (`OutgoingMessage.ref`, A7)
  - `sm_newsletter/campaigns/test_send.py` (sets `ref`)
  - `sm_newsletter/core/errors.py` (`TransportUnavailable.stage`)
- Create: `sm_newsletter/sending/classify.py`
- Test:
  - `tests/sending/test_smtp.py`
  - `tests/sending/test_console.py`
  - `tests/sending/test_classify.py` (new)

**Interfaces (Produces):**
```python
# transport/base.py
Stage = Literal["connect", "tls", "auth", "mail", "rcpt", "data"]
@dataclass(frozen=True)
class DeliveryResult: outcome: Outcome; code: int | None; detail: str; stage: Stage | None = None
# transport/message.py (A7)
@dataclass(frozen=True)
class OutgoingMessage: ...  # existing fields, plus:
    ref: str = ""   # "campaign=<id> send=<id>" or "test campaign=<id>"; for logs only, never a header
# transport/smtp.py (A4)
SmtpConfig.timeout = 20        # per SMTP command (was 30)
SmtpConfig.send_deadline = 45  # one recipient in total, a lazy reconnect included
# core/errors.py
class TransportUnavailable(NewsletterError):
    stage: str | None = None
    def __init__(self, detail: str | None = None, *, stage: str | None = None) -> None
# sending/classify.py
Action = Literal["sent", "retry", "bounce", "pause", "fail", "unknown", "skip"]
@dataclass(frozen=True)
class Verdict:
    action: Action
    stop_tick: bool
    error_kind: str | None = None     # constants.ERROR_*
    pause_code: str | None = None     # constants.PAUSE_*
def enhanced_code(detail: str) -> tuple[int, int, int] | None   # a leading "X.Y.Z"
def classify(result: DeliveryResult) -> Verdict                  # the S4 table, exactly
```
`skip` is never returned by `classify`. The dispatcher uses it for a row it skipped without an
SMTP call (Task 6).

- [ ] **Step 1: Failing tests.**
  - `test_classify` is parametrized over the S4 table, at least these cases:
    - `accepted 250`;
    - `unknown`;
    - `failed` with stage `connect`, and `failed` with stage `auth`;
    - `rejected None`;
    - `451 "4.3.0 Try again"` at `data`: retry, does not stop;
    - `421 "4.7.0 Try again later"`: retry, stops;
    - `450 "4.2.1 …"` at `rcpt`: retry, does not stop;
    - `550 "5.1.1 No such user"` at `rcpt`: bounce, `error_kind=hard_bounce`;
    - `553 "5.1.3 …"` at `rcpt`: bounce;
    - `550 "5.1.1 …"` at `mail`: pause `smtp_rejected`;
    - `550 "5.7.1 relay denied"` at `rcpt`: pause;
    - `554 "5.4.5 Daily sending quota exceeded"` at `data`: pause;
    - `550 "No such user"` (no enhanced code) at `rcpt`: pause.
  - `test_enhanced_code`:
    - `" 5.1.1 x"` → `(5, 1, 1)`;
    - `"5.1"` → `None`;
    - `""` → `None`;
    - `"5.1.1000"` → `None` (each part is 1–3 digits).
  - `test_smtp`:
    - `bounce@` gives `rejected`, 550, stage `rcpt`;
    - `soft@` gives `rejected`, 451, stage `data`;
    - a wrong-password transport raises `TransportUnavailable` with `.stage == "auth"`;
    - `test_reconnect_auth_failure_reports_stage`: drop via `droprcpt@`, then set
      `transport._config` to a wrong password; the next send is `failed` with stage `auth`;
    - the connect stage on a closed port is `.stage == "connect"`.
  - `test_console_bad_header_rejected`: a `to` with `\r\n` returns `rejected`/`None` and is
    neither raised nor captured.
  - `test_console_logs_ref_and_domain_only` (A7). It replaces the existing assertion that the
    INFO line holds `to` and `subject`. The line holds `msg.ref` and the recipient's domain
    (`example.org`), and never the local part, the subject or any URL.
  - `test_send_deadline_bounds_one_recipient` (A4): `send_deadline=0.3` and a `timeout` of 0.2
    with the relay stalling at RCPT and then after DATA (`STALL` 0.6). The result is `failed`
    before the body and `unknown` after it, each within 0.5 s.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/sending/test_classify.py tests/sending/test_smtp.py tests/sending/test_console.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `_SmtpSession.send` keeps a local `stage`: `"mail"` before `client.mail`, `"rcpt"` before
    `rcpt`, `"data"` from the `DATA` command on. Every `DeliveryResult` it builds passes it. The
    non-ASCII and header-error results keep `stage=None`.
  - `connect`, `_upgrade` and `_login` raise `TransportUnavailable(..., stage=...)`.
  - A4: the whole of `_SmtpSession.send` (the lazy reconnect, MAIL, RCPT, DATA, the body and
    the final reply) runs under `asyncio.timeout(config.send_deadline)`. `TimeoutError` is
    already in `_LOST`, so it maps to `failed` before the body and `unknown` after it. These
    are the numbers the SQLite lease (120 s) relies on: a recipient takes at most 45 s, which
    leaves 75 s of margin. Write that in the module docstring.
  - A7: the console transport logs
    `"Newsletter console transport: %s to domain %s", msg.ref, domain`, never `to` or `subject`.
    `send_test` sets `ref=f"test campaign={campaign_id}"`.
  - `smtp.py` stays under 280 lines.
- [ ] **Step 4: Run** the Step 2 command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): transport reports the SMTP stage; verdict classifier`.

### Task 3: Send tokens and the worker secret

**Files:**
- Create:
  - `sm_newsletter/core/tokens.py`
  - `sm_newsletter/core/secret.py`
- Test:
  - `tests/core/test_tokens.py`
  - `tests/core/test_worker_secret.py` (SQLite-only: `sync_db` file database, as `test_worker.py`)

**Interfaces (Produces):**
```python
# core/tokens.py
MAX_TOKEN = 200
@dataclass(frozen=True)
class SendToken: tenant_id: str; campaign_id: int; send_id: int
def sign(secret: str, *, tenant_id: str, campaign_id: int, send_id: int) -> str   # ValueError on "" secret / bad tenant
def parse(secret: str, token: str) -> SendToken | None   # never raises; hmac.compare_digest
def unsubscribe_url(public_base: str, token: str) -> str  # f"{public_base.rstrip('/')}{UNSUBSCRIBE_PREFIX}{token}"
def host_secret(app) -> str   # app.state.sm.settings.secret_key or "" (callers treat "" as "cannot verify")
# core/secret.py
class SecretMissing(RuntimeError): ...
def resolve_worker_secret() -> str
def install(secret: str) -> None  # crypto.set_secret_provider(lambda: secret) only if crypto._secret_provider is None
```
**Resolution order** (S11), in `resolve_worker_secret`:
1. `os.environ["SM_SECRET_KEY"]`;
2. else `crypto._dotenv_secret()` (the `BootstrapSettings` `.env`, explicit only);
3. else the `host.secret_key` value from
   `simple_module_db.stored_settings.get_overrides_sync(session, "host")` through
   `background_tasks.sync_db.sync_session()`;
4. else `SecretMissing`.

A failure to read the database (no table, unreachable) counts as "no row". The error message
names the exception class only.

- [ ] **Step 1: Failing tests.**
  - `test_tokens.py`:
    - round trip;
    - a tenant with dots (`"org.a"`) round-trips;
    - tampering with each of the four parts → `None`;
    - `"test"` → `None`;
    - a 201-character token → `None`;
    - non-ASCII → `None`;
    - another secret → `None`;
    - `""` secret: `sign` raises and `parse` → `None`;
    - the MAC part decodes to exactly 16 bytes;
    - the URL contains no `@`.
  - `test_worker_secret.py`. Fixture: a SQLite file database with the settings table,
    `sync_db.set_database_url`. Each test sets `SM_PROJECT_ROOT` to an empty `tmp_path`, deletes
    `SM_SECRET_KEY`, calls `crypto._dotenv_secret.cache_clear()`, and resets
    `crypto._secret_provider` to `None`.
    - `test_env_and_stored_row_env_wins`: env `"env-secret"`, row `host.secret_key="row-secret"`.
      Resolves to `"env-secret"`. After `install`, `crypto.decrypt_value(enc_under("env-secret"),
      "smtp_password")` gives the plaintext. A token signed with the result parses under
      `"env-secret"`.
    - `test_env_only`.
    - `test_stored_row_only`: resolves to the row's value, and decrypts a password encrypted
      under it.
    - `test_neither_refuses`: `SecretMissing`, and the message holds no secret-looking text.
    - `test_wrong_secret_never_yields_plaintext`: password encrypted under `"other"`, env
      `"env-secret"`. `decrypt_value` raises `SmtpPasswordUnreadable` and returns nothing.
    - `test_install_keeps_an_app_provider`: with a provider set, `install` does not replace it.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/core/test_tokens.py tests/core/test_worker_secret.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Tokens are modelled on `sm_records.public_submissions.links`. Keep
  both files under 150 lines.
- [ ] **Step 4: Run** the Step 2 command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): signed send tokens and the worker secret resolver`.

### Task 4: Campaign lifecycle and the render snapshot

**Files:**
- Create:
  - `sm_newsletter/campaigns/lifecycle.py`
  - `sm_newsletter/campaigns/snapshot.py`
  - `sm_newsletter/campaigns/audience.py`
  - `sm_newsletter/campaigns/checks.py`
- Modify:
  - `sm_newsletter/campaigns/test_send.py`: move `_check_sender` and `_check_headers` into
    `checks.py` (moves only; same behaviour).
  - `sm_newsletter/campaigns/drafts.py`: use `audience_filters`.
  - `sm_newsletter/content/merge.py`: `CAPABILITY_TAGS`, `check_no_capability` (A7).
  - `sm_newsletter/web/schemas/campaigns.py`: `Subject` and `Preheader` run
    `check_no_capability` (A7).
  - `sm_newsletter/core/errors.py`: `InvalidTransition`, `EmptyCampaign`, `HttpsRequired` (A6); the
    `AudienceUnsupported` detail becomes "Only the whole list can be the audience until segments
    arrive".
- Create: `tests/support/campaign_world.py`
- Test:
  - `tests/campaigns/test_lifecycle.py`
  - `tests/campaigns/test_snapshot.py`
  - `tests/content/test_merge.py`, `tests/web/test_campaigns_api.py` (A7)
  - existing: `tests/campaigns/test_test_send.py`, `tests/campaigns/test_drafts.py`

**Interfaces (Produces):**
```python
# core/errors.py
class InvalidTransition(NewsletterError): status = 409; code = "invalid_transition"
class EmptyCampaign(NewsletterError):     status = 422; code = "empty_campaign"
class HttpsRequired(NewsletterError):     status = 422; code = "https_required"   # A6
# content/merge.py (A7)
CAPABILITY_TAGS = (UNSUBSCRIBE_TAG,)   # merge fields whose value carries a send token; PR 5 adds its own
def check_no_capability(text: str, *, field: str) -> str   # ValueError naming the field, never the value
# campaigns/audience.py
def audience_filters(audience: str) -> list[str]        # "all" -> []; else AudienceUnsupported
# campaigns/checks.py
def check_sender(settings: NewsletterSettings) -> None    # was test_send._check_sender
def check_campaign_headers(campaign: Campaign) -> None    # was test_send._check_headers
# campaigns/snapshot.py
async def snapshot_render(app, session, *, tenant_id: str, campaign: Campaign, now: datetime) -> CampaignRender
async def drop_render(session, *, tenant_id: str, campaign_id: int) -> None
# campaigns/lifecycle.py
async def transition(session, *, tenant_id: str, campaign_id: int, from_statuses: tuple[str, ...],
                     values: dict[str, Any], expected_revision: int | None = None) -> bool
async def schedule(app, session, *, tenant_id, campaign_id, roles, expected_revision: int,
                   scheduled_at: datetime | None, now: datetime) -> Campaign
async def unschedule(session, *, tenant_id, campaign_id, roles, expected_revision: int) -> Campaign
async def pause(session, *, tenant_id, campaign_id, roles, now: datetime) -> Campaign
async def resume(session, *, tenant_id, campaign_id, roles, now: datetime) -> Campaign
async def cancel(session, *, tenant_id, campaign_id, roles, now: datetime) -> Campaign
def paused_reason(code: str, detail: str = "") -> str   # "code|detail"[:1000]; code in PAUSE_CODES
def split_paused(reason: str | None) -> tuple[str | None, str | None]
```
- **`transition`.** One Core `UPDATE` with `revision = revision + 1`, pinned to `id`,
  `tenant_id`, `status IN from_statuses` (and `revision` when given). Returns whether one row
  changed. It does not commit.
- **Public functions.** Each reads with `require_campaign` (C4), validates per S19, and calls
  `transition`. On `False` it re-reads and raises per S14. It returns the campaign re-read with
  `populate_existing`. The caller commits.
- **`cancel`** also runs one Core `UPDATE newsletter_send SET status='cancelled' WHERE
  tenant_id=:t AND campaign_id=:c AND status='queued'`.
- **The freeze fence (A1).** `schedule`, `unschedule` and `cancel`-from-`scheduled` each set
  `freeze_gen = freeze_gen + 1`, `freeze_owner = NULL` and `freeze_until = NULL` in their
  conditional `UPDATE`.
  - `unschedule` also runs `DELETE FROM newsletter_send WHERE tenant_id=:t AND campaign_id=:c`
    in the same transaction, after the conditional `UPDATE` (nothing of a never-started
    campaign was sent).
  - Because the `UPDATE` comes first, it waits on a freezer's page transaction (a row lock on
    Postgres, the single writer on SQLite). So it deletes every row that page wrote, and every
    later page of the old generation fails its fence (Task 5).
- **`schedule` adds two checks**, both before the snapshot is written:
  - **A6:** with `settings.transport == "smtp"`, both `ctx.content_base` and `ctx.public_base`
    must start with `https://`, else 422 `https_required`. The console transport allows
    `http://`.
  - **A7:** the stored subject and preheader are re-checked with `check_no_capability`, else 422
    `invalid_campaign` (`subject: merge field not allowed here`), for rows written around the
    API.
- **`snapshot_render`** renders as `test_send._message` does, but without the `[TEST]` prefix
  and keeping the merge tags.
  - `sender = formataddr((campaign.from_name or settings.from_name, settings.from_address.strip()))`.
  - It replaces any existing row.

- [ ] **Step 1: Failing tests.** `tests/support/campaign_world.py` provides:
  - `seed_campaign(state, tenant, *, status="draft", body=BODY, subject="Hello", list_key="news", started_at=None, scheduled_at=None) -> int`;
  - `seed_render(state, tenant, campaign_id, *, public_base=BASE_URL) -> None`;
  - `send_rows(state, tenant, campaign_id) -> list[Send]`.

  `test_lifecycle.py` (SQLite and Postgres):
  - `test_schedule_now_snapshots_and_schedules`:
    - status `scheduled`, revision +1, `scheduled_at == now`;
    - the render row's `html` holds `{{unsubscribe_url}}` (still a tag);
    - `sender == "News <news@example.org>"`;
    - `public_base == BASE_URL`.
  - `test_schedule_later_keeps_the_time`.
  - `test_schedule_stale_409_and_no_snapshot`.
  - `test_schedule_not_a_draft_409`.
  - `test_schedule_refusals`, parametrized:
    - blank `from_address` → `sender_not_configured`;
    - blank `physical_address` → `sender_not_configured`;
    - empty body → `empty_campaign`;
    - blank subject → `invalid_campaign`;
    - no `public_base_url` → `public_base_url_required`;
    - `scheduled_at` 2 min in the past → `invalid_campaign`;
    - 400 days ahead → `invalid_campaign`;
    - audience `tag:x` → `audience_unsupported`;
    - transport `smtp` with `public_base_url="http://news.example.org"` → `https_required` (A6);
    - transport `smtp` with an `http` tenant content origin and an `https` `public_base_url` →
      `https_required` (A6);
    - a stored subject `"Hi {{unsubscribe_url}}"` → `invalid_campaign` (A7).

    Each leaves status `draft`, `revision` unchanged and no render row.
  - `test_console_transport_allows_http_base` (A6).
  - `test_schedule_and_unschedule_bump_freeze_gen` (A1): `unschedule` deletes every send row of
    the campaign.
  - `test_schedule_restricted_list_is_404` (roles, C4).
  - `test_unschedule_back_to_draft_drops_snapshot`.
  - `test_action_matrix`: every one of the 6 statuses × {pause, resume, cancel} is either the
    S14 transition or 409 `invalid_transition`, and the status is unchanged on refusal.
  - `test_resume_before_freeze_goes_back_to_scheduled`.
  - `test_cancel_marks_only_queued_rows`: rows `queued`, `sending` and `sent` become
    `cancelled`, `sending` and `sent`.
  - `test_two_concurrent_cancels_one_wins`: `asyncio.gather` on a file/PG database gives exactly
    one success and one 409.
  - `test_transition_pins_the_tenant`: tenant B's campaign id used under tenant A is 404, and B
    is unchanged.
  - `test_paused_reason_round_trip`: `split_paused(paused_reason("smtp_rejected", "554 5.4.5 x"))`;
    a 2000-character detail is clipped to 1000 in total; an unknown code raises `ValueError`.

  A7 schema tests:
  - `tests/content/test_merge.py::test_check_no_capability`: `{{unsubscribe_url}}` → ValueError;
    `{{first_name|x}}` passes; the message names the field and not the value.
  - `tests/web/test_campaigns_api.py::test_patch_subject_with_unsubscribe_tag_422`, and the
    same for the preheader: 422 `invalid_campaign`, and the detail does not echo the value.

  `test_snapshot.py`:
  - `test_snapshot_replaces_previous`;
  - `test_snapshot_uses_campaign_from_name_and_reply_to`;
  - `test_snapshot_rejects_header_injection_in_settings` (a `from_name` with a control
    character is refused, 422).

  Existing `test_test_send*.py` and `test_drafts.py` pass unchanged.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/campaigns tests/content/test_merge.py tests/web/test_campaigns_api.py -q -p no:cacheprovider -n 8`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Keep `lifecycle.py` under 250 lines. If it grows, split the
  refusal re-read into `campaigns/_refusal.py`, extending `drafts._refusal` rather than copying it.
- [ ] **Step 4: Run** the Step 2 command, then the same with the Postgres prefix. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): campaign lifecycle (schedule, pause, resume, cancel) and render snapshot`.

### Task 5: Freeze — starting due campaigns

**Files:**
- Create: `sm_newsletter/sending/freeze.py`
- Test: `tests/sending/test_freeze.py`

**Interfaces (Produces):**
```python
PAGE = MAX_SUBSCRIBER_BATCH   # from sm_records.contracts.newsletter (1000)
FREEZE_LEASE = timedelta(minutes=5)
@dataclass(frozen=True)
class FreezeResult: started: bool; queued: int; suppressed: int
@dataclass(frozen=True)
class FreezeClaim: owner: str; gen: int   # owner = f"freeze:{secrets.token_hex(8)}"
async def claim_freeze(session, *, tenant_id: str, campaign_id: int, now: datetime) -> FreezeClaim | None
async def hold_freeze(session, claim: FreezeClaim, *, tenant_id: str, campaign_id: int, now: datetime) -> bool
async def due_campaigns(factory, *, now: datetime) -> list[tuple[str, int]]   # (tenant_id, id); scheduled, scheduled_at <= now; oldest first; cross-tenant, narrow
async def freeze(factory, *, tenant_id: str, campaign_id: int, now: datetime) -> FreezeResult
async def start_due(factory, *, now: datetime) -> int   # campaigns moved to sending; per-campaign failures logged, the rest continue
```
**The fence (A1, A2).** Freeze has exactly one owner per campaign, and it works for one
generation.
- **`claim_freeze`** reads `freeze_gen`, then runs one conditional `UPDATE` setting
  `freeze_owner = <new owner>` and `freeze_until = now + FREEZE_LEASE`, where:
  - `id`, `tenant_id` and `status = 'scheduled'` match;
  - `freeze_gen` is the value read;
  - `freeze_owner IS NULL OR freeze_until < now`.

  It returns the claim, or `None` when another live owner holds it or the generation moved on.
  It does **not** bump `revision`: an editor's view is unaffected.
- **`hold_freeze`** is the same conditional `UPDATE`, matching `freeze_owner = claim.owner` and
  `freeze_gen = claim.gen`, and extending `freeze_until`. It returns whether it matched. It runs
  **first** inside each page's transaction, so the page's inserts commit only if the fence
  held, and a concurrent `unschedule`/`cancel` serialises against it (Task 4).

**`freeze`** (S18). Each step uses its own session under `tenant_scope(tenant_id)`.
1. The campaign must be `scheduled` and have a render row; otherwise it returns
   `started=False` (a missing render is logged as an error). Then `claim_freeze`; `None` →
   `started=False`.
2. If the list is not in `subscription_lists(tenant)`, transition `scheduled → paused` with
   `paused_reason(PAUSE_LIST_UNAVAILABLE)`, conditional on the claim (`freeze_owner`,
   `freeze_gen`), and return.
3. Page through `iter_subscribers(filters=audience_filters(c.audience), limit=PAGE, after=cursor)`.
   - Skip blank emails.
   - Call `suppressed(session, tenant_id=…, emails=…)`.
   - `hold_freeze`. If it fails, roll back the page and return `started=False`: the fence was
     lost and nothing more is written.
   - Insert rows with `insert_ignore(conflict=["tenant_id", "campaign_id", "record_uuid"])`,
     status `queued` or `suppressed`, plus `email`, `first_name`, `tenant_id` and
     `freeze_gen = claim.gen`.
   - Finish each page with `finalize_session`.
4. Count by status the rows with `freeze_gen = claim.gen` (pinned). Then one conditional
   `UPDATE` on `status = 'scheduled'`, `freeze_owner = claim.owner` and `freeze_gen = claim.gen`
   sets:
   - `status = 'sending'`, `started_at = now`;
   - `recipient_count = queued`, `suppressed_count = suppressed`;
   - `freeze_owner = NULL`, `freeze_until = NULL`;
   - `revision = revision + 1`.

   If no row changed, the claim was lost (unschedule, cancel or takeover), and that path already
   cleaned up its rows. Return `started=False` and write nothing.

A crashed freezer's rows stay, stamped with the current generation. After `FREEZE_LEASE` the
next tick claims the campaign again and continues idempotently.

**Unbound.** `start_due` must be called with no tenant bound. It binds one per campaign, so a
bound caller gets `TenantIsolationError` from `tenant_scope`.

- [ ] **Step 1: Failing tests** (SQLite and Postgres). Seed with `records_seed.seed_subscriber`
  and `campaign_world.seed_campaign` plus `seed_render`, `status="scheduled"`.
  - `test_freeze_queues_confirmed_only`: `pending` and `unsubscribed` subscribers get no row.
    Confirmed ones are `queued` with `first_name` copied.
  - `test_freeze_marks_suppressed_rows`: a `hard_bounce` suppression gives the row
    `suppressed`. `suppressed_count == 1` and `recipient_count` counts the queued rows only.
  - `test_freeze_is_idempotent`: freeze, put the status back to `scheduled`, freeze again. One
    row per record.
  - `test_freeze_pages`: `PAGE` monkeypatched to 2 with 5 subscribers gives 5 rows.
  - `test_start_due_only_due_and_scheduled`: a future `scheduled_at` and a draft are untouched.
  - `test_freeze_list_gone_pauses`: the list type is no longer a list. The result is `paused`,
    `paused_reason` starts with `list_unavailable|`, and `started_at` is `None`.
  - `test_cancel_during_freeze_leaves_no_queued_rows`: `iter_subscribers` is wrapped to call
    `lifecycle.cancel` in another session after page 1. The final status is `cancelled` and there
    are no `queued` rows.
  - `test_interrupted_freeze_then_unschedule_reschedule_uses_new_list` (A1):
    - freeze list `news` with `PAGE=2`, and raise after page 1 (a crash);
    - `unschedule`, move the campaign to list `other`, `schedule` again;
    - the next `start_due` makes rows only for `other`'s subscribers, all with the new
      `freeze_gen`.
  - `test_stale_freezer_after_reschedule_writes_nothing` (A1):
    - freezer 1 is paused inside page 2's read (an `asyncio.Event` in a wrapped
      `iter_subscribers`);
    - meanwhile `unschedule` and `schedule` run, and freezer 2 completes;
    - freezer 1 resumes: its `hold_freeze` fails, it inserts nothing, and the campaign's rows and
      counts are exactly freezer 2's.
  - `test_overlapping_freezes_one_owner` (A2):
    - two `freeze` calls race (`asyncio.gather`, a file/PG database), with a signup committed
      between their first page reads;
    - exactly one gets the claim and publishes;
    - the other returns `started=False` with no rows written;
    - `recipient_count` equals the rows present.
  - `test_expired_freeze_lease_is_taken_over` (A2): a claim with `freeze_until < now` and no
    progress. A new `freeze` claims it and finishes, and the old owner's `hold_freeze` then
    returns `False`.
  - `test_start_due_per_tenant`: tenants A and B each have a due campaign and a subscriber. Each
    campaign's rows hold only its own tenant's subscriber, stamped with that tenant.
  - `test_start_due_refuses_a_bound_tenant`: with the autouse `default` bound and a due campaign
    in tenant `other`, `TenantIsolationError` is raised. The unbound case uses
    `@pytest.mark.unbound_tenant`.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/sending/test_freeze.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): fenced freeze of a due campaign's audience into send rows`.

### Task 6: Delivering one recipient

**Files:**
- Create:
  - `sm_newsletter/sending/compose.py`
  - `sm_newsletter/sending/rows.py`
  - `sm_newsletter/sending/deliver.py`
- Modify: `sm_newsletter/sending/lock.py` (`HeldLock.fence`, A4)
- Create: `tests/support/fake_transport.py`
- Test:
  - `tests/sending/test_compose.py`
  - `tests/sending/test_deliver.py`
  - `tests/sending/test_lock.py` (fence)

**Interfaces (Produces):**
```python
# sending/compose.py
def compose(render: CampaignRender, send: Send, *, secret: str, list_unsubscribe: bool) -> OutgoingMessage
    # ValueError when a personalised header is invalid; sets ref=f"campaign={c} send={s}" (A7)
# sending/lock.py (A4)
class HeldLock:
    async def renew(self) -> None                  # unchanged
    async def fence(self, session: AsyncSession) -> None
        # SQLite: in the caller's transaction, UPDATE the lock row SET locked_until = now + lease
        #   WHERE holder = me AND locked_until > now; rowcount 0 -> DispatchBusy (the caller rolls back)
        # Postgres: no-op (the advisory lock is held until released)
# sending/rows.py
LEASE = timedelta(minutes=10)
MAX_ATTEMPTS = 3
BACKOFF = (timedelta(minutes=5), timedelta(minutes=30))
async def next_row(session, *, tenant_id: str, campaign_id: int, now: datetime) -> Send | None
async def claim(session, *, tenant_id: str, send_id: int, now: datetime) -> bool
    # A3: one conditional UPDATE newsletter_send SET status='sending', lease_until=now+LEASE
    #     WHERE id=:id AND tenant_id=:t AND status='queued'
    #       AND EXISTS (SELECT 1 FROM newsletter_campaign c
    #                   WHERE c.id = newsletter_send.campaign_id AND c.tenant_id=:t AND c.status='sending')
    #     -> rowcount == 1
async def record(session, send: Send, verdict: Verdict, result: DeliveryResult, *, now: datetime) -> None
async def skip(session, send: Send, *, status: Literal["suppressed", "skipped_unsubscribed"]) -> None
async def bump(session, *, tenant_id: str, campaign_id: int, **deltas: int) -> None   # col = col + n
# sending/deliver.py
@dataclass(frozen=True)
class Step: spent: bool; verdict: Verdict
async def deliver_one(factory, smtp: TransportSession, lock: HeldLock, *, tenant_id: str, campaign_id: int,
                      secret: str, list_unsubscribe: bool, clock: Callable[[], datetime]) -> Step | None
# tests/support/fake_transport.py
class FakeTransport:   # name="fake", supports_list_unsubscribe=True
    def __init__(self, script: Mapping[str, DeliveryResult | Sequence[DeliveryResult]] | None = None,
                 *, open_error: TransportUnavailable | None = None,
                 on_send: Callable[[OutgoingMessage], Awaitable[None]] | None = None) -> None
    sent: list[OutgoingMessage]; opened: int
```
**`next_row`**: status `queued` and (`retry_at IS NULL` or `retry_at <= now`), lowest `id`,
pinned to tenant and campaign.

**`record`** applies the verdict (S4/S17):

| Verdict | Row | Campaign | Other |
|---|---|---|---|
| `sent` | `sent`, `sent_at`, `attempts + 1` | `sent_count + 1` | |
| `retry` | `attempts + 1`. At ≥ `MAX_ATTEMPTS`: `failed/retries_exhausted`. Else `queued` with `retry_at = now + BACKOFF[attempts − 1]` | `failed_count + 1` (exhausted only) | |
| `unknown` | `failed/outcome_unknown`, `attempts + 1` | `failed_count + 1` | |
| `fail` | `failed` with `verdict.error_kind`, `attempts + 1` | `failed_count + 1` | |
| `bounce` | `bounced` | `bounced_count + 1` | `suppress(reason=hard_bounce, source=SOURCE_SEND, now=now)` |
| `pause` | back to `queued`, attempts unchanged | `transition(sending → paused, paused_reason=paused_reason(code, f"{result.code} {result.detail}"))` | |

Every verdict clears `lease_until` and sets `last_error = result.detail`, except `sent`, which
clears it.

**`deliver_one`.** Everything runs in `tenant_scope(tenant_id)` with one session. The order
matters (A3, A4):
1. Re-read the campaign (pinned). If it is not `sending`, return `None`. This is only a
   shortcut; the claim in step 6 is what decides.
2. `next_row`. If there is none, return `None`.
3. Re-check eligibility:
   - `subscribers_by_uuid(..., [row.record_uuid])`: a missing hit, a trashed one or one not
     `confirmed` → `skip(status="skipped_unsubscribed")`, finalize, return
     `Step(False, Verdict("skip", False))`;
   - `suppressed(..., [row.email])` → `skip(status="suppressed")` (`suppressed_count + 1`).
   The skip `UPDATE` is conditional on `status = 'queued'`.
4. Load the render and `compose`. A `ValueError` → `record(fail, invalid_message)` with no
   attempt row and no SMTP call, returned as `Step(False, …)`.
5. `await lock.renew()` (`DispatchBusy` propagates).
6. **The reservation**, one transaction:
   1. `await lock.fence(session)`;
   2. `claimed = await claim(session, tenant_id=…, send_id=row.id, now=clock())`. If it is
      `False` (paused, cancelled or claimed meanwhile), roll back and return
      `Step(False, Verdict("skip", False))`;
   3. `ledger.open_attempt(kind="campaign", send_id=row.id, campaign_id=…, recipient=row.email, now=clock())`;
   4. `finalize_session`.

   A `DispatchBusy` from the fence rolls the transaction back (nothing claimed, no attempt) and
   propagates.
7. `result = await smtp.send(message)`. Send only after a successful claim.
8. `close_attempt`, `classify`, `record`, `finalize_session`. Return `Step(True, verdict)`.

- [ ] **Step 1: Failing tests.**
  - `test_compose.py`:
    - `{{first_name|there}}` uses the row's first name, or the fallback when it is `None`;
    - the unsubscribe URL in the HTML, the text and `List-Unsubscribe` is the same URL, and
      `tokens.parse` gives the row's `(tenant, campaign, send)`;
    - the recipient's address is not in the URL;
    - a first name with `\r\n` is flattened (no `ValueError`);
    - `list_unsubscribe=False` adds no `List-*` headers;
    - `List-Unsubscribe-Post` is exactly `List-Unsubscribe=One-Click` and `Precedence` is `bulk`.
  - `test_lock.py` (SQLite only): `test_fence_inside_transaction`. With `me` holding, `fence`
    passes and extends `locked_until`. With the lease expired, or taken over by another holder,
    `fence` raises `DispatchBusy`. On Postgres `fence` is a no-op (Postgres-only test).
  - `test_deliver.py` (SQLite and Postgres; a `sending` campaign with render and rows; a no-op
    `HeldLock`):
    - `test_accepted_marks_sent_and_counts`;
    - `test_attempt_and_claim_committed_before_smtp`: `on_send` opens a *separate* session and
      asserts the row is `sending` with `lease_until` set and a `pending` attempt exists for
      `send_id`;
    - `test_retry_backoff_then_exhausted`: `451` three times, with the clock advanced past each
      `retry_at`. Asserts `retry_at` is +5 min, then +30 min, then `failed/retries_exhausted`
      with `failed_count == 1`. `next_row` returns `None` before `retry_at`;
    - `test_unknown_is_failed_never_retried`;
    - `test_bounce_suppresses_tenant_wide`: the row is `bounced`, and `suppressed(...)` is true
      for the address in the tenant;
    - `test_pause_reply_leaves_row_queued_and_pauses`: `554 5.4.5`. The row is `queued` with
      `attempts == 0`, the campaign is `paused`, `split_paused` gives
      `("smtp_rejected", "554 5.4.5 …")`, and no suppression is written;
    - `test_rejected_without_code_fails_invalid`;
    - `test_unsubscribed_since_freeze_is_skipped`: no attempt row, nothing sent;
    - `test_suppressed_since_freeze_is_skipped`;
    - `test_campaign_not_sending_sends_nothing` (`paused` and `cancelled`);
    - `test_lost_lease_sends_nothing`: `renew` raises `DispatchBusy`, and there is no claim and
      no attempt;
    - `test_fence_failure_rolls_back_the_reservation` (A4): `fence` raises `DispatchBusy`. The
      row is still `queued`, there is no attempt row and nothing was sent;
    - `test_pause_before_claim_sends_nothing` (A3): `subscribers_by_uuid` is wrapped to commit
      `lifecycle.pause` in another session after the eligibility read. Nothing is sent, there is
      no attempt row, and the row stays `queued`;
    - `test_cancel_before_claim_sends_nothing` (A3): the same with `cancel`. The row ends
      `cancelled` and nothing is sent;
    - `test_claim_requires_queued_row`: a row claimed by someone else between `next_row` and the
      claim (status set to `sending` directly) gives a `False` claim and no second send;
    - `test_tenant_pinned`: tenant B's campaign under `tenant_id="A"` returns `None`.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/sending/test_compose.py tests/sending/test_deliver.py tests/sending/test_lock.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep each file under 220 lines.
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): deliver one recipient through the ledger with re-check and verdicts`.

### Task 7: The dispatcher tick

**Files:**
- Create:
  - `sm_newsletter/sending/dispatch.py`
  - `sm_newsletter/sending/upkeep.py`
- Test: `tests/sending/test_dispatch.py`. If it nears 280 lines, split it into
  `test_dispatch_budget.py` and `test_dispatch_control.py`.

**Interfaces (Produces):**
```python
# sending/upkeep.py
async def sending_campaigns(factory) -> list[tuple[str, int]]   # sending, started_at ASC, id ASC; cross-tenant, narrow
async def recover_expired(factory, *, now: datetime) -> int      # S7
async def finish_done(factory, *, now: datetime) -> int          # sending with no queued/sending rows -> sent
async def pause_all_sending(factory, *, code: str, detail: str) -> int
# sending/dispatch.py
SLICE = 10
TICK_SECONDS = 50.0
HOLDER = "dispatcher"
@dataclass
class TickSummary:
    started: int = 0; spent: int = 0; skipped: int = 0; recovered: int = 0
    finished: int = 0; paused: int = 0
    stopped: str | None = None   # "idle" | "budget" | "busy" | "relay" | "transport_unavailable" | "deadline" | "not_configured"
async def tick(factory, *, settings: NewsletterSettings, secret: str, transport: Transport,
               clock: Callable[[], datetime] = utcnow, deadline_s: float = TICK_SECONDS,
               lock_wait_s: float = 15) -> TickSummary
```
**`tick`** runs these steps in order:
1. `recover_expired`, then `start_due`.
2. If `sending_campaigns` is empty → `finish_done`, `stopped="idle"`. No transport session is
   opened.
3. Open `transport.session()` once.
   - `TransportUnavailable` with stage `auth` → `pause_all_sending(PAUSE_SMTP_AUTH, exc.detail)`,
     `stopped="relay"`.
   - Any other stage → `stopped="transport_unavailable"`.
4. Loop until the deadline, under `async with dispatch_lock(factory, holder=HOLDER, wait_s=lock_wait_s) as lock:`:
   - `budget = current_budget(factory, settings, now=clock())`; `n = min(budget.left, SLICE)`.
     If `n == 0` → `"budget"`.
   - Until `n` are spent: walk `sending_campaigns` oldest first and call `deliver_one` for the
     first campaign that returns a `Step`. If none does → `"idle"`. Count `spent` and `skipped`.
   - A verdict with `stop_tick` → `"relay"` (a pause verdict also counts `paused`).
   - `DispatchBusy` from the lock or from `renew` → `"busy"`.
   - Release the lock between slices.
5. `finish_done`.

- [ ] **Step 1: Failing tests** (SQLite file database or Postgres; `FakeTransport`; a pinned
  `clock`).
  - `test_daily_cap_rollover_two_days`: `daily_limit=5`, `per_minute_limit=100`, 8 recipients.
    - Tick at T sends 5 (`stopped="budget"`).
    - Tick at T + 1 h sends 0.
    - Tick at T + 24 h + 1 s sends 3, and the campaign is `sent`.
    - No 24 h window holds more than 5 counted attempts.
  - `test_per_minute_limit`: `per_minute_limit=3`, 7 recipients. 3, then 0 at the same clock,
    then 3 at +61 s.
  - `test_test_sends_share_the_budget`: `support.sending.used(count=4)` with `daily_limit=5`
    leaves 1 for the campaign.
  - `test_oldest_started_first_across_tenants`: B started 09:00 and A 10:00, cap 2, 2 rows
    each. Both sends are B's, and each message's token tenant matches its row.
  - `test_crash_between_accept_and_commit_never_resends`: a row is `sending` with
    `lease_until < now` and a `pending` attempt. After the tick the row is
    `failed/outcome_unknown`, the attempt is `unknown`, nothing was sent to that address, and
    the attempt is still counted by `attempts_since`.
  - `test_unexpired_lease_left_alone`.
  - `test_relay_quota_reply_stops_tick`: the first recipient gets `421 4.7.0`. One spent, the
    row is retried later, `stopped="relay"`.
  - `test_pause_class_pauses_and_stops`: `554 5.4.5`. The campaign is `paused`, nothing more is
    sent, another tenant's campaign is untouched this tick and sends on the next one.
  - `test_auth_failure_at_open_pauses_all_sending`: two tenants' campaigns are both `paused`
    with `smtp_auth`, no attempt rows, no row changed.
  - `test_connect_failure_changes_nothing`.
  - `test_finishes_campaign_when_done`. A campaign with a retry-pending row (`retry_at` in the
    future) stays `sending`.
  - `test_cancel_mid_tick`: `on_send` cancels the campaign after the first message. The rest
    are `cancelled`, exactly 1 message was sent, and the status is `cancelled`.
  - `test_pause_resume_continues_without_duplicates`:
    - pause after 2 messages; the next tick sends nothing;
    - resume; the next tick sends the rest;
    - every address appears exactly once in `FakeTransport.sent`.
  - `test_dispatch_lock_busy_skips`: the test holds `dispatch_lock` with `lock_wait_s=0.2`.
    `stopped="busy"`, nothing sent.
  - `test_concurrent_ticks_never_exceed_cap`: `asyncio.gather` of two ticks on a file/PG
    database with cap 3 and 5 rows. At most 3 counted attempts, no address sent twice.
  - `test_no_work_opens_no_transport`: `FakeTransport.opened == 0`.
  - A4, SQLite file database, `daily_limit=3`, 5 rows, the dispatcher's lock taken with a short
    `lease_s`:
    - `test_takeover_during_eligibility_never_over_budget`. `subscribers_by_uuid` is wrapped to:
      1. expire the dispatcher's lease (set `locked_until` in the past);
      2. run a test send (`campaigns.test_send.send_test`) that takes the lock and spends the
         remaining budget.
      The dispatcher's fence then fails: `stopped="busy"`, no claim, no attempt. Across both,
      at most 3 counted attempts.
    - `test_takeover_during_smtp_never_over_budget`. `FakeTransport.on_send` does the same during
      the first message. That message completes; the next recipient's fence fails. At most 3
      counted attempts, and no address is sent twice.
  - `test_freeze_then_send_in_one_tick`: a `scheduled` campaign due now is `sending` after the
    tick, with messages sent.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/sending/test_dispatch.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS. Then run
  `tests/campaigns/test_test_send_delivery.py` to show test sends still coexist with the lock.
- [ ] **Step 5: Commit** `feat(newsletter): dispatcher tick with slices, budget, recovery and finish`.

### Task 8: The Celery task, worker runtime and an SMTP end-to-end

**Files:**
- Create: `sm_newsletter/sending/runtime.py`
- Modify:
  - `sm_newsletter/tasks.py`
  - `sm_newsletter/task_config.py`
  - `sm_newsletter/sending/__init__.py` (docstring)
- Test:
  - `tests/core/test_task_discovery.py`
  - `tests/core/test_worker_dispatch.py` (new, SQLite-only)
  - `tests/sending/test_dispatch_smtp.py` (new)

**Interfaces (Produces):**
```python
# sending/runtime.py
@dataclass(frozen=True)
class DispatchConfig:
    settings: NewsletterSettings
    secret: str = field(repr=False)
    transport: Transport
def dispatch_config() -> DispatchConfig
    # settings_for(NewsletterSettings, constants.PACKAGE); refuse_plaintext_password(); resolve_worker_secret();
    # install(); transport_for()
class PlaintextPassword(RuntimeError): ...   # A5
def refuse_plaintext_password(settings: NewsletterSettings) -> None
    # transport "smtp" and a non-empty smtp_password without crypto.ENC_PREFIX -> PlaintextPassword,
    # whose message names PUT /api/newsletter/settings/smtp-password and never the value
async def dispatch_async(factory, *, clock: Callable[[], datetime] = utcnow) -> TickSummary
    # SecretMissing / PlaintextPassword / SmtpPasswordUnreadable / settings read error
    #   -> logger.error(class name [+ the endpoint for PlaintextPassword]), TickSummary(stopped="not_configured"):
    #   no recovery, no freeze, no transport
# task_config.py
DISPATCH = "newsletter.dispatch"
DISPATCH_INTERVAL_SECONDS = 60.0
TASK_ROUTES[DISPATCH] = {"queue": QUEUE_DEFAULT}
BEAT_SCHEDULE["newsletter-dispatch"] = {"task": DISPATCH, "schedule": DISPATCH_INTERVAL_SECONDS,
                                        "options": {"queue": QUEUE_DEFAULT, "expires": 55}}
# tasks.py
@shared_task(name=DISPATCH)
def dispatch() -> dict[str, Any]   # run_platform(dispatch_async); logs and returns asdict(summary)
```

- [ ] **Step 1: Failing tests.**
  - `test_task_discovery.py`: the beat has both entries. `dispatch` runs every 60 s on the
    `newsletter` queue with `expires == 55`. Update the reconcile test's single-entry unpacking.
  - `test_worker_dispatch.py`. Fixture as in `test_worker.py`, seeding the settings table rows
    `sm_newsletter.transport=console`, `from_address`, `physical_address`, and `host.secret_key`.
    The `SM_PROJECT_ROOT` / env isolation is the same as in Task 3.
    - `test_dispatch_task_sends_through_the_worker_runtime`: a scheduled campaign with a render
      and 2 confirmed subscribers. `tasks.dispatch()` gives 2 console captures in tenant
      `default`. Each `List-Unsubscribe` token parses under the stored secret, the rows are
      `sent` and the campaign is `sent`.
    - `test_dispatch_refuses_without_a_secret`: no env and no row. `stopped == "not_configured"`,
      no attempt rows, nothing captured, the campaign still `scheduled`, and an ERROR record that
      names `SecretMissing`.
    - `test_dispatch_refuses_unreadable_password`: transport `smtp`, password encrypted under
      another secret, `smtp_host=127.0.0.1` on a closed port. `not_configured`, no attempt rows.
    - `test_dispatch_refuses_a_plaintext_password` (A5). A real settings row
      `sm_newsletter.smtp_password=hunter2` (no `enc:v1:`), transport `smtp`, and a secret
      present. Asserts:
      - `not_configured`;
      - no connection attempted (a relay fixture records none);
      - no attempt rows;
      - a due `scheduled` campaign is still `scheduled` with no send rows (no freeze);
      - one ERROR record naming `PUT /api/newsletter/settings/smtp-password`;
      - `hunter2` appears in no log record.
    - `test_dispatch_task_unbinds_the_callers_tenant`, as for the reconcile.
    - `test_no_token_in_any_log` (A7): run the sending test above with `caplog` at DEBUG for
      the `sm_newsletter`, `aiosmtplib` and `celery` loggers. No record contains any minted
      token's MAC part, nor the string `/newsletter/u/`.
  - `test_dispatch_smtp.py` (aiosmtpd relay from `tests/sending/conftest.py`, `make_transport`):
    one tick over `ok@`, `bounce@` and `soft@`.
    - `ok@` is delivered. The relay's received message has `List-Unsubscribe: <…/newsletter/u/…>`,
      `List-Unsubscribe-Post: List-Unsubscribe=One-Click` and `Precedence: bulk`.
    - `bounce@` is `bounced` with a `hard_bounce` suppression.
    - `soft@` is `queued` with `retry_at` set, and the tick `stopped == "relay"` only if S4 says
      so: a `451 4.3.0` does not stop it.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/core/test_task_discovery.py tests/core/test_worker_dispatch.py tests/sending/test_dispatch_smtp.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** `tasks.py` stays light: every import goes inside the body.
- [ ] **Step 4: Run** the Step 2 command. Expected: PASS. Run `test_dispatch_smtp.py` on
  Postgres too.
- [ ] **Step 5: Commit** `feat(newsletter): newsletter.dispatch beat task through the worker runtime`.

### Task 9: Sending API — send, unschedule, pause, resume, cancel, progress, estimate

**Files:**
- Create:
  - `sm_newsletter/web/endpoints/sending_api.py`
  - `sm_newsletter/web/schemas/sending.py`
  - `sm_newsletter/campaigns/progress.py`
- Modify:
  - `sm_newsletter/web/endpoints/__init__.py` (include the router)
  - `sm_newsletter/web/schemas/campaigns.py` (`CampaignDetail` fields)
- Test:
  - `tests/web/test_sending_api.py`
  - `tests/campaigns/test_progress.py`
  - `tests/web/test_route_guards.py`
  - `tests/web/test_campaigns_api.py` (detail fields)

**Interfaces (Produces):**
```python
# web/schemas/sending.py  (parsed with parse_payload; 422 invalid_campaign never echoes)
class ScheduleIn(BaseModel):  # extra="forbid"
    expected_revision: StrictInt
    scheduled_at: AwareDatetime | None = None
class RevisionIn(BaseModel):  # extra="forbid"
    expected_revision: StrictInt
class ProgressOut(BaseModel):
    status: str; recipients: int; queued: int; sending: int; sent: int; failed: int; bounced: int
    suppressed: int; skipped: int; cancelled: int
    paused_code: str | None; paused_detail: str | None
    scheduled_at: datetime | None; started_at: datetime | None; finished_at: datetime | None
    estimated_finish: datetime | None; daily_rate: int
class EstimateOut(BaseModel): recipients: int; estimated_finish: datetime; overlaps: bool; daily_rate: int
# CampaignDetail gains:
scheduled_at, started_at, finished_at: datetime | None
paused_code, paused_detail: str | None   # computed from paused_reason via split_paused
failed_count, bounced_count, suppressed_count, unsubscribe_count: int
# campaigns/progress.py
def daily_rate(settings: NewsletterSettings) -> int                          # S16
def estimate_finish(*, start: datetime, ahead: int, own: int, rate: int) -> datetime
async def queued_ahead(factory, *, started_before: datetime | None, exclude_campaign_id: int | None) -> int
async def progress(session, factory, settings, *, tenant_id: str, campaign: Campaign, now: datetime) -> ProgressOut
async def estimate(session, factory, settings, *, tenant_id: str, campaign: Campaign, at: datetime) -> EstimateOut
```
**Routes.** One router with `dependencies=[Depends(bind_admin)]`; each route adds its
permission after it.

| Method | Path | Permission | Body | Answers |
|---|---|---|---|---|
| POST | `/campaigns/{id}/send` | `PERM_SEND` | `ScheduleIn` | `CampaignDetail` |
| POST | `/campaigns/{id}/unschedule` | `PERM_SEND` | `RevisionIn` | `CampaignDetail` |
| POST | `/campaigns/{id}/pause` | `PERM_SEND` | none | `CampaignDetail` |
| POST | `/campaigns/{id}/resume` | `PERM_SEND` | none | `CampaignDetail` |
| POST | `/campaigns/{id}/cancel` | `PERM_SEND` | none | `CampaignDetail` |
| GET | `/campaigns/{id}/progress` | `PERM_VIEW` | | `ProgressOut` |
| GET | `/campaigns/{id}/estimate?at=` | `PERM_SEND` | | `EstimateOut` |

All take `caller_roles(request)`. `estimate.recipients` is `count_subscribers` with the
audience's filters (approximate: suppressions are not subtracted, and the UI says "about").

- [ ] **Step 1: Failing tests.**
  - `test_progress.py`:
    - `daily_rate`: 9500/30 → 9500, and 100000/30 → 43200;
    - `estimate_finish`: own 19 000, ahead 0, rate 9500 → start + 2 days; ahead 9500 → + 3 days;
    - `queued_ahead` counts only `sending` campaigns started earlier, across two tenants.
  - `test_sending_api.py`:
    - send-now 200: `status == "scheduled"`, revision +1;
    - 403 without `newsletter.send`;
    - 409 `stale`, and 409 `not_a_draft`;
    - 422 `empty_campaign`, and 422 `sender_not_configured`;
    - a naive `scheduled_at` → 422 `invalid_campaign`, with a detail holding no input text;
    - a restricted list → 404;
    - pause, resume and cancel each 200, and 409 `invalid_transition` from `sent`;
    - multi-tenant: tenant B's campaign id with `x-tenant: A` → 404, and B is unchanged;
    - progress counts after seeding rows of each status;
    - progress `paused_code` / `paused_detail`;
    - estimate overlap is true while another tenant's campaign is sending, and the response has
      exactly the `EstimateOut` keys (no other tenant's data);
    - CSRF: with `session=True`, POST `/send` without the token → 403.
  - `test_route_guards.py`: add the seven routes to `EXPECTED`.
  - `test_campaigns_api.py`: `GET /campaigns/{id}` holds the new fields.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/web/test_sending_api.py tests/campaigns/test_progress.py tests/web/test_route_guards.py tests/web/test_campaigns_api.py -q -p no:cacheprovider -n 8`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): sending API (send, unschedule, pause, resume, cancel, progress, estimate)`.

### Task 10: The unsubscribe page and the one-click POST

**Files:**
- Create:
  - `sm_newsletter/web/endpoints/unsubscribe.py` (router)
  - `sm_newsletter/web/endpoints/unsubscribe_page.py` (HTML)
  - `sm_newsletter/web/services/unsubscribe.py`
  - `sm_newsletter/core/messages.py`
- Modify:
  - `sm_newsletter/module.py`: `register_public_routes`, a new `register_rate_limits`, and
    `mount_public_routes`, which includes both public routers, each guarded by its own path.
  - `sm_newsletter/content/context.py`: `_footer` uses `core/messages.server_copy`.
  - `sm_newsletter/locales/en.json` and `de.json` (`unsubscribe_page.*`)
  - `tests/support/app.py`: `app.state.sm_records = RecordsServices(settings=RecordsSettings())`
    when absent, and the public routers mounted.
- Test:
  - `tests/web/test_unsubscribe.py`
  - `tests/web/test_unsubscribe_tenancy.py`
  - `tests/core/test_module_boot.py` (exemption and rate rules)

**Interfaces (Produces):**
```python
# core/messages.py
def server_copy(app, section: str, keys: tuple[str, ...]) -> tuple[str, dict[str, str]]
    # (locale, copy): host i18n_default_locale; registry messages, else the package en.json fallback
# web/services/unsubscribe.py
async def unsubscribe_by_token(app, token: str, *, resolved_tenant: str | None, now: datetime) -> bool
    # True only when records wrote. Invalid or foreign token -> False, no statement run.
# web/endpoints/unsubscribe_page.py
def render_page(*, copy: dict[str, str], locale: str, done: bool) -> str   # every value html.escape'd
# web/endpoints/unsubscribe.py
router = APIRouter(tags=["newsletter-public"])
@router.get(constants.UNSUBSCRIBE_PREFIX + "{token}")  -> HTMLResponse   # no DB, no tenant binding
@router.post(constants.UNSUBSCRIBE_PREFIX + "{token}") -> HTMLResponse   # done page, always 200
```
**The service**, in order (S8/S9):
1. `secret = tokens.host_secret(app)`. If it is empty, log once and return `False`.
2. `tokens.parse` returns `None` → `False`.
3. `resolved_tenant` (`tenancy._resolved(request)`, passed in by the route) is set and differs
   from the token's tenant → `False`.
4. In `tenant_scope(tok.tenant_id)`, with a session from `app.state.sm.db.session_factory`:
   1. Load `Send` pinned to `(id, tenant_id, campaign_id)` and the campaign pinned. If either is
      missing → `False`.
   2. Call records:
      ```python
      unsubscribe(session, tenant_id=…, type_key=campaign.list_type_key, uuid=send.record_uuid,
                  unless_confirmed_after=send.sent_at or campaign.started_at or now,
                  settings=app.state.sm_records.settings, bus=app.state.sm.event_bus)
      ```
      `SubscriberFilterError` counts as "the type stopped being a list".
   3. If records wrote: `suppress(…)` and `bump(unsubscribe_count=1)`.
   4. If not, look up `subscribers_by_uuid`. When the hit is missing, trashed or
      `unsubscribed`, or the type stopped being a list: `suppress(…)` with no count.
   5. `finalize_session`.

**The responses.** Both answer `text/html; charset=utf-8` with these headers:
- `Cache-Control: no-store`
- `Referrer-Policy: no-referrer`
- `X-Robots-Tag: noindex`
- `Content-Language: <locale>`

A token longer than `MAX_TOKEN` is treated as forged. The module docstring says why there is no
CSRF (S9) and why the tenant comes from the token (S8).

**Module hooks:**
```python
registry.add_prefix(constants.UNSUBSCRIBE_PREFIX, methods={"GET", "POST"})
def register_rate_limits(self, registry: RateLimitRegistry) -> None:
    registry.add_prefix(constants.UNSUBSCRIBE_PREFIX, RateLimitRule("60/minute", key="ip", methods=frozenset({"GET"})))
    registry.add_prefix(constants.UNSUBSCRIBE_PREFIX, RateLimitRule("300/minute", key="ip", methods=frozenset({"POST"})))
```
If the registry keeps only one rule per prefix, register the POST rule on the same prefix in
the form the registry accepts, and pin it with the test.

**Locale keys** (`en` and `de`): `unsubscribe_page.title`, `.intro`, `.button`, `.done`.

- [ ] **Step 1: Failing tests.**
  - `test_unsubscribe.py` (SQLite and Postgres; a sent campaign with one `sent` row and its
    token from `tokens.sign(SECRET, …)`):
    - `test_get_page_has_button_and_changes_nothing`: 200, `<form method="post"`, the subscriber
      still `confirmed`, no suppression;
    - `test_get_is_identical_for_real_test_and_forged`: the body bytes are equal for a real
      token, `test` and `x.1.1.AAAA`;
    - `test_one_click_post_unsubscribes`: form body `List-Unsubscribe=One-Click` →
      - records status `unsubscribed`;
      - a suppression row with reason `unsubscribed`, the list, source `unsubscribe_page`;
      - `unsubscribe_count == 1`;
      - one `SubscriptionChanged` on the app's bus (spy);
    - `test_button_post_with_empty_body_unsubscribes`;
    - `test_post_is_idempotent`: twice gives count 1 and identical bodies;
    - `test_old_link_after_resignup_changes_nothing`: re-confirm with `confirmed_at` after
      `sent_at` (records_seed `signup` + `confirm_link`) → still `confirmed`, no suppression,
      count 0, the same body;
    - `test_forged_and_test_tokens_change_nothing`: a tampered MAC, `test`, another secret, an
      unknown send id with a valid MAC. No DB change, and the same body as a real POST;
    - `test_deleted_record_is_still_suppressed`: the record is purged, so a suppression is
      written and the count is 0;
    - `test_headers_no_store_no_referrer_noindex`;
    - `test_page_language_follows_host_default`: `i18n_default_locale="de"` with the `de`
      catalogue → `lang="de"` and the German button text;
    - `test_get_does_no_database_work`: `app.state.sm.db.session_factory` replaced with one that
      raises, and GET is still 200.
  - `test_unsubscribe_tenancy.py` (A9). Tenants A and B each have a list, a confirmed subscriber,
    a sent campaign and a `sent` row. Their ids are **distinct real ids**: B's campaign and send
    ids are never A's. Each foreign case compares the response body with a genuine A POST's,
    and snapshots records statuses, `newsletter_suppression` and every campaign counter in both
    tenants before and after.
    - `test_signed_token_pairing_tenant_a_with_b_send_id_changes_nothing`:
      `tokens.sign(SECRET, tenant_id="A", campaign_id=<A's campaign>, send_id=<B's send>)` →
      identical page, nothing changed in A or B;
    - `test_signed_token_pairing_a_campaign_with_b_send_changes_nothing`: the tenant is A,
      A's campaign id, B's send id. The `(id, tenant_id, campaign_id)` pin finds nothing →
      identical page, nothing changed;
    - `test_resolved_host_tenant_mismatch_changes_nothing`: A's genuine token POSTed with
      `x-tenant: B` (the host resolved B) → identical page, nothing changed in A or B;
    - `test_multi_tenant_apex_binds_the_tokens_tenant`: a multi app with no `x-tenant`. A's
      genuine token unsubscribes A's subscriber only; B is unchanged.
  - `test_module_boot.py`: the public-route registry exempts `/newsletter/u/` for GET and POST;
    the rate registry has both rules.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/web/test_unsubscribe.py tests/web/test_unsubscribe_tenancy.py tests/core/test_module_boot.py tests/content/test_context.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** the Step 2 command on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): unsubscribe page and RFC 8058 one-click POST`.

### Task 11: Frontend foundation — types, client, catalogue, progress hook

**Files:**
- Modify:
  - `sm_newsletter/ui/utils/types.ts`
  - `sm_newsletter/ui/utils/api.ts`
  - `sm_newsletter/locales/en.json`, `de.json`
- Create: `sm_newsletter/ui/hooks/useCampaignProgress.ts`
- Test:
  - `sm_newsletter/ui/utils/api.test.ts`
  - `sm_newsletter/ui/hooks/useCampaignProgress.test.ts`
  - `tests/core/test_error_catalogue.py` (new, Python)

**Interfaces (Produces):**
```ts
// types.ts
export interface CampaignDetail extends CampaignSummary {   // existing fields, plus:
  scheduled_at: string | null; started_at: string | null; finished_at: string | null;
  paused_code: PausedCode | null; paused_detail: string | null;
  failed_count: number; bounced_count: number; suppressed_count: number; unsubscribe_count: number;
}
export type PausedCode = 'manual' | 'smtp_rejected' | 'smtp_auth' | 'list_unavailable';
export interface Progress { status: string; recipients: number; queued: number; sending: number; sent: number;
  failed: number; bounced: number; suppressed: number; skipped: number; cancelled: number;
  paused_code: PausedCode | null; paused_detail: string | null; scheduled_at: string | null;
  started_at: string | null; finished_at: string | null; estimated_finish: string | null; daily_rate: number }
export interface Estimate { recipients: number; estimated_finish: string; overlaps: boolean; daily_rate: number }
// api.ts
sendCampaign(id: number, b: { expected_revision: number; scheduled_at: string | null }): Promise<CampaignDetail>
unscheduleCampaign(id: number, expected_revision: number): Promise<CampaignDetail>
pauseCampaign(id: number): Promise<CampaignDetail>
resumeCampaign(id: number): Promise<CampaignDetail>
cancelCampaign(id: number): Promise<CampaignDetail>
progress(id: number, signal?: AbortSignal): Promise<Progress>
estimate(id: number, at: string | null): Promise<Estimate>
// hooks/useCampaignProgress.ts
export const PROGRESS_POLL_MS = 10_000;
export function useCampaignProgress(id: number, status: string | undefined):
  { progress: Progress | null; error: string | null; reload: () => Promise<void> }
// polls while status is 'scheduled' | 'sending'; one fetch otherwise; aborts on unmount
```
**Catalogue keys** (`en` and `de`, same tree):
- `errors.invalid_transition`, `errors.empty_campaign`, `errors.https_required` (A6)
- `sending.send_button`
- `sending.dialog.{title, description, now, later, at_label, recipients, estimate, overlap, confirm, sending, cancel}`
- `sending.panel.{scheduled_for, progress, eta, finished, paused, counts.{failed, bounced, suppressed, skipped, unsubscribed}}`
- `sending.actions.{pause, resume, cancel, unschedule}`
- `sending.cancel_confirm.{title, description, confirm, keep}`
- `sending.paused_code.{manual, smtp_rejected, smtp_auth, list_unavailable}`

Placeholders: `{count}`, `{date}`, `{sent}`, `{total}`, `{days}`, `{rate}`, `{detail}`.

- [ ] **Step 1: Failing tests.**
  - `api.test.ts`: each new call hits the right path, method and body (`fetch` mocked).
  - `useCampaignProgress.test.ts`, with fake timers:
    - polls every 10 s while `sending`;
    - fetches once for `sent`;
    - stops polling when a poll returns `sent`;
    - unmount aborts and stops;
    - an error is exposed through `errorMessage`.
  - `test_error_catalogue.py`: every `code` of every `NewsletterError` subclass in
    `core/errors.py` (walk `__subclasses__` recursively) has `errors.<code>` in `en.json`
    (ruling C13).
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/utils/api.test.ts modules/newsletter/sm_newsletter/ui/hooks/useCampaignProgress.test.ts` and
  `uv run --directory modules/newsletter pytest tests/core/test_error_catalogue.py -q -p no:cacheprovider`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** the Step 2 commands and `npx tsc --noEmit -p modules/newsletter/tsconfig.json`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): sending client, catalogue keys and progress hook`.

### Task 12: Send dialog, sending panel and the editor wiring

**Files:**
- Create:
  - `sm_newsletter/ui/components/sending/SendDialog.tsx`
  - `sm_newsletter/ui/components/sending/SendingPanel.tsx`
  - `sm_newsletter/ui/utils/progress.ts`
- Modify:
  - `sm_newsletter/pages/CampaignEditor.tsx`
  - `sm_newsletter/ui/hooks/useCampaignEditor.ts` (A8)
- Test:
  - `ui/components/sending/SendDialog.test.tsx`
  - `ui/components/sending/SendDialog.editor.test.tsx` (A8: the real hook)
  - `ui/hooks/useCampaignEditor.test.ts` (A8)
  - `ui/components/sending/SendingPanel.test.tsx`
  - `ui/utils/progress.test.ts`

**Interfaces (Produces):**
```ts
// utils/progress.ts
export function daysLeft(p: Progress): number | null           // ceil((queued + sending) / daily_rate) days; null when nothing is left
export function toUtcIso(local: string): string | null          // a datetime-local value -> ISO UTC; null when invalid
export function formatWhen(iso: string, locale: string): string // Intl.DateTimeFormat, dateStyle medium, timeStyle short
// components
export function SendDialog(props: {
  campaign: CampaignDetail;
  onSent: (c: CampaignDetail) => void;
  flush: () => Promise<boolean>;
  dirty: boolean;
  incomplete: boolean;
  currentRevision: () => number;
}): JSX.Element
// hooks/useCampaignEditor.ts (A8): the return value gains `currentRevision: () => number`
// (reads revisionRef), and flush() resolves false when the body is incomplete
// (edits.incomplete), as well as when the save fails or the editor is stale.
export function SendingPanel(props: { campaign: CampaignDetail; canSend: boolean; onChange: (c: CampaignDetail) => void }): JSX.Element | null
```
**`SendDialog`.**
- It is a trigger button, `sending.send_button`, shown when the status is `draft` and
  `can_send`.
- A8: the trigger is disabled while `incomplete`, with `test_send.incomplete` as its hint.
  Opening it flushes pending autosave (`flush`; `false` → show `test_send.unsaved` and stop),
  then loads `estimate(id, null)`.
- The radio choices are *now* and *later*. *Later* shows a `datetime-local` field and reloads
  the estimate for that time.
- It shows recipients, the estimated finish, and the overlap warning when `overlaps`.
- Confirm (A8):
  1. calls `flush()` again;
  2. if it returns `false`, or `incomplete` or `dirty` is still true afterwards, stops with
     `test_send.unsaved` and posts nothing;
  3. otherwise calls `sendCampaign` with `currentRevision()`, the revision the final save
     produced, not the one the dialog opened with.
- Errors show `errorMessage(e, t)`. A 409 `stale` tells the user to reload.

**`SendingPanel`.** It renders nothing for `draft` and otherwise shows:
- `scheduled`: the date, plus *Unschedule* and *Cancel*;
- `sending`: progress (`{sent} of {total} sent`) and the ETA (`about {days} more days at
  {rate}/day`), plus *Pause* and *Cancel*;
- `paused`: the translated `paused_code` and `paused_detail` verbatim, plus *Resume* and
  *Cancel*;
- `sent` / `cancelled`: the finish date, and the counts (failed, bounced, suppressed, skipped,
  unsubscribed).

Cancel asks first (`sending.cancel_confirm`). Actions are hidden without `canSend`. Each action
calls `onChange` with the returned campaign. It uses `useCampaignProgress`.

**`CampaignEditor.tsx`.** Add `SendDialog` in the header beside `EditorTabs`, and render
`SendingPanel` under the header for non-drafts. Its `onChange` / `onSent` refresh the editor's
campaign (the hook's `reload`). Keep the file under 260 lines.

- [ ] **Step 1: Failing tests.**
  - `SendDialog.test.tsx`:
    - hidden without `can_send` or for a non-draft;
    - opening loads the estimate and shows the recipients;
    - *Send now* posts `{expected_revision, scheduled_at: null}` and calls `onSent`;
    - *Later* with an empty or past value disables confirm; a future value posts its UTC ISO;
    - the overlap warning appears when `overlaps`;
    - 409 `stale` shows the translated stale text;
    - `flush` returning `false` does not post;
    - the trigger is disabled while `incomplete`.
  - `SendDialog.editor.test.tsx` (A8). A small harness renders the **real** `useCampaignEditor`
    and passes its `flush`, `dirty`, `incomplete` and `currentRevision` to `SendDialog`.
    `fetch` is mocked at the network layer and the hook is not mocked.
    - An edit that leaves a block incomplete: the trigger is disabled, and no `/send` request is
      made.
    - A complete edit made just before Confirm: the requests are `PATCH /campaigns/{id}`, then
      `POST /campaigns/{id}/send` with `expected_revision` equal to the PATCH response's
      revision.
    - A PATCH answered 409 `stale`: no `/send` request.
  - `useCampaignEditor.test.ts`: `flush()` resolves `false` while the body is incomplete, and
    `currentRevision()` follows each successful save.
  - `SendingPanel.test.tsx`:
    - `null` for a draft;
    - the progress line and ETA for `sending`;
    - Pause visible and posting;
    - Resume visible for `paused`, with the paused reason translated and the detail shown;
    - Cancel asks for confirmation and posts only after it;
    - no action buttons without `canSend`;
    - counts shown for `sent`.
  - `progress.test.ts`: `daysLeft`, `toUtcIso` (invalid → `null`), `formatWhen`.
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/components/sending modules/newsletter/sm_newsletter/ui/utils/progress.test.ts modules/newsletter/sm_newsletter/ui/hooks/useCampaignEditor.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `@simple-module-py/ui` components (`Button`, `Dialog`,
  `AlertDialog`, `RadioGroup`, `Badge`), as `TestSendDialog.tsx` does.
- [ ] **Step 4: Run** the Step 2 command, `npx vitest run modules/newsletter/sm_newsletter/ui/components/editor`,
  `npx tsc --noEmit -p modules/newsletter/tsconfig.json` and `npx biome check modules/newsletter`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): send dialog and sending controls on the campaign screen`.

### Task 13: Docs, wiring and branch verification

**Files:**
- Create:
  - `modules/newsletter/docs/sending.md`: the status machine (S14); freeze; the dispatcher
    (slices, lock, budget, oldest first, multi-day); the verdict table (S4); retries and
    backoff; the lease and outcome-unknown; the unsubscribe route (S8, S9, why no CSRF); tokens
    (S10); the render snapshot and what *unschedule* refreshes (S1).
  - `modules/newsletter/docs/operations.md`:
    - **The worker and beat must run**: `make worker` (the `newsletter` queue) and `make beat`.
      With `SM_BG_TASKS_TASK_ALWAYS_EAGER=true` and no beat, nothing is dispatched.
    - **The secret**: `SM_SECRET_KEY` in env/`.env`, or the host's stored `host.secret_key`.
      Without either, the tick refuses and logs at ERROR.
    - **The DKIM checklist** (amendment 10): enable DKIM for the domain in the Google Admin
      console, send a test, and confirm that `DKIM-Signature: … h=` lists `List-Unsubscribe`
      and `List-Unsubscribe-Post`.
    - **The relay**: `smtp-relay.gmail.com`, the daily cap headroom, what a pause means and how
      to resume.
- Modify:
  - `modules/newsletter/docs/index.md` (status: PR 4; links to both pages)
  - `modules/newsletter/README.md`
  - `CLAUDE.md` (the paragraph below)
  - `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`: set the PR 4 row's plan path.
    Add "Notes for PR 5":
    - reuse `core.tokens.sign` for `/o/` and `/c/`;
    - link rewriting must happen in `campaigns/snapshot.py`, writing `newsletter_link` rows when
      the campaign is scheduled;
    - the tag audience moved to PR 6 (S3).
  - `host/tests/test_newsletter_wiring.py`: add `test_unsubscribe_route_is_public`. On the built
    host app, an anonymous `GET /newsletter/u/test` is 200 HTML, not 401 or a redirect.

**The `CLAUDE.md` paragraph** (append to the newsletter rules) says:
1. Campaigns are sent only by the `newsletter.dispatch` beat. It holds the install-wide
   `dispatch_lock` per slice, and each recipient's attempt row is committed before its SMTP
   call.
2. The worker never renders. It personalises the render snapshot written when the campaign was
   scheduled.
3. `/newsletter/u/{token}` is the **second documented exception** to "the public surface binds
   the resolved tenant", after records' signed form token. It binds the tenant from the
   HMAC-verified token. It answers an unknown, foreign or forged token exactly as it answers a
   real one, so it cannot be used to probe which tokens exist. It carries no CSRF on purpose
   (RFC 8058).
4. Only an RCPT-stage `5.1.x` bounces. Any other 5xx pauses the campaign.

**Also edit the existing newsletter sentence on `scripts/set_setting.py` (A5).** It currently
says the script "would store it in plaintext, accepted with a warning; use the endpoint".
Change it to: workers **refuse** a non-empty SMTP password stored without `enc:v1:`. The
dispatcher does not run until it is re-saved through
`PUT /api/newsletter/settings/smtp-password`, so always use the endpoint.

- [ ] **Step 1: Write the docs and the host test.**
- [ ] **Step 2: Verify.** Run `~/.claude/bin/wait-for-headroom` first.
  - The host test: `uv run --directory host pytest tests/test_newsletter_wiring.py -q -p no:cacheprovider`.
  - From the root:
    - `uv run ruff check modules/newsletter host/tests/test_newsletter_wiring.py`
    - `uv run ruff format --check modules/newsletter host/tests/test_newsletter_wiring.py`
    - `uv run python scripts/check_file_size.py`
    - `uv run python scripts/check_rules.py`
    - `uv run python scripts/check_locales.py`
    - `uv run python scripts/check_hardcoded_strings.py`
    - `uv run python scripts/check_readmes.py`
    - `uv run python scripts/check_migration_heads.py`
    - `npx biome check modules/newsletter`
    - `npx tsc --noEmit -p modules/newsletter/tsconfig.json`

  Expected: all pass. A WARNING at 280+ lines on a touched file means split it now.
- [ ] **Step 3: Migration check.**
  - SQLite: on a scratch database, `upgrade heads`, then
    `uv run --project host alembic -c host/alembic.ini check` ("No new upgrade operations
    detected").
  - Postgres: the same on a scratch `smpy_newsletter_check`, created and dropped (Task 1, Step 5).
- [ ] **Step 4: Commit** `docs(newsletter): sending, operations and the DKIM checklist (PR 4)`.

---

## Amendments (Codex review 2026-11-05)

The Codex plan review raised nine findings, and the team lead accepted all of them. Each is
folded into the tasks named; where a ruling above says otherwise, the amendment wins.

- **A1 (P1). An interrupted freeze survives unschedule.**
  - **Fence.** Freezes are fenced by a freeze generation: `newsletter_campaign.freeze_gen`, and
    `newsletter_send.freeze_gen` on every row (Task 1).
  - **Bumps.** `schedule`, `unschedule` and cancel-from-`scheduled` bump the generation inside
    their conditional status `UPDATE`.
  - **Unschedule cleanup.** `unschedule` deletes the campaign's send rows in the same
    transaction (Task 4).
  - **Freezer writes.** A freezer's page inserts and its final `scheduled → sending` are
    conditional on its generation still being current (Task 5, S18).
  - **Tests:**
    - a crash after a page, then unschedule, a change of list and reschedule → only the new
      list's recipients;
    - an old freezer that keeps going after the reschedule writes nothing (Task 5).
- **A2 (P1). Overlapping freezes.**
  - **Owner.** One fenced freeze owner per campaign: `freeze_owner` + `freeze_until`, claimed
    by a conditional `UPDATE` (`claim_freeze`).
  - **Page writes.** Each page renews the claim with `hold_freeze` inside its transaction, and
    writes only while it holds the claim and the freeze is unpublished.
  - **Takeover.** An expired claim can be taken over, and the old owner then writes nothing.
  - **Test:** two overlapping freezes with a signup between their page reads (Task 5).
- **A3 (P1). Pause or cancel racing the claim.**
  - **The claim.** One conditional `UPDATE` requiring `newsletter_send.status = 'queued'` and
    `EXISTS` a campaign row with `status = 'sending'`, returning whether it changed a row.
    Mail is sent only after a successful claim.
  - **Pause and cancel** are conditional `UPDATE`s (S14).
  - **Tests:** pause before the claim, and cancel before the claim → nothing sent, no attempt
    row (Task 6).
- **A4 (P1). The SQLite lease.**
  - **Per recipient:**
    1. eligibility, render and compose come before any reservation;
    2. `renew()`;
    3. one reservation transaction, fenced on the held lease (`HeldLock.fence`: a conditional
       `UPDATE` on `holder = me AND locked_until > now`), holding the claim and `open_attempt`;
    4. SMTP.
  - **SMTP bounds:** 20 s per command and a 45 s `send_deadline` per recipient (a reconnect
    included), against the 120 s lease (Task 2, S6).
  - **Tests:** a takeover during eligibility and during SMTP, with a test send spending the
    remaining budget; never over budget (Tasks 2, 6, 7).
- **A5 (P1). A plaintext SMTP password.**
  - **Refusal.** The worker refuses a non-empty `smtp_password` without `enc:v1:` before it
    builds a transport. It logs at ERROR, naming `PUT /api/newsletter/settings/smtp-password`.
  - **Test** with a real plaintext row: no connection, no attempt row, no freeze (Task 8).
  - **Docs.** Task 13 updates the `CLAUDE.md` sentence on `set_setting.py`.
- **A6 (P2). HTTPS for real campaigns.**
  - **Check.** On the `smtp` transport, scheduling requires `https://` for both
    `content_base` and `public_base`, else 422 `https_required` (new; en and de keys).
  - **Console.** The console transport allows `http://`.
  - **Test:** the rejection leaves no snapshot and no status change (Tasks 4, 11).
- **A7 (P2). Capability-bearing merge fields and logging.**
  - **Merge fields.** The subject and preheader refuse capability-bearing merge fields
    (`{{unsubscribe_url}}`; `CAPABILITY_TAGS` is where later token-bearing fields go) with 422,
    at PATCH and again at schedule (Task 4).
  - **Console logging.** The console transport never logs a personalised subject. It logs
    `OutgoingMessage.ref` (campaign id and send id) and the recipient's domain only (Task 2).
  - **Test:** a log-capture regression test shows no token in any log (Task 8).
- **A8 (P2). `SendDialog` and unsaved edits.**
  - **Blocking.** `SendDialog` is blocked while the editor is incomplete or dirty.
  - **The hook.** `flush()` resolves `false` for an incomplete body, and `currentRevision()`
    gives the revision after the final flush. Confirm re-checks after that flush.
  - **Tests** use the real `useCampaignEditor` hook, not a mock (Task 12).
- **A9 (P2). Distinct real ids in the tenancy tests.**
  - **Cases.** The same-send-id test is replaced by distinct real ids:
    - a correctly signed token pairing tenant A with B's send id;
    - A's campaign with B's send;
    - a host-resolved tenant that does not match the token's.
  - **Expected:** an identical page, and no change to records, suppressions or counters
    (Task 10).

## Spec coverage (self-review)

| Spec item | Task |
|---|---|
| Start: resolve the audience in pages, subtract suppressions, `queued` rows in batches, then `sending` (§Sending 1) | 5 |
| Dispatch every minute, rolling 24 h and per-minute budget across tenants, oldest campaign first (§Sending 2; amendment 4) | 7, 8 |
| Re-check confirmed and unsuppressed right before sending (§Sending 2; amendment 3) | 6 |
| Render once, personalise per recipient, List-Unsubscribe headers (§Sending 3) | 4 (S1), 6 |
| Results: 2xx sent; RCPT 5.1.x bounced + `hard_bounce`; other 5xx and auth pause; 4xx retry ×3 then failed; 4.x quota stops the minute (§Sending 4) | 2, 6, 7 |
| Pre-acceptance retries only; unknown never retried (amendment 2) | 2, 6 |
| Duplicate guard: a lease, expiry → failed/outcome unknown (§Sending) | 6, 7 |
| `sent` when no `queued` rows remain (§Sending 5); `CampaignSent` | 7 (event deferred, S15) |
| Secrets in workers: env/.env, else `host.secret_key`, else refuse (§Sending; PR 2 carry-over) | 3, 8 |
| Several campaigns share the budget; estimated finish and overlap warning (§Sending) | 7, 9, 12 |
| Pause, resume, cancel; progress line (§Sending) | 4, 9, 12 |
| Test sends count against the cap (§Sending) | 7 (`test_test_sends_share_the_budget`) |
| Unsubscribe page (GET changes nothing) and one-click POST; records' transition with the cutoff; suppression in the same transaction; counted once (§Tracking; amendments 1, 5, 7, 8) | 10 |
| Token HMAC over (tenant, campaign, send), 128-bit; forged = same answer (§Tracking) | 3, 10 |
| `/newsletter/u/test` answered like a forged token (PR 3 R1) | 10 |
| DKIM covers the unsubscribe headers: an operations checklist (amendment 10) | 13 |
| Tenant isolation on every route and task (§Testing) | 4, 5, 6, 7, 9, 10 |
| Fake SMTP server for 2xx, 4xx and 5xx paths and header presence (§Testing) | 2, 8 |
| Daily cap rollover across two days with a fake clock (§Testing) | 7 |
| en/de catalogues, errors translated | 10, 11 |
| Migration: one revision, single head, `alembic check` on SQLite and Postgres | 1, 13 |

**Out of PR 4, by roadmap:**
- opens, clicks and the report screen (PR 5);
- segments, tags and the subscriber screen (PR 6, with S3);
- the import and the e2e spec (PR 7).

## Open questions

None. On 2026-11-05 the team lead confirmed S4, S8 and S11 (the fifth case included) and accepted
every other ruling as written. The three that depart from the brief's wording are:
- **S4.** Only an RCPT-stage `5.1.x` bounces; other 5xx pause the campaign. This follows spec
  §Sending 4.
- **S8.** The unsubscribe route takes its tenant from the token rather than `bind_public` with
  a 404. This follows the spec and records' precedent; `bind_public` breaks multi-tenant links.
- **S11.** The "four cases" are the secret-key sources, plus a fifth for a password the secret
  cannot decrypt.
