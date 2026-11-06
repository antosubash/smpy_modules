# Newsletter PR 7: the Mailchimp import, the list action, docs and the e2e spec — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin with `newsletter.manage` creates a newsletter list, or picks an existing one,
and uploads Mailchimp's audience export (the ZIP, or its `subscribed`, `unsubscribed` and
`cleaned` CSVs). The admin checks the counts, the column mapping and the tags found, then
applies the import. A background task writes the subscribed people to records as `confirmed`,
makes everyone who left or bounced unmailable, and reports created, updated, skipped, suppressed
and failed counts, with per-row errors. Nobody who opted out anywhere is ever made mailable. The
module docs are finished, and one standalone e2e spec walks the whole product.

**Architecture:**
- **Records owns the people (spec, "The key decision").** A new contract module,
  `sm_records.contracts.newsletter_import`, holds the write half:
  - `import_subscribers`, the spec's contract 5;
  - `add_tag_choices` (G1's write half);
  - `importable_fields`, the mapping targets;
  - `create_list`, the spec's "create list" action, which no earlier PR built.

  Each is tenant- and list-pinned, writes `sm_*` only through `system=`, and runs in the
  caller's transaction. `contracts/newsletter.py` (272 lines) stays untouched.
- **Newsletter stages the upload in the request and applies it in a worker.**
  1. The upload streams through Starlette's spooled file. Each CSV is parsed row by row
     (`imports/mailchimp.py`) and staged into `newsletter_import_row`, deduplicated by address
     hash with suppression precedence.
  2. The preview, the mapping and the tags found are read from the staged rows.
  3. *Apply* queues `newsletter.run_import`. It works in 45-second slices of 200-row batches,
     each batch in one transaction under `tenant_scope`: records' `import_subscribers`, then
     newsletter's suppressions, then the row outcomes and counters.
  4. When the import finishes, its staged rows (addresses) are deleted.
- **An import never clears anything.**
  - It writes suppressions with `refresh=False` (insert-ignore) and never calls
    `clear_for_confirmation`.
  - Records' import writes run inside `events.muted`, so no `SubscriptionChanged` (least of all
    `pending → confirmed`) and no `RecordCreated` is published.
  - Newsletter writes the matching suppression rows itself, in the same transaction
    (amendment 1's pattern).

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic, Celery (framework
`background_tasks`), Python `csv`/`zipfile`/`email-validator`, React 19 + Inertia,
`@simple-module-py/ui`, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md`. Its "Amendments"
(1–11) override its body. This plan implements:
- §"Mailchimp import";
- goal 6;
- the spec's contract 5, `import_subscribers`;
- the "create list" action in §"The key decision";
- the *Import* screen in §"Screens";
- the import half of §"Testing";
- the e2e spec of §"Testing";
- delivery order 7–8.

Also read:
- the roadmap `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`: the PR 7 row and
  "Notes for PR 7" (written by PR 6's Task 14);
- the PR 4 plan `docs/superpowers/plans/2026-11-03-newsletter-pr4-sending.md`: S2 (start is the
  beat), S8 (unsubscribe page), A1–A9;
- `.superpowers/sdd/pr5-plan-draft.md` (or its committed copy): the report page and API (Task 7);
- `.superpowers/sdd/pr6-plan-draft.md` (or its committed copy):
  - G1 (`list_fields` is the tag-choice read);
  - G10 (permissions);
  - G16 (`PERM_RECORDS_VIEW`);
  - G18 (test databases);
  - C2 (`row_lock.lock_record`, `transition(lock=True)`, `opt_in.leave` locks);
  - the audience picker (Task 10) and the Subscribers screen (Task 13);
- the PR 2 ledger `.superpowers/sdd/2026-11-03-newsletter-pr2-scaffold/progress.md`: the
  hashing ruling, and F2 (only a double-opt-in confirmation clears);
- `sm_newsletter/core/suppression/__init__.py` and `mirror.py` (the clearing rules this PR must
  not break).

**Precondition.** Execute only after PRs 4, 5 and 6 are committed on the stack. Before each
task that names a PR 4–6 file, re-read it and adapt only names; the behaviour below stays:
- PR 6's `contracts/newsletter_admin.py` (`FieldChoice`, `list_fields`);
- PR 6's `row_lock.py` and `transition(lock=)`;
- PR 6's `campaigns/access.py:require_list`;
- PR 5's report page;
- PR 4's `sending/runtime.py`.

## Rulings (decided here; cost if wrong in each)

- **R1. CSV and ZIP only; no Mailchimp API.**
  - The spec says "Upload Mailchimp's audience export (the ZIP or its CSVs)" and never names
    the API.
  - So there is no API key, no new secret setting and no outbound HTTP.
  - Cost if wrong: an API source is a new `imports/source_api.py` feeding the same staging,
    plus an `enc:v1:` setting written like the SMTP password.
- **R2. What each Mailchimp file becomes.** There is no `imported_unsubscribed` reason.
  - The spec's table is binding:
    - *unsubscribed* becomes an "`unsubscribed` suppression record in records" (a records
      record in status `unsubscribed`);
    - *cleaned* becomes "newsletter `imported_cleaned` suppression (and no subscriber)".
  - Newsletter also writes its own `unsubscribed` suppression row for every unsubscribed
    contact: the list-scoped reason, `source="import"`. This is amendment 1's rule that
    newsletter's own unsubscribe writes its row in the same transaction as records'.
  - So both kinds are suppressed tenant-wide at once, without waiting for the reconcile.
  - `REASONS` and `SOURCES` already hold everything needed (`"import"` is in `SOURCES`).
  - *nonsubscribed* files (Mailchimp's transactional contacts) are listed with kind `ignored`,
    and none of their rows are staged.
  - Cost if wrong: an `imported_unsubscribed` reason is one constant, one lift rule (G12) and a
    catalogue key. The column is a string, so it needs no migration.
- **R3. The decision table.** Records decides from the record holding the address (trash
  included) under the row lock; newsletter adds its suppressions. The records outcome is in
  backticks.

  | Records has | Mailchimp *subscribed* | Mailchimp *unsubscribed* | Mailchimp *cleaned* |
  |---|---|---|---|
  | nothing | create `confirmed` → `created` | create `unsubscribed` (email only) → `created_unsubscribed`; suppression | no record; `imported_cleaned` suppression |
  | `confirmed` | append new tags; fill only empty mapped fields → `updated` / `unchanged` | `leave` with cutoff = `UNSUB_TIME` → `unsubscribed` and a suppression; or `kept_confirmed` (confirmed after the cutoff): no suppression | suppression |
  | `pending` | no write → `kept_pending` | no write → `kept_pending`; suppression (a later confirm link clears it, created before the confirmation) | suppression |
  | `unsubscribed` | no write → `kept_unsubscribed` (never resubscribed) | `kept_unsubscribed`; suppression | suppression |
  | trashed (any) | no write → `trashed` | `trashed`; suppression | suppression |

  - **Before records is called**, a *subscribed* address is skipped with `suppressed` when
    newsletter already suppresses it (any reason, any list: suppression is tenant-wide) **or**
    records holds it `unsubscribed` on any of the tenant's lists, trash included (D1, records'
    `opted_out_anywhere`; spec amendment 1: the import consults records' status directly, not
    only the mirror). It is never created, so an opted-out or bounced person never becomes a
    mailable record.
  - **`pending` is never confirmed.** That would be the `pending → confirmed` transition that
    alone clears suppressions (PR 2 ruling). A person who signed up on the new site and has not
    clicked confirm keeps their pending signup and their confirmation mail.
  - Cost if wrong: such a person gets campaigns only after confirming. That is the safe error.
- **R4. Imported subscribers' system values** (records side, all through `system=`):

  | Field | Value |
  |---|---|
  | `sm_email` | the normalised address |
  | `sm_status` | `confirmed` |
  | `sm_confirmed_at` | `CONFIRM_TIME`, else `OPTIN_TIME`, else the import time; never later than now |
  | `sm_consent_at` | `OPTIN_TIME`, else the import time |
  | `sm_consent_text` | `Imported from Mailchimp on <YYYY-MM-DD>` (the spec's snapshot; stored English, like every consent text) |
  | `sm_locale` | records' default content locale |
  | `sm_nonce` | fresh |
  | `sm_consent_ip_hash`, `sm_source_page` | `None` |

  - An *unsubscribed* record gets `sm_status = unsubscribed`, `sm_unsubscribed_at =
    UNSUB_TIME` (else now) and a nonce. No consent, no ordinary values: the same shape
    `opt_in.leave` leaves.
  - Records' `created_at` is the import time; PR 6's G4 note already says "signed up" means
    "added" for imported people.
  - Cost if wrong: one dictionary.
- **R5. No events.**
  - `import_subscribers` runs inside records' `events.muted(session)` and takes no `bus`.
  - Nothing is published: no `RecordCreated`, no `RecordUpdated`, no `SubscriptionChanged`.
  - This makes "never emits `pending → confirmed`" structural rather than a convention.
  - Other `RecordCreated` listeners (none today for subscription lists) do not see imported
    people; the docs say so.
  - Cost if wrong: if a listener needs them, emit `RecordCreated` only, after the batch.
- **R6. Stage in the request; apply in the worker.**
  - The request streams, parses and inserts staged rows in 1 000-row chunks, about 5–15 s for
    60 000 rows.
  - The preview is then exact and needs no extra task state, and the worker never sees the
    file, so there is no file storage dependency.
  - Staged rows hold addresses, so they are deleted when the import finishes. A `staged` import
    nobody applies, and a `failed` one, is deleted by the janitor after 24 h.
  - Cost if wrong: a slow upload request on a very large export. The alternative (store the
    file, parse in the worker) adds an "analysing" state and needs `file_storage`.
- **R7. Limits**, as constants in `imports/constants.py` (not settings: nothing an operator
  tunes):

  | Limit | Value |
  |---|---|
  | `MAX_UPLOAD_BYTES` | 50 MiB, registered with `register_body_limits` (+1 MiB multipart framing) |
  | `MAX_FILES` | 4 parts, or 1 ZIP |
  | `MAX_ZIP_ENTRIES` | 16 |
  | `MAX_ENTRY_BYTES` | 200 MiB declared, uncompressed |
  | `MAX_TOTAL_BYTES` | 400 MiB |
  | `MAX_RATIO` | 200 |
  | `MAX_ROWS` | 250 000 staged rows in all |
  | `MAX_COLUMNS` | 200 |
  | `MAX_CELL` | 4 096 characters |
  | `MAX_TAGS_PER_ROW` | 50 |
  | `MAX_TAG_LEN` | 100 |
  | `MAX_NEW_TAGS` | 500 |
  | `KEEP_ERRORS` | 1 000 |
  | `STAGED_TTL` | 24 h |

  ZIP safety:
  - An encrypted entry, a compression other than stored or deflate, a declared size over the
    caps, or a declared ratio over 200 refuses the archive (`import_zip_unsafe`).
  - `zipfile` itself stops at the declared size and raises on a CRC mismatch, so a lying header
    is a refusal, not a bomb.
  - Folders, `__MACOSX/`, dot-files and non-`.csv` entries are skipped.
  - Cost if wrong: one constant each.
- **R8. Parsing.**
  - UTF-8 with or without a BOM. Anything else refuses the file (`import_not_utf8`, with the
    line).
  - The delimiter is sniffed from the header line among `,` `;` and tab, so a German Excel
    re-save works.
  - Headers are matched case-insensitively after trimming. The email column is the first header
    in `EMAIL_HEADERS`; the mapping UI never needs to pick it, because without one the file is
    refused (`import_no_email_column`).
  - **Kind** is detected from the file name's prefix (`subscribed` / `unsubscribed` / `cleaned`
    / `nonsubscribed`, case-insensitive, `unsubscribed` tested before `subscribed`), else from
    the columns (`UNSUB_TIME` → unsubscribed, `CLEAN_TIME` → cleaned), else subscribed.
  - **Times** (`OPTIN_TIME`, `CONFIRM_TIME`, `UNSUB_TIME`, `CLEAN_TIME`) are Mailchimp's
    `YYYY-MM-DD HH:MM:SS` in UTC. Anything else reads as missing.
  - **Tags** come only from the `TAGS` column, which Mailchimp never localises. A cell like
    `"VIP","Customers, 2020"` is read with `csv.reader` on the cell. Each tag is trimmed and
    must be 1–100 characters with no control characters; at most 50 per row.
  - A tag's choice **value** is decided by D8's `tag_values` (amended): deterministic and
    collision-free. A value never contains `,`, because records' `in:` filter splits on commas
    and has no escape (`records/_grammar.py:103`). The label stays as written.
  - Mailchimp's own bookkeeping columns (`MAILCHIMP_SYSTEM`) are not offered for mapping.
  - Cost if wrong: one alias, or one helper.
- **R9. Mapping.**
  - The import maps any other column to one of the list's **ordinary** fields of type `text`,
    `longtext`, `email`, `url` or `select`, at most one column per field. A `select` value must
    match a choice value or label.
  - Defaults: `First Name` / `Vorname` → `first_name`, `Last Name` / `Nachname` →
    `last_name`, when the list has them.
  - Tags are a switch, on by default when tags were found and the list can hold them.
  - A value the field refuses is dropped for that row. The row is still imported and an
    `invalid_value` row error names the field.
  - Cost if wrong: more permissive or stricter coercion is local to records'
    `campaign_import.py`.
- **R10. Tags on the list.**
  - `add_tag_choices` appends new choices to the list's `tags` multiselect (`indexed`), once,
    before the first batch.
  - A list without a `tags` field gets one only while it holds **no records, trash included**.
    That takes records' fast path, with no reindex. Otherwise it raises `TagsFieldMissing`, and
    the mapping step shows tags as unavailable, with the hint to add a `tags` multiselect in
    records.
  - `create_list` makes `first_name` and `last_name` (text, at most 100 characters) and no
    `tags` field, because records refuses a multiselect with no choices.
  - Cost if wrong: an admin must add the field in records before importing tags into a
    populated list.
- **R11. The "create list" action ships here.**
  - The spec's §"The key decision" promises it, and no earlier PR built it. The import needs a
    target with `first_name`, `last_name` and a place for tags, and the e2e spec needs a list.
  - It is `POST /api/newsletter/lists` with `newsletter.manage` (the spec: "manage: lists,
    import, settings"). Records' `records.manage_types` is not required, because the action
    creates only a subscription list.
  - The list uses records' preset defaults: form disabled, double opt-in on, shown in the
    records menu.
  - Cost if wrong: a newsletter manager can create a records type. If that is too much, add
    `records.manage_types` to the route (one dependency).
- **R12. Permissions.**
  - Every import route needs `newsletter.manage` and C4 list access (`require_list` with
    `caller_roles`). An unreadable list is a 404.
  - Reading an import that names an unreadable list is also a 404.
  - Cost: none; it matches PR 6's G10.
- **R13. Workers.**
  - `newsletter.run_import(tenant_id, import_id)` runs on the existing `newsletter` queue
    (`make worker` runs it with `-c 4`, so it never starves the minute's dispatch tick).
  - Its body is `run_platform`, then `tenant_scope(tenant_id)`.
  - It claims a lease (`lease_owner`, `lease_until = now + 5 min`, renewed per batch) and works
    for at most `SLICE_SECONDS = 45` s, then re-enqueues itself.
  - Under Celery eager (tests, e2e, a dev host without a broker), `launch` awaits the slices
    inline on the request's loop, as images' `ingest/imports/launch.py` does. Never `.delay()`.
  - Records' settings in a worker come from `background_tasks.settings_for(RecordsSettings,
    RECORDS_PACKAGE)`, with both names re-exported by the contract.
  - Cost if wrong: one queue name.
- **R14. Resumable and idempotent.**
  - Each staged row gets its `outcome` in the same transaction as its effects. A slice works on
    `outcome IS NULL ORDER BY seq`.
  - A crash mid-batch rolls the whole batch back, and the next claim redoes it.
  - Re-running a finished export as a new import changes no data: records' table makes every
    address `unchanged` or `kept_*`, and the suppression writes are insert-ignore.
  - The hourly janitor re-launches a `queued` or `running` import whose lease expired (a lost
    message).
  - Cost: none.
- **R15. Counts** (the lead's created / updated / skipped / suppressed, plus failed). Every
  staged row lands in exactly one count:
  - `created`: records outcome `created`.
  - `updated`: `updated`.
  - `skipped`: a subscribed row that wrote nothing (`unchanged`, `kept_*`, `trashed`, or
    already suppressed).
  - `suppressed`: every unsubscribed or cleaned row. It is suppressed after the batch, whether
    or not a row was new, so a re-run reports the same number and writes nothing. The exception
    is `kept_confirmed`, which counts as `skipped`.
  - `failed`: records outcome `invalid`. An invalid unsubscribed row is still suppressed by
    hash and counts as `suppressed`.
  - Staging's refusals (invalid address, duplicate) are reported as `invalid` and `duplicates`
    and are never staged.
- **R16. Errors never echo values.**
  - A row error is `{file, line, code, field}`. `file` is the file's index, `field` a list
    field key, and `code` comes from a fixed vocabulary.
  - Logs carry counts and the import id only.
  - The errors CSV (`GET /imports/{id}/errors.csv`) adds the file name. Every cell starting
    with `=`, `+`, `-`, `@`, tab or CR is prefixed with `'` (CSV injection).
  - HTTP refusals name the file by index and line, never the file name or a cell.
  - The page shows file names as React text.
- **R17. The e2e spec sends mail through an e2e-only dispatch hook.**
  - Campaigns are sent only by the minute beat (PR 4 S2), and the e2e server has no beat. An
    eager `.delay()` from a request cannot run `run_platform` either.
  - So `POST /api/newsletter/outbox/dispatch` runs one dispatcher tick in the web process with
    the app's session factory, settings and secret.
  - It exists only while **all three** hold (team lead, 2026-11-05):
    - `transport == "console"`;
    - Celery is eager;
    - the host's environment (`SM_ENVIRONMENT`) is `development` or `testing`.

    If any one fails, it is a 404, like `GET /outbox`. It needs `newsletter.manage` and the
    API's CSRF check, like every other admin POST.
  - Cost if wrong: a development-only route that runs the install-wide tick on demand. It can
    never send real mail (console transport), and production is never eager.
- **R18. The spec configures what it needs itself.**
  - It needs four newsletter settings (`transport=console`, `from_address`, `from_name`,
    `physical_address`). In `beforeAll` it writes them through `PUT /api/newsletter/settings`.
  - It also needs the host's `public_base_url`, because schedule and test send refuse relative
    links (`422 public_base_url_required`). It writes that through `PUT
    /api/settings/modules/host`.
  - It records each original before changing it, and `afterAll` restores exactly those
    through a fresh authenticated context (D7): the newsletter values with a second PUT, and
    the host field with `DELETE /api/settings/modules/host/public_base_url` when it was unset.
  - The spec runs only in its own CI job, `E2E (newsletter)` (D4), with `SM_ENVIRONMENT=testing`
    and no bundle, so the R17 hook is present there and absent everywhere else.
  - Why not `start-test-server.sh`: `public_base_url` changes records' confirmation links and
    Inertia's site URL for every spec, and in the multi-tenant run it would point organisations'
    links at plain `localhost`. Nothing here is truly suite-wide.
  - Cost if wrong: two lines in `start-test-server.sh` and no restore.
- **R19. Migration.** Exactly one revision, creating `newsletter_import` and
  `newsletter_import_row`, off the single head at execution time (check with
  `scripts/check_migration_heads.py`). No branch label.
- **R20. Test databases** (PR 6's G18):
  - newsletter runs on `smpy_newsletter_test` and its `_gw0`…`_gw7` copies, dropped and
    recreated after Task 3;
  - records' Postgres runs use a scratch `smpy_newsletter_rec_test`, created and dropped by the
    implementer;
  - alembic checks use `smpy_newsletter_mig_check`.

  Only `smpy_newsletter_*` names may be created.

## Global Constraints

- **Before every run.** Run `~/.claude/bin/wait-for-headroom` before every pytest, vitest, tsc,
  biome, alembic or Playwright run. If it exits 1, stop and report.
- **Targeted tests only.** Run the files each task names, never a full suite (`make test-py`,
  `make test-py-pg` and the full e2e suite run once, at the end of the stack). Use `-n 8` at most.
- **Shell.** Use `/usr/bin/ps`, never `ps`. One plain command per Bash call, with literal paths.
  Nothing heavy in parallel.
- **Formatting.** Format only the files you touched (`uv run ruff format <files>`).
- **300-line cap** (`scripts/check_file_size.py`). Split at 280+ by responsibility. Never touch
  records' `contracts/newsletter.py` (272). Watch `module.py`, `tasks.py`, `task_config.py`,
  `web/endpoints/views.py`, `ui/utils/api.ts` and `ui/utils/types.ts`: new import code goes in
  new files.
- **Layout** (`docs/module-layout.md`). New domain area `sm_newsletter/imports/`, tests in
  `tests/imports/`. HTTP goes in `web/endpoints|schemas`, UI in `ui/components/import/`,
  `ui/hooks/useImport.ts` and `ui/utils/importApi.ts`. Records: implementation in
  `sm_records/public_submissions/campaign_import.py` and `campaign_lists.py`, contract in
  `sm_records/contracts/newsletter_import.py`.
- **Pages rule.** The only new file under `sm_newsletter/pages/` is `Import.tsx`, a real Inertia
  page with `export default`. Its test lives in `ui/components/import/`.
- **Contracts.** Newsletter imports nothing from `sm_records` except `sm_records.contracts.*`.
  In the web process records' settings come from `app.state.sm_records.settings`; in a worker
  they come from R13's `settings_for`.
- **Tenancy.**
  - Both new tables carry `MultiTenantMixin`.
  - Every Core statement pins `tenant_id`, and imports are looked up by `(id, tenant_id)`.
  - Records' functions bind with `tenant_scope` and pin `tenant_id` (amendment 6).
  - A request names its tenant through `bind_admin`, and the worker names it in the task
    arguments.
- **Locales.**
  - Every key goes into `en.json` **and** `de.json` in the same commit
    (`uv run python scripts/check_locales.py`).
  - Every new error code gets `errors.<code>`, and every row-error code gets
    `import.row_errors.<code>`.
  - No `defaultValue`. A runtime family is a `Record<Union, string>` of `keys.…` leaves.
- **Errors** follow R16.
- **Python tests.** `uv run --directory modules/newsletter pytest <paths> -q -p no:cacheprovider`.
  On Postgres, prefix
  `SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_test`.
- **Records tests.** `uv run --directory modules/records pytest <paths> -q -p no:cacheprovider`.
  On Postgres:
  1. `PGPASSWORD=postgres createdb -h localhost -U postgres smpy_newsletter_rec_test`;
  2. run with
     `SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_rec_test`;
  3. `PGPASSWORD=postgres dropdb -h localhost -U postgres smpy_newsletter_rec_test`.
- **JS.** `npx vitest run <paths>`, `npx tsc --noEmit -p modules/newsletter/tsconfig.json`,
  `npx biome check modules/newsletter`.
- **Commits** end with the session's `Claude-Session:` line.

## Review Focus

1. **One address in two files, or spelled two ways** (`Ada@X.org` subscribed, `ada@x.org `
   cleaned). Expected: one staged row, the `cleaned` one; the duplicate is counted; Ada is
   never created. Pinned in Task 5 (`test_precedence_cleaned_beats_subscribed_any_spelling`,
   `test_precedence_unsubscribed_beats_subscribed`).
2. **Someone who left here appears as subscribed in the export, or is pending here.** Expected:
   - an `unsubscribed` record stays unsubscribed;
   - a `pending` one stays pending;
   - no `SubscriptionChanged` is published at all;
   - every existing suppression row (`hard_bounce`, `imported_cleaned`, `unsubscribed`,
     `complaint`) survives with its `created_at`.

   Pinned in Task 2 (`test_never_resubscribes_unsubscribed`, `test_pending_is_never_confirmed`,
   `test_import_publishes_no_events`) and Task 6 (`test_import_clears_no_suppression`,
   `test_suppressed_address_is_never_created`).
3. **A German or Excel-re-saved export**: `E-Mail-Adresse;Vorname;Nachname;TAGS` with `;` and
   a BOM. Expected: parsed, `Vorname` mapped to `first_name`. Pinned in Task 4
   (`test_semicolon_bom_german_headers`).
4. **The worker dies mid-import, or the same export is applied twice.** Expected:
   - no duplicate record;
   - counts that add up to the staged total;
   - a second run writes nothing.

   Pinned in Task 6 (`test_crash_mid_batch_resumes_without_duplicates`,
   `test_rerun_same_export_changes_nothing`).
5. **A hostile upload**: a ZIP bomb (declared ratio), an encrypted entry, 300 columns, a
   15 MB cell, invalid UTF-8, or a header `=HYPERLINK(...)` that later reaches the errors CSV.
   Expected:
   - each is refused before any row is staged, with its code and no echo;
   - formula cells in the errors CSV are neutralised.

   Pinned in Task 4 (`test_archive_refusals`, `test_parse_refusals`) and Task 8
   (`test_errors_csv_neutralises_formulas`).

---

### Task 1: Records — lists, mapping targets and tag choices (`contracts.newsletter_import`, part 1)

**Files:**
- Create:
  - `modules/records/sm_records/contracts/newsletter_import.py`
  - `modules/records/sm_records/public_submissions/campaign_lists.py`
- Modify: `modules/records/docs/api-reference.md` (§ Newsletter lists: a "Newsletter import
  contract" subsection, finished in Task 2)
- Test:
  - `modules/records/tests/public_submissions/test_newsletter_import_lists.py`
  - `modules/records/tests/core/test_layout.py`

**Interfaces (Produces):**
```python
# sm_records/contracts/newsletter_import.py
from sm_records.contracts.newsletter_admin import FieldChoice      # PR 6, reused
from sm_records.core.settings import RecordsSettings                # re-exported (R13)
RECORDS_PACKAGE = "sm_records"                                      # settings_for key (R13)
MAPPABLE_TYPES = ("text", "longtext", "email", "url", "select")
TAGS_FIELD = "tags"
MAX_NEW_CHOICES = 500
MAX_CHOICE_LEN = 100
class ImportField(SQLModel): key: str; label: str; type: str; choices: list[FieldChoice] = []
class ImportTargets(SQLModel):
    fields: list[ImportField]                          # ordinary, MAPPABLE_TYPES, not "tags", declared order
    tags: Literal["present", "creatable", "missing"]   # creatable = no tags field and no records (trash incl.)
class ListExists(Exception): ...                       # create_list: key taken in this tenant
class InvalidListKey(ValueError): ...                  # create_list: records refused key or label
class TagsFieldMissing(LookupError): ...               # add_tag_choices: R10

async def create_list(session, *, tenant_id: str, key: str, label: str,
                      settings: RecordsSettings, actor: str | None = None) -> str
async def importable_fields(session, *, tenant_id: str, type_key: str) -> ImportTargets | None
    # None for no such type in the tenant; SubscriberFilterError("not_a_list") for a non-list type
async def add_tag_choices(session, *, tenant_id: str, type_key: str, choices: Sequence[FieldChoice],
                          settings: RecordsSettings, actor: str | None = None) -> list[str]
    # values actually added, in the given order; existing values (and their labels) kept
```
- **`create_list`:** `type_service.create_type`, with:
  - `fields_raw` = `first_name` and `last_name` (text, `constraints.max_length = 100`, not
    required, not indexed);
  - `public_submissions={"kind": "subscription"}` (records fills its defaults);
  - `show_in_menu=True`.

  It maps records' `Conflict` to `ListExists` and `ValidationFailed` to `InvalidListKey`. It
  returns the key and does not commit.
- **`add_tag_choices`:**
  1. Validate first: at most `MAX_NEW_CHOICES`; each value and label a `str` of 1–100
     characters with no control characters or NUL; no duplicate values. Else `ValueError`.
  2. Take `lock_type`, then reload the type.
  3. With a `tags` multiselect, append the missing choices. With no `tags` field and no records
     (`record_count(include_deleted=True) == 0`), add
     `{"key": "tags", "type": "multiselect", "label": "Tags", "indexed": True,
     "options": {"choices": [...]}}`. Otherwise, or when `tags` is another type, raise
     `TagsFieldMissing`.
  4. Write with `update_type(..., fields_raw=…, expected_version=rtype.version)`. Retry once
     on `Conflict`.
  5. An empty addition writes nothing.
- **Shared behaviour.** Each function validates the tenant with `_checked_tenant`, binds with
  `tenant_scope` and pins `tenant_id`, as `contracts/newsletter.py` does. None commits.

- [ ] **Step 1: Failing tests** in `test_newsletter_import_lists.py`:
  - `test_create_list_is_a_subscription_list_with_names`:
    - `subscription_lists` contains the key;
    - `importable_fields` gives `first_name` and `last_name`, with `tags == "creatable"`;
    - the type's config has `double_opt_in` true and `enabled` false.
  - `test_create_list_twice_raises_list_exists`.
  - `test_create_list_bad_key_raises_invalid_list_key` (`"Bad Key"`).
  - `test_importable_fields_skips_system_tags_and_unmappable`: a list with `sm_*`, `tags`
    (multiselect), `age` (integer) and `team` (select) gives only `first_name`, `last_name`
    and `team` with its choices, and `tags == "present"`.
  - `test_importable_fields_unknown_is_none_and_form_raises` (`not_a_list`).
  - `test_add_tag_choices_appends_once`: `[a, b]`, then `[b, c]` gives `["c"]`. The labels of
    existing choices are unchanged.
  - `test_add_tag_choices_creates_field_on_empty_list`: after the call, `list_fields` (PR 6)
    shows `tags` with `many is True` and `indexed`, and `count_subscribers(filters=["tags:eq:a"])
    == 0` raises nothing (no reindex pending).
  - `test_add_tag_choices_refuses_populated_list_without_field`: one subscriber seeded →
    `TagsFieldMissing`, and the type version is unchanged.
  - `test_add_tag_choices_validates` (parametrized): 501 choices, an empty value, a 101-character
    label, a `"\x00"` and a duplicate value each raise `ValueError` with nothing written.
  - `test_import_lists_pin_the_tenant`: a list in `other` is invisible to `default`, and
    `create_list` in `default` with the same key succeeds.
  - `test_bound_other_tenant_raises` (`TenantIsolationError`).

  In `test_layout.py`, add `test_newsletter_import_contract_imports_cleanly_first`, the
  fresh-interpreter import, as for `contracts.newsletter`.
- [ ] **Step 2: Run**
  `uv run --directory modules/records pytest tests/public_submissions/test_newsletter_import_lists.py tests/core/test_layout.py -q -p no:cacheprovider`.
  Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `campaign_lists.py` (under 200 lines) and the contract's part 1. Reuse
  `campaign_reads.list_type`, `type_service.create_type`, `update_type`, `lock_type` and
  `record_count`.
- [ ] **Step 4: Run** Step 2 on SQLite and on Postgres (the scratch database, created and
  dropped). Expected: PASS.
- [ ] **Step 5: Commit** `feat(records): newsletter import contract — create_list, importable_fields, add_tag_choices`.

### Task 2: Records — `import_subscribers` (`contracts.newsletter_import`, part 2)

**Files:**
- Create: `modules/records/sm_records/public_submissions/campaign_import.py`
- Modify:
  - `modules/records/sm_records/contracts/newsletter_import.py`
  - `modules/records/docs/api-reference.md`
- Test: `modules/records/tests/public_submissions/test_newsletter_import_subscribers.py`

**Interfaces (Produces):**
```python
# contracts/newsletter_import.py (added)
ImportStatus = Literal["confirmed", "unsubscribed"]
ImportOutcome = Literal["created", "created_unsubscribed", "updated", "unchanged", "unsubscribed",
                        "kept_confirmed", "kept_pending", "kept_unsubscribed", "trashed", "invalid"]
MAX_IMPORT_BATCH = 500
CONSENT_TEMPLATE = "Imported from {source} on {date}"
class ImportRow(SQLModel):
    email: str
    status: ImportStatus
    fields: dict[str, str] = {}          # ordinary field key -> raw text (R9)
    tags: list[str] = []                 # tag VALUES; each must be a choice of `tags`
    confirmed_at: datetime | None = None # aware; R4
    consent_at: datetime | None = None
    unsubscribed_at: datetime | None = None   # the cutoff for an existing confirmed record (R3)
class ImportResult(SQLModel):
    email: str                           # normalised
    outcome: ImportOutcome
    dropped: list[str] = []              # field keys whose value records refused (R9)
async def import_subscribers(session, *, tenant_id: str, type_key: str, rows: Sequence[ImportRow],
                             settings: RecordsSettings, now: datetime,
                             source: str = "Mailchimp") -> list[ImportResult]
    # results in input order. ValueError before any query: > MAX_IMPORT_BATCH rows, a duplicate
    # normalised email, a naive datetime, an unknown status.
    # SubscriberFilterError("not_a_list") for a non-list type; LookupError for no such list.
async def opted_out_anywhere(session, *, tenant_id: str, emails: Sequence[str]) -> set[str]   # D1
    # the normalised addresses among `emails` that are `unsubscribed` on ANY of the tenant's
    # subscription lists, trashed records included; tenant-bound and pinned like the rest;
    # at most MAX_IMPORT_BATCH addresses (ValueError); one indexed query per list
    # (Filter("sm_email", IN, chunk) and sm_status = unsubscribed, include_deleted=True)
```
**Algorithm** (`campaign_import.py`). The whole call runs inside `events.muted(session)` (R5):
1. Look up every row's normalised address in one query: records' index, `Filter("sm_email",
   FilterOp.IN, chunk)`, `include_deleted=True`, tenant- and type-pinned, as `subscribe.find`
   does for one address. This gives `{email: Record}`.
2. Per row, inside `session.begin_nested()`, apply R3's records column:
   - **Create** (no record): `record_service.create_record(..., data=<mapped fields; {} for
     unsubscribed>, status=RecordStatus.DRAFT, system=<R4 values>)`.
   - **Existing confirmed + confirmed row** (amended by D5: a **validating** write only):
     1. Take PR 6's `row_lock.lock_record(db, record)` (the reload under the row lock).
     2. Re-check `sm_status == confirmed` and not trashed. A row whose status moved is decided
        again by the table (pending → `kept_pending`, and so on).
     3. Build `merged`: `_ordinary(rtype, row)`, plus each mapped field whose stored value is
        `None` or `""`, plus `tags` = stored tags with the new ones appended, deduplicated
        (`_merged` in `campaign_writes`). Equal to the stored values → `unchanged`, no write.
     4. Write with `record_service.update_record(db, rtype, row, expected_version=row.version,
        data=merged, settings=settings)`, which validates. **Never** `transition` and never
        `_merge_marks`: the direct-merge fallback writes unvalidated ordinary values, which an
        import must not do.
     5. `Conflict` (the version moved, which the lock makes rare): reload under the lock and
        decide once more; a second `Conflict` is `invalid`.
   - **Existing confirmed + unsubscribed row:** `opt_in.leave(db, rtype, record, settings,
     still=campaign_writes._holds(row.unsubscribed_at))`, which takes the PR 6 lock. `wrote` →
     `unsubscribed`, else `kept_confirmed`. `leave` emits only into the muted session.
   - Everything else is the table's `kept_*` or `trashed`, with no write.
3. `ValidationFailed` on create or merge: roll back the savepoint, drop the ordinary keys its
   `errors` name (`tags` included), and try once more in a new savepoint. A second failure is
   `invalid`. On the merge path a dropped key is dropped from the *new* values only; the
   stored value is kept (D5).
4. `Conflict` (a concurrent signup took the address under `unique`): reload the address and
   decide once more from the table. A second `Conflict` is `invalid`.

Lock order is the record row first (records), then newsletter's suppression rows (Task 6), the
same order as the unsubscribe page and PR 6's lift.

- [ ] **Step 1: Failing tests** in `test_newsletter_import_subscribers.py` (SQLite and
  Postgres). Use a list made by `create_list`, then `add_tag_choices([a, b])`. Attach a spy bus
  with `events.attach(session, spy)` before each call, and finish with `events.commit`:
  - `test_creates_confirmed_with_consent_snapshot`:
    - outcome `created`;
    - `iter_subscribers` (status `confirmed`) shows it with tags `[a]` and `first_name`;
    - `sm_consent_text == "Imported from Mailchimp on 2026-11-05"` (fixed `now`);
    - `sm_confirmed_at` equals the row's `confirmed_at`.
  - `test_confirmed_at_falls_back_and_is_clamped`: no times gives `now`; a future time gives
    `now`.
  - `test_creates_unsubscribed_record_without_values`: outcome `created_unsubscribed`; status
    `unsubscribed` with `sm_unsubscribed_at`; no `first_name`, no consent.
  - `test_existing_confirmed_appends_tags_and_fills_empty_fields`: tags `[b]` → `[b, a]`;
    `first_name` filled; an existing `last_name` kept; `updated`. Then the same row again gives
    `unchanged` with no version bump.
  - `test_existing_merge_validates` (D5, parametrized): on an existing confirmed subscriber
    with an empty `team` (select) and empty `first_name`, an import giving `team = "nope"`
    (not a choice), a 101-character `first_name` (over `max_length`) or tag `zzz` (not a
    choice) gives `updated` or `unchanged` with that key in `dropped`, and the stored record
    holds none of the refused values (read back through the ORM, not the hit).
  - `test_opted_out_anywhere` (D1): ada unsubscribed on list A (trashed afterwards), bob
    unsubscribed on list B, cy confirmed on A, dee pending → `{ada, bob}`; tenant `other`'s
    opt-outs are not reported; 501 addresses → `ValueError`.
  - `test_never_resubscribes_unsubscribed` (Review Focus 2): `kept_unsubscribed`, the record
    unchanged.
  - `test_pending_is_never_confirmed` (Review Focus 2): a `pending` signup plus a confirmed row
    gives `kept_pending`; status still `pending`; `sm_nonce` unchanged.
  - `test_unsubscribed_row_unsubscribes_confirmed_before_cutoff`: confirmed at T, cutoff T+1 →
    `unsubscribed`.
  - `test_unsubscribed_row_keeps_reconfirmed_after_cutoff`: cutoff T−1 → `kept_confirmed`.
  - `test_trashed_is_never_written`.
  - `test_import_publishes_no_events` (Review Focus 2): after a batch covering every outcome,
    the spy saw **no** event of any type, and in particular no `SubscriptionChanged` with
    `status_before == "pending"` and `status_after == "confirmed"`.
  - `test_invalid_value_is_dropped_not_fatal`: a `select` field given a non-choice gives
    `created` with `dropped == ["team"]`.
  - `test_unknown_tag_is_dropped`: tag `zzz` (not a choice) gives `created`, `dropped ==
    ["tags"]`, no tags.
  - `test_concurrent_signup_conflict_redecides` (Postgres only): session 1 creates the address
    through `subscribe` and holds; session 2's import of it ends `kept_pending`, never a
    500.
  - `test_import_takes_the_row_lock` (Postgres only): session 1 holds PR 6's
    `lock_confirmation(ada)`. Session 2's import of ada as unsubscribed has not finished after
    0.3 s, and finishes once session 1 commits. The same holds for an import of ada as
    confirmed with a new tag (the D5 merge path).
  - `test_batch_arguments_refused`: 501 rows; two spellings of one address; a naive datetime →
    `ValueError`.
  - `test_import_pins_the_tenant`: the same address in tenant `other` is untouched, and results
    in `default` are `created`.
- [ ] **Step 2: Run**
  `uv run --directory modules/records pytest tests/public_submissions/test_newsletter_import_subscribers.py -q -p no:cacheprovider`.
  Expected: FAIL.
- [ ] **Step 3: Implement** `campaign_import.py` (under 280 lines; split the per-row decision
  into `campaign_import_rows.py` if it grows) and the contract's part 2. Document the contract
  in `api-reference.md`:
  - R3's records column;
  - R4;
  - "publishes nothing";
  - "the caller writes suppressions".
- [ ] **Step 4: Run** Step 2, then records' existing newsletter tests (they must not change),
  on SQLite and Postgres:
  `uv run --directory modules/records pytest tests/public_submissions -q -p no:cacheprovider -n 8 -k "newsletter or opt_in or unsubscribe or confirm"`.
  Expected: PASS.
- [ ] **Step 5: Commit** `feat(records): import_subscribers for the newsletter Mailchimp import`.

### Task 3: Newsletter models, constants, errors and the migration

**Files:**
- Create:
  - `sm_newsletter/models/imports.py`
  - `sm_newsletter/imports/__init__.py` (docstring: R2, R3, R6, R14)
  - `sm_newsletter/imports/constants.py`
  - `sm_newsletter/core/errors_import.py`
  - `host/migrations/versions/<rev>_newsletter_imports.py`
- Modify:
  - `sm_newsletter/models/__init__.py`
  - `sm_newsletter/locales/en.json`, `de.json` (`errors.*`)
  - `tests/core/test_error_catalogue.py` (imports `core.errors_import`)
- Test: `tests/core/test_models.py`

(Paths without a prefix are under `modules/newsletter/`.)

**Interfaces (Produces):**
```python
# models/imports.py
class ImportJob(Base, MultiTenantMixin, table=True):
    __tablename__ = "newsletter_import"
    __table_args__ = (Index("ix_newsletter_import_at", "tenant_id", "created_at"),
                      Index("ix_newsletter_import_status", "status", "lease_until"))
    id: big_pk; list_type_key: str(MAX_TYPE_KEY_LEN); status: str(STATUS_LEN)   # ImportState
    files: list[dict] = json_col(list)       # [{name, kind, rows}]   name ≤ 200 chars
    columns: list[dict] = json_col(list)     # [{key, header}]        mappable columns, index = position
    mapping: dict = json_col(dict)           # {"fields": {"<col index>": "<field key>"}, "tags": bool}
    tags_found: list[dict] = json_col(list)  # [{label, value, count}], most frequent first
    tags_added: bool = False
    total: int = 0; duplicates: int = 0; invalid: int = 0                       # staging
    processed: int = 0; created: int = 0; updated: int = 0; skipped: int = 0
    suppressed: int = 0; failed: int = 0                                        # apply (R15)
    errors: list[dict] = json_col(list)      # [{file, line, code, field}] ≤ KEEP_ERRORS
    errors_total: int = 0
    error_code: str | None (STATUS_LEN)      # why status == failed
    lease_owner: str | None (36); lease_until: datetime | None
    created_by: str | None (64); created_at: datetime; started_at / finished_at: datetime | None
class ImportEntry(Base, MultiTenantMixin, table=True):
    __tablename__ = "newsletter_import_row"
    __table_args__ = (UniqueConstraint("tenant_id", "import_id", "email_hash", name="uq_newsletter_import_row"),
                      Index("ix_newsletter_import_row_todo", "tenant_id", "import_id", "outcome", "seq"))
    id: big_pk; import_id: int (FK newsletter_import.id ON DELETE CASCADE); seq: int
    file_index: int; line: int; kind: str(16)          # subscribed | unsubscribed | cleaned
    email: str(320); email_hash: str(64)
    fields: dict = json_col(dict)            # {"<col index>": value}, non-empty cells only
    tags: list[str] = json_col(list)         # labels (R8)
    event_at: datetime | None                # CONFIRM/OPTIN, UNSUB or CLEAN time
    consent_at: datetime | None              # OPTIN_TIME
    outcome: str | None (32)                 # NULL = to do (R14)
# imports/constants.py: R7's limits, plus
STAGED, QUEUED, RUNNING, DONE, FAILED = "staged", "queued", "running", "done", "failed"
STATES = (STAGED, QUEUED, RUNNING, DONE, FAILED)
KINDS = ("subscribed", "unsubscribed", "cleaned"); IGNORED = "ignored"
KIND_ORDER = {"cleaned": 0, "unsubscribed": 1, "subscribed": 2}         # precedence (R3)
EMAIL_HEADERS = ("email address", "email", "e-mail", "e-mail address", "e-mail-adresse", "email_address")
NAME_DEFAULTS = {"first_name": ("first name", "fname", "vorname"), "last_name": ("last name", "lname", "nachname")}
TAGS_HEADER = "tags"
MAILCHIMP_SYSTEM = frozenset({...})  # member_rating, optin_time, optin_ip, confirm_time, confirm_ip, latitude,
    # longitude, gmtoff, dstoff, timezone, cc, region, last_changed, leid, euid, notes, unsub_time,
    # unsub_campaign_title, unsub_campaign_id, unsub_reason, unsub_reason_other, clean_time,
    # clean_campaign_title, clean_campaign_id
BATCH_SIZE = 200; SLICE_SECONDS = 45; LEASE = timedelta(minutes=5); STAGE_CHUNK = 1000
ROW_ERROR_CODES = ("invalid_email", "cell_too_long", "tag_invalid", "invalid_value", "record_refused")
# core/errors_import.py (each a NewsletterError subclass; 422 unless noted)
ImportNotCsv "import_not_csv"; ImportNotUtf8 "import_not_utf8"; ImportMalformedCsv "import_malformed_csv"
ImportEmptyFile "import_empty_file"; ImportNoEmailColumn "import_no_email_column"
ImportZipUnsafe "import_zip_unsafe"; ImportTooLarge (413) "import_too_large"
ImportTooManyFiles "import_too_many_files"; ImportTooManyRows "import_too_many_rows"
ImportTooManyColumns "import_too_many_columns"; ImportTooManyTags "import_too_many_tags"
ImportBadMapping "import_bad_mapping"; ImportNotStaged (409) "import_not_staged"
ImportRunning (409) "import_running"; ListExists (409) "list_exists"; InvalidListKey "invalid_list_key"
```
Each class's `detail` names a file index, line, column index or field key, never a value.

- [ ] **Step 1: Failing tests** in `tests/core/test_models.py`:
  - add both tables to the expected set;
  - `test_import_job_defaults` (status, zero counters, empty JSON);
  - `test_import_row_unique_per_import_and_hash`: a second insert of the same hash in one
    import raises `IntegrityError`, and in another import it does not;
  - `test_import_rows_cascade_with_job`.

  `test_error_catalogue.py` picks up the new codes, so it fails until the catalogues have them.
- [ ] **Step 2: Run**
  `uv run --directory modules/newsletter pytest tests/core/test_models.py tests/core/test_error_catalogue.py -q -p no:cacheprovider`.
  Expected: FAIL.
- [ ] **Step 3: Implement** the models, constants and errors. Add `errors.<code>` in en and de
  for all 16 codes, then run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Generate the revision** against a scratch SQLite database, never `host/app.db`.
  1. With `SM_DATABASE_URL=sqlite+aiosqlite:////tmp/newsletter-pr7-mig.db`, run
     `uv run --project host alembic -c host/alembic.ini upgrade heads`.
  2. Run `… revision --autogenerate -m "newsletter imports"`.
  3. Check that the file:
     - creates exactly the two tables, their indexes, the unique constraint and the cascade FK;
     - has no branch label;
     - has `down_revision` set to the single prior head.
  4. Delete unrelated drift and report it. Run `upgrade heads`, `check`, `downgrade <parent>`,
     `upgrade heads` and `check`. Delete the scratch file.
- [ ] **Step 5: Postgres.**
  1. `PGPASSWORD=postgres createdb -h localhost -U postgres smpy_newsletter_mig_check`.
  2. With `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_mig_check`,
     run the same five alembic commands.
  3. `dropdb` it. Then drop and recreate `smpy_newsletter_test` and `…_gw0`…`_gw7` (R20).
- [ ] **Step 6: Run** `uv run python scripts/check_migration_heads.py` (one head, the new one),
  then Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 7: Commit** `feat(newsletter): import job and staged-row tables`.

### Task 4: Reading the export — archive safety and Mailchimp parsing (pure)

**Files:**
- Create:
  - `sm_newsletter/imports/archive.py`
  - `sm_newsletter/imports/mailchimp.py`
- Test:
  - `tests/imports/__init__.py`
  - `tests/imports/fixtures.py` (builders: `csv_bytes(headers, rows, delimiter=",", bom=False)`,
    `zip_bytes({name: bytes}, encrypt=False, ...)`)
  - `tests/imports/test_archive.py`
  - `tests/imports/test_mailchimp.py`

**Interfaces (Produces):**
```python
# archive.py
@dataclass(frozen=True)
class Source: index: int; name: str; open: Callable[[], BinaryIO]   # re-openable, so a file is peeked then read
def sources(uploads: Sequence[tuple[str, BinaryIO]]) -> list[Source]
    # one .zip (alone) or 1..MAX_FILES .csv parts; R7 checks; name = basename, ≤ 200 chars, control chars removed
    # raises ImportTooManyFiles, ImportNotCsv, ImportZipUnsafe, ImportTooLarge
# mailchimp.py
@dataclass(frozen=True)
class Header: delimiter: str; names: list[str]; email: int; tags: int | None
    times: dict[str, int]          # "optin" / "confirm" / "unsub" / "clean" -> column index
    mappable: list[int]            # columns offered for mapping (not email, TAGS or MAILCHIMP_SYSTEM)
@dataclass(frozen=True)
class Parsed: line: int; email: str; fields: dict[int, str]; tags: list[str]; event_at: datetime | None; consent_at: datetime | None
@dataclass(frozen=True)
class RowError: line: int; code: str; field: str | None = None   # field: a column header key, never a value
def header_key(text: str) -> str           # strip, BOM removed, casefold
def detect_kind(name: str, header: Header) -> str          # KINDS or IGNORED (R8)
def read_header(stream: TextIO) -> Header                  # ImportEmptyFile, ImportNoEmailColumn, ImportTooManyColumns
def read_rows(stream: TextIO, header: Header, kind: str) -> Iterator[Parsed | RowError]
    # ImportMalformedCsv(line) on csv.Error; ImportNotUtf8(line) on UnicodeDecodeError
def text_stream(binary: BinaryIO) -> TextIO                # utf-8-sig, newline="", strict
def parse_tags(cell: str) -> tuple[list[str], bool]        # (labels, any dropped)
def tag_values(labels: Sequence[str], existing: Sequence[FieldChoice]) -> dict[str, str]   # D8
    # label -> value, deterministic for the same inputs:
    # 1. an existing choice with exactly this label -> its value (reused);
    # 2. else the label itself, when it has no "," and no existing choice or other label in this
    #    call already has it as a value;
    # 3. else slug(label)[:80] + "-" + sha256(label.encode()).hexdigest()[:8], where slug is
    #    casefolded, every run outside [a-z0-9] -> "-", trimmed of "-" (empty slug -> "tag").
    # Labels are processed in sorted order, so the result does not depend on input order.
def parse_time(cell: str) -> datetime | None               # "%Y-%m-%d %H:%M:%S" as UTC
def valid_email(raw: str) -> str | None                    # normalise_email + email_validator(check_deliverability=False)
```
- `event_at` is `CONFIRM_TIME` or `OPTIN_TIME` for a subscribed row, `UNSUB_TIME` for an
  unsubscribed row and `CLEAN_TIME` for a cleaned one. `consent_at` is `OPTIN_TIME`.
- A cell over `MAX_CELL` is left out of the row, which carries a `RowError("cell_too_long",
  field=<header key>)` with the same line. Over `MAX_CELL` in the email column, the whole row
  is `invalid_email`.

- [ ] **Step 1: Failing tests.**
  - `test_mailchimp.py`:
    - `test_detect_kind_by_name_then_columns` (parametrized):
      - `subscribed_members_export_ab12.csv` → subscribed;
      - `unsubscribed_members_export_x.csv` → unsubscribed;
      - `cleaned_email_audience_export_x.csv` → cleaned;
      - `nonsubscribed_…` → ignored;
      - `list.csv` with `UNSUB_TIME` → unsubscribed;
      - `list.csv` plain → subscribed.
    - `test_standard_export_row`: Mailchimp's real header set (all `MAILCHIMP_SYSTEM` columns
      plus `Email Address,First Name,Last Name,TAGS`). Expected:
      - `email` is normalised;
      - `tags == ["VIP", "Customers, 2020"]`;
      - `event_at` is `CONFIRM_TIME` as UTC;
      - `mappable` holds only `First Name` and `Last Name`.
    - `test_semicolon_bom_german_headers` (Review Focus 3): `E-Mail-Adresse;Vorname;Nachname;TAGS`
      with a BOM gives `email == 0` and delimiter `;`.
    - `test_tag_rules`: an empty tag and a tag with a control character are dropped and
      flagged; 51 tags keep 50.
    - `test_tag_values_distinct_and_deterministic` (D8): `Customers, 2020` and `Customers; 2020`
      get different values, neither containing `,`; the same call twice, or with the labels
      reversed, gives the same mapping; `VIP` maps to `VIP`.
    - `test_tag_values_collision_with_existing_choice` (D8): an existing choice `{value: "VIP",
      label: "Very important"}` makes the new label `VIP` take the slug-and-hash value; an
      existing choice labelled `VIP` is reused as is.
    - `test_time_parse`: the Mailchimp format gives an aware UTC datetime; `""`, `"yesterday"`
      and `"2020-13-40 00:00:00"` give `None`.
    - `test_invalid_email_is_a_row_error_without_value`: `RowError(line=3,
      code="invalid_email", field=None)`, and its `repr` does not contain the address.
    - `test_cell_too_long_drops_cell_keeps_row`.
    - `test_parse_refusals` (parametrized, Review Focus 5):
      - an empty file → `ImportEmptyFile`;
      - no email header → `ImportNoEmailColumn`;
      - 201 columns → `ImportTooManyColumns`;
      - `b"\xff\xfe"` mid-file → `ImportNotUtf8` naming the line;
      - a NUL byte → `ImportMalformedCsv`.

      Each exception's `detail` contains no cell content.
  - `test_archive.py`:
    - `test_zip_members_selected`: `__MACOSX/x.csv`, `.hidden.csv`, `readme.txt` and
      `nested/dir/subscribed_x.csv` give one source named `subscribed_x.csv`.
    - `test_plain_csv_parts`: three `.csv` parts give three sources, in order.
    - `test_archive_refusals` (parametrized, Review Focus 5):
      - a ZIP plus a CSV → `ImportTooManyFiles`;
      - five CSVs → `ImportTooManyFiles`;
      - a `.xlsx` part → `ImportNotCsv`;
      - an encrypted entry (flag bit 0x1 set in the built archive) → `ImportZipUnsafe`;
      - an entry declaring 300 MiB → `ImportTooLarge`;
      - a declared ratio of 500 → `ImportZipUnsafe`;
      - a `bzip2` entry → `ImportZipUnsafe`;
      - 17 entries → `ImportZipUnsafe`;
      - a corrupt ZIP → `ImportZipUnsafe`.
- [ ] **Step 2: Run**
  `uv run --directory modules/newsletter pytest tests/imports/test_archive.py tests/imports/test_mailchimp.py -q -p no:cacheprovider`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** No database code. Use `csv.Sniffer().sniff(first_line,
  delimiters=",;\t")` with a `,` fallback. Never change `csv.field_size_limit` (it is
  process-global); a field over it is `csv.Error`, which is `ImportMalformedCsv`. Keep each file
  under 250 lines.
- [ ] **Step 4: Run** Step 2. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): Mailchimp export parsing with archive and CSV limits`.

### Task 5: Staging, the preview and the mapping

**Files:**
- Create:
  - `sm_newsletter/imports/staging.py`
  - `sm_newsletter/imports/mapping.py`
  - `sm_newsletter/imports/service.py`
  - `sm_newsletter/imports/lists.py`
- Test:
  - `tests/imports/test_staging.py`
  - `tests/imports/test_mapping.py`
  - `tests/imports/test_service.py`

**Interfaces:**
- Consumes:
  - Task 1 (`importable_fields`, `ImportTargets`, `create_list`, `ListExists`,
    `InvalidListKey`);
  - Task 3 models and constants;
  - Task 4 `sources`, `read_header`, `read_rows`, `detect_kind`, `tag_values`;
  - `core.suppression.email_hash`.
- Produces:
```python
# staging.py
async def stage(session, *, tenant_id: str, list_type_key: str, sources: Sequence[Source],
                created_by: str | None, now: datetime) -> ImportJob
    # 1. peek every source's header and kind; 2. stage files in KIND_ORDER (cleaned first), each row
    #    streamed into STAGE_CHUNK-row insert_ignore chunks on (tenant_id, import_id, email_hash):
    #    a skipped insert is a duplicate (R3 precedence, any spelling); 3. columns = union of mappable
    #    headers by header_key, in first-seen order; 4. tags_found from subscribed rows' tags
    #    (value, label, count), top 500 by count (ImportTooManyTags over MAX_NEW_TAGS distinct);
    #    value = tag_values(labels, existing=<the list's current tags choices>) - a preview value,
    #    re-decided by Task 6's tags-once step (D8);
    #    5. errors (≤ KEEP_ERRORS) and counts; 6. mapping = suggest(...). Over MAX_ROWS staged in all
    #    raises ImportTooManyRows; the caller's transaction is then rolled back, so nothing stays.
# mapping.py
Mapping = dict  # {"fields": {"<col>": key}, "tags": bool}
def suggest(columns: list[dict], targets: ImportTargets, tags_found: list[dict]) -> Mapping
def validate(raw: object, *, columns: list[dict], targets: ImportTargets, tags_found: list[dict]) -> Mapping
    # ImportBadMapping("fields.<col>") for: an unknown column, an unknown or non-mappable field, one field
    # twice; ImportBadMapping("tags") when tags is true and targets.tags == "missing"
# service.py
async def get_import(session, *, tenant_id: str, import_id: int, roles: Roles) -> ImportJob   # NotFound, R12
async def list_imports(session, *, tenant_id: str, roles: Roles, limit: int = 20) -> list[ImportJob]  # newest first, readable lists only
async def set_mapping(session, *, tenant_id: str, job: ImportJob, raw: object, targets: ImportTargets) -> ImportJob  # STAGED only, else ImportNotStaged
async def queue_apply(session, *, tenant_id: str, job: ImportJob) -> ImportJob
    # STAGED or FAILED -> QUEUED (conditional UPDATE pinned id, tenant, status), else ImportNotStaged
async def discard(session, *, tenant_id: str, job: ImportJob) -> None
    # STAGED/DONE/FAILED: rows and job deleted; QUEUED/RUNNING: ImportRunning
# lists.py
async def create_list(app, session, *, tenant_id: str, key: str, label: str) -> str
    # contract create_list with app.state.sm_records.settings, actor=current_user_id; ListExists -> errors_import.ListExists,
    # InvalidListKey -> errors_import.InvalidListKey
```

- [ ] **Step 1: Failing tests** (SQLite and Postgres). Use the records seed helpers in
  `tests/support/records_seed.py`, and lists from the records contract's `create_list`.
  - `test_staging.py`:
    - `test_stage_counts_kinds_and_columns`: subscribed ×3, unsubscribed ×1, cleaned ×1 give:
      - `total == 5`;
      - `files` with kinds and row counts;
      - `columns` holding First Name and Last Name;
      - `tags_found` with counts.
    - `test_precedence_cleaned_beats_subscribed_any_spelling` (Review Focus 1).
    - `test_precedence_unsubscribed_beats_subscribed`.
    - `test_duplicate_in_one_file_counted_once`.
    - `test_invalid_rows_reported_not_staged`: two bad addresses give `invalid == 2`, with
      errors `{file: 0, line: 3, code: "invalid_email", field: None}`.
    - `test_ignored_file_not_staged`.
    - `test_too_many_rows_refused`: monkeypatch `MAX_ROWS = 3` → `ImportTooManyRows`, and
      after rollback no job or row exists.
    - `test_stage_pins_the_tenant` (every inserted row has the job's `tenant_id`).
  - `test_mapping.py`:
    - `test_suggest_names_and_tags`: First Name maps to `first_name`, and tags is on when
      found and `tags != "missing"`;
    - `test_suggest_german_names`;
    - `test_validate_refusals` (parametrized): an unknown column, an unknown field, one field
      twice, tags on a list where tags are `missing`, and a non-dict all give
      `ImportBadMapping` with a detail naming the column index only.
  - `test_service.py`:
    - `test_get_import_other_tenant_is_404`;
    - `test_restricted_list_import_is_404` (`restrict_list`);
    - `test_queue_apply_only_from_staged_or_failed`;
    - `test_discard_deletes_rows`;
    - `test_discard_running_refused`;
    - `test_create_list_maps_errors`.
- [ ] **Step 2: Run**
  `uv run --directory modules/newsletter pytest tests/imports/test_staging.py tests/imports/test_mapping.py tests/imports/test_service.py -q -p no:cacheprovider -n 8`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** Use `core.upsert.insert_ignore` for the chunks: rows inserted ≠
  rows sent gives the duplicates. Pin `tenant_id` on every row.
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): stage a Mailchimp export with precedence, preview and mapping`.

### Task 6: Applying — the batch and the runner

**Files:**
- Create:
  - `sm_newsletter/imports/apply.py`
  - `sm_newsletter/imports/runner.py`
- Test:
  - `tests/imports/test_apply.py`
  - `tests/imports/test_runner.py`
  - `tests/support/import_world.py` (a list, a staged job from fixture CSVs, `run_all(factory)`)

**Interfaces:**
- Consumes:
  - Task 2 `import_subscribers`, `ImportRow`, `MAX_IMPORT_BATCH`, `opted_out_anywhere` (D1);
  - Task 4 `tag_values` (D8); PR 6 `list_fields`;
  - Task 1 `add_tag_choices`, `TagsFieldMissing`, `importable_fields`;
  - `core.suppression.suppressed` and `suppress_many`.
- Produces:
```python
# apply.py
@dataclass
class BatchResult: created: int; updated: int; skipped: int; suppressed: int; failed: int
    errors: list[dict]                        # {file, line, code, field}
async def apply_batch(session, *, tenant_id: str, job: ImportJob, rows: list[ImportEntry],
                      targets: ImportTargets, records_settings: Any, now: datetime) -> BatchResult
# runner.py
SliceResult = Literal["done", "more", "busy", "gone"]
async def run_import_async(factory, *, tenant_id: str, import_id: int, records_settings: Any,
                           clock: Callable[[], datetime] = utcnow,
                           slice_seconds: float = SLICE_SECONDS) -> SliceResult
```
**`apply_batch`**, in the caller's transaction. Order matters (lock order: records, then
suppressions):
1. **Subscribed rows that may not be admitted** get outcome `skipped_suppressed` and nothing
   else. A row is refused when either:
   - newsletter suppresses the address (`suppressed(...)` over the batch's addresses), or
   - records holds it `unsubscribed` on any of the tenant's lists, trash included (D1: records'
     `opted_out_anywhere`, in the same transaction, before any records write).
