# Newsletter PR 5: tracking and reports — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every campaign email carries an open pixel and click-tracked links, each signed with a
purpose-bound token for its send (T17). Two anonymous routes record opens and clicks in race-free counters. A report
screen per campaign, and metrics on the campaign list, show the results, labelled as honestly as
the data allows.

**Architecture:**
- **Snapshot (web process, at schedule).** After PR 4's `build_render`, `tracking/rewrite.prepare`
  replaces every trackable `<a href>` in the HTML part with a `{{link:N}}` placeholder, inserts one
  `{{open_pixel}}` placeholder before `</body>`, and returns the campaign's distinct URLs. They are
  stored as `newsletter_link` rows (position `N`) in the same transaction as the render row.
- **Compose (worker).**
  - `tracking/rewrite.fill` swaps the placeholders for `/newsletter/c/{click_token}/{N}` and the
    pixel `<img>` with `{open_token}`. With tracking off it puts back the original URL and drops
    the pixel.
  - It runs on the trusted snapshot *before* personalisation (B2).
  - The tokens are purpose-bound (T17): `"c"` for clicks, `"o"` for opens, and `"u"` for the
    unsubscribe link. A click or open URL cannot unsubscribe anyone.
  - No app and no render in the worker (S1 holds).
- **Routes (web process).** `GET /newsletter/o/{token}.gif` and `GET /newsletter/c/{token}/{N}`.
  Tenant from the verified token, as PR 4's S8. Counters are conditional `UPDATE`s and an
  `INSERT … ON CONFLICT DO NOTHING` per `(send, link)`.
- **Report (web process).** `GET /api/newsletter/campaigns/{id}/report` (newsletter.view, C4 list
  access) and an Inertia page `Newsletter/CampaignReport`.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic, React 19 + Inertia,