2. **The rest of the subscribed rows, and every unsubscribed row**, go through
   `import_subscribers`:
   - `fields` comes from `job.mapping["fields"]`: column → field key, keeping only targets that
     are still in `targets.fields`;
   - `tags` = each row label's value in the job's **final** `tags_found` map (D8; set by the
     tags-once step) when `mapping["tags"]`, else `[]`;
   - `confirmed_at = event_at`, `consent_at`, `unsubscribed_at = event_at`;
   - chunks of `MAX_IMPORT_BATCH`.

   Each `dropped` key becomes an `invalid_value` error with `field=<key>`, and `invalid`
   becomes `record_refused`.
3. **`suppress_many(reason=unsubscribed, list_type_key=job.list_type_key, source="import",
   refresh=False, now=now)`** for every unsubscribed row except `kept_confirmed`. Then
   **`suppress_many(reason=imported_cleaned, list_type_key="", source="import", refresh=False,
   now=now)`** for every cleaned row.
4. **Store each row's outcome** with grouped `UPDATE`s pinned to `(tenant_id, import_id, id IN
   …)`, and tally R15's counts.

**`run_import_async`** (amended by D2, D3, D6). One session per step, from `factory`, under
`tenant_scope(tenant_id)`.

**The fence (D3).** Every state write after the claim is a statement guarded by `WHERE id =
:id AND tenant_id = :t AND lease_owner = :me AND status = 'running'`. That covers:
- the tags-once mutation;
- each batch's counter update;
- the lease renewal;
- completion;
- the staged-row `DELETE`;
- the slice release;
- the failure write.

Writes to other tables in the same transaction (records, suppressions, row outcomes) are
committed only if that guard updated one row. The staged-row `DELETE` runs after the fenced job
`UPDATE`, in the same transaction, and only when it matched. A guard that matches zero rows
raises `LeaseLost`. The transaction rolls back, and the runner **writes nothing more**: no
failure write and no state change. It returns `"busy"`.

1. **Claim.** `UPDATE newsletter_import SET status='running', lease_owner=:me,
   lease_until=:now+LEASE, started_at=COALESCE(started_at, :now) WHERE id AND tenant_id AND
   status IN ('queued','running') AND (lease_owner IS NULL OR lease_until < :now)`. Zero rows:
   `gone` if the job is missing or not queued or running, else `busy`. `:me` is a fresh uuid4
   per call.
2. **Tags, once** (fenced; D8). In the first slice, when `mapping["tags"]` and `tags_found`
   and not `tags_added`:
   1. read the list's current `tags` choices (`list_fields`);
   2. recompute `tag_values(labels, existing)`;
   3. write the final values into `tags_found`;
   4. call `add_tag_choices` with the `FieldChoice(value, label)` of the values not yet
      present;
   5. set `tags_added`.

   All of this is in one transaction, which commits only if the fence matched.
   - `TagsFieldMissing` (the list gained records since staging) turns tags off for this import
     and adds one error `{file: None, line: None, code: "tags_unavailable", field: "tags"}`.
     Add `tags_unavailable` to `ROW_ERROR_CODES` and the catalogue.
3. **Loop while time remains** (`clock()`-based). Read ≤ `BATCH_SIZE` rows `outcome IS NULL
   ORDER BY seq`, then `apply_batch`, then the fenced counter update. The update also appends
   errors up to `KEEP_ERRORS`, adds to `errors_total` and renews `lease_until`. Then
   `finalize_session`.
4. **No rows left.** In one fenced transaction: `status='done'`, `finished_at`, lease cleared,
   and the `DELETE` of the job's rows (R6). Return `done`.
5. **Out of time** (D2). Commit a fenced release (`lease_owner = NULL`, `lease_until = :now`,
   which records when it was released; status stays `running`), then return `more`. The released job is claimable at once by the
   next slice with the same clock, so no expiry is needed.
6. **An unexpected exception (not `LeaseLost`)** (D6):
   1. Roll back.
   2. In a fresh session, write the fenced failure (`status='failed'`,
      `error_code='import_failed'`, lease cleared). A zero-row match writes nothing.
   3. Log `"newsletter import %s failed: %s"` with the import id and the exception's **class
      name** only. Never use `exc_info`, `str(exc)` or `repr(exc)`: an exception can carry an
      address.
   4. `raise ImportFailed("import failed") from None` (`errors_import.ImportFailed`, code
      `import_failed`, a fixed message), so no original exception is chained into a Celery
      result or traceback.
   5. Add `import_failed` to the catalogues.

- [ ] **Step 1: Failing tests** (SQLite and Postgres; `import_world` stages the fixture
  export):
  - `test_apply.py`:
    - `test_apply_writes_records_and_suppressions`: subscribed ada (tag VIP) and bob,
      unsubscribed cy, cleaned dee. Expected:
      - records has ada and bob `confirmed` (ada tagged `VIP`) and cy `unsubscribed`;
      - newsletter has `unsubscribed` (list, `source="import"`) for cy and `imported_cleaned`
        (`""`) for dee;
      - `suppressed(…)` reports cy and dee;
      - counts `created=2, suppressed=2, skipped=0, failed=0`.
    - `test_import_clears_no_suppression` (Review Focus 2): before the import, ada has
      `hard_bounce`, bob `imported_cleaned` and eve `complaint`, each with a known
      `created_at`. After an import naming all three as subscribed, all rows remain with
      unchanged `created_at` and `source`.
    - `test_suppressed_address_is_never_created` (Review Focus 2): ada has a newsletter
      `unsubscribed` row from another list. A subscribed ada is `skipped`, and records has no
      ada.
    - `test_opted_out_in_records_without_mirror_row_is_skipped` (D1): ada is `unsubscribed` on
      list A in records, and newsletter has **no** suppression row for her (the mirror was
      withheld). Importing her as subscribed into list B gives `skipped`; list B has no ada
      record; no records write happened for her.
    - `test_tag_values_final_and_distinct` (D8): an import with `Customers, 2020` and
      `Customers; 2020`, into a list whose existing choice already holds the value `VIP` under
      another label, gives distinct stored values, the original labels, and subscribers tagged
      with the right values.
    - `test_no_pending_to_confirmed_event`: with the newsletter mirror subscribed on a spy bus
      (`register_event_handlers`), run the import over a pending signup → the spy saw no
      `SubscriptionChanged`, and `clear_for_confirmation` was never called (monkeypatched to
      fail).
    - `test_kept_confirmed_gets_no_suppression`.
    - `test_invalid_value_reported_as_row_error`: `{code: "invalid_value", field: "team"}` with
      the row's file and line, and no value anywhere in `job.errors`.
    - `test_apply_pins_the_tenant`: the same address in tenant `other` and its suppressions are
      untouched.
  - `test_runner.py`:
    - `test_run_to_done_deletes_staged_rows`: `done`; there are no `newsletter_import_row`
      rows; `processed == total`; the counts add up to `total` (R15).
    - `test_slices_resume`: `slice_seconds=0` returns `more` after one batch, and the next call
      continues to `done`.
    - `test_consecutive_slices_with_fixed_clock` (D2): with a clock that never moves and
      `slice_seconds=0`, consecutive calls each claim at once (no `busy`, no manual lease
      expiry) and reach `done`. After each `more`, `lease_owner` is `NULL`.
    - `test_crash_mid_batch_resumes_without_duplicates` (Review Focus 4): monkeypatch
      `suppress_many` to raise on the second batch. The job is `failed` and the first batch's
      outcomes are kept. `queue_apply` then a run gives `done` and one record per address.
    - `test_rerun_same_export_changes_nothing` (Review Focus 4): stage and run the same export
      twice. The second run has `created=0, updated=0`; records rows and versions and the
      suppression rows are identical before and after.
    - `test_busy_when_leased`: a live lease gives `busy`; an expired lease is taken over.
    - `test_lease_lost_rolls_back_batch`: another owner written mid-batch means that batch's
      outcomes and records writes are absent.
    - `test_stale_worker_after_takeover_changes_nothing` (D3; two real sessions, run on both
      backends):
      1. Worker A claims and pauses (an `asyncio.Event`) after reading a batch.
      2. A's lease is expired; worker B claims and runs to `done`.
      3. A resumes.

      Expected: A gets `busy`; there are no extra records, suppressions or outcome writes; the
      job stays `done` with B's counts and `finished_at`; A did not set `failed`, did not touch
      `tags_found` or `tags_added`, and did not delete or re-insert rows. The same holds when A
      pauses inside the tags-once step, and when A's pending action is the failure write
      (injected exception).
    - `test_failure_is_sanitised` (D6): `import_subscribers` monkeypatched to raise
      `RuntimeError("boom sentinel-7f3a@example.org")`. Expected:
      - `ImportFailed` is raised and its `__cause__` and `__context__` are `None`;
      - `caplog.text` has no `sentinel-7f3a`;
      - `job.error_code == "import_failed"`;
      - nothing stored on the job contains the sentinel.
    - `test_tags_added_once_and_unavailable_turns_tags_off`.
    - `test_runner_pins_the_tenant`: running tenant A's id with `tenant_id="other"` gives
      `gone`.
- [ ] **Step 2: Run**
  `uv run --directory modules/newsletter pytest tests/imports/test_apply.py tests/imports/test_runner.py -q -p no:cacheprovider -n 8`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): apply staged imports in leased, resumable batches`.