`@simple-module-py/ui`, vitest.

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md`. Its "Amendments"
override its body. This plan implements §"Tracking and analytics" (opens, clicks, the report
screen, the campaign list), the `tracking_opens`/`tracking_clicks` settings and the `tracking/`
area of §"Module shape". Also read:
- `docs/superpowers/plans/2026-11-03-newsletter-pr4-sending.md`, the contract this builds on: S1
  (render snapshot), S8 (tenant from the token), S10 (the per-send token, amended here by T17),
  A6, A7.
- The PR 4 ledger `.superpowers/sdd/2026-11-03-newsletter-pr4-sending/progress.md` (rulings P1,
  P2 and the Task 4–7 rulings) and the PR 3 ledger (C4, C7, C11, C13).
- `.superpowers/sdd/newsletter-stack.md`.

**Precondition.** Execute only after all 13 PR 4 tasks are committed. Tasks 6, 7, 9 and 10 build
on PR 4 Tasks 9–12, which did not exist when this was written. Before each of those tasks, the
implementer re-reads the named PR 4 file and adapts only the names; the behaviour stays.

## Rulings (decided here; cost if wrong in each)

- **T1. Placeholders in the snapshot, the token at compose.**
  - The snapshot (S1) holds `{{link:N}}` and `{{open_pixel}}`. The worker fills them per
    recipient. Neither placeholder can come from author content: `check_merge` refuses any
    unknown `{{…}}`, and card/branding text is `inert` (`{` → `&#123;`).
  - `newsletter_link` rows are written with the render row, in the schedule transaction.
    `drop_render` (unschedule) deletes them, and their clicks, explicitly.
  - Cost if wrong: none found. The alternative (rewriting at compose by URL lookup) needs the same
    map and re-parses every message.
- **T2. The click path carries the link's `position`, not its id:** `/newsletter/c/{token}/{N}`,
  looked up by the existing unique `(tenant_id, campaign_id, position)`. A global id would leak row
  counts across tenants. Cost: none.
- **T3. What is rewritten.**
  - Only the HTML part, only `<a href="…">` whose unescaped value is `http://` or `https://` with
    a host (`urls.is_http_link`).
  - Never rewritten:
    - `{{unsubscribe_url}}` (not http);
    - `mailto:`;
    - anything under `public_base + "/newsletter/"` (the module's own routes);
    - an image `src`, so the logo is never touched (it is an `<img>`, not a link).
  - Equal URLs share one position, numbered from 1 in order of first appearance. A card's image,
    title and "Read more" are therefore one link.
  - At most `MAX_TRACKED_LINKS = 100` distinct URLs, each ≤ 2048 characters (`Link.url`). Beyond
    either, the link is left as it is, untracked, with one WARNING naming the campaign id.
  - Cost if wrong: an issue with more than 100 links loses per-link stats for the rest.
- **T4. The plain-text part is not rewritten.** Its URLs are spelled out by the renderer in
  several shapes. Matching them back is fragile, and the spec's report needs per-link counts, not
  per-part coverage. Cost: clicks from text-only clients are not counted. `docs/tracking.md` says
  so.
- **T5. Tracking settings.**
  - Spec: `tracking_opens` and `tracking_clicks` are SYSTEM-scope, default `true`, and "off
    removes the pixel or the rewrite". There is **no per-tenant switch**: the spec has none, and
    one sender serves the install.
  - **Composition (B7).** The tick reads the settings once, when it starts (`dispatch_config()`,
    PR 4 Task 8), and composes every message of that tick with them. They are not frozen into
    the snapshot.
    - A change applies from the next tick, within about 60 s. `settings_for`'s cache of about
      30 s can delay it by one more tick.
    - A tick already running finishes with the settings it started with.
  - **Recording.** The settings also gate recording, read from
    `app.state.sm_newsletter.settings` on every request, so a change applies at once. With opens off, the pixel route still answers the GIF and writes
    nothing. With clicks off, the click route still redirects and writes nothing. "Off" therefore
    means "stop tracking", including mail already delivered.
  - Cost if wrong: an admin who switches tracking off briefly loses counts from that window. The
    settings note says so (Task 8).
- **T6. Forged, unknown and foreign tokens (no oracle).** Steps, in order:
  1. `tokens.parse` with the route's own purpose, `"o"` or `"c"` (no statement before it);
  2. the resolved-tenant check;
  3. the database.

  | Request | `/o/{token}.gif` | `/c/{token}/{N}` |
  |---|---|---|
  | MAC fails (incl. a token of another purpose, T17), `test`, too long, non-ASCII | the GIF, nothing written | 404, the fixed body |
  | Verifies, but the request resolved another tenant (S8) | the GIF, nothing written | 404, the fixed body |
  | Verifies, no link at `N` for that campaign (or `N` not 1–4 digits) | — | 404, the fixed body |
  | Verifies, link exists, no send row with `(id, tenant, campaign)` | the GIF, nothing written | 302 to the stored URL, nothing written |
  | Verifies, link and send exist, tracking on | the GIF, counted | 302 to the stored URL, counted |
  | Verifies, tracking off for that kind | the GIF, nothing written | 302, nothing written |

  - The 404 is the same bytes for every row that has one: `text/plain` `Not found`, `no-store`.
  - A token of another purpose fails `parse` like any forgery, so it does **no** database work:
    no session is opened (B1).
  - A verified token can only be minted with the host secret, so a verified holder learning that
    a position exists reveals nothing a forger could use.
  - The redirect target is always `newsletter_link.url` for the token's own campaign. A URL from
    the request is never used, and a stored value that is not `is_http_link` answers 404 instead
    (defence in depth).
  - Cost if wrong: none for safety. A purged send still redirects, which is what a reader expects.
- **T7. A click implies an open.** It sets `opened_at` (and `open_count = 1`) when that was empty,
  and bumps `open_unique_count` and `open_total_count` by 1 (spec: "A click also sets `opened_at`
  if it is empty"). Bumping the total too keeps `total ≥ unique`.
  - **Only while open tracking is on (B3).** `record_click` takes `count_open` (the route passes
    `settings.tracking_opens`). With opens off, a click records the click and leaves `opened_at`,
    `open_count` and the open counters alone.
  - Cost: none.
- **T8. One click row per `(send, link)`.**
  - `newsletter_click` gains `click_count` (`NOT NULL DEFAULT 1`) and a unique constraint
    `uq_newsletter_click_send_link (tenant_id, send_id, link_id)`. `clicked_at` means the first
    click.
  - A click is `insert_ignore`. Rowcount 1 means a new unique click on that link. Otherwise
    `UPDATE … SET click_count = click_count + 1`.
  - So per-link unique and total are exact under concurrency on both backends. The table is
    bounded by sends × links, so a replayed token cannot grow it.
  - Cost if wrong: no per-click timestamp after the first. The report never needs one, and the
    spec puts per-person timelines out of v1.
- **T9. Counters are race-free, in one transaction per event.**
  - Unique: `UPDATE newsletter_send SET opened_at = :now WHERE … AND opened_at IS NULL` (rowcount),
    and the same for `first_clicked_at`.
  - Totals: `SET n = n + 1`.
  - Campaign: one `UPDATE … SET open_total_count = open_total_count + 1, open_unique_count =
    open_unique_count + :u, …`.
  - Lock order: send row, then click row, then campaign row. PR 4's `rows.record` is also send
    before campaign, so no deadlock cycle.
  - One `finalize_session` per request.
- **T10. Privacy.**
  - The spec names no IP or user-agent storage, so the routes **never read**
    `request.client`, `User-Agent` or any `X-Forwarded-*`, and the tables have no such columns.
  - Nothing tries to detect Apple Mail Privacy Protection or link scanners. Detection without the
    IP and UA is impossible, and with them it is guesswork; the spec says label, don't fake it.
  - The UI says:
    - opens: "Approximate. Privacy features such as Apple Mail Privacy Protection load images
      automatically, so opens may be inflated";
    - clicks: "May include automated link scanners".
  - `docs/tracking.md` lists exactly what is stored per recipient.
  - Cost: none.
- **T11. Rate limits** are per IP and on `GET` only:
  - `/newsletter/o/`: `600/minute`. Gmail's and Apple's image proxies fetch from shared egress
    IPs right after a send.
  - `/newsletter/c/`: `300/minute`, as PR 4's one-click POST. A refused click breaks a reader's
    navigation, and corporate NAT shares IPs.
  - Cost if wrong: an attacker with a *valid* token inflates totals by ≤ 300/min per IP. Unique
    counts cannot be inflated (T8, T9), and forged tokens cost one HMAC and no query.
- **T12. Recording never breaks the answer (B4).**
  - The failure boundary is one `try` around **both** the recording statements and
    `finalize_session`. Any exception there:
    1. rolls the whole transaction back, so no counter is half-applied;
    2. is logged at WARNING with the send id only (A7: never the token);
    3. still returns the GIF or the 302.
  - The click route reads the link before that boundary. If *that* read fails, it answers 404.
  - Cost: silent undercounting during an outage, visible in logs.
- **T13. Response headers.**
  - Both routes:
    - `Cache-Control: no-store, no-cache, must-revalidate, private`;
    - `Pragma: no-cache`;
    - `Expires: 0`;
    - `Referrer-Policy: no-referrer`;
    - `X-Robots-Tag: noindex`.
  - The GIF is `image/gif`: the 43-byte transparent 1×1, a module constant.
  - The 302 is `RedirectResponse(url, status_code=302)` with the same headers.
- **T14. Report semantics.**
  - "Accepted" is `sent_count`: the relay took it. It is not labelled "delivered"; synchronous
    bounces only (spec).
  - **Rates (B5).**
    - The denominator is `sent_count`.
    - The numerators are unique opens and unique clicks **from sends whose status is `sent`**:
      `opens_unique_accepted` and `clicks_unique_accepted`, counted from `newsletter_send` when
      the report or list is read.
    - Every `sent` row bumped `sent_count` in the same transaction, so numerator ≤ denominator.
      A rate never passes 100 %, with no clamping anywhere.
    - Engagement on a row that is `failed/outcome_unknown`, or that arrives while the row is
      still `sending`, counts in the overall totals. It joins the rate's numerator only once the
      row is `sent`.
    - The overall totals (unique and total opens and clicks, from the campaign counters, every
      send) are shown separately, labelled "all messages".
    - The API returns raw counts and the UI computes rates. A rate with accepted = 0 shows `—`.
  - **Timeline (B6).** It counts **first** opens (`newsletter_send.opened_at`) and **first**
    clicks (`first_clicked_at`) in UTC calendar buckets.
    - **Hourly.** `b0 = started_at` floored to the UTC hour. Used when `now − b0 ≤ 72 h`.
      `n = min(72, max(1, ceil((now − b0) / 1 h)))`.
    - **Daily.** Otherwise `b0 = started_at` floored to the UTC midnight, and
      `n = min(90, max(1, ceil((now − b0) / 1 day)))`.
    - The window is `[b0, b0 + n × bucket)`, with an **exclusive** end. An event exactly at the
      end is excluded, and so is one before `b0`.
    - The points are the `n` contiguous bucket starts.
    - Events outside the window still count in the totals. The UI says "first 72 hours" /
      "first 90 days" and labels every point in UTC, so labels match the buckets.
  - Buckets are computed in Python in UTC (portable across SQLite and Postgres, ≤ one row per
    recipient).
  - No per-recipient report (spec non-goal).
  - Cost: a 60k-recipient report reads ≤ 60k timestamp pairs. Acceptable for a page load, and the
    page is not polled faster than 60 s.
- **T15. No chart library.** The timeline is a CSS bar list over a `<table>`, so it is accessible
  and testable in jsdom. No module uses `recharts` today, and adding it is not worth one chart.
  Cost: a plainer chart.
- **T16. Previews and test sends are never tracked.** They never go through the snapshot, so they
  carry no placeholders (spec: test sends have "no rows or tracking").
- **T17. Purpose-bound tokens (team-lead ruling on Q2, 2026-11-05).** This amends PR 4's S10.
  - `tokens.sign` and `tokens.parse` take a required keyword `purpose: Purpose`, where
    `Purpose = Literal["u", "o", "c"]` (unsubscribe, open, click).
  - The MAC message becomes `"newsletter|{purpose}|{tenant}|{campaign}|{send}"`. The token's
    shape is unchanged (`{tenant}.{campaign}.{send}.{mac}`). The purpose is never in the token;
    each route implies it.
  - A token minted for one purpose fails `parse` for both others. So a click or open URL leaked
    from browser history, a proxy log or a forwarded mail cannot unsubscribe anyone.
  - Each message carries three tokens, all minted in `compose` and never stored.
  - PR 4 is unreleased, so the unsubscribe MAC changes with no compatibility handling. Task 2
    updates every PR 4 caller and test.
  - There is no default for `purpose`: a caller that forgets it fails at once rather than
    minting the wrong capability.
  - The redirect still sends `Referrer-Policy: no-referrer`.
  - Cost: two more HMACs per message.
- **T18. Migration.** Exactly one revision off the single head at execution time
  (`5a1f7e77d9c6` when this was written; check with `scripts/check_migration_heads.py`). No
  branch label. It adds `newsletter_click.click_count` (server default `"1"`) and the unique
  constraint, via `batch_alter_table` as `0fa7184b108f` does. Nothing else: the link table, send
  columns and campaign counters exist since PR 2. The stack is unreleased, so no deployed rows
  need a data migration.
- **T19. Postgres databases.** Tests use `smpy_newsletter_test` and its xdist copies
  `smpy_newsletter_test_gw0`…`gw7`; drop and recreate all of them after Task 1, since
  `create_all` adds no constraint. The alembic scratch database is `smpy_newsletter_mig_check`
  (PR 4 ruling P1). Only `smpy_newsletter_*` names may be created.

## Global Constraints

- **Before every run.** Run `~/.claude/bin/wait-for-headroom` before every pytest, vitest, tsc,
  biome or alembic run. If it exits 1, stop and report.
- **Targeted tests only.** Never a full suite (`/ship` runs them once at the end of the stack).
  `-n 8` at most (`PYTEST_WORKERS=8`).
- **Shell.** Use `/usr/bin/ps`, never `ps`. One plain command per Bash call, literal paths.
- **Formatting.** Never a repo-wide `ruff format`; `uv run ruff format <touched files>` only.
- **Secrets and logs (A7).** Never log, return or echo a token, the host secret or the SMTP
  password. A log line may name a send id or campaign id. The tracking routes log nothing about
  the request (no IP, UA, path).
- **300-line cap** (`scripts/check_file_size.py`). At 280+ lines, split by responsibility. Watch
  `sending/deliver.py` (231), `campaigns/lifecycle.py` (245), `web/schemas/campaigns.py`, the
  PR 4 `CampaignEditor.tsx` and `SendingPanel.tsx`.
- **Layout** (`docs/module-layout.md`):
  - tracking domain code in `sm_newsletter/tracking/`;
  - HTTP in `web/endpoints|schemas|services`;
  - tests mirror the areas (`tests/tracking/`, `tests/web/`).
- **Pages rule.** The only new file under `sm_newsletter/pages/` is `CampaignReport.tsx` (a real
  Inertia page with `export default`). Components go to `ui/components/report/`.
- **Locales.** Every new key goes into `en.json` **and** `de.json` in the same commit; run
  `uv run python scripts/check_locales.py`. UI strings use `t(keys.newsletter.…)` with no
  `defaultValue`. No new error code is added (the report reuses `not_found`); PR 4's
  `test_error_catalogue.py` keeps that honest.
- **Admin routers.** `Depends(bind_admin)` first, then `RequiresPermission(PERM_*)`. Every
  campaign read goes through `access.require_campaign(…, roles=caller_roles(request))` (C4).
- **Public routes.**
  - Exempted in `register_public_routes`; no `RequiresCsrf` (GET only).
  - The tenant comes from the verified token; a resolved tenant that differs means forged (S8).
  - Bind with `tenant_scope(token.tenant_id)` and a session from
    `app.state.sm.db.session_factory`.
- **Contracts.** Tracking touches no records table and calls no records contract.
- **Tenancy.** Every Core statement over a newsletter table pins `tenant_id`.
- **Settings.** Web: `app.state.sm_newsletter.settings`. Worker: the `settings` that
  `dispatch_config()` already hands the tick. No environment variables.
- **Commits outside a request** finish with `simple_module_db.finalize_session(session)`.
- **Python tests.** `uv run --directory modules/newsletter pytest <paths> -q -p no:cacheprovider`.
  - **Postgres:** prefix
    `SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_test`.
- **JS.** `npx vitest run <paths>`, `npx tsc --noEmit -p modules/newsletter/tsconfig.json`,
  `npx biome check modules/newsletter`.
- **Commits** end with the session's `Claude-Session:` line.

## Review Focus

1. **Concurrent first opens** (Apple's proxy prefetch and the reader, within milliseconds).
   Expected: `open_unique_count == 1` and `open_total_count == 2`, on SQLite (file) and Postgres.
   Pinned in Task 5, `test_concurrent_first_opens_count_one_unique`.
2. **A link scanner clicks before the reader does, the same link twice.** Expected:
   - both redirect;
   - the per-link and campaign unique counts are 1 and the totals 2;
   - `first_clicked_at` is the scanner's time;
   - the report labels clicks "may include automated link scanners".

   Pinned in Task 5 (`test_repeat_click_same_link_one_unique`) and Task 10 (the label).
3. **A link whose URL has a query string, `&`, a fragment or non-ASCII.** Expected: the 302
   `Location` is exactly the author's URL. The `&amp;` in the HTML is decoded before storing, and
   is never double-encoded. Pinned in Task 2 (`test_prepare_unescapes_href`) and Task 6
   (`test_click_redirects_to_exact_stored_url`).
4. **Tracking switched off mid-campaign.** Expected:
   - messages composed afterwards carry no pixel and the original URLs;
   - already-delivered pixels and links still answer (GIF, 302) and count nothing.

   Pinned in Task 4 (`test_tick_follows_tracking_settings`) and Task 6
   (`test_tracking_off_records_nothing`).
5. **A multi-tenant apex with a foreign or mismatched token.** Expected:
   - A's genuine token with the request resolving B: the GIF or a 404, and nothing written in
     either tenant;
   - a correctly signed token pairing A with B's send id: the same.

   Pinned in Task 6, `test_tracking_tenancy.py`.

---

### Task 1: Click rows per (send, link) and the migration

**Files:**
- Modify: `modules/newsletter/sm_newsletter/models/link.py`
- Create: `host/migrations/versions/<rev>_newsletter_tracking.py`
- Test: `modules/newsletter/tests/core/test_models.py`

**Interfaces (Produces):**
```python
class Click(Base, MultiTenantMixin, table=True):   # "newsletter_click"
    __table_args__ = (UniqueConstraint("tenant_id", "send_id", "link_id",
                                       name="uq_newsletter_click_send_link"),)
    id: int | None            # big_pk, unchanged
    send_id: int              # unchanged
    link_id: int              # unchanged
    clicked_at: datetime      # unchanged column; now "the first click"
    click_count: int = Field(default=1, sa_column_kwargs={"nullable": False, "server_default": "1"})
```

- [ ] **Step 1: Failing tests** in `tests/core/test_models.py`:
  - `test_click_is_unique_per_send_and_link`: a second `Click` with the same
    `(tenant_id, send_id, link_id)` raises `IntegrityError`. Another link or another send is
    fine.
  - `test_click_count_defaults_to_one`: a Core insert without `click_count` reads back 1
    (server default).
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/core/test_models.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement the model.** The docstring says one row per recipient per link: the
  first click's time and how many (T8).
- [ ] **Step 4: Generate the revision** against a scratch SQLite database, never `host/app.db`.
  1. From the root, with `SM_DATABASE_URL=sqlite+aiosqlite:////tmp/newsletter-pr5-mig.db`, run
     `uv run --project host alembic -c host/alembic.ini upgrade heads`.
  2. Run `… revision --autogenerate -m "newsletter tracking"`.
  3. Check the file. It must:
     - add `click_count` with `server_default="1"`;
     - create `uq_newsletter_click_send_link`, both inside `batch_alter_table("newsletter_click")`;
     - have no branch label;
     - have `down_revision` equal to the prior single head.
  4. Delete unrelated drift and report it. Write a docstring like `5a1f7e77d9c6`'s.
  5. Run `upgrade heads`, `check` ("No new upgrade operations detected"), `downgrade <parent>`,
     `upgrade heads` and `check` again. Delete the scratch file.
- [ ] **Step 5: Postgres.**
  1. `PGPASSWORD=postgres createdb -h localhost -U postgres smpy_newsletter_mig_check`.
  2. With `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_mig_check`,
     run `upgrade heads`, `check`, `downgrade <parent>`, `upgrade heads` and `check`.
  3. Drop it. Drop and recreate `smpy_newsletter_test` and `smpy_newsletter_test_gw0`…`gw7`
     (T19).
- [ ] **Step 6: Run** `uv run python scripts/check_migration_heads.py` (one head, the new one).
  Then run the Step 2 test on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 7: Commit** `feat(newsletter): one click row per send and link, with a count`.

### Task 2: Purpose-bound tokens, link rewriting and the pixel

**Files:**
- Create:
  - `sm_newsletter/tracking/__init__.py` (docstring: what the area holds)
  - `sm_newsletter/tracking/rewrite.py`
- Modify:
  - `sm_newsletter/core/constants.py`
  - `sm_newsletter/core/tokens.py`: `Purpose`, the `purpose` keyword (T17), `open_url`, `click_url`
  - `sm_newsletter/sending/compose.py`: the unsubscribe token is minted with `purpose="u"`
  - `sm_newsletter/web/services/unsubscribe.py` (PR 4 Task 10): parse with `purpose="u"`
  - `sm_newsletter/content/urls.py` (`is_http_link`)
  - `sm_newsletter/content/merge.py` (`CAPABILITY_TAGS`)
- Modify (PR 4 tests that mint or parse a token; add `purpose="u"`, behaviour unchanged):
  - `tests/core/test_worker_secret.py:54` and `:64`
  - `tests/core/test_worker_dispatch.py:168`
  - `tests/support/dispatch_world.py:75` (`token_of`)
  - `tests/sending/test_compose.py`
  - `tests/web/test_unsubscribe.py`
  - `tests/web/test_unsubscribe_tenancy.py`
  - any other hit of `grep -rn "tokens\.\(sign\|parse\)" modules/newsletter`
- Test:
  - `tests/tracking/__init__.py`
  - `tests/tracking/test_rewrite.py`
  - `tests/core/test_tokens.py`
  - `tests/content/test_merge.py`
  - `tests/web/test_unsubscribe.py` (one new case)

**Interfaces (Produces):**
```python
# core/constants.py
OPEN_PREFIX = f"{PUBLIC_PREFIX}o/"
CLICK_PREFIX = f"{PUBLIC_PREFIX}c/"
MAX_TRACKED_LINKS = 100
MAX_LINK_URL = 2048          # Link.url's max_length
# core/tokens.py (T17)
Purpose = Literal["u", "o", "c"]
PURPOSES: Final = ("u", "o", "c")
def sign(secret: str, *, purpose: Purpose, tenant_id: str, campaign_id: int, send_id: int) -> str
    # ValueError on "" secret, a bad tenant, or a purpose not in PURPOSES
def parse(secret: str, token: object, *, purpose: Purpose) -> SendToken | None   # never raises; None for an unknown purpose
# _mac message: f"newsletter|{purpose}|{tenant_id}|{campaign_id}|{send_id}"
def open_url(public_base: str, token: str) -> str              # f"{base}{OPEN_PREFIX}{token}.gif"
def click_url(public_base: str, token: str, position: int) -> str  # f"{base}{CLICK_PREFIX}{token}/{position}"
# content/urls.py
def is_http_link(value: str) -> bool      # _plain(value) and _http(value)
# content/merge.py
CAPABILITY_TAGS = (UNSUBSCRIBE_TAG, "{{open_pixel}}", "{{link:")   # substring test, as today
# tracking/rewrite.py
PIXEL_TAG = "{{open_pixel}}"
@dataclass(frozen=True)
class Tracking:
    opens: bool
    clicks: bool
TRACKING_OFF = Tracking(opens=False, clicks=False)
@dataclass(frozen=True)
class Prepared:
    html: str
    links: tuple[str, ...]          # links[i] is position i + 1, unescaped
def prepare(html: str, *, own_base: str) -> Prepared
    # ValueError if html already holds "{{link:" or PIXEL_TAG
def fill(html: str, *, open_token: str, click_token: str, public_base: str,
         links: Mapping[int, str], tracking: Tracking) -> str
    # open_token minted with purpose "o", click_token with "c" (the caller's job, Task 4);
    # runs on the trusted snapshot BEFORE personalisation (B2);
    # ValueError for a {{link:N}} with N not in links when clicks are off
PIXEL_HTML: str   # '<img src="{src}" width="1" height="1" alt="" border="0" style="display:block;width:1px;height:1px;border:0;margin:0;padding:0">'
```
**`prepare`.**
- Match `<a href="([^"]*)"` (the only shape the renderer and `richtext` emit).
- Rewrite per T3: `value = html.unescape(group)`, then rewrite when `is_http_link(value)`, it is
  not under `own_base.rstrip("/") + PUBLIC_PREFIX` (when `own_base` is set), and
  `len(value) ≤ MAX_LINK_URL`. Equal values reuse a position; the 101st distinct one is left
  as-is, with one WARNING.
- Insert `PIXEL_TAG` immediately before the last `</body>`, or append it if there is none.

**`fill`.**
- With `tracking.clicks`: `href="{{link:N}}"` →
  `href="{html.escape(click_url(public_base, click_token, N), quote=True)}"`. Otherwise →
  `html.escape(links[N], quote=True)`.
- `PIXEL_TAG` → `PIXEL_HTML` with the escaped `open_url(public_base, open_token)` when
  `tracking.opens`, else `""`.
- The placeholder regex is `\{\{link:(\d{1,4})\}\}`.

- [ ] **Step 1: Failing tests.**
  - `tests/core/test_tokens.py`:
    - `test_purpose_is_bound`, parametrized over every ordered pair of distinct purposes: a
      token signed for one fails `parse` for the other, and parses for its own;
    - `test_unknown_purpose`: `sign(…, purpose="x")` raises `ValueError`;
      `parse(…, purpose="x")` returns `None`;
    - `test_mac_message_names_the_purpose`: the MAC equals HMAC-SHA256 over
      `b"newsletter|o|default|3|9"`, truncated to 16 bytes and base64url (a pinned vector, so
      the message cannot drift silently);
    - `open_url` and `click_url` shapes, with a trailing slash on the base stripped;
    - the existing cases, with `purpose="u"`.
  - `tests/web/test_unsubscribe.py::test_open_and_click_tokens_cannot_unsubscribe`: tokens for
    the same send signed with `purpose="o"` and `"c"` and POSTed to `/newsletter/u/…` give the
    forged-token page. The subscriber stays `confirmed`, with no suppression and count 0.
  - `tests/tracking/test_rewrite.py`:
    - `test_prepare_rewrites_http_links_in_order`: two different links, then the first again,
      give positions 1, 2, 1 and `links == (a, b)`;
    - `test_prepare_skips_untrackable`: `{{unsubscribe_url}}`, `mailto:x@example.org`,
      `https://pub.example.org/newsletter/brand/logo`, a `<img src="https://…">`, and
      `javascript:x`, each untouched;
    - `test_prepare_unescapes_href`: `href="https://e.org/?a=1&amp;b=2#f"` is stored as
      `https://e.org/?a=1&b=2#f`;
    - `test_prepare_caps_distinct_links`: 101 distinct URLs make 100 links, and the 101st href is
      unchanged;
    - `test_prepare_leaves_overlong_url`: 2049 characters, untouched;
    - `test_prepare_inserts_one_pixel_before_body_end`;
    - `test_prepare_refuses_existing_placeholders` → `ValueError`;
    - `test_card_links_share_a_position`: render a real `ArticleCard` body with
      `content.render.render`, then `prepare`, and assert one link;
    - `test_fill_clicks_on`: each href is
      `https://pub.example.org/newsletter/c/<click_token>/<N>`;
    - `test_fill_clicks_off_restores_original`: the URL is re-escaped, `&amp;` included;
    - `test_fill_opens_on_off`: the pixel `src` is `…/newsletter/o/<open_token>.gif`, or no
      `<img` with `width="1"` at all;
    - `test_fill_unknown_position_clicks_off_raises`;
    - `test_fill_leaves_merge_tags`: `{{first_name|x}}` survives `fill`.
  - `test_merge.py`: `check_no_capability("{{open_pixel}}")` and `("{{link:1}}")` raise, and
    `check_merge("{{link:1}}")` raises.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/tracking/test_rewrite.py tests/core/test_tokens.py tests/content/test_merge.py tests/web/test_unsubscribe.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Update every PR 4 caller and test listed above to pass `purpose="u"`. No behaviour changes.
  - Fix the `core/tokens.py` docstring: the MAC is per purpose (T17), amending S10.
  - `rewrite.py` stays under 150 lines.
- [ ] **Step 4: Run** the Step 2 command, then the PR 4 token users:
  `uv run --directory modules/newsletter pytest tests/core/test_worker_secret.py tests/core/test_worker_dispatch.py tests/sending/test_compose.py tests/sending/test_dispatch_budget.py tests/web/test_unsubscribe_tenancy.py -q -p no:cacheprovider`
  on SQLite, and the unsubscribe files on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): purpose-bound send tokens; link placeholders and the open pixel`.

### Task 3: The snapshot writes the link table

**Files:**
- Modify:
  - `sm_newsletter/campaigns/snapshot.py`
  - `sm_newsletter/campaigns/lifecycle.py` (the two call sites)
- Test:
  - `tests/campaigns/test_snapshot.py`
  - `tests/campaigns/test_lifecycle.py`

**Interfaces:**
- Consumes: `rewrite.prepare` (Task 2).
- Produces:
```python
@dataclass(frozen=True)
class Snapshot:
    render: CampaignRender
    links: tuple[str, ...]
def build_render(settings, campaign, ctx, *, tenant_id: str, now: datetime) -> Snapshot
    # render.html is prepare(template.html, own_base=ctx.public_base).html
async def store_render(session: AsyncSession, snap: Snapshot) -> CampaignRender
    # drop_render first, then the row, then newsletter_link rows (Core insert, tenant pinned,
    # position = index + 1)
async def snapshot_render(app, session, *, tenant_id, campaign, now) -> CampaignRender   # unchanged signature
async def drop_render(session, *, tenant_id: str, campaign_id: int) -> None
    # also: DELETE newsletter_click WHERE tenant_id=:t AND link_id IN (SELECT id FROM newsletter_link
    #       WHERE tenant_id=:t AND campaign_id=:c); then DELETE newsletter_link (pinned)
```

- [ ] **Step 1: Failing tests.**
  - `test_snapshot.py`:
    - `test_snapshot_stores_links_and_placeholders`: a body with a Button
      (`https://e.org/a`) and an Image with `href` `https://e.org/b`. Expected: link rows at
      positions 1 and 2 with those URLs and the tenant; the render HTML holds `{{link:1}}`,
      `{{link:2}}` and exactly one `{{open_pixel}}`, and no `https://e.org/a`; the text part
      still holds `https://e.org/a` (T4).
    - `test_snapshot_replaces_links`: a second snapshot after changing the body leaves only
      the new links.
    - `test_drop_render_drops_links`.
  - `test_lifecycle.py`:
    - `test_unschedule_drops_links`;
    - `test_schedule_writes_links_in_same_transaction`: a schedule refused after the snapshot
      is built (A7 subject check) leaves no link rows.
  - The existing `test_schedule_now_snapshots_and_schedules` stays green (`{{unsubscribe_url}}`
    still a tag).
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/campaigns/test_snapshot.py tests/campaigns/test_lifecycle.py tests/campaigns/test_lifecycle_actions.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** `lifecycle.py` changes only its `build_render`/`store_render` lines.
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): the render snapshot records the campaign's tracked links`.

### Task 4: Compose with tracking; the dispatcher passes the settings

**Files:**
- Modify:
  - `sm_newsletter/sending/compose.py`
  - `sm_newsletter/sending/deliver.py` (`_due` loads the links; `deliver_one` takes `tracking`)
  - `sm_newsletter/sending/dispatch.py` (`_Run.tracking` from `settings`)
- Test:
  - `tests/sending/test_compose.py`
  - `tests/sending/test_deliver.py`
  - `tests/sending/test_dispatch_tracking.py` (new)
  - `tests/core/test_worker_dispatch.py` (PR 4 Task 8's A7 log test)

**Interfaces:**
- Consumes: `fill`, `Tracking`, `TRACKING_OFF` (Task 2).
- Produces:
```python
def compose(render: CampaignRender, send: Send, *, secret: str, list_unsubscribe: bool,
            tracking: Tracking = TRACKING_OFF, links: Mapping[int, str] | None = None) -> OutgoingMessage
    # mints three tokens for the send (T17): purpose "u" for the unsubscribe URL and
    # List-Unsubscribe, "o" for the pixel, "c" for the links.
    # Order (B2): html = fill(render.html, ...) on the trusted snapshot FIRST, then personalise
    # (first name, unsubscribe URL). Recipient data therefore never reaches fill, and a first
    # name holding "{{open_pixel}}" or "{{link:0}}" stays inert text.
    # A fill ValueError propagates (the caller fails the row invalid_message, as for a bad header).
async def deliver_one(..., tracking: Tracking = TRACKING_OFF) -> Step | None   # new keyword
# deliver._due returns (row, list_key, render, links: dict[int, str]); links read pinned to
# tenant and campaign, in the same read phase
```
The default keeps PR 4's tests unchanged. Only `dispatch.tick` passes the real value:
`Tracking(opens=settings.tracking_opens, clicks=settings.tracking_clicks)`.

- [ ] **Step 1: Failing tests.**
  - `test_compose.py`:
    - `test_compose_tracking_tokens_are_purpose_bound`: a render holding `{{link:1}}` and the
      pixel, with clicks and opens on.
      - The click URL's token parses only with `purpose="c"`, the pixel's only with `"o"`, and
        the `List-Unsubscribe` token only with `"u"`.
      - All three name the row's `(tenant, campaign, send)`.
      - The three tokens differ.
      - The pixel `src` ends `.gif`, and the text part has no `/newsletter/c/`.
    - `test_compose_tracking_off_restores_links`.
    - `test_recipient_data_cannot_add_tracking` (B2). A render whose body text and an image
      `alt` attribute both hold `{{first_name}}`, with one link and one pixel placeholder, is
      composed for a row whose `first_name` is `{{open_pixel}} {{link:0}}`. Parse the HTML with
      `html.parser.HTMLParser`, and assert:
      - exactly one `<img width="1">` pixel;
      - exactly one `/newsletter/c/` href (the snapshot's own link);
      - the `alt` attribute's value is the escaped first name, intact, with no `<` or `"` break;
      - the literal `{{open_pixel}}` appears only as text, never as a tag.
    - `test_compose_default_is_untracked`: no `/newsletter/o/`, and an existing render without
      placeholders is unchanged.
    - `test_subject_never_tracked`.
  - `test_deliver.py::test_deliver_passes_tracking_and_links`: a seeded link row at position 1,
    and the sent message's HTML holds `/newsletter/c/` with `tracking=Tracking(True, True)`.
  - `test_dispatch_tracking.py` (SQLite file and Postgres; `dispatch_world`):
    - `test_tick_follows_tracking_settings` (B7). Tick 1 runs with both settings on and gives
      the pixel and click URLs. The settings handed to the next tick have
      `tracking_opens=False` and `tracking_clicks=False`. Tick 2's messages carry no pixel and
      the original URLs (Review Focus 4).
    - `test_settings_fixed_for_one_tick` (B7): a settings change made from `on_send` during
      tick 1 does not change tick 1's later messages.
  - `test_worker_dispatch.py::test_no_token_in_any_log`: also asserts no record contains
    `/newsletter/o/` or `/newsletter/c/`.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/sending/test_compose.py tests/sending/test_deliver.py tests/sending/test_dispatch_tracking.py tests/core/test_worker_dispatch.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** `deliver.py` stays under 260 lines. If it grows past that, move
  `_due` into `sending/due.py` (moves only).
- [ ] **Step 4: Run** it on SQLite and on Postgres (`test_worker_dispatch.py` is SQLite-only).
  Then run `tests/sending/test_dispatch_budget.py tests/sending/test_dispatch_control.py tests/sending/test_deliver_races.py tests/sending/test_deliver_stops.py` to show PR 4 is unchanged. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): personalise tracked links and the pixel per recipient`.

### Task 5: Recording opens and clicks

**Files:**
- Create: `sm_newsletter/tracking/record.py`
- Create: `tests/support/tracking_world.py`
- Test: `tests/tracking/test_record.py`, `tests/tracking/test_record_races.py`

**Interfaces (Produces):**
```python
# tracking/record.py — callers bind the tenant and commit (finalize_session)
async def record_open(session: AsyncSession, *, tenant_id: str, campaign_id: int, send_id: int,
                      now: datetime) -> bool
    # False (nothing written) when the send row does not exist; True when counted.
    # 1. UPDATE send SET open_count = open_count + 1 WHERE id, tenant_id, campaign_id   (rowcount 0 -> False)
    # 2. UPDATE send SET opened_at = :now WHERE ... AND opened_at IS NULL               (first)
    # 3. UPDATE campaign SET open_total_count + 1, open_unique_count + first WHERE id, tenant_id
async def link_url(session: AsyncSession, *, tenant_id: str, campaign_id: int, position: int) -> tuple[int, str] | None
    # (link id, url), pinned; None when absent or not is_http_link(url)
async def record_click(session: AsyncSession, *, tenant_id: str, campaign_id: int, send_id: int,
                       link_id: int, now: datetime, count_open: bool) -> bool
    # False when the send row does not exist. Order (T9 lock order):
    # 1. only when count_open (B3):
    #    UPDATE send SET opened_at=:now, open_count = open_count + 1 WHERE ... AND opened_at IS NULL  -> implied open
    # 2. UPDATE send SET first_clicked_at=:now WHERE ... AND first_clicked_at IS NULL                  -> unique click
    #    (if both rowcounts are 0, SELECT 1 to tell "exists" from "missing"; missing -> False)
    # 3. insert_ignore(Click, [{tenant_id, send_id, link_id, clicked_at: now, click_count: 1}],
    #                  conflict=["tenant_id", "send_id", "link_id"]); 0 inserted -> UPDATE click_count + 1
    # 4. _bump_campaign(session, tenant_id=, campaign_id=, **deltas): one UPDATE campaign SET
    #    click_total_count + 1, click_unique_count + unique, open_unique_count + implied,
    #    open_total_count + implied (record_open uses it too; a module-level function so B4's
    #    partial-failure test can patch it)
async def _bump_campaign(session: AsyncSession, *, tenant_id: str, campaign_id: int, **deltas: int) -> None
# tests/support/tracking_world.py
async def sent_campaign(state, tenant: str = "default", *, links: Sequence[str] = ("https://e.org/a",),
                        recipients: int = 1) -> tuple[int, list[int]]   # (campaign id, send ids), rows "sent"
async def counters(state, tenant: str, campaign_id: int) -> dict[str, int]   # the four open/click counters
async def set_send(state, tenant: str, send_id: int, **values) -> None      # e.g. status="failed", error_kind=...
async def clicks(state, tenant: str) -> list[Click]
```

- [ ] **Step 1: Failing tests** (SQLite and Postgres).
  - `test_record.py`:
    - `test_first_open_counts_unique_and_total`;
    - `test_second_open_counts_total_only`: `opened_at` is unchanged and `open_count == 2`;
    - `test_open_for_missing_send_writes_nothing`;
    - `test_open_pins_tenant`: B's send id under `tenant_id="A"` returns `False`, and B is
      unchanged;
    - `test_click_implies_open` (T7): unique and total opens 1, `opened_at == now`;
    - `test_click_after_open_does_not_count_open`;
    - `test_click_without_count_open_leaves_opens` (B3): `count_open=False` on a never-opened
      send leaves `opened_at` `None`, `open_count` 0 and both open counters 0. The click counters
      move.
    - `test_repeat_click_same_link_one_unique` (Review Focus 2): link unique 1 / total 2,
      campaign `click_unique_count == 1` and `click_total_count == 2`, and `first_clicked_at`
      from the first call;
    - `test_click_two_links_one_unique_recipient`: campaign click unique 1, total 2, and two
      click rows;
    - `test_link_url_missing_or_foreign_campaign`: another campaign's position returns `None`;
    - `test_link_url_refuses_non_http_stored_value`: a row written directly with `javascript:x`
      returns `None`.
  - `test_record_races.py` (file SQLite via `make_db_state(file=…)`, and Postgres):
    - `test_concurrent_first_opens_count_one_unique` (Review Focus 1): `asyncio.gather` of two
      `record_open` in two sessions, each committed. Expected: unique 1, total 2.
    - `test_concurrent_first_clicks_one_row`: two `record_click` on the same send and link.
      Expected: one click row with `click_count == 2`, campaign click unique 1, total 2.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/tracking -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** `record.py` stays under 180 lines.
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): race-free open and click counters`.

### Task 6: The public open and click routes

**Files:**
- Create:
  - `sm_newsletter/web/services/tracking.py`
  - `sm_newsletter/web/endpoints/tracking.py`
- Modify:
  - `sm_newsletter/module.py`: `register_public_routes` adds both prefixes for GET;
    `register_rate_limits` adds two rules; `mount_public_routes` includes the tracking router,
    guarded by its own path the way PR 4 Task 10 guards the unsubscribe router.
  - `tests/support/app.py`: mount the tracking router, following PR 4's public routers.
- Test:
  - `tests/web/test_tracking_routes.py`
  - `tests/web/test_tracking_tenancy.py`
  - `tests/core/test_module_boot.py`
  - `tests/web/test_route_guards.py` (public and unguarded assertion)

**Interfaces:**
- Consumes: `tokens.parse`, `tokens.host_secret`, `tenancy._resolved`, `tenant_scope`
  (PR 4), and `record_open`, `link_url`, `record_click` (Task 5).
- Produces:
```python
# web/services/tracking.py
async def open_by_token(app, token: str, *, resolved_tenant: str | None, now: datetime) -> None
    # never raises; parse(purpose="o"); T5 gate (settings.tracking_opens), T6, T12
async def click_by_token(app, token: str, position: str, *, resolved_tenant: str | None,
                         now: datetime) -> str | None
    # the redirect URL or None (-> 404); parse(purpose="c"); T5 gate (settings.tracking_clicks)
    # skips only the record; record_click(count_open=settings.tracking_opens) (B3)
# web/endpoints/tracking.py
GIF: Final[bytes]            # the 43-byte transparent GIF89a
NO_STORE: Final[dict[str, str]]   # T13 headers
router = APIRouter(tags=["newsletter-public"])
@router.get(constants.OPEN_PREFIX + "{token}.gif")                -> Response(GIF, media_type="image/gif")
@router.get(constants.CLICK_PREFIX + "{token}/{position}")        -> RedirectResponse(302) | 404 text/plain "Not found"
# module.py
registry.add_prefix(constants.OPEN_PREFIX, methods={"GET"})
registry.add_prefix(constants.CLICK_PREFIX, methods={"GET"})
rates.add_prefix(constants.OPEN_PREFIX, RateLimitRule("600/minute", key="ip", methods=frozenset({"GET"})))
rates.add_prefix(constants.CLICK_PREFIX, RateLimitRule("300/minute", key="ip", methods=frozenset({"GET"})))
```
- **`position`** is a `str` path parameter, refused unless it is 1–4 digits, so FastAPI never
  answers a 422 that would differ from the 404.
- **The service order** (T6):
  1. `secret` empty → nothing;
  2. `parse` with the route's purpose. A wrong purpose is a forgery: no session is opened (B1);
  3. resolved tenant mismatch;
  4. `with tenant_scope(tok.tenant_id)` and one session;
  5. the click route reads `link_url`, outside the failure boundary (a failure here → 404);
  6. **the failure boundary (B4):**
     ```python
     try:
         await record_*(...)
         await finalize_session(session)
     except Exception:
         await session.rollback()
         logger.warning(…send_id…)
     ```
     The answer (GIF or 302) is returned either way.
- **The module docstring** says why there is no CSRF (GET, no state a forger can usefully
  change), why the tenant comes from the token (S8), and that the routes never read the client
  address or user agent (T10).

- [ ] **Step 1: Failing tests.**
  - `test_tracking_routes.py` (SQLite and Postgres; `build_app(settings=…)` with
    `tracking_world.sent_campaign` and `tokens.sign(SECRET, purpose=…, …)`):
    - `test_wrong_purpose_is_forged`, parametrized (B1):
      - a `"u"` or `"c"` token on `/o/`: the identical GIF;
      - a `"u"` or `"o"` token on `/c/`: the identical 404;
      - each with `app.state.sm.db.session_factory` replaced by one that raises, which proves no
        database work.
    - `test_open_returns_gif_and_counts`: 200, `image/gif`, the body equals `GIF`, the T13
      headers, and the counters move;
    - `test_open_identical_for_real_forged_test`: the body and headers are equal for a real
      token, `test`, `x.1.1.AAAA`, a 201-character token and a valid MAC with an unknown send
      id. Only the real one writes;
    - `test_open_path_with_dotted_tenant`: tenant `org.a` round-trips through the
      `{token}.gif` route;
    - `test_click_redirects_to_exact_stored_url` (Review Focus 3): a link
      `https://e.org/p?a=1&b=2#x` gives 302 with exactly that `Location` and the T13 headers,
      and counts;
    - `test_click_unknown_position_404`, `test_click_bad_position_404` (`0x1`, `12345`, `-1`):
      identical 404 bodies;
    - `test_click_forged_404_no_query`: `app.state.sm.db.session_factory` is replaced by one
      that raises; a forged token still answers the 404;
    - `test_click_missing_send_redirects_without_counting`;
    - `test_tracking_settings_matrix` (Review Focus 4, B3), parametrized over all four
      `(tracking_opens, tracking_clicks)` pairs. One pixel GET and one click GET on a
      never-opened send. Every case gives the identical GIF and the 302. What is written:

      | opens | clicks | written |
      |---|---|---|
      | on | on | the open counted (unique 1, total 1); the click counted; the click does not add a second unique open |
      | on | off | the pixel's open only, with no click row and no click counters |
      | off | on | the click only, with `opened_at` `None` and the open counters 0 |
      | off | off | nothing |
    - `test_commit_failure_still_answers` (B4): `finalize_session` in the service is
      monkeypatched to raise. Both routes still answer the GIF and the 302. A fresh session
      shows no counter, `opened_at` or click row changed. The log holds the send id and not the
      token's MAC.
    - `test_partial_failure_rolls_back` (B4): `record._bump_campaign` is monkeypatched to raise,
      after the send `UPDATE`s and the click insert have run. The route answers the 302, and a
      fresh session shows `opened_at`, `first_clicked_at` and `open_count` unchanged and no click
      row.
    - `test_routes_ignore_client_identity`: a request with `User-Agent`, `X-Forwarded-For` and
      `X-Real-IP` set; `inspect.getsource` of the service and endpoint modules contains none of
      `user_agent`, `client.host`, `x-forwarded`.
  - `test_tracking_tenancy.py` (A9-style, distinct real ids in tenants A and B; snapshot every
    counter, click row and `opened_at` in both tenants before and after):
    - `test_signed_pairing_a_with_b_send_changes_nothing` (both routes);
    - `test_resolved_tenant_mismatch_changes_nothing`: A's genuine token with `x-tenant: B`
      gives the GIF, or 404 for a click, and nothing changes;
    - `test_multi_tenant_apex_binds_the_tokens_tenant`: a multi app with no `x-tenant`; A's
      token counts in A only.
  - `test_module_boot.py`:
    - the public registry matches `GET` on both prefixes and not `POST`;
    - the rate registry gives `600/minute` for `/newsletter/o/x.gif` and `300/minute` for
      `/newsletter/c/x/1`, through `match`.
  - `test_route_guards.py::test_tracking_routes_are_public_and_unguarded`, modelled on the logo
    test: the router has exactly the two GET routes and neither carries `bind_admin` nor a
    `RequiresPermission`.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/web/test_tracking_routes.py tests/web/test_tracking_tenancy.py tests/core/test_module_boot.py tests/web/test_route_guards.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Each file stays under 160 lines.
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): public open pixel and click redirect, tenant from the token`.

### Task 7: The report service and API; list metrics

**Files:**
- Create:
  - `sm_newsletter/tracking/report.py`
  - `sm_newsletter/tracking/timeline.py`
  - `sm_newsletter/web/schemas/report.py`
  - `sm_newsletter/web/endpoints/report_api.py`
- Modify:
  - `sm_newsletter/web/endpoints/__init__.py` (include the router)
  - `sm_newsletter/web/schemas/campaigns.py`: `CampaignSummary` gains `started_at`,
    `finished_at`, `opens_unique_accepted` and `clicks_unique_accepted` (B5). Move `started_at`
    and `finished_at` there from PR 4's `CampaignDetail`.
  - `sm_newsletter/web/endpoints/campaigns_api.py` (`list_campaigns`): fills the two accepted
    counts from one `accepted_engagement` query for the page's ids.
- Test:
  - `tests/tracking/test_timeline.py`
  - `tests/tracking/test_report.py`
  - `tests/web/test_report_api.py`
  - `tests/web/test_route_guards.py` (`EXPECTED`)
  - `tests/web/test_campaigns_api.py` (list fields)

**Interfaces (Produces):**
```python
# tracking/timeline.py (pure)
HOURLY_WINDOW = timedelta(hours=72)
MAX_DAYS = 90
Bucket = Literal["hour", "day"]
@dataclass(frozen=True)
class Point: at: datetime; opens: int; clicks: int
def bucketize(opens: Sequence[datetime], clicks: Sequence[datetime], *, start: datetime,
              now: datetime) -> tuple[Bucket, list[Point]]
    # exactly the T14 / B6 rule: UTC calendar buckets, b0 floored, n capped at 72 / 90 (min 1),
    # window [b0, b0 + n*bucket) with an exclusive end; events outside dropped; naive = UTC
# tracking/report.py
@dataclass(frozen=True)
class LinkStat: position: int; url: str; unique: int; total: int
@dataclass(frozen=True)
class Report:
    campaign_id: int; status: str; started_at: datetime | None; finished_at: datetime | None
    recipients: int; sent: int; failed: int; bounced: int; suppressed: int; skipped: int; unsubscribed: int
    opens_unique: int; opens_total: int; clicks_unique: int; clicks_total: int   # every send (campaign counters)
    opens_unique_accepted: int; clicks_unique_accepted: int                       # sends with status 'sent' (B5)
    tracking_opens: bool; tracking_clicks: bool
    links: list[LinkStat]          # unique desc, total desc, position asc
    bucket: Bucket; timeline: list[Point]
async def link_stats(session, *, tenant_id: str, campaign_id: int) -> list[LinkStat]
    # Link LEFT JOIN Click (both pinned): COUNT(click.id), COALESCE(SUM(click_count), 0), GROUP BY link
async def accepted_engagement(session, *, tenant_id: str, campaign_ids: Sequence[int]) -> dict[int, tuple[int, int]]
    # B5: {campaign_id: (opens, clicks)} over sends with status 'sent'; one pinned GROUP BY with
    # SUM(CASE WHEN opened_at IS NOT NULL ...); a campaign with none maps to (0, 0)
async def campaign_report(session, settings: NewsletterSettings, *, tenant_id: str,
                          campaign: Campaign, now: datetime) -> Report
    # counters from the campaign row; skipped = COUNT(status='skipped_unsubscribed') pinned;
    # timeline from (opened_at, first_clicked_at) of the campaign's sends; empty when started_at is None
# web/schemas/report.py — mirror Report / LinkStat / Point (from_attributes)
class ReportOut(BaseModel): ...
# web/endpoints/report_api.py
router = APIRouter(dependencies=[Depends(bind_admin)])
@router.get("/campaigns/{campaign_id}/report", response_model=ReportOut,
            dependencies=[Depends(RequiresPermission(PERM_VIEW))])
    # require_campaign(..., roles=caller_roles(request)); settings = app.state.sm_newsletter.settings
```

- [ ] **Step 1: Failing tests.**
  - `test_timeline.py` (B6):
    - `test_start_off_the_hour`: start 10:20, now 15:20 gives hourly points 10:00 through 15:00
      (6 of them). Events at 10:05 and 10:59 land in 10:00; an event at 09:59 is dropped.
    - `test_exactly_72h_is_hourly`: `now − b0 == 72 h` gives 72 hourly points. An event at
      `b0 + 71:59:59` is in the last one; an event at exactly `b0 + 72 h` is excluded.
    - `test_just_over_72h_is_daily`: `now − b0 == 72 h + 1 s` gives daily points from the UTC
      midnight.
    - `test_exactly_90_days`: `now − b0 == 90 days` (daily) gives 90 points, and an event at
      exactly `b0 + 90 days` is excluded.
    - `test_window_caps_at_90_days`: start 200 days ago gives 90 points, and later events are
      dropped.
    - `test_start_late_in_utc_day`: start 23:30 UTC with now 4 days later; the first daily point
      is that UTC midnight.
    - `test_empty_inputs_give_zero_counts`: `n` points, all zero.
    - `test_naive_datetimes_are_utc` (SQLite returns what `AwareDateTime` gives; pin both).
  - `test_report.py` (SQLite and Postgres; `tracking_world`):
    - `test_report_counts`: the counters equal what `record_*` wrote and what the seeds set
      (`sent`, `failed`, `bounced`, `suppressed`, `unsubscribed`), and `skipped` comes from rows;
    - `test_link_stats_order_and_zero_links`: an unclicked link is listed with 0/0, and the
      order is by unique, then total, then position;
    - `test_report_pins_tenant`: B's clicks never reach A's link stats, even with equal ids;
    - `test_report_not_started_has_empty_timeline`.
    - `test_unknown_outcome_engagement_not_in_rate` (B5): two sends both opened and clicked, one
      `sent` (`sent_count = 1`) and one `failed/outcome_unknown`. Expected:
      - `opens_unique == 2` and `clicks_unique == 2` (all messages);
      - `opens_unique_accepted == 1` and `clicks_unique_accepted == 1`;
      - accepted ≤ `sent`.
    - `test_engagement_before_acceptance_joins_later` (B5): an open recorded while the row is
      `sending` gives `opens_unique_accepted == 0`. After `rows.record` marks it `sent` (the
      dispatcher's own path, which bumps `sent_count`), it is 1, and still ≤ `sent`.
    - `test_accepted_engagement_for_a_page`: three campaigns, one with none, give `(0, 0)` for
      that one, pinned to the tenant.
  - `test_report_api.py`:
    - 200 with exactly `ReportOut`'s keys;
    - 403 without `newsletter.view`;
    - 404 for an unknown id;
    - 404 for a campaign on a list restricted from the caller's roles (C4);
    - 404 for tenant B's id under `x-tenant: A` (multi);
    - `tracking_opens` reflects the settings.
  - `test_route_guards.py`: add `("GET", f"{API}/campaigns/{{campaign_id}}/report")`.
  - `test_campaigns_api.py::test_list_has_metrics`: the four new summary fields, and
    `opens_unique_accepted` counts only `sent` rows (B5).
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/tracking/test_timeline.py tests/tracking/test_report.py tests/web/test_report_api.py tests/web/test_route_guards.py tests/web/test_campaigns_api.py -q -p no:cacheprovider -n 8`. Expected: FAIL.
- [ ] **Step 3: Implement.** The domain module returns dataclasses. The endpoint maps them with
  `ReportOut.model_validate(report, from_attributes=True)`, so `tracking/` never imports
  `web.schemas`.
- [ ] **Step 4: Run** it on SQLite and on Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): campaign report API and list metrics`.

### Task 8: Frontend foundation — types, client, hook, utils, catalogue

**Files:**
- Modify:
  - `sm_newsletter/ui/utils/types.ts`
  - `sm_newsletter/ui/utils/api.ts`
  - `sm_newsletter/locales/en.json`, `de.json`
  - `sm_newsletter/ui/components/campaigns/urls.ts`
- Create:
  - `sm_newsletter/ui/hooks/useCampaignReport.ts`
  - `sm_newsletter/ui/utils/report.ts`
- Test:
  - `ui/utils/api.test.ts`
  - `ui/hooks/useCampaignReport.test.ts`
  - `ui/utils/report.test.ts`

**Interfaces (Produces):**
```ts
// types.ts — CampaignSummary gains (moved from PR 4's CampaignDetail where present):
started_at: string | null; finished_at: string | null; opens_unique_accepted: number; clicks_unique_accepted: number;
export interface LinkStat { position: number; url: string; unique: number; total: number }
export interface ReportPoint { at: string; opens: number; clicks: number }
export interface Report { campaign_id: number; status: string; started_at: string | null; finished_at: string | null;
  recipients: number; sent: number; failed: number; bounced: number; suppressed: number; skipped: number;
  unsubscribed: number; opens_unique: number; opens_total: number; clicks_unique: number; clicks_total: number;
  opens_unique_accepted: number; clicks_unique_accepted: number;
  tracking_opens: boolean; tracking_clicks: boolean; links: LinkStat[]; bucket: 'hour' | 'day'; timeline: ReportPoint[] }
// api.ts
report(id: number, signal?: AbortSignal): Promise<Report>      // GET /campaigns/{id}/report
// urls.ts
export const reportUrl = (id: number): string => `/admin/newsletter/campaigns/${id}/report`;
// utils/report.ts
export function rate(part: number, whole: number): number | null          // null when whole <= 0; never clamps (B5)
export function formatRate(r: number | null, locale: string): string | null // Intl percent, 1 decimal; null passes through
export function bucketLabel(at: string, bucket: 'hour' | 'day', locale: string): string
    // B6: Intl.DateTimeFormat with timeZone 'UTC'; 'hour' = date + "HH:00", 'day' = date only
export function hasStarted(c: { status: string; started_at: string | null }): boolean
    // started_at set and status in sending | paused | sent | cancelled
// hooks/useCampaignReport.ts
export const REPORT_POLL_MS = 60_000;
export function useCampaignReport(id: number): { report: Report | null; error: string | null; reload: () => Promise<void> }
    // polls while report.status === 'sending'; aborts on unmount; error = errorMessage(e, t) (PR 4 ruling P2)
```
**Catalogue keys** (`en` and `de`, the same tree; the `en` text is fixed here where it carries a
ruling):
- `report.title` "Report: {name}", `report.back` "Back to campaigns", `report.loading`,
  `report.refresh`, `report.not_started` "This campaign has not started sending yet.",
  `report.open_editor`.
- `report.stats.{recipients, accepted, accepted_hint, failed, bounced, suppressed, skipped, unsubscribed, opens, clicks, unique, total, rate, rate_hint, all_messages}`.
  - `rate_hint` is "Unique, among messages the mail server accepted".
  - `all_messages` is "All messages, including those whose outcome is unknown: {unique} unique,
    {total} total" (B5).
  `accepted_hint` is "Accepted by the mail server. Bounces that arrive later by email are not
  counted."
- `report.approx.opens` is "Approximate. Privacy features such as Apple Mail Privacy Protection
  load images automatically, so opens may be inflated."
- `report.approx.clicks` is "May include automated link scanners."
- `report.tracking_off.opens` "Open tracking is off." and `.clicks` "Click tracking is off."
- `report.links.{title, url, unique, total, empty}`; `empty` is "No tracked links in this
  campaign."
- `report.timeline.{title, opens, clicks, empty, window_hour, window_day, caption}`.
  `window_hour` is "First 72 hours" and `window_day` "First 90 days". `caption` is "First opens
  and first clicks per {bucket}, in UTC" (B6).
- `report.timeline.bucket.{hour, day}`.
- `campaigns.columns.{sent, recipients, opens, clicks}`, `campaigns.no_rate` "—",
  `campaigns.report_link` "Report", `campaigns.report_label` "Report for {name}".
- `sending.panel.report` "View report" (beside PR 4's `sending.panel.*`).
- `settings.tracking_note` replaced by "Applies to emails sent from now on. Switching tracking off
  also stops counting opens and clicks of emails already sent. Nothing about the reader's device
  or address is stored." The German replaces "Tracking gilt ab PR 5…" too.

- [ ] **Step 1: Failing tests.**
  - `api.test.ts`: `report(7)` hits `GET /api/newsletter/campaigns/7/report`.
  - `report.test.ts`:
    - `rate(1, 0) === null`;
    - `rate(1, 4) === 0.25`;
    - `formatRate(0.25, 'de')` holds `25`;
    - `bucketLabel('2026-11-05T23:00:00Z', 'hour', 'en')` shows 23:00 on 5 Nov even when
      `process.env.TZ` is `Pacific/Auckland` (B6: labels match the UTC buckets). `day` shows the
      UTC date and no time;
    - `rate(3, 2) === 1.5`: no clamping (B5; the server guarantees ≤ 1);
    - `hasStarted` covers every status.
  - `useCampaignReport.test.ts` (fake timers):
    - polls every 60 s while `sending`;
    - fetches once for `sent`;
    - stops when a poll returns `sent`;
    - unmount aborts;
    - an error sets `error`.
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/utils/api.test.ts modules/newsletter/sm_newsletter/ui/utils/report.test.ts modules/newsletter/sm_newsletter/ui/hooks/useCampaignReport.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** the Step 2 command and `npx tsc --noEmit -p modules/newsletter/tsconfig.json`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): report client, hook and catalogue keys`.

### Task 9: The report page

**Files:**
- Create:
  - `sm_newsletter/pages/CampaignReport.tsx`
  - `sm_newsletter/ui/components/report/ReportStats.tsx`
  - `sm_newsletter/ui/components/report/LinkTable.tsx`
  - `sm_newsletter/ui/components/report/ReportTimeline.tsx`
- Modify:
  - `sm_newsletter/web/endpoints/views.py` (route `/campaigns/{campaign_id}/report`)
  - `sm_newsletter/core/constants.py` (`_PAGE_REPORT = "Newsletter/CampaignReport"`)
- Test:
  - `ui/components/report/ReportStats.test.tsx`
  - `ui/components/report/LinkTable.test.tsx`
  - `ui/components/report/ReportTimeline.test.tsx`
  - `tests/web/test_views.py`
  - `tests/web/test_route_guards.py` (`EXPECTED` gains the view)

**Interfaces:**
- Consumes: Task 8's `useCampaignReport`, `rate`, `formatRate`, `bucketLabel` and `reportUrl`.
- Produces:
```python
# views.py: bind_admin (router) then RequiresPermission(PERM_VIEW); require_campaign -> 404 page
@router.get("/campaigns/{campaign_id}/report")   # props: view_props, campaign_id, name (campaign.name)
```
```tsx
export function ReportStats(props: { report: Report }): JSX.Element
export function LinkTable(props: { links: LinkStat[]; trackingOff: boolean }): JSX.Element
export function ReportTimeline(props: { bucket: 'hour' | 'day'; points: ReportPoint[] }): JSX.Element
```
- **`ReportStats`** shows tiles:
  - recipients;
  - accepted, with `accepted_hint`;
  - failed, bounced, suppressed, skipped, unsubscribed;
  - opens: `opens_unique_accepted` and its rate over accepted (`rate_hint`), then the
    `all_messages` line (`opens_unique`, `opens_total`). `report.approx.opens` is always visible
    as text, not only a tooltip;
  - clicks: the same with the `clicks_*` fields and `report.approx.clicks`.

  With tracking off for a kind it also shows `report.tracking_off.*` (the counts may still be
  non-zero from before).
- **`LinkTable`** lists position, URL (truncated with `title`, rendered as text, never an
  `<a href>` to the target), unique and total. The empty state is `report.links.empty`.
- **`ReportTimeline`** is a `<table>` with a visually hidden caption, one row per point, and CSS
  bars scaled to the maximum. It shows `window_hour` or `window_day`, and the empty state.
- **`CampaignReport.tsx`** uses `AuthenticatedLayout` and `PageShell` with title
  `report.title`.
  - Actions: *Back* (to `campaignsUrl`), *Open in editor* (`editorUrl`) and *Refresh*.
  - Body: `not_started` while `!hasStarted`; else stats, timeline and links.
  - It stays under 150 lines.

- [ ] **Step 1: Failing tests.**
  - `ReportStats.test.tsx`:
    - the opens tile shows `opens_unique_accepted`, `25 %` (50 of 200 accepted), the
      all-messages line with `opens_unique` and `opens_total`, and the approximate text (B5);
    - accepted 0 shows `—`;
    - tracking off shows the note.
  - `LinkTable.test.tsx`:
    - rows in the given order;
    - a URL is text, not a link;
    - the empty state.
  - `ReportTimeline.test.tsx`:
    - one row per point;
    - the bar widths are proportional (`style.width`);
    - the window label per bucket, and row labels from `bucketLabel` (UTC);
    - the empty state.
  - `test_views.py`:
    - `test_report_view_renders`: the component is `Newsletter/CampaignReport` and the props
      hold `campaign_id` and `name`;
    - 404 for an unknown or restricted campaign;
    - 403 without `newsletter.view`.
  - `test_route_guards.py`: add `("GET", f"{VIEW}/campaigns/{{campaign_id}}/report")`.
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/components/report` and `uv run --directory modules/newsletter pytest tests/web/test_views.py tests/web/test_route_guards.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `@simple-module-py/ui` (`Card`, `Table`, `Badge`, `Button`,
  `Skeleton`, `PageShell`), as `Campaigns.tsx` does.
- [ ] **Step 4: Run** the Step 2 commands, `npx tsc --noEmit -p modules/newsletter/tsconfig.json`
  and `npx biome check modules/newsletter`. Expected: PASS. Run `uv run python scripts/check_rules.py`
  (the pages rule).
- [ ] **Step 5: Commit** `feat(newsletter): campaign report screen`.

### Task 10: Metrics on the campaign list; report links

**Files:**
- Modify:
  - `sm_newsletter/ui/components/campaigns/CampaignTable.tsx`
  - `sm_newsletter/ui/components/sending/SendingPanel.tsx` (PR 4 Task 12): a "View report" link
    when `hasStarted`
- Test:
  - `ui/components/campaigns/CampaignTable.test.tsx` (new)
  - `ui/components/sending/SendingPanel.test.tsx`

**Interfaces:** Consumes Task 8's `rate`, `formatRate`, `hasStarted` and `reportUrl`.

**`CampaignTable`** columns become:
1. Name, a link to the editor, with the subject as a muted second line;
2. Status;
3. List;
4. Sent: the `started_at` date, or `campaigns.never`;
5. Recipients;
6. Opens: `rate(opens_unique_accepted, sent_count)` (B5), else `campaigns.no_rate`;
7. Clicks: the same;
8. Updated;
9. an actions column, now shown to everyone. *Report* (`report_label` as the accessible name) when
   `hasStarted`; *Delete* only for drafts with `canEdit`.

The Opens header carries `title={t(report.approx.opens)}`. If the file nears 280 lines, move
`DeleteDraft` to `DeleteDraft.tsx` (moves only).

- [ ] **Step 1: Failing tests.**
  - `CampaignTable.test.tsx`:
    - a sent campaign (`sent_count` 200, `opens_unique_accepted` 50, `clicks_unique_accepted` 10)
      shows `25` and `5` percent and a Report link to `/admin/newsletter/campaigns/<id>/report`;
    - a draft shows `—` in both and no Report link;
    - Delete is only for drafts with `canEdit`;
    - a viewer (`canEdit` false) still sees Report.
  - `SendingPanel.test.tsx`: `sent` and `sending` show "View report" with the href; `scheduled`
    does not.
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/components/campaigns modules/newsletter/sm_newsletter/ui/components/sending`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Step 2 command, `npx tsc --noEmit -p modules/newsletter/tsconfig.json`
  and `npx biome check modules/newsletter`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): open and click rates on the campaign list`.

### Task 11: Docs, wiring and branch verification

**Files:**
- Create: `modules/newsletter/docs/tracking.md`. It covers:
  1. **What is stored per recipient:** first open time, open count, first click time, and per
     link the first click time and a count. Nothing else: no IP, user agent, location, device or
     client.
  2. How the pixel and links are built (T1–T4), and that the text part is untracked.
  3. The token (S10, T17) and the forged-token table (T6).
  4. What switching tracking off does (T5, B7): new messages from the next tick (about 60 s,
     plus the settings cache); recording at once.
  5. Why opens are approximate (MPP and image proxies) and clicks may include scanners (T10).
  6. The report's definitions (T14): accepted, the rates' numerators (B5), "all messages", and
     the UTC timeline buckets (B6).
  7. The rate limits (T11).
  8. Retention: the rows live as long as the campaign.
  9. Operator note: the host's access log records request paths, which include tokens, as it
     already does for `/newsletter/u/`. Point log retention at it.
- Modify:
  - `modules/newsletter/docs/index.md`: the status table (PR 5: this PR), a "Tracking and
    reports" paragraph linking `tracking.md`, and the screens list (`…/campaigns/{id}/report`).
  - `modules/newsletter/README.md`: the "later pull requests" sentence.
  - `CLAUDE.md`, the newsletter paragraph PR 4 added:
    - `/newsletter/o/` and `/newsletter/c/` follow the unsubscribe route's rule (tenant from the
      verified token, the same answer for forged tokens);
    - the click route only ever redirects to the campaign's own stored `newsletter_link` URL;
    - tracking stores no IP or user agent.
  - `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`: the PR 5 row's plan path, and
    "Notes for PR 6" (the report's timeline window, and that segments need no tracking change).
  - `host/tests/test_newsletter_wiring.py`: `test_tracking_routes_are_public`. On the built host
    app, anonymous `GET /newsletter/o/x.1.1.AAAA.gif` is 200 `image/gif`, and
    `GET /newsletter/c/test/1` is 404, not 401 and not a redirect to login.

- [ ] **Step 1: Write the docs and the host test.**
- [ ] **Step 2: Verify.** Run `~/.claude/bin/wait-for-headroom` first.
  - `uv run --directory host pytest tests/test_newsletter_wiring.py -q -p no:cacheprovider`
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
- [ ] **Step 3: Migration check** on a scratch SQLite database and on `smpy_newsletter_mig_check`
  (created and dropped): `upgrade heads`, then `check` ("No new upgrade operations detected").
- [ ] **Step 4: Commit** `docs(newsletter): tracking, privacy and the report (PR 5)`.

---

## Amendments (Codex review 2026-11-05)

Codex reviewed the draft from before T17 was rewritten. The team lead accepted all seven
findings, and each is folded into the tasks named below. Where a ruling above disagrees, the
amendment wins; the rulings above have already been edited to match.

- **B1 (P1). T17 is consistent everywhere.**
  - `fill` takes `open_token` and `click_token` (Task 2).
  - `compose` mints all three purposes (Task 4).
  - No test asserts that the click token equals the unsubscribe token. The three-purpose matrix
    replaces any such assertion (Task 2 `test_purpose_is_bound`, Task 4
    `test_compose_tracking_tokens_are_purpose_bound`).
  - Wrong-purpose tokens do no database work on either route: no session is opened (T6, Task 6
    `test_wrong_purpose_is_forged`).
  - Every caller is updated (Task 2): `tests/support/dispatch_world.py:75`,
    `tests/core/test_worker_secret.py:54`/`:64`, `tests/core/test_worker_dispatch.py:168`,
    `tests/sending/test_compose.py`, the unsubscribe service and its tests, and any further
    `grep` hit.
  - No Q2 default text remains.
- **B2 (P1). Tracking placeholders are filled before personalisation.** `compose` runs `fill` on
  the trusted snapshot first, then the merge fields, so recipient data can never introduce or
  multiply a placeholder (Task 4 `test_recipient_data_cannot_add_tracking`: a parsed-HTML
  assertion covering body text and an `alt` attribute).
- **B3 (P2). No implied open while open tracking is off.** `record_click(count_open=…)` (Task 5).
  The four-way settings matrix is in Task 6.
- **B4 (P2). The failure boundary covers recording and `finalize_session`.** The whole
  transaction is rolled back and the GIF or 302 still returned (T12, Task 6). Tests cover a
  commit failure and a failure after partial updates.
- **B5 (P2). Rate numerators count only `sent` sends.**
  - `opens_unique_accepted` and `clicks_unique_accepted` are counted from rows when the report
    or list is read (Task 7 `accepted_engagement`, `campaign_report`). The denominator stays
    `sent_count`.
  - No clamping. The overall totals are shown separately as "all messages" (Tasks 8–10).
  - Tests: an engaged outcome-unknown send, and engagement before acceptance (Task 7).
- **B6 (P2). Timeline buckets.** UTC calendar buckets, an exclusive end, at most 72 hourly or 90
  daily buckets, and UTC labels (T14, Task 7 boundary tests, Task 8 `bucketLabel`, Task 9).
- **B7 (P2). When a settings change applies.** Composition takes the settings from the next
  tick (about 60 s); recording reads them per request (T5). Task 4 tests a change between ticks,
  and that a change within a tick does not split it. Task 11's docs say so.

## Spec coverage (self-review)

| Spec item | Task |
|---|---|
| `GET /newsletter/o/{token}.gif`: 1×1 GIF, sets `opened_at` and the count | 2, 5, 6 |
| Opens labelled approximate (Apple MPP) | 8, 9 (T10) |
| `GET /newsletter/c/{token}/{link}`: records, 302 to the stored URL, never a request URL | 5, 6 (T6) |
| A click sets `opened_at` if empty | 5 (T7) |
| Public, no auth, tenant from the token | 6 (S8, T6) |
| Forged or unknown token gets the same answer (pixel and redirect target excepted) | 6 (T6) |
| Tokens: HMAC over (tenant, campaign, send), 128-bit | PR 4 S10, now purpose-bound (T17, Task 2) |
| `newsletter_link` (campaign, position, url), `newsletter_click` (send, link, at) | 1, 3 (T8) |
| Rewritten links carry the send's token, plus the pixel (§Sending 3) | 2, 4 |
| `tracking_opens` / `tracking_clicks`: off removes the pixel or the rewrite | 4, 6 (T5) |
| Report: recipients, sent, failed, bounced, unique and total opens (approximate), unique clicks, click table per link, unsubscribes | 7, 9 |
| Campaign list: sent date, recipients, open %, click % | 7, 10 |
| Counters update in the same transaction as the event | 5 (T9) |
| `newsletter.view` for reports; per-list access (amendment 9, C4) | 7, 9 |
| Tenant isolation on every route (§Testing) | 5, 6, 7, 9 |
| `tracking/` area (§Module shape) | 2, 5, 7 |
| en/de catalogues | 8 |
| Migration: one revision, single head, `alembic check` on both backends | 1, 11 |

**Out of PR 5, by roadmap:**
- segments and the subscriber screen (PR 6);
- the import, the e2e spec (whose "see the report" step lands then) and the final docs pass
  (PR 7);
- non-goals: per-person timelines, cross-campaign reports, asynchronous bounces.

## Open questions

None. The team lead ruled on 2026-11-05:
- **Q1** (T5): yes. Switching tracking off also stops recording for mail already delivered.
- **Q2** (T17): purpose-bound MACs, `"u"`, `"o"` and `"c"`, in Task 2, which updates PR 4's
  unsubscribe callers and tests.

Every other ruling was accepted as written.