### Task 7: The task, the launch and the janitor

**Files:**
- Create:
  - `sm_newsletter/imports/launch.py`
  - `sm_newsletter/imports/janitor.py`
- Modify:
  - `sm_newsletter/tasks.py` (`run_import`, `import_janitor`; keep the module light)
  - `sm_newsletter/task_config.py` (routes and the hourly beat)
- Test:
  - `tests/imports/test_launch.py`
  - `tests/imports/test_janitor.py`
  - `tests/core/test_task_discovery.py`

**Interfaces (Produces):**
```python
# task_config.py
RUN_IMPORT = "newsletter.run_import"; IMPORT_JANITOR = "newsletter.import_janitor"
TASK_ROUTES[...] = {"queue": QUEUE_DEFAULT}; JANITOR_INTERVAL_SECONDS = 3600.0
BEAT_SCHEDULE["newsletter-import-janitor"] = {"task": IMPORT_JANITOR, "schedule": 3600.0, "options": {"queue": QUEUE_DEFAULT}}
# tasks.py
@shared_task(name=RUN_IMPORT)
def run_import(tenant_id: str, import_id: int) -> str
    # run_platform(lambda f: run_import_async(f, tenant_id=..., import_id=..., records_settings=records_worker_settings()))
    # "more" -> the slice already committed its release (D2), so enqueue the next one:
    #   run_import.s(tenant_id, import_id).apply_async(queue=QUEUE_DEFAULT); returns the SliceResult.
    # ImportFailed -> returns "failed" (D6): the failure is already recorded on the job, and the
    #   task result is the fixed string, never an exception that could carry a value.
@shared_task(name=IMPORT_JANITOR)
def import_janitor() -> dict[str, int]          # run_platform(janitor_async)
# launch.py
def records_worker_settings() -> RecordsSettings   # background_tasks.settings_for(RecordsSettings, RECORDS_PACKAGE)
async def launch(app, *, tenant_id: str, import_id: int) -> None
    # celery_eager(): loop `await run_import_async(app.state.sm.db.session_factory, ..., records_settings=
    #   app.state.sm_records.settings)` while it returns "more" (each slice has released its lease, D2);
    #   ImportFailed is caught (the job says failed; the request answers 202 with that state);
    # else run_import.s(...).apply_async(queue=QUEUE_DEFAULT)
def celery_eager() -> bool                         # current_app.conf.task_always_eager, as images
# janitor.py
async def janitor_async(factory, *, now: datetime) -> dict[str, int]   # {"expired", "relaunched", "failed"}
    # one narrow read under all_tenants(): (tenant_id, id, status) of jobs STAGED/FAILED older than
    # STAGED_TTL, QUEUED older than LEASE, and RUNNING whose lease_until < now - LEASE (released
    # by a slice whose follow-up message was lost, D2) or, while owned, lease_until < now;
    # per tenant under tenant_scope: delete expired (rows cascade), relaunch the rest via run_import.apply_async
```
- [ ] **Step 1: Failing tests.**
  - `test_launch.py`:
    - `test_eager_launch_runs_inline_to_done` (`task_always_eager` on): with
      `SLICE_SECONDS = 0` and a fixed clock, one `launch` reaches `done` across several slices
      (D2);
    - `test_broker_launch_sends_message` (eager off, `apply_async` monkeypatched to record its
      args and queue);
    - `test_task_chains_slices_to_done` (D2): the `run_import` task body called directly, with
      `apply_async` monkeypatched to call the task body again synchronously, `SLICE_SECONDS = 0`
      and a fixed clock. One launch reaches `done`, and no slice returns `busy`;
    - `test_task_result_is_sanitised` (D6): with eager on and `import_subscribers` raising an
      exception that carries a sentinel address, `run_import.apply(args=…)` gives `.result ==
      "failed"`; `str(result.traceback or "")` and `caplog.text` have no sentinel;
    - `test_records_worker_settings_reads_settings_for` (monkeypatched).
  - `test_janitor.py`:
    - `test_expires_old_staged_and_failed`;
    - `test_relaunches_stale_queued_and_expired_running`;
    - `test_leaves_fresh_and_done`;
    - `test_janitor_per_tenant`: two tenants, each touched under its own tenant.
  - `test_task_discovery.py`: both task names are registered, routed to `newsletter`, and the
    beat has the janitor entry.
- [ ] **Step 2: Run**
  `uv run --directory modules/newsletter pytest tests/imports/test_launch.py tests/imports/test_janitor.py tests/core/test_task_discovery.py -q -p no:cacheprovider`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): import task, eager launch and hourly import janitor`.

### Task 8: The import and list API

**Files:**
- Create:
  - `sm_newsletter/web/schemas/imports.py`
  - `sm_newsletter/web/endpoints/imports_api.py`
  - `sm_newsletter/web/endpoints/lists_api.py`
  - `sm_newsletter/imports/csv_safe.py`
- Modify:
  - `sm_newsletter/web/endpoints/__init__.py`
  - `sm_newsletter/module.py` (`register_body_limits`)
  - `tests/web/test_route_guards.py`
- Test:
  - `tests/web/test_imports_api.py`
  - `tests/web/test_lists_api.py`
  - `tests/imports/test_csv_safe.py`

**Routes** (`bind_admin` first, then `RequiresPermission(PERM_MANAGE)`; every write is under the
module's CSRF wrapper):

| Method, path | Body | Answer |
|---|---|---|
| `POST /lists` | `{key, label}` | 201 `{key}`. `parse_payload`: `key` 1–64, `label` 1–200 |
| `POST /imports` | multipart: `list` (type key), `files` (1–4) | 201 `ImportOut`. `require_list`; `request.form(max_part_size=MAX_UPLOAD_BYTES, max_files=MAX_FILES, max_fields=8)`; `MultiPartException` → `ImportNotCsv` |
| `GET /imports` | | `list[ImportSummaryOut]` |
| `GET /imports/{id}` | | `ImportOut` (polled) |
| `PATCH /imports/{id}` | `{mapping}` | `ImportOut` |
| `POST /imports/{id}/apply` | `{}` | 202 `ImportOut`. Commits `queued` (`finalize_session`), then `launch` |
| `DELETE /imports/{id}` | | 204 |
| `GET /imports/{id}/errors.csv` | | `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="import-<id>-errors.csv"`, `Cache-Control: no-store` |

```python
class ImportFileOut(BaseModel): name: str; kind: str; rows: int
class ImportColumnOut(BaseModel): index: int; header: str
class ImportTagOut(BaseModel): label: str; value: str; count: int
class ImportErrorOut(BaseModel): file: int | None; line: int | None; code: str; field: str | None
class ImportOut(BaseModel):
    id: int; list_type_key: str; status: str; files: list[ImportFileOut]; columns: list[ImportColumnOut]
    mapping: dict; targets: ImportTargetsOut          # {fields: [{key, label, type}], tags}
    tags_found: list[ImportTagOut]; total: int; duplicates: int; invalid: int; processed: int
    created: int; updated: int; skipped: int; suppressed: int; failed: int
    errors: list[ImportErrorOut]                      # the first 50; the CSV has up to KEEP_ERRORS
    errors_total: int; error_code: str | None; created_at: datetime; started_at: datetime | None
    finished_at: datetime | None
class ImportSummaryOut(BaseModel): id: int; list_type_key: str; status: str; total: int; processed: int; created_at: datetime
# csv_safe.py
def neutralise(cell: str) -> str       # prefix "'" when the cell starts with = + - @ \t \r
def errors_csv(job: ImportJob) -> str  # header file,file_name,line,code,field; every cell neutralised
```
`targets` is read live with `importable_fields`, so a field removed since staging disappears
from the mapping.

`module.register_body_limits` registers the ceiling `MAX_UPLOAD_BYTES + 1 MiB` for `POST` on
the regex `^/api/newsletter/imports/?$`, as images does.

- [ ] **Step 1: Failing tests.**
  - `test_imports_api.py` (the HTTP test app; fixtures from `tests/imports/fixtures.py`):
    - `test_upload_zip_then_preview` (201; counts, files, columns, `tags_found`, suggested
      mapping);
    - `test_upload_three_csv_parts`;
    - `test_patch_mapping_round_trip_and_bad_mapping_422`;
    - `test_apply_eager_runs_to_done` (polled `GET` shows `done` and the counts);
    - `test_apply_twice_is_409`;
    - `test_discard_then_404`;
    - `test_upload_over_limit_413` (`Content-Length` over the ceiling, through the framework
      body guard on the test app; if the test app has no guard, assert `ImportTooLarge` from a
      monkeypatched lower `MAX_UPLOAD_BYTES`);
    - `test_refusals_do_not_echo` (parametrized over Task 4's refusals): each response body
      contains neither the file name nor any cell text;
    - `test_permissions` (`newsletter.edit` → 403 on every route; manage → OK);
    - `test_csrf_required_on_writes`;
    - `test_restricted_list_404` (upload to a list narrowed by `allowed_roles`);
    - `test_other_tenants_import_404` (`x-tenant: other`);
    - `test_errors_csv_neutralises_formulas` (Review Focus 5): a file named `=cmd.csv` with an
      invalid row gives a CSV whose `file_name` cell starts with `'=`, with the headers above.
  - `test_lists_api.py`:
    - create 201;
    - duplicate 409 `list_exists`;
    - bad key 422 `invalid_list_key`;
    - `newsletter.edit` → 403;
    - the new list appears in `GET /lists`.
  - `test_csv_safe.py`: every trigger character, and a safe cell unchanged.
  - `test_route_guards.py`: every new route is guarded by `PERM_MANAGE` and `bind_admin`.
- [ ] **Step 2: Run**
  `uv run --directory modules/newsletter pytest tests/web/test_imports_api.py tests/web/test_lists_api.py tests/imports/test_csv_safe.py tests/web/test_route_guards.py -q -p no:cacheprovider -n 8`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** The upload handler stages in the request transaction and finishes
  with `finalize_session`. The `UploadFile`s are closed in `finally`.
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): import and create-list API`.

### Task 9: The e2e dispatch hook (R17)

**Files:**
- Modify:
  - `sm_newsletter/sending/runtime.py` (`tick_in_app`)
  - `sm_newsletter/web/endpoints/outbox_api.py`
  - `tests/web/test_route_guards.py`
- Test: `tests/web/test_outbox_api.py`

**Interfaces (Produces):**
```python
async def tick_in_app(app) -> TickSummary
    # settings = app.state.sm_newsletter.settings; secret = the web process's secret (as the test send
    # reads it); transport = transport_for(settings); then, under the framework's no_tenant(),
    # tick(app.state.sm.db.session_factory, settings=..., secret=..., transport=...)
@router.post("/outbox/dispatch", response_model=TickOut)   # PERM_MANAGE (router), bind_admin
    # 404 OutboxUnavailable unless dispatch_hook_enabled(app); CSRF via the API router's wrapper
def dispatch_hook_enabled(app) -> bool
    # settings.transport == "console" and celery_eager() and the host's environment
    # (app.state.sm.settings.environment, i.e. SM_ENVIRONMENT) in {"development", "testing"}
class TickOut(BaseModel): started: int; spent: int; finished: int; stopped: str | None
```
- [ ] **Step 1: Failing tests** in `test_outbox_api.py`:
  - `test_dispatch_404_unless_all_conditions` (parametrized): each case flips exactly one
    condition and expects 404; the all-true case expects 200.
    - smtp transport (eager, `testing`) → 404;
    - not eager (console, `testing`) → 404;
    - environment `production` (console, eager) → 404;
    - environment `staging` (console, eager) → 404;
    - console + eager + `development` → 200; console + eager + `testing` → 200.
  - `test_dispatch_requires_csrf`: no token → 403, as the other write tests check.
  - `test_dispatch_sends_a_due_campaign`: seed a scheduled campaign due now (PR 4's
    `dispatch_world`), call the route (once or twice), then `GET /outbox` has the message and
    progress shows `sent`.
  - `test_dispatch_needs_manage` (403 for `newsletter.send`).
- [ ] **Step 2: Run**
  `uv run --directory modules/newsletter pytest tests/web/test_outbox_api.py tests/web/test_route_guards.py -q -p no:cacheprovider`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): console-only dispatch hook for development and e2e`.

### Task 10: UI foundation — types, client, hook, catalogue

**Files:**
- Create:
  - `ui/utils/importTypes.ts`
  - `ui/utils/importApi.ts`
  - `ui/hooks/useImport.ts`
- Modify: `locales/en.json`, `de.json` (`import.*`, `menu.import`)
- Test:
  - `ui/utils/importApi.test.ts`
  - `ui/hooks/useImport.test.ts`

(UI paths are under `modules/newsletter/sm_newsletter/`.)

**Interfaces (Produces):**
```ts
export type ImportStatus = 'staged' | 'queued' | 'running' | 'done' | 'failed';
export type ImportKind = 'subscribed' | 'unsubscribed' | 'cleaned' | 'ignored';
export type RowErrorCode = 'invalid_email' | 'cell_too_long' | 'tag_invalid' | 'invalid_value' | 'record_refused' | 'tags_unavailable';
export interface ImportMapping { fields: Record<string, string>; tags: boolean }
export interface ImportJob { /* mirrors ImportOut */ }
export interface ImportSummary { id: number; list_type_key: string; status: ImportStatus; total: number; processed: number; created_at: string }
// importApi.ts (uses http.ts's BASE, csrfHeaders, errorFrom; FormData without a JSON content-type)
createList(key: string, label: string): Promise<{ key: string }>
uploadImport(list: string, files: File[]): Promise<ImportJob>
getImport(id: number, signal?: AbortSignal): Promise<ImportJob>
listImports(): Promise<ImportSummary[]>
setMapping(id: number, mapping: ImportMapping): Promise<ImportJob>
applyImport(id: number): Promise<ImportJob>
discardImport(id: number): Promise<void>
errorsCsvUrl(id: number): string
// useImport.ts
export function useImport(initialId: number | null): {
  job: ImportJob | null; error: string | null; busy: boolean;
  upload(list: string, files: File[]): Promise<void>; saveMapping(m: ImportMapping): Promise<void>;
  apply(): Promise<void>; discard(): Promise<void>; open(id: number): void; reset(): void }
  // polls getImport every 2 s while queued/running (as useCampaignProgress), aborts on unmount
```
**Catalogue keys** (en and de):
- `menu.import`
- `import.{title, description, list_label, new_list, upload_label, upload_hint, upload, files, kind, rows, duplicates, invalid, columns, column, target, not_imported, tags_switch, tags_found, tags_missing_hint, tags_hint_segments, apply, applying, discard, history, history_empty, errors, errors_download, errors_more, done, failed, progress, summary}`
- `import.kinds.{subscribed, unsubscribed, cleaned, ignored}`
- `import.status.{staged, queued, running, done, failed}`
- `import.counts.{created, updated, skipped, suppressed, failed}`
- `import.row_errors.{invalid_email, cell_too_long, tag_invalid, invalid_value, record_refused, tags_unavailable}`
- `import.new_list_dialog.{title, key, key_hint, label, create, cancel}`
- `import.suppression_note`: "Unsubscribed and cleaned contacts are never mailed. Existing
  opt-outs and bounces stay."

- [ ] **Step 1: Failing tests.**
  - `importApi.test.ts`:
    - the upload is a `POST` of `FormData` with a `list` field and `files` parts, carrying the
      CSRF header and no JSON `Content-Type`;
    - a 422 `{code: "import_not_utf8"}` becomes `HttpError` with that code;
    - `errorsCsvUrl(3) === "/api/newsletter/imports/3/errors.csv"`.
  - `useImport.test.ts`:
    - polling starts on `queued` and stops on `done`;
    - unmount aborts;
    - an upload error sets `error` to the translated `errors.<code>`.
- [ ] **Step 2: Run**
  `npx vitest run modules/newsletter/sm_newsletter/ui/utils/importApi.test.ts modules/newsletter/sm_newsletter/ui/hooks/useImport.test.ts`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2, `tsc` and `biome`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): import client, types and polling hook`.

### Task 11: UI — the Import screen

**Files:**
- Create:
  - `pages/Import.tsx`
  - `ui/components/import/ListPicker.tsx`
  - `ui/components/import/CreateListDialog.tsx`
  - `ui/components/import/UploadStep.tsx`
  - `ui/components/import/ImportSummary.tsx`
  - `ui/components/import/MappingTable.tsx`
  - `ui/components/import/ImportProgress.tsx`
  - `ui/components/import/ImportErrors.tsx`
  - `ui/components/import/ImportHistory.tsx`
- Modify:
  - `web/endpoints/views.py` (or a new `views_import.py` if `views.py` passes 250 lines):
    `GET /import` (`bind_admin`, `PERM_MANAGE`) renders `Newsletter/Import` with
    `{…view_props, lists: readable_lists, initial_import: ?id}`
  - `web/endpoints/menu.py`: Import, `[PERM_MANAGE]`, order 360, icon `upload`
  - `core/constants.py` (menu constants)
- Test:
  - `ui/components/import/ImportPage.test.tsx` (it renders `pages/Import.tsx`)
  - `ui/components/import/MappingTable.test.tsx`
  - `ui/components/import/CreateListDialog.test.tsx`
  - `ui/components/import/ImportProgress.test.tsx`
  - `tests/web/test_views.py`
  - `tests/web/test_route_guards.py`

**The page** runs top to bottom. Each step is a card, using `@simple-module-py/ui`.
1. **List.** `ListPicker` is a select of `lists`, plus *New list*, which opens
   `CreateListDialog`.
   - `key` is pre-filled from the label as a slug (`[a-z0-9_]`).
   - After it is created, the list is selected and added to the options.
2. **Upload.** A file input (`accept=".zip,.csv"`, `multiple`) and *Upload*. While uploading,
   the button is busy.
3. **Preview** (status `staged`):
   - `ImportSummary`: per file its name, kind badge and rows; totals with duplicates and
     invalid; `import.suppression_note`.
   - `MappingTable`: one row per column, with a select of `targets.fields` and *Not imported*.
     A field already chosen is disabled in the other selects.
   - The tags switch is disabled with `tags_missing_hint` when `targets.tags === 'missing'`.
   - `tags_found` is shown as badges with counts, under `tags_hint_segments` ("Mailchimp
     segments are not exported; recreate them as segments with these tags").
   - *Apply* saves the mapping first, then applies. *Discard* asks, then discards.
4. **Progress** (`queued` / `running`): `ImportProgress` shows `processed / total`, a progress
   bar and the five counts.
5. **Result** (`done` / `failed`):
   - the counts;
   - `ImportErrors`, a table of the first 50 errors: file name (`files[file].name`), line,
     `import.row_errors.<code>`, field;
   - *Download all errors* (`errorsCsvUrl`) when `errors_total > 0`;
   - for `failed`, `errors.<error_code>` and *Apply again*.

`ImportHistory` lists recent imports. Choosing one opens it, which reloads its state (a running
import is resumed in the view).

- [ ] **Step 1: Failing tests.**
  - `ImportPage.test.tsx`: a staged job renders the summary, mapping and tags; *Apply* calls
    `setMapping` then `applyImport`; a running job shows progress; a done job shows the counts
    and the errors link.
  - `MappingTable.test.tsx`: choosing `first_name` for column 0 disables it for column 1;
    `missing` tags disables the switch and shows the hint.
  - `CreateListDialog.test.tsx`: the key derives from the label; a 409 `list_exists` is shown
    translated.
  - `ImportProgress.test.tsx`: `processed / total` and the counts.
  - `test_views.py`: `GET /admin/newsletter/import` needs manage and passes `lists`.
  - `test_route_guards.py`: the new view.
- [ ] **Step 2: Run**
  `npx vitest run modules/newsletter/sm_newsletter/ui/components/import` and
  `uv run --directory modules/newsletter pytest tests/web/test_views.py tests/web/test_route_guards.py -q -p no:cacheprovider`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** Keep every file under 250 lines. Run
  `uv run python scripts/check_locales.py` and `uv run python scripts/check_hardcoded_strings.py`.
- [ ] **Step 4: Run** Step 2, `tsc` and `biome`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): Mailchimp import screen with list creation and mapping`.

### Task 12: The e2e spec, its own CI job (D4) and its config

**Files:**
- Create:
  - `tests/e2e/newsletter.spec.ts`
  - `tests/e2e/newsletter-helpers.ts`, holding:
    - `configureNewsletter(page, cleanup: Cleanup)` (R18, D7);
    - `restoreSettings(cleanup)`;
    - `mailchimpCsv(rows)`;
    - `importViaApi(page, list, files) → ImportJob` (`POST /imports`, `POST …/apply`, polled
      to `done`);
    - `outbox(page)`;
    - `tickUntil(page, campaignId, predicate)`;
    - `lookupSuppressions(page, email)` (PR 6's `POST /api/newsletter/suppressions/lookup`).
- Modify:
  - `tests/e2e/helpers.ts`: `moduleCsrfHeader`'s view union gains `'/admin/newsletter/'`.
  - `playwright.config.ts` (D4):
    - `E2E_NEWSLETTER=1` matches only `newsletter\.spec\.ts`. Every other run ignores both
      `billing-user\.spec\.ts` and `newsletter\.spec\.ts`, so the production-bundle shards
      never run it.
    - With `E2E_NEWSLETTER=1`, `webServer.env.SM_ENVIRONMENT` is `testing`, not
      `development` or `production`.
    - The config throws at load when `E2E_NEWSLETTER=1` and `E2E_BUNDLE=1` are both set (the
      hook is a 404 in production by design, R17), and likewise with `E2E_MULTI_TENANT` or
      `E2E_BILLING_USER`.
    - A comment explains why, in the style of the `E2E_BILLING_USER` block.
  - `.github/workflows/ci.yml` (D4): a job `e2e-newsletter`, `name: E2E (newsletter)`, modelled
    on `e2e-billing-user`:
    - `env: E2E_NEWSLETTER: "1"` and **no** `E2E_BUNDLE`;
    - `timeout-minutes: 30`;
    - the `e2e-setup` action;
    - `npm run test:e2e`;
    - the flaky summary;
    - a `playwright-report-newsletter` artifact.

    Celery eager and the in-memory broker come from `start-test-server.sh` as for every run.
    The console transport is set by the spec (R18).

The spec is standalone (CLAUDE.md): it seeds everything it reads and restores every setting it
changes.

**Settings lifetime (D7).**
- The describe block holds a `cleanup` record `{newsletter?: object, host?: {had: boolean,
  value?: string}}`.
- `configureNewsletter` writes into it the original value of each setting **before** that
  setting's first write. So `cleanup` is registered before the first mutation, and a setup
  that fails half-way leaves exactly the changed settings recorded.
- `test.afterAll(async ({ browser }) => …)` restores through a **fresh authenticated
  context**, as `tests/e2e/branding.spec.ts:105` does: `browser.newPage()`, `login`,
  `restoreSettings(cleanup)`, close. It runs whether the test passed or not, and needs no
  page from the test.
- `restoreSettings` restores only what `cleanup` names:
  - the newsletter settings with one `PUT`;
  - the host field with `PUT` of its old value, or `DELETE
    /api/settings/modules/host/public_base_url` when there was none.

**Test 1, `restore handles a partial setup` (D7).**
1. Call `configureNewsletter` with the helper's `failAfter: "newsletter"` option. It throws
   after writing the newsletter settings and before the host write.
2. Call `restoreSettings(cleanup)`.
3. Expect the newsletter settings to equal the originals (GET), and `cleanup.host` to be
   undefined (nothing to restore).

**Test 2, the walkthrough: one `test()` of named `test.step`s:**
1. **Setup.**
   - `login`;
   - `configureNewsletter(page, cleanup)`: `PUT /api/newsletter/settings {transport:
     "console", from_address: "news@example.org", from_name: "E2E News", physical_address: "1
     Test Street, 12345 Testville"}`, then `PUT /api/settings/modules/host {public_base_url:
     <baseURL>}`;
   - `seedArticle(page, {titlePrefix: "Newsletter card", publish: true, body:
     paragraphBody("…")})`.
2. **Create a list.** On `/admin/newsletter/import`, *New list* → label `E2E list <rand>` →
   Create. It is selected. Addresses below are `<name>-<rand>@example.org`.
3. **A suppressed `vip` subscriber, before the main import (D9).**
   1. `importViaApi` a subscribed file with carl (`TAGS` `"vip"`). Carl is a confirmed `vip`
      subscriber.
   2. `importViaApi` a cleaned file with carl. Carl now has an `imported_cleaned` suppression,
      the import's own bounce kind, and records still holds him `confirmed`.
4. **Import through the UI.**
   - Upload three in-memory CSVs:
     - `subscribed_members_export_e2e.csv`: ada with `TAGS` `"vip"`, bob with `"other"`, carl
       with `"vip"`;
     - `unsubscribed_members_export_e2e.csv`: cy;
     - `cleaned_members_export_e2e.csv`: dee.
   - The preview shows the three kinds, the tags `vip` and `other`, and First Name mapped.
   - Apply. The result shows `created 2`, `skipped 1` (carl, suppressed) and `suppressed 2`.
5. **The suppressions are checked on their own (D9).**
   - `lookupSuppressions(cy)` shows reason `unsubscribed` with `source` `import` and the list.
   - `lookupSuppressions(dee)` shows `imported_cleaned`.
   - `lookupSuppressions(carl)` shows `imported_cleaned`.
   - On the Subscribers screen (PR 6), the list's *Unsubscribed* tab lists cy, and dee appears
     on no tab (no record).
6. **Campaign with an article card.** Create a campaign on the new list with subject `E2E issue
   <rand>`. Insert a news article card and pick the seeded article; it is saved.
7. **Preview.** The preview iframe contains the article's title.
8. **Test send.** Send a test to `tester-<rand>@example.org`. `GET /api/newsletter/outbox` has
   a message to it whose subject starts with `[TEST]`.
9. **Schedule to a tag.** Audience *A tag* → `vip` (PR 6's picker), then *Send now* and
   confirm. The status is scheduled.
10. **Dispatch and progress.** `tickUntil` posts `/api/newsletter/outbox/dispatch` until
    `GET …/campaigns/{id}/progress` reports no `queued` rows and `sent == 1` (at most 5 ticks).
    After a reload, the campaign screen shows the progress text for 1 sent.
11. **Suppression proven in delivery (D9).** Of the campaign's messages in the outbox
    (subject `E2E issue <rand>`):
    - exactly one went to ada;
    - **none to carl**, a confirmed `vip` subscriber who is suppressed;
    - none to bob (other tag), cy or dee.

    The progress or report counts carl as suppressed, not sent.
12. **Report.** The report page (PR 5) shows sent 1.
13. **Unsubscribe.**
    - Take ada's message's `List-Unsubscribe` URL (it points at the configured base) and
      `page.goto` it. Click *Unsubscribe*; the page confirms.
    - The Subscribers screen's *Unsubscribed* tab lists ada.
    - The report's unsubscribes is 1.

- [ ] **Step 1: Write the spec, the helpers and the config and CI changes.** Locate elements by
  role and accessible name from the catalogues' English text. No `waitForTimeout`; poll with
  `expect.poll` or `tickUntil`.
- [ ] **Step 2: Check the default run ignores it.**
  `npx playwright test --list tests/e2e/newsletter.spec.ts` lists 0 tests, and with
  `E2E_NEWSLETTER=1` it lists 2. Listing starts no server.
- [ ] **Step 3: Prepare the browser run.**
  1. Run `~/.claude/bin/wait-for-headroom`.
  2. Run `ls -l /proc/*/fd 2>/dev/null | grep -c anon_inode:inotify`. Near 128, follow the
     machine rule in `~/.claude/CLAUDE.md`: kill stale `playwright-mcp` and Codex processes
     older than a day.
- [ ] **Step 4: Run it once, alone:** `E2E_NEWSLETTER=1 npx playwright test`.
  - Expected: 2 passed.
  - On a failure, read `test-results/**/error-context.md`, fix, and re-run this command only.
- [ ] **Step 5: Lint** `npx biome check tests/e2e/newsletter.spec.ts tests/e2e/newsletter-helpers.ts tests/e2e/helpers.ts playwright.config.ts`.
- [ ] **Step 6: Commit** `test(e2e): newsletter end to end in its own CI job — import, suppression, tag send, report, unsubscribe`.

### Task 13: Docs, wiring and branch verification

**Files:**
- Create: `modules/newsletter/docs/import.md`. It covers:
  - what to export from Mailchimp (*Audience → Export audience*, the ZIP);
  - R2's table and R3's decision table;
  - R4's values;
  - precedence;
  - the limits (R7);
  - parsing (R8);
  - mapping (R9);
  - tags and the `tags` field (R10);
  - "segments are not exported: recreate them from the tags found";
  - the counts (R15);
  - errors and the CSV (R16);
  - workers, slices and the janitor (R13, R14);
  - "imports publish no records events" (R5);
  - "staged addresses are deleted when the import ends or after 24 h".
- Modify:
  - `modules/newsletter/docs/index.md`: the status table (PRs 1–6 merged, 7 this PR); an
    *Import* section linking `import.md`; and *Lists*: the create-list action (R11).
  - `modules/newsletter/docs/operations.md`: the import task on the `newsletter` queue, the
    janitor beat, and the `/outbox/dispatch` hook (only with the console transport, Celery
    eager, and `SM_ENVIRONMENT` `development` or `testing`).
  - `import.md` and `index.md` *Lists* also say:
    - **Creating a list needs only `newsletter.manage`** (R11), so a newsletter manager can
      create a records list type (subscription kind only) without `records.manage_types`.
    - **An import publishes no `SubscriptionChanged`** (nor `RecordCreated` or
      `RecordUpdated`; R5). Other consumers of records' events do not see imported people or
      the opt-outs an import writes; newsletter's own suppressions are written directly.
  - `modules/newsletter/README.md`: the screens and the import.
  - `README.md` (root): the newsletter row's description, now complete.
  - `modules/records/docs/api-reference.md`: whatever Tasks 1–2 left.
  - `modules/newsletter/pyproject.toml`: the records floor comment also names
    `contracts.newsletter_import (newsletter PR 7)`. The value is unchanged.
  - `docs/releasing.md`: a "First newsletter release" checklist item. Before publishing
    `simple_module_newsletter` for the first time:
    - raise `simple_module_records>=0.0.13`, the `news` extra's `simple_module_news>=0.0.13`
      and the `pagebuilder` extra's `simple_module_pagebuilder>=0.0.13` to the release that
      first ships `contracts.newsletter` / `newsletter_admin` / `newsletter_import`,
      `contracts.articles` and `contracts.cards`;
    - update each `# floor:` comment with the floor;
    - `scripts/check_rules.py` checks the comment, not the value.
  - `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`: the PR 7 plan path, every row
    marked done, and the line "Roadmap complete (2026-11-xx): all seven PRs delivered."
  - `CLAUDE.md`: the paragraph below.
  - `host/tests/test_newsletter_wiring.py`: `test_import_is_mounted`. On the built host app:
    - `GET /admin/newsletter/import` and `POST /api/newsletter/imports` are routes;
    - the menu has *Import* with `newsletter.manage`;
    - the body-limit registry gives `POST /api/newsletter/imports` a ceiling above the global
      one.

**The `CLAUDE.md` paragraph** is appended after "Newsletter mirrors records' unsubscribes…":
> **The Mailchimp import never clears and never confirms a pending signup.**
> - Records' `contracts.newsletter_import.import_subscribers` creates `confirmed` (or
>   `unsubscribed`) records directly through `system=`. It never moves `pending` or
>   `unsubscribed` to `confirmed`, unsubscribes a confirmed record only under PR 6's row lock,
>   and publishes no events (`events.muted`).
> - Newsletter then writes `unsubscribed` (list) and `imported_cleaned` suppressions with
>   `refresh=False`, in the same transaction, and never calls `clear_for_confirmation`.
> - A subscribed address newsletter already suppresses is not created.
> - Uploads are staged in `newsletter_import_row` (addresses, deleted when the import ends or
>   after 24 h) and applied by `newsletter.run_import` in leased 45 s slices under
>   `tenant_scope`. Eager hosts run it inline.
> - The import publishes no `SubscriptionChanged`, so no other consumer of records' events sees
>   imported changes.
> - `POST /api/newsletter/lists` creates a records list type with only `newsletter.manage`.
> - `POST /api/newsletter/outbox/dispatch` runs a dispatcher tick in-process only with the
>   console transport, under Celery eager, with `SM_ENVIRONMENT` `development` or `testing`;
>   the e2e spec depends on it.

**`CLAUDE.md`, also (D4).**
- In "Every e2e spec file stands alone", and in "Known deferred work" next to the
  multi-tenant and billing-user notes, add: `newsletter.spec.ts` is opt-in with
  `E2E_NEWSLETTER=1`. It runs only in its own CI job, `E2E (newsletter)`, against a
  non-bundle host with `SM_ENVIRONMENT=testing`, because its dispatch hook is absent in
  production. The bundle shards ignore it. Run it locally with `E2E_NEWSLETTER=1 npx
  playwright test`.
- `modules/newsletter/docs/import.md` and `operations.md` say the same.
> - Docs: `modules/newsletter/docs/import.md`.

- [ ] **Step 1: Write the docs and the host test.**
- [ ] **Step 2: Verify.** Run `~/.claude/bin/wait-for-headroom` first.
  - The host test: `uv run --directory host pytest tests/test_newsletter_wiring.py -q -p no:cacheprovider`.
  - From the root:
    - `uv run ruff check modules/newsletter modules/records host/tests/test_newsletter_wiring.py`
    - `uv run ruff format --check <every touched Python file>`
    - `uv run python scripts/check_file_size.py`
    - `uv run python scripts/check_rules.py`
    - `uv run python scripts/check_locales.py`
    - `uv run python scripts/check_hardcoded_strings.py`
    - `uv run python scripts/check_readmes.py`
    - `uv run python scripts/check_migration_heads.py`
    - `npx biome check modules/newsletter tests/e2e/newsletter.spec.ts tests/e2e/newsletter-helpers.ts`
    - `npx tsc --noEmit -p modules/newsletter/tsconfig.json`
    - `npx vitest run modules/newsletter`, the newsletter UI tests only; not a full suite

  Expected: all pass. A WARNING at 280+ lines on a touched file means split it now.
- [ ] **Step 3: Migration check.** SQLite and Postgres (`smpy_newsletter_mig_check`, created and
  dropped), as in Task 3, Steps 4–5.
- [ ] **Step 4: Commit** `docs(newsletter): Mailchimp import, finished module docs, roadmap complete (PR 7)`.

---

## Amendments (Codex review 2026-11-05)

Codex raised nine findings and the team lead accepted all of them. Each is folded into the tasks
named, and where a ruling above says otherwise, the amendment wins.

- **D1 (P1, Tasks 2, 6). Records' opt-outs are checked directly before a subscribed row is
  admitted** (spec amendment 1: the import consults records' status, not only the mirror).
  - Records adds `opted_out_anywhere(session, *, tenant_id, emails) -> set[str]`, which is
    tenant-bound and pinned. It looks across every subscription list of the tenant, trash
    included.
  - `apply_batch` step 1 skips a subscribed address that newsletter suppresses **or** that
    records holds unsubscribed anywhere.
  - Tests: `test_opted_out_anywhere` (records) and
    `test_opted_out_in_records_without_mirror_row_is_skipped`: opted out of list A, no mirror
    row, imported into list B → skipped, and no record is created in B.
- **D2 (P1, Tasks 6, 7). A slice releases its lease before `more`.**
  - The out-of-time path commits a fenced release (`lease_owner = NULL`, `lease_until =
    now`). Only then does the caller enqueue the next slice (worker) or await it (eager).
  - The janitor treats a released `running` job older than `LEASE` as a lost message.
  - Tests: `test_consecutive_slices_with_fixed_clock`, `test_eager_launch_runs_inline_to_done`
    and `test_task_chains_slices_to_done`. Each uses a fixed clock with no manual expiry and
    finishes in one launch.
- **D3 (P1, Task 6). Every state write is fenced on `(lease_owner = me, status =
  'running')`.** That covers the tags-once mutation, counters, renewal, completion, the
  staged-row delete, the release and the failure write.
  - `LeaseLost` means ownership is gone: roll back, write nothing, and leave the job's state
    alone (no `failed`). The runner returns `busy`.
  - Test: `test_stale_worker_after_takeover_changes_nothing`, with two real sessions, for a
    batch, the tags step and the failure write.
- **D4 (P1, Tasks 9, 12, 13; CI). `newsletter.spec.ts` gets its own job, `E2E (newsletter)`.**
  - It runs with `E2E_NEWSLETTER=1`, `SM_ENVIRONMENT=testing`, no bundle, Celery eager (from
    `start-test-server.sh`) and the console transport (from the spec).
  - `playwright.config.ts` matches only that spec under the flag and ignores it otherwise, so
    it is excluded from the production-bundle shards. It refuses the flag together with
    `E2E_BUNDLE`, `E2E_MULTI_TENANT` or `E2E_BILLING_USER`.
  - The hook keeps its production 404 (Task 9).
  - `CLAUDE.md`'s e2e notes name the new job (Task 13).
- **D5 (P2, Task 2). An import's merge into an existing subscriber validates.**
  - The merge goes through `update_record` under PR 6's `lock_record`, never `transition` (its
    direct-merge fallback writes unvalidated values) and never `_merge_marks`.
  - A refused new value is dropped and reported; the stored value stays.
  - Tests: `test_existing_merge_validates`, for an invalid select value, a name over
    `max_length` and an unknown tag. None is stored, and each is in `dropped`.
  - `test_import_takes_the_row_lock` also covers the merge path.
- **D6 (P2, Tasks 6, 7). Failures are sanitised at the worker boundary.**
  - The failure is recorded (fenced), and the log carries the class name and the import id
    only. Then `raise ImportFailed("import failed") from None`, which the task turns into the
    result `"failed"`.
  - Tests: `test_failure_is_sanitised` and `test_task_result_is_sanitised`. A sentinel
    address in the exception never reaches `caplog`, the job or the task result or traceback.
- **D7 (P2, Task 12). Settings are restored through a fresh authenticated context.**
  - The restore runs in `afterAll`, as `branding.spec.ts:105` does, from a `cleanup` record.
  - Each original is recorded before its first write, so a partial setup restores exactly what
    it changed.
  - Test: `restore handles a partial setup`.
- **D8 (P2, R8, Tasks 4–6). Tag values are deterministic and collision-free** (`tag_values`):
  - an existing choice with the same label is reused;
  - else the label, when it has no comma and is not taken;
  - else slug + `-` + 8 hex characters of the label's SHA-256.

  Labels stay as written. Staging computes a preview value, and the tags-once step decides the
  final one against the list's current choices.
  - Tests: `test_tag_values_distinct_and_deterministic`,
    `test_tag_values_collision_with_existing_choice` and `test_tag_values_final_and_distinct`
    (`Customers, 2020` and `Customers; 2020` stay distinct).
- **D9 (P2, Task 12). The e2e proves suppression.**
  - Carl is a confirmed `vip` subscriber, given an `imported_cleaned` suppression by an
    earlier import, then named again as subscribed in the main import. He is skipped there,
    and he is excluded from the `vip` send while ada is delivered.
  - Cy's `unsubscribed` (source `import`) and dee's `imported_cleaned` are checked on their own
    through PR 6's suppression lookup and the Subscribers screen.

## Spec coverage (self-review)

| Spec item | Task |
|---|---|
| Goal 6: one-time Mailchimp import keeping statuses and tags | 2, 4–8, 11 |
| §Mailchimp import: ZIP or its CSVs, pick the target list, preview the counts, apply as a background task with progress | 4, 5, 7, 8, 11 |
| subscribed → `confirmed`, consent snapshot "imported from Mailchimp", TAGS → `tags` with new options added, first and last name | 1, 2 (R4), 6 |
| unsubscribed → `unsubscribed` suppression record in records | 2, 6 (R2) |
| cleaned → newsletter `imported_cleaned` suppression and no subscriber | 6 |
| Matching by lowercased email; suppression always wins; an address unsubscribed here stays unsubscribed; a re-run is a no-op | 2, 5, 6 (R3, R14) |
| "lists the tag values it found" for recreating segments | 5, 11 |
| Contract 5 `import_subscribers`: system write, may set `sm_status`, consent snapshot, never `unsubscribed → confirmed` | 2 |
| "Create list" action: Newsletter list preset plus `tags`, `first_name`, `last_name` | 1, 8, 11 (R10, R11) |
| Anti-goals: never mail an opted-out person (the import included); never leak across tenants | 2, 5, 6, 8 (tenant tests) |
| PR 2 ruling: never emit `pending → confirmed`; never clear a suppression | 2, 6 (R3, R5) |
| PR 6 C2: unsubscribes take the row lock | 2 |
| Amendment 1: newsletter writes its suppression in the same transaction as records' change | 6 |
| Amendment 6: contracts never switch a bound tenant | 1, 2 |
| §Permissions: `newsletter.manage` (lists, import) | 8, 11 (R12) |
| §Screens: Import | 11 |
| §Testing: import mapping per status, suppression precedence, re-run no-op; records' functions tested in records; tenant isolation | 1, 2, 4–6, 8 |
| §Testing: e2e covering list, signup or import, campaign with an article card, send to a tag, report, unsubscribe, subscriber unsubscribed (own CI job, D4; suppression proven, D9) | 12 |
| Delivery order 8: docs | 13 |
| en/de catalogues | 3, 6, 10, 11 |
| One migration, single head, `alembic check` on both backends | 3, 13 |

**Deviations from the spec, all ruled above:**
- The e2e imports subscribers instead of a website signup and confirm (the lead's brief allows
  either; the signup path has records' own e2e).
- The e2e uses a console-only dispatch hook (R17).
- Imports publish no records events (R5).

## Resolved questions (team lead, 2026-11-05)

1. **R2 accepted.** Follow the spec; there is no `imported_unsubscribed` reason.
2. **R11 accepted.** Create-list needs only `newsletter.manage`. Task 13's docs say that this
   lets newsletter managers create records list types.
3. **R17 accepted, narrowed.** The hook exists only when the transport is console, Celery is
   eager **and** `SM_ENVIRONMENT` is `development` or `testing`. It needs `newsletter.manage`
   and CSRF. Task 9 tests a 404 for each failed condition and a 403 without CSRF.
4. **R18 accepted.** The e2e settings are set in the spec's `beforeAll` and restored in
   `afterAll`; `start-test-server.sh` is unchanged.

R5 (muted events) is accepted. Task 13's docs and the `CLAUDE.md` paragraph say that an import
publishes no `SubscriptionChanged`. All other rulings are accepted.
