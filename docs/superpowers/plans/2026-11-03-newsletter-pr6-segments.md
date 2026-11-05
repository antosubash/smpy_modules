# Newsletter PR 6: segments, audiences, the subscriber screen and suppression lifts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An editor saves segments (rules over a list's indexed fields, with a live count). A campaign
goes to the whole list, one tag or a segment, and that audience is snapshotted when the campaign is
scheduled. An admin browses a list's subscribers (search, status counts, tag and segment filters),
sees one subscriber's sends, opens, clicks and suppressions, tags or untags them and unsubscribes
them. An admin with `newsletter.manage` lists suppressions by kind and lifts the ones the rules
allow, with an audit row saying who, when and why.

**Architecture:**
- **Records owns the people.** Every subscriber read and write goes through
  `sm_records.contracts`. Three reads are added in a new contract module,
  `sm_records.contracts.newsletter_admin` (`list_fields`, `browse_subscribers`,
  `subscriber_status_counts`, plus a URL helper), because `contracts/newsletter.py` is at 272
  lines. They are tenant-pinned and filter server-side, like PR 1's.
- **Segments are newsletter's.** A segment stores the editor's `rules` and the records-grammar
  `filters` compiled from them (`segments/rules.py`, a pure function). Only `filters` is ever
  evaluated.
- **The audience is resolved once, when the campaign is scheduled.** `campaigns/audience.py`
  turns `all` / `tag:<v>` / `segment:<id>` into filters. `lifecycle.schedule` stores them on the
  render snapshot (`newsletter_campaign_render.audience_filters`) beside PR 4's S1 render. Freeze
  reads them from there, after it holds its A1/A2 claim. A segment edited or deleted after
  scheduling changes nothing that is already scheduled.
- **Suppressions stay hashed.** The admin screen lists rows by fingerprint. A lift needs the
  address typed in (its hash must match), a note, and a kind the rules allow. It deletes the row
  conditionally and writes a `newsletter_suppression_lift` audit row in the same transaction.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic, React 19 + Inertia,
`@simple-module-py/ui`, vitest.

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md`. Its "Amendments" override
its body. This plan implements §"The key decision" (the subscriber screen wrapping the contract),
§"Data model" (`newsletter_segment`, the campaign audience, the suppression lift), §"Screens"
(Segments, Subscribers) and goal 2 (segments). Also read:
- the roadmap `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md` (PR 6 and PR 7 rows);
- the PR 4 plan `docs/superpowers/plans/2026-11-03-newsletter-pr4-sending.md`: S1 (render
  snapshot), S3 (audience seam), S14 (status machine), S16 (estimate), S18 and A1/A2 (the freeze
  fence), and its ledger `.superpowers/sdd/2026-11-03-newsletter-pr4-sending/progress.md`;
- the PR 5 plan (`.superpowers/sdd/pr5-plan-draft.md`, or its committed copy): T8/T9
  (`newsletter_click.click_count`, `newsletter_send.first_clicked_at`);
- PR 3's rulings C4 (list access), C13 (every error code translated), C14 (test databases), in
  `.superpowers/sdd/2026-11-03-newsletter-pr3-campaigns/progress.md`;
- the PR 2 ledger `.superpowers/sdd/2026-11-03-newsletter-pr2-scaffold/progress.md`: the hashing
  ruling, the double-opt-in-only clearing (F2) and "the admin lift ships with PR 6".

**Precondition.** Execute only after PR 4 (all 13 tasks) and PR 5 are committed. Tasks 5, 6, 8,
10 and 13 touch files PR 4 Tasks 10–13 and PR 5 create (`SendingPanel.tsx`, `types.ts`'s
`PausedCode`, `newsletter_click.click_count`). Before each of those tasks, re-read the named file
and adapt only names; the behaviour below stays.

## Rulings (decided here; cost if wrong in each)

- **G1. The read half of "tag choices" moves into PR 6; the write half stays in PR 7.**
  - PR 6 needs a list's tag choices for the tag audience picker, the tag editor on the subscriber
    screen and the segment editor, and needs to validate a tag before calling `set_tags`. So
    `list_fields` (Task 1) returns every filterable field with its choices; the `tags` field's
    choices are the tag choices.
  - PR 7's import still adds the *write*, `add_tag_choices` (new tag values found in the export),
    beside `import_subscribers`, where its only caller is.
  - Cost if wrong: none; PR 7 reads choices through `list_fields`.
- **G2. A new contract module, `sm_records.contracts.newsletter_admin`.** `contracts/newsletter.py`
  is 272 lines. The new reads serve admin screens, not sending, so they get their own module; the
  queries go in `sm_records/public_submissions/campaign_browse.py`. Cost: one more import path.
- **G3. A segment stores `rules` and compiled `filters`.**
  - `rules` is what the editor shows: `[{field, op, value}]`. `filters` is the spec's
    records-grammar terms, ANDed.
  - Both are written by one function, in one statement, so they cannot drift. Only `filters` is
    evaluated.
  - Why not terms alone: "tags has all of a, b" compiles to two `eq` terms, and "none of" to two
    `ne` terms. Reading terms back into rows is ambiguous.
  - Cost if wrong: one JSON column.
- **G4. The segment vocabulary.**
  - Fields: every field `list_fields` returns, except `sm_status`, plus the synthetic `created_at`
    ("Signed up": records' fixed column, the record's creation time).
  - Operators per field type are fixed in Task 3's table. Tags (any multiselect) get
    `any` / `all` / `none`.
  - There is **no status rule.** A campaign only ever mails `confirmed` subscribers, and the
    subscriber screen has its own status filter.
  - OR across fields stays out (spec). There are at most 10 rules and 20 compiled terms
    (records' `max_filter_terms` default).
  - Cost if wrong: a status rule is one more row in the table. PR 7's imports get `created_at` =
    the import time, so "signed up since" means "added since" for imported people. The docs say
    so.
- **G5. Audience values.**
  - `all`, `tag:<value>` (exactly one tag, the spec's form) or `segment:<id>`.
  - "Any of several tags" is a segment.
  - A tag must be a choice of the list's `tags` field; a segment must exist in the tenant and
    belong to the campaign's list.
  - Cost if wrong: one more click for multi-tag sends.
- **G6. Scheduling snapshots the audience.**
  - `lifecycle.schedule` resolves the audience to filters, dry-runs `count_subscribers` with them
    (so a filter records cannot answer is a 422 now, not a pause later), and stores them on the
    render row (`audience_filters`), in the same transaction as `draft → scheduled`.
  - This extends S1: what leaves draft is frozen. Editing or deleting the segment afterwards does
    not change a scheduled campaign. *Unschedule* and schedule again picks up the new definition.
  - Deleting a segment that a **draft** names is refused with 409 `segment_in_use`. Scheduled and
    later campaigns hold their own snapshot, so they do not block a delete.
  - Cost if wrong: an editor who fixes a segment after scheduling must unschedule and reschedule.
    The docs and the send dialog's hint say so.
- **G7. Freeze reads the snapshot after it holds its claim.**
  - The filters are read from the render row after `claim_freeze` succeeds, not before.
  - Why: if a reschedule landed between a read and the claim, the claim would hold the new
    generation with the old filters. A reschedule after the claim kills the claim (A1), so the
    first `hold_freeze` fails and nothing is written.
  - A filter records refuses while freezing (`SubscriberFilterError`):
    - `reindexing` (temporary): nothing is written, the campaign stays `scheduled`, and the claim
      expires (`FREEZE_LEASE`). A later tick retries.
    - `not_a_list`: pause with `list_unavailable` (PR 4's code).
    - anything else: pause with the new code `audience_unavailable`, with records' reason as the
      detail.
  - Cost if wrong: a reindex delays a send by about 5 minutes.
- **G8. Unschedule also accepts a campaign paused before it started** (`paused` with
  `started_at IS NULL`). This amends S14.
  - A pre-start pause (`list_unavailable`, `audience_unavailable`) could otherwise only be
    resumed, which re-pauses with the same snapshot, or cancelled.
  - Unschedule deletes the render and any send rows, as it does from `scheduled`.
  - Cost if wrong: none; it reuses the A1 fence bump.
- **G9. Count previews are "about".**
  - Segment and audience previews are `count_subscribers` over the filters: confirmed,
    untrashed, matching. Suppressions are not subtracted, as in PR 4's S16.
  - Cost: an overcount by the number of suppressed confirmed subscribers.
- **G10. Permissions.** Every admin route has `bind_admin` first, then its permissions. Every
  route that names a list checks C4 access with `caller_roles(request)`.

  | Surface | Read | Write |
  |---|---|---|
  | Segments, list fields, audience count | `newsletter.view` | `newsletter.edit` |
  | Subscribers (list, detail) | `newsletter.view` + `records.view` (spec: "Reading subscribers also needs `records.view`") | tags: `newsletter.edit` + `records.view` (spec: edit covers "tags"); unsubscribe: `newsletter.manage` + `records.view` |
  | Suppressions (list, lookup, lift, lift log) | `newsletter.manage` | `newsletter.manage` |

  - A subscriber route for a list the caller cannot read, or that is not a list, answers 404 (no
    oracle).
  - Segment create on a forbidden list answers 403 `list_forbidden`, as campaigns do (C4).
  - A suppression row whose list is unreadable to the caller is hidden: absent from listings,
    404 on lift.
  - Tags follow the spec (team lead, 2026-11-05): tagging and untagging need `newsletter.edit`.
    The admin unsubscribe stays at `newsletter.manage`. Cost if wrong: one constant.
- **G11. Suppressions stay hashed** (PR 2's ruling: the hash keeps proof of an opt-out after
  records purges the address).
  - The suppression screen shows a **fingerprint** (the first 12 hex characters of the hash), the
    reason, the list, the source and the date.
  - Finding one address's rows is a `POST /suppressions/lookup {email}`. It is a POST so the
    address is not written to access logs.
  - The subscriber detail shows that subscriber's rows, found by their address.
  - Cost: a row whose address nobody knows any more can be seen and counted, but not lifted.
- **G12. What can be lifted.** Every lift needs `newsletter.manage`, the address typed (its hash
  must equal the row's) and a note (1–500 characters).

  | Reason | Lift |
  |---|---|
  | `complaint` | never: 409 `lift_not_allowed` |
  | `hard_bounce` | yes. The dialog never pre-fills the address and says the mailbox must be fixed (the strong confirmation) |
  | `imported_cleaned` | yes (spec) |
  | `unsubscribed` | only when records has that address on the row's list `confirmed`, untrashed, with `confirmed_at` **after** the row's `created_at`. Else 409 `opt_out_stands` |

  - The `unsubscribed` case covers both items deferred to this PR:
    - a stale opt-out on a single-opt-in list. Records purged the old record, and a new signup
      was `None → confirmed`, which the mirror deliberately never clears (PR 2 F2);
    - a reconfirmation whose clear was lost (the volatile event).
  - The dialog warns that on a list without double opt-in anyone can type an address into the
    form.
  - Cost if wrong: an admin may re-enable mail to someone signed up by a third party. It is a
    human decision, made against a warning and audited.
  - This extends the spec, which names only `hard_bounce` and `imported_cleaned` as liftable. The
    team lead ruled it in on 2026-11-05; see "Spec amendment" below.
- **G13. A lift is a conditional delete** (amended by C2, C3).
  - The request carries the row `version` the admin saw (its `created_at`, C3).
  - The delete is `DELETE … WHERE id = :id AND tenant_id = :t AND created_at = :version`. Zero
    rows (a repeat opt-out or bounce refreshed the row since the admin saw it, or it is gone) is
    409 `suppression_changed`.
  - An `unsubscribed` lift decides and deletes while holding records' row lock on the subscriber
    (`lock_confirmation`, C2), which records' unsubscribe also takes.
  - The audit row (`newsletter_suppression_lift`) is written in the same transaction: hash,
    reason, list, source, `suppressed_at`, `lifted_at`, `lifted_by` (`current_user_id`) and the
    note.
  - The hourly reconcile cannot undo an `unsubscribed` lift, because it walks only records'
    `unsubscribed` subscribers and G12 requires `confirmed`.
- **G14. The admin unsubscribe.**
  - It is records' `unsubscribe` with `unless_confirmed_after=None`, plus newsletter's
    `unsubscribed` suppression (`source="admin"`, the list), in the same transaction (amendment 1).
  - The action finishes with `finalize_session`, so `SubscriptionChanged` publishes.
  - If records did not write (pending, already unsubscribed): 409 `not_subscribed`. A missing or
    trashed subscriber: 404.
- **G15. The subscriber detail shows aggregates, never a per-event list** (the spec's non-goal
  "per-person activity timelines"; team lead, 2026-11-05). From the subscriber's
  `newsletter_send` rows (pinned `tenant_id`, `record_uuid`), one aggregate query gives:
  - `campaigns_sent`: rows with status `sent`;
  - `last_sent_at` and `last_campaign_name`: the latest `sent_at`, and that row's campaign
    (pinned) name;
  - `opened_campaigns`: rows with `opened_at IS NOT NULL`, labelled approximate as PR 5 does;
  - `clicked_campaigns`: rows with `first_clicked_at IS NOT NULL`.

  The current suppressions are shown beside them (G11).
  - No campaign list, no per-send status or timestamps, and no click table is returned.
  - Cost if wrong: none; a later per-person view would be a new spec decision.
- **G16. `records.view` is named once in newsletter** as `constants.PERM_RECORDS_VIEW`. A test
  keeps it equal to `sm_records.core.constants.PERM_VIEW`, as `PERM_SETTINGS_EDIT` is kept.
- **G17. Errors.** `core/errors.py` is 243 lines. PR 6's error classes go in a new
  `core/errors_audience.py` (subclasses of `NewsletterError`, so the existing handler renders
  them). PR 4's `test_error_catalogue.py` imports it too.
  - `AudienceUnsupported` and its `errors.audience_unsupported` keys are removed: nothing raises
    it any more.
- **G18. Test databases.**
  - Newsletter: `smpy_newsletter_test` and its xdist copies `…_gw0`…`gw7`. Drop and recreate all
    of them after Task 2.
  - Records' Postgres runs use a scratch `smpy_newsletter_rec_test`, created and dropped by the
    implementer (only `smpy_newsletter_*` names may be created; `smpy_records_test` was dropped
    with the user's approval).
  - The alembic scratch database is `smpy_newsletter_mig_check`.

## Global Constraints

- **Before every run.** Run `~/.claude/bin/wait-for-headroom` before every pytest, vitest, tsc,
  biome or alembic run. If it exits 1, stop and report.
- **Targeted tests only.** Run the files each task names, never a full suite (`/ship` runs them
  once at the end of the stack). Use `-n 8` at most.
- **Shell.** Use `/usr/bin/ps`, never `ps`. One plain command per Bash call, with literal paths.
- **Formatting.** Format only the files you touched (`uv run ruff format <files>`). Never
  repo-wide.
- **300-line cap** (`scripts/check_file_size.py`). At 280+ lines, split by responsibility. Watch:
  - `sending/freeze.py` (265): Task 6 splits it;
  - `campaigns/lifecycle.py` (245);
  - `campaigns/drafts.py` (180);
  - `ui/hooks/useCampaignEditor.ts` (279): do not grow it. The audience rides on `MetaPatch` in
    `usePendingEdits.ts`;
  - `pages/CampaignEditor.tsx`;
  - `ui/components/sending/SendingPanel.tsx`;
  - records' `contracts/newsletter.py` (272): untouched.
- **Layout** (`docs/module-layout.md`). New domain areas:
  - `sm_newsletter/segments/` (rules, store);
  - `sm_newsletter/subscribers/` (browse, engagement, actions, suppression admin).
  - The audience stays in `campaigns/audience.py`.
  - HTTP goes in `web/endpoints|schemas`. Tests mirror the areas (`tests/segments/`,
    `tests/subscribers/`).
  - UI goes in `ui/components/{segments,subscribers,suppressions}/` and `ui/hooks/`.
- **Pages rule.** New files under `sm_newsletter/pages/` are only `Segments.tsx`,
  `Subscribers.tsx` and `Suppressions.tsx`, each a real Inertia page with `export default`.
- **Locales.**
  - Every key goes into `en.json` **and** `de.json` in the same commit
    (`uv run python scripts/check_locales.py`).
  - Every new error code gets `errors.<code>` (C13).
  - UI strings use `t(keys.newsletter.…)` with no `defaultValue`. A family chosen at runtime
    (operators, statuses, reasons) is a `Record<Union, string>` of `keys.…` leaves.
- **Contracts.** Newsletter imports nothing from `sm_records` except `sm_records.contracts.*`.
  Records' settings come from `app.state.sm_records.settings` and the bus from
  `app.state.sm.event_bus`.
- **Tenancy.** Every Core statement over a newsletter table pins `tenant_id`. Segment ids and
  suppression ids are looked up with `(id, tenant_id)`, never `id` alone.
- **Errors never echo a submitted value** (rule values, emails, tags): details name the field or
  the rule index only.
- **Migration.** Exactly one new revision, off the single head at execution time (re-check with
  `uv run python scripts/check_migration_heads.py`; it was `5a1f7e77d9c6` before PR 5's). No
  branch label. `alembic check` passes on SQLite and Postgres.
- **Python tests.** `uv run --directory modules/newsletter pytest <paths> -q -p no:cacheprovider`.
  On Postgres, prefix
  `SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_test`.
- **Records tests.** `uv run --directory modules/records pytest <paths> -q -p no:cacheprovider`.
  On Postgres, prefix with `SM_TEST_DATABASE_URL=…/smpy_newsletter_rec_test` (G18).
- **JS.** `npx vitest run <paths>`, `npx tsc --noEmit -p modules/newsletter/tsconfig.json` and
  `npx biome check modules/newsletter`.
- **Commits** end with the session's `Claude-Session:` line.

## Review Focus

1. **A segment edited, or deleted, after its campaign was scheduled.** Expected: the frozen send
   rows follow the definition at schedule time. Unschedule and schedule again picks up the new
   one. Pinned in Task 6:
   - `test_segment_edited_after_schedule_keeps_snapshot`
   - `test_segment_deleted_after_schedule_still_freezes`
   - `test_reschedule_picks_up_new_definition`
2. **A reschedule racing a freezer between its read and its claim**, including a switch to
   another list. Expected: rows only for the new list and audience, stamped with the new
   generation. Pinned in Task 6 (`test_filters_are_read_after_the_claim`,
   `test_list_switch_between_ready_and_claim_queues_only_new_list`).
3. **Lifting an opt-out for an address a stranger re-entered on a single-opt-in list.**
   Expected:
   - the lift is refused unless records shows that address confirmed after the opt-out;
   - when it is allowed, the dialog has warned, a note is required, and an audit row exists;
   - a complaint is never liftable;
   - a repeat opt-out between the read and the lift answers 409.

   Pinned in Task 7 (`test_lift_unsubscribed_requires_later_confirmation`,
   `test_complaint_never_lifts`, `test_lift_after_refresh_is_409`,
   `test_concurrent_unsubscribe_wins_and_lift_keeps_protection`) and Task 12
   (`LiftDialog.test.tsx`, the warning).
4. **Another tenant's ids.** Tenant B's segment id used as tenant A's audience, B's suppression id
   lifted under A, and B's subscriber uuid on A's list. Expected: `unknown_segment` or 404, and
   nothing in B read or changed. Pinned in Tasks 4, 5, 7 and 8 (`test_*_pins_the_tenant`).
5. **A list narrowed by `allowed_roles`.** Expected: its segments, subscribers and `unsubscribed`
   suppressions are invisible to a caller without access, and a write answers 404 or 403 as C4
   does. Pinned in Tasks 4, 7 and 8 (`test_restricted_list_*`).

---

### Task 1: Records — the admin reads (`contracts.newsletter_admin`)

**Files:**
- Create:
  - `modules/records/sm_records/contracts/newsletter_admin.py`
  - `modules/records/sm_records/public_submissions/campaign_browse.py`
- Modify:
  - `modules/records/docs/api-reference.md` (§ Newsletter lists: the three reads and the URL
    helper)
  - `modules/newsletter/pyproject.toml`: the records floor comment also names
    `contracts.newsletter_admin (newsletter PR 6)`. The floor value is unchanged; it is raised at
    the first release (PR 3 M7).
- Test:
  - `modules/records/tests/public_submissions/test_newsletter_contract_admin.py`
  - `modules/records/tests/core/test_layout.py`

**Interfaces (Produces):**
```python
# sm_records/contracts/newsletter_admin.py
BrowseStatus = Literal["pending", "confirmed", "unsubscribed"]
BROWSE_STATUSES: tuple[str, ...] = ("pending", "confirmed", "unsubscribed")
MAX_BROWSE_LIMIT = 100
MAX_BROWSE_OFFSET = 100_000
MAX_SEARCH_LEN = 200

class FieldChoice(SQLModel):  value: str; label: str
class ListField(SQLModel):
    key: str
    label: str
    type: str                 # records' FieldType value
    many: bool                # a multiselect
    choices: list[FieldChoice]  # select/multiselect, stored order; [] otherwise
    system: bool              # an sm_* field
class SubscriberPage(SQLModel):  items: list[SubscriberHit]; total: int

async def list_fields(session, *, tenant_id: str, type_key: str) -> list[ListField]
async def browse_subscribers(session, *, tenant_id: str, type_key: str, filters: Sequence[str] = (),
                             status: BrowseStatus | None = None, search: str | None = None,
                             offset: int = 0, limit: int = 50) -> SubscriberPage
async def subscriber_status_counts(session, *, tenant_id: str, type_key: str,
                                   filters: Sequence[str] = (), search: str | None = None) -> dict[str, int]
def subscriber_admin_url(type_key: str, uuid: str | None = None) -> str
```
- **`list_fields`** returns the declared fields that are `indexed`, are not `system="internal"`
  and are not `relation`, in declared order. It returns `[]` for a tenant without that list, and
  raises `SubscriberFilterError("not_a_list")` for a type that is not a list.
- **`browse_subscribers`** returns untrashed subscribers in **any** status (or the one named),
  newest first (`Record.id DESC`), with offset paging and an exact total.
  - Records' `WALKABLE` stays as it is: browsing is not an audience.
  - `search` is stripped and lower-cased, then becomes `Filter("sm_email", CONTAINS, …)`.
    Records' text clause escapes `%`, `_` and `\`.
  - Build the statement with `filtered(select(record).where(record.type_id == rtype.id), …)` plus
    `record.tenant_id == tenant`. Do not use `build_query`, which imposes its own order.
- **`subscriber_status_counts`** returns `{"pending", "confirmed", "unsubscribed"}`, untrashed:
  one count per status over the same filters and search. Zeros for a tenant without that list.
- **Shared behaviour.** Each function binds with `tenant_scope` and pins `tenant_id`, as PR 1's
  do. Argument errors are `ValueError` before any query: `limit` 1–100 (not a bool), `offset`
  0–100 000, an unknown status, `search` over 200 characters or containing a NUL. A malformed
  term or a field records cannot answer raises `SubscriberFilterError` with records' reason.
- **`subscriber_admin_url`** gives `/admin/records/{key}` or `/admin/records/{key}/{uuid}`
  (records' `VIEW_PREFIX`, path-quoted). It is pure.

- [ ] **Step 1: Failing tests** in `test_newsletter_contract_admin.py`. Use the existing
  `audience` fixture: ada (confirmed, `a`), bob (confirmed, `b`), cy (pending, `a`+`b`).
  - `test_list_fields_has_tags_with_choices`: `tags` has `many is True` and choices
    `[("a", "A"), ("b", "B")]`. `sm_email` and `sm_status` are present with `system is True`;
    `sm_nonce` is absent.
  - `test_list_fields_unknown_list_is_empty_and_not_a_list_raises`.
  - `test_browse_includes_pending_newest_first`: `[cy, bob, ada]` and `total == 3`.
  - `test_browse_status_filter`: `status="pending"` gives `[cy]`.
  - `test_browse_search_is_case_insensitive_and_literal`: `search="ADA@"` gives ada.
    `search="%"` gives nothing (escaped).
  - `test_browse_tag_filter`: `filters=["tags:eq:a"]` gives `[cy, ada]`.
  - `test_browse_offset_pages`: `limit=1, offset=1` gives `[bob]`, total 3.
  - `test_browse_excludes_trash`.
  - `test_status_counts`: `{"pending": 1, "confirmed": 2, "unsubscribed": 0}`. With
    `filters=["tags:eq:a"]`: `{"pending": 1, "confirmed": 1, "unsubscribed": 0}`.
  - `test_browse_pins_the_tenant`: `seed_list(db_state, "other", "zed@example.org")`, then
    browse `default` → no zed, and browse `other` → only zed.
  - `test_bound_other_tenant_raises`: with `default` bound, naming `other` raises
    `TenantIsolationError`.
  - `test_browse_refuses_bad_arguments`, parametrized: `limit` 0, 101 and `True`; `offset` -1;
    `status="x"`; a 201-character search; a search containing a NUL → `ValueError`. A term
    `"nope"` → `SubscriberFilterError` with reason `"malformed"`.
  - `test_subscriber_admin_url`: `("news", None)` → `"/admin/records/news"`; `("news", "ab12")`
    → `"/admin/records/news/ab12"`.

  In `test_layout.py`, add `test_newsletter_admin_contract_imports_cleanly_first`, the
  fresh-interpreter import, as for `contracts.newsletter`.
- [ ] **Step 2: Run** `uv run --directory modules/records pytest tests/public_submissions/test_newsletter_contract_admin.py tests/core/test_layout.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep each new file under 200 lines. Reuse
  `campaign_reads.list_type`, `moment`, `stored_tags`, `_hit` (from `_newsletter_args`) and
  `parse_term`. Do not edit `contracts/newsletter.py`.
- [ ] **Step 4: Run** Step 2 on SQLite, then on Postgres:
  1. `PGPASSWORD=postgres createdb -h localhost -U postgres smpy_newsletter_rec_test`;
  2. run Step 2 with
     `SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_rec_test`;
  3. `PGPASSWORD=postgres dropdb -h localhost -U postgres smpy_newsletter_rec_test`.

  Also run `uv run --directory modules/records pytest tests/public_submissions/test_newsletter_contract_reads.py -q -p no:cacheprovider` (unchanged, still passes). Expected: PASS.
- [ ] **Step 5: Commit** `feat(records): newsletter admin reads (list fields, browse, status counts)`.

### Task 2: Models, constants and the migration

**Files:**
- Modify:
  - `sm_newsletter/models/segment.py`
  - `sm_newsletter/models/render.py`
  - `sm_newsletter/models/suppression.py`
  - `sm_newsletter/models/send.py`
  - `sm_newsletter/models/__init__.py`
  - `sm_newsletter/core/constants.py`
- Create: `host/migrations/versions/<rev>_newsletter_segments_and_lifts.py`
- Test: `tests/core/test_models.py`

(Paths without a prefix are under `modules/newsletter/`.)

**Interfaces (Produces):**
```python
# Segment gains (G3):
rules: list[dict[str, Any]] = json_col(list)     # the editor's rows; `filters` stays the compiled terms
# CampaignRender gains (G6):
audience_filters: list[str] = json_col(list)     # migration: server_default '[]'
# Send gains an index:
Index("ix_newsletter_send_record", "tenant_id", "record_uuid", "id")
# Suppression gains an index:
Index("ix_newsletter_suppression_reason_at", "tenant_id", "reason", "created_at")
# new, in models/suppression.py (G13):
class SuppressionLift(Base, MultiTenantMixin, table=True):
    __tablename__ = "newsletter_suppression_lift"
    __table_args__ = (Index("ix_newsletter_suppression_lift_at", "tenant_id", "lifted_at"),)
    id: big_pk; email_hash: str(64); reason: str(STATUS_LEN); list_type_key: str(MAX_TYPE_KEY_LEN, default "")
    source: str(STATUS_LEN); suppressed_at: datetime (dt_col NOT NULL); lifted_at: datetime (dt_col NOT NULL)
    lifted_by: str | None (64); note: str (500)
# core/constants.py gains:
PAUSE_AUDIENCE_UNAVAILABLE = "audience_unavailable"   # appended to PAUSE_CODES
PERM_RECORDS_VIEW = "records.view"                    # G16
SOURCE_ADMIN = "admin"                                # already in SOURCES
TAGS_FIELD = "tags"                                   # spec: the list's tags multiselect
LIFTABLE = (REASON_HARD_BOUNCE, REASON_IMPORTED_CLEANED, REASON_UNSUBSCRIBED)   # never complaint
```
- [ ] **Step 1: Failing tests** in `tests/core/test_models.py`:
  - add `newsletter_suppression_lift` to the expected table set;
  - `test_segment_has_rules_and_filters`;
  - `test_render_has_audience_filters_default_empty` (an inserted row without it reads `[]`);
  - `test_lift_row_is_tenant_owned`;
  - `test_pause_codes_include_audience_unavailable`.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/core/test_models.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement the models and constants.**
- [ ] **Step 4: Generate the revision** against a scratch SQLite database, never `host/app.db`.
  1. With `SM_DATABASE_URL=sqlite+aiosqlite:////tmp/newsletter-pr6-mig.db`, run
     `uv run --project host alembic -c host/alembic.ini upgrade heads`.
  2. Run `… revision --autogenerate -m "newsletter segments and lifts"`.
  3. Check that the file:
     - creates `newsletter_suppression_lift` and its index;
     - adds `newsletter_segment.rules` and `newsletter_campaign_render.audience_filters`, both
       `NOT NULL` with `server_default=sa.text("'[]'")`, through `batch_alter_table` as
       `0fa7184b108f` does;
     - adds the two indexes;
     - has no branch label;
     - has `down_revision` set to the prior single head.
  4. Delete unrelated drift and report it. Run `upgrade heads`, `check`, `downgrade <parent>`,
     `upgrade heads` and `check`. Delete the scratch file.
- [ ] **Step 5: Postgres.**
  1. `PGPASSWORD=postgres createdb -h localhost -U postgres smpy_newsletter_mig_check`.
  2. With `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_newsletter_mig_check`,
     run the same five alembic commands.
  3. `dropdb` it. Then drop and recreate `smpy_newsletter_test` and `smpy_newsletter_test_gw0`…`gw7`
     (G18).
- [ ] **Step 6: Run** `uv run python scripts/check_migration_heads.py` (one head, the new one),
  then Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 7: Commit** `feat(newsletter): segment rules, audience snapshot column, suppression lift log`.

### Task 3: Segment rules — validation and compilation (pure)

**Files:**
- Create:
  - `sm_newsletter/segments/__init__.py` (docstring only)
  - `sm_newsletter/segments/rules.py`
- Test:
  - `tests/segments/__init__.py`
  - `tests/segments/test_rules.py`

**Interfaces (Produces):**
```python
RuleOp = Literal["is", "is_not", "any", "all", "none", "contains", "starts_with",
                 "gt", "gte", "lt", "lte", "before", "since"]
SIGNUP_FIELD = "created_at"
MAX_RULES = 10; MAX_TERMS = 20; MAX_VALUES = 20; MAX_VALUE_LEN = 200
class Rule(BaseModel):  # model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=64); op: RuleOp; value: str | list[str]
class RuleError(ValueError):
    def __init__(self, index: int, message: str): ...   # str(e) == f"rules[{index}]: {message}"; never the value
def segment_fields(fields: Sequence[ListField]) -> dict[str, ListField]
    # drops sm_status and types outside the table below; adds SIGNUP_FIELD
    # (ListField(key="created_at", label="Signed up", type="datetime", many=False, choices=[], system=True))
def ops_for(field: ListField) -> tuple[RuleOp, ...]
def compile_rules(rules: Sequence[Rule], fields: Mapping[str, ListField]) -> list[str]
```
**The table** (G4). `value` is a list for `any`/`all`/`none` (1–20 items) and a string otherwise.
Every string is 1–200 characters, with no NUL and no control characters.

| Field type | Ops | Compiles to |
|---|---|---|
| `multiselect` (`many`) | `any` / `all` / `none` | `k:in:v1,v2` / one `k:eq:v` per value / one `k:ne:v` per value |
| `select` | `is` / `is_not` / `any` | `k:eq:v` / `k:ne:v` / `k:in:…` |
| `text`, `email`, `url` | `is` / `is_not` / `contains` / `starts_with` | `eq` / `ne` / `contains` / `starts_with` |
| `number`, `integer` | `is` / `is_not` / `gt` / `gte` / `lt` / `lte` | `k:eq:v` / `k:ne:v` / `k:gt:v` / `k:gte:v` / `k:lt:v` / `k:lte:v` (C4); the value must parse as a finite number |
| `boolean` | `is` | `k:eq:true` or `k:eq:false` |
| `date` | `before` / `since` | `k:lt:YYYY-MM-DD` / `k:gte:YYYY-MM-DD` |
| `datetime` (incl. `created_at`) | `before` / `since` | `k:lt:YYYY-MM-DDT00:00:00+00:00` / `k:gte:…` (UTC midnight) |

- Choice fields refuse a value that is not a choice. List values refuse `,` (records' `in`
  splits on it).
- `sm_email` values are lower-cased (records stores the normalised address).
- More than `MAX_RULES` rules, or more than `MAX_TERMS` compiled terms, is a `RuleError`.
- An unknown field or an op outside `ops_for` is a `RuleError`.
- Dates must match `YYYY-MM-DD` and be a real date.

- [ ] **Step 1: Failing tests** in `test_rules.py`, built from a hand-written `ListField` set:
  `tags` (multiselect a/b/c), `plan` (select free/pro), `city` (text), `sm_email` (email),
  `age` (integer), `vip` (boolean), `born` (date), `sm_status` (select).
  - `test_compile_table`, parametrized, one case per row of the table, with exact terms. For
    example:
    - `Rule(field="tags", op="all", value=["a", "b"])` → `["tags:eq:a", "tags:eq:b"]`;
    - `Rule(field="created_at", op="since", value="2026-01-01")` →
      `["created_at:gte:2026-01-01T00:00:00+00:00"]`;
    - C4: `Rule(field="age", op="is", value="30")` → `["age:eq:30"]` and `op="is_not"` →
      `["age:ne:30"]`; every numeric op is asserted as its exact term, and no compiled term ever
      contains an op outside records' `FilterOp` (`eq ne in contains starts_with gt gte lt lte`).
  - `test_rules_are_anded_in_order`.
  - `test_refusals`, parametrized, each raising `RuleError` whose message starts with
    `rules[<i>]:` and does not contain the bad value:
    - unknown field;
    - `sm_status` (dropped by `segment_fields`);
    - `contains` on `tags`;
    - a value outside the choices;
    - a comma in an `any` value;
    - `age` with `"abc"` or `"inf"`;
    - `born` with `"2026-02-30"`;
    - 11 rules;
    - `all` with 21 values;
    - an empty string;
    - a NUL.
  - `test_term_cap`: 4 rules of `all` with 6 values each (24 terms) → `RuleError`.
  - `test_email_is_lowercased`.
  - `test_ops_for_matches_table`.
  - `test_value_colons_survive`: `city is "a:b"` → `"city:eq:a:b"`.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/segments/test_rules.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement** `rules.py` under 200 lines, with the table as data (a dict from type
  to `{op: term_op}`), not branches.
- [ ] **Step 4: Run** Step 2. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): segment rules compile to records filter terms`.

### Task 4: Segment store and API

**Files:**
- Create:
  - `sm_newsletter/segments/store.py`
  - `sm_newsletter/core/errors_audience.py`
  - `sm_newsletter/web/schemas/segments.py`
  - `sm_newsletter/web/endpoints/segments_api.py`
  - `sm_newsletter/web/endpoints/audience_api.py`
- Modify:
  - `sm_newsletter/web/endpoints/__init__.py` (both routers)
  - `sm_newsletter/locales/en.json`, `de.json` (`errors.*`)
  - `tests/support/records_seed.py`
  - `tests/core/test_error_catalogue.py` (also import `core.errors_audience`)
  - `tests/web/test_route_guards.py` (the new routes)
- Test:
  - `tests/segments/test_store.py`
  - `tests/web/test_segments_api.py`

**Interfaces:**
- Consumes: Task 1 `list_fields`; Task 3 `Rule`, `RuleError`, `compile_rules`, `segment_fields`,
  `ops_for`; `campaigns.access.check_list` and `readable_lists`.
- Produces:
```python
# core/errors_audience.py (each subclasses NewsletterError)
InvalidSegment(422, "invalid_segment")        # detail "rules[i]: …" or "filter: <records reason>"
SegmentNameTaken(409, "segment_name_taken")
SegmentInUse(409, "segment_in_use")
UnknownSegment(422, "unknown_segment")
SegmentListMismatch(422, "segment_list_mismatch")
UnknownTag(422, "unknown_tag")
InvalidAudience(422, "invalid_audience")
InvalidQuery(422, "invalid_query")            # a bad query parameter on a listing; never echoes it
# segments/store.py
async def fields_for(session, *, tenant_id: str, list_type_key: str) -> dict[str, ListField]   # segment_fields(list_fields(...))
async def filter_count(session, *, tenant_id: str, list_type_key: str, filters: list[str]) -> int
    # count_subscribers; SubscriberFilterError -> InvalidSegment(f"filter: {reason}")
async def list_segments(session, *, tenant_id: str, roles: Roles, list_type_key: str | None) -> list[Segment]
async def get_segment(session, *, tenant_id: str, segment_id: int, roles: Roles) -> Segment
async def create_segment(session, *, tenant_id: str, roles: Roles, name: str, list_type_key: str, rules: list[Rule]) -> Segment
async def update_segment(session, *, tenant_id: str, segment_id: int, roles: Roles,
                         name: str | None, rules: list[Rule] | None) -> Segment
async def delete_segment(session, *, tenant_id: str, segment_id: int, roles: Roles) -> None
async def preview(session, *, tenant_id: str, roles: Roles, list_type_key: str, rules: list[Rule]) -> int
```
- **`list_segments`** returns only segments of readable lists, by name.
- **`get_segment`** is `NotFound` when the segment is missing, in another tenant, or on a list
  the caller cannot read.
- **`create_segment` and `update_segment`**, in order:
  1. `check_list` (422 `unknown_list` / 403 `list_forbidden`);
  2. compile against `fields_for` (a `RuleError` becomes `InvalidSegment(str(e))`);
  3. `filter_count` as a dry run;
  4. write `rules=[r.model_dump() for r in rules]` and `filters` together;
  5. a duplicate name, checked first and the `IntegrityError` caught as well, is
     `SegmentNameTaken`.

  `list_type_key` cannot be changed.
- **`delete_segment`** raises `SegmentInUse` when a campaign with `status='draft'` and
  `audience == f"segment:{id}"` exists in the tenant (G6).
- Writes use `mark_written(session)` as `drafts.write_draft` does.

**Routes** (router `dependencies=[Depends(bind_admin)]`):

| Method, path | Permission | Answer |
|---|---|---|
| `GET /segments?list_type_key=` | view | `list[SegmentOut]` |
| `POST /segments` | edit | 201 `SegmentOut` |
| `GET /segments/{segment_id}` | view | `SegmentOut` |
| `PATCH /segments/{segment_id}` | edit | `SegmentOut` |
| `DELETE /segments/{segment_id}` | edit | 204 |
| `POST /segments/preview` | view | `CountOut` |
| `GET /lists/{list_type_key}/fields` (`audience_api.py`) | view | `list[ListFieldOut]`; 404 for an unreadable or non-list key |

```python
# web/schemas/segments.py (bodies parsed with campaigns.parse_payload, so a 422 never echoes)
class SegmentCreate(BaseModel): name: str (1..200, stripped, check_header_text); list_type_key: str (1..64); rules: list[Rule] (max MAX_RULES)
class SegmentPatch(BaseModel):  name: str | None = None; rules: list[Rule] | None = None
class SegmentPreviewIn(BaseModel): list_type_key: str; rules: list[Rule]
class SegmentOut(BaseModel): id: int; name: str; list_type_key: str; rules: list[Rule]; updated_at: datetime | None
class CountOut(BaseModel): count: int
class ListFieldOut(ListField): ops: list[str]      # ops_for(field)
```
**`records_seed.py` gains:**
- `TAGS = {"key": "tags", "type": "multiselect", "label": "Tags", "indexed": True, "options": {"choices": [{"value": "vip", "label": "VIP"}, {"value": "events", "label": "Events"}]}}`;
- `seed_list(..., fields: list[dict] | None = None)`;
- `seed_subscriber(..., data: dict | None = None)` (ordinary fields, such as tags);
- `backdate(db_state, tenant, uuid, created_at, key=LIST)`, which sets the record's `created_at`
  through records' tables (test-only import).

**Locale keys:** `errors.{invalid_segment, segment_name_taken, segment_in_use, unknown_segment, segment_list_mismatch, unknown_tag, invalid_audience, invalid_query}`.

- [ ] **Step 1: Failing tests.**
  - `test_store.py` (SQLite and Postgres; a list with `TAGS` and three subscribers):
    - `test_create_compiles_and_counts`;
    - `test_create_refusals`: unknown list → `unknown_list`; a bad rule → `invalid_segment`; a
      duplicate name → `segment_name_taken`;
    - `test_update_recompiles_rules_and_filters_together`;
    - `test_delete_blocked_by_draft_not_by_scheduled`: a draft naming it → 409. Once that
      campaign is `scheduled` (set directly) → 204;
    - `test_segment_pins_the_tenant`: tenant B's segment id under A → `NotFound`, and B is
      unchanged;
    - `test_restricted_list_segments_hidden`: `restrict_list(…, ["editor"])`, then
      `list_segments` with roles `[]` lacks it and `get_segment` is `NotFound`;
    - `test_preview_counts_confirmed_only`;
    - `test_compiled_terms_execute_through_records` (C4): a list whose fields cover every row of
      Task 3's table (`tags` multiselect, `plan` select, `city` text, `age` integer, `vip`
      boolean, `born` date) and four confirmed subscribers with known values. For each table row,
      one rule is compiled and run through `count_subscribers` (the records contract, no mock),
      and the count equals the expected one: for example `age is 30` → 1, `age is_not 30` → 3,
      `age gte 30` → 2, `tags all [vip, events]` → 1, `tags none [vip]` → 2,
      `created_at since <tomorrow>` → 0.
  - `test_segments_api.py`:
    - `test_crud_round_trip`;
    - `test_permissions` (view cannot POST, PATCH or DELETE: 403);
    - `test_422_never_echoes_values`: a rule value `"SECRET-VALUE"` outside the choices → the
      body has no `SECRET-VALUE`;
    - `test_list_fields_includes_ops_and_signup`: `tags` ops are `["any", "all", "none"]`,
      `created_at` is present, and `sm_status` is absent;
    - `test_list_fields_unreadable_list_404`.
  - `test_route_guards.py`: the seven routes, each `bind_admin` before its permission.
  - `test_error_catalogue.py`: passes with the new codes.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/segments tests/web/test_segments_api.py tests/web/test_route_guards.py tests/core/test_error_catalogue.py -q -p no:cacheprovider -n 8`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): saved segments with a live count`.

### Task 5: The campaign audience — resolve, validate, snapshot at schedule

**Files:**
- Modify:
  - `sm_newsletter/campaigns/audience.py` (rewritten)
  - `sm_newsletter/campaigns/drafts.py` (PATCH validation)
  - `sm_newsletter/campaigns/lifecycle.py` (`schedule` snapshot, `unschedule` from a pre-start
    pause, G8)
  - `sm_newsletter/campaigns/progress.py` (`estimate`)
  - `sm_newsletter/web/endpoints/audience_api.py` (the count route)
  - `sm_newsletter/core/errors.py`: remove `AudienceUnsupported`
  - `locales/en.json`, `de.json`: remove `errors.audience_unsupported`
  - `ui/utils/api.test.ts`: drop `audience_unsupported` from its code list
  - `tests/web/test_route_guards.py`
- Test:
  - `tests/campaigns/test_audience.py` (new)
  - `tests/campaigns/test_drafts.py` (replace `test_audience_segment_unsupported`)
  - `tests/campaigns/test_lifecycle.py` (the `tag_audience` case and the new cases)
  - `tests/web/test_campaigns_api.py` (the `segment:1` case becomes `unknown_segment`)
  - `tests/web/test_audience_api.py` (new)

**Interfaces:**
- Consumes: Task 4 `fields_for`, `filter_count`, the errors; the `Segment` model.
- Produces:
```python
# campaigns/audience.py
AUDIENCE_ALL = "all"; TAG_PREFIX = "tag:"; SEGMENT_PREFIX = "segment:"
@dataclass(frozen=True)
class Audience: kind: Literal["all", "tag", "segment"]; tag: str | None = None; segment_id: int | None = None
def parse_audience(raw: str) -> Audience
    # InvalidAudience for: an unknown form, an empty tag, a tag over 100 chars or with a control char,
    # a segment id that is not a canonical positive int <= 2**31 - 1
async def audience_filters(session, *, tenant_id: str, list_type_key: str, audience: str) -> list[str]
    # all -> []; tag -> TAGS_FIELD is a `many` field of the list with that choice, else UnknownTag -> [f"tags:eq:{tag}"]
    # segment -> Segment pinned (id, tenant_id) else UnknownSegment; other list -> SegmentListMismatch -> list(segment.filters)
async def audience_count(session, *, tenant_id: str, list_type_key: str, audience: str) -> int
# campaigns/lifecycle.py
async def transition(..., unstarted: bool = False) -> bool    # adds `started_at IS NULL` to the WHERE
```
**Changes:**
- **`drafts.update_draft`.** When `audience` or `list_type_key` is in the patch, validate the
  resulting pair:
  `await audience_filters(session, tenant_id=…, list_type_key=<new or current>, audience=<new or current>)`.
- **`lifecycle.schedule`.** S19 step 4 becomes:
  - `filters = await audience_filters(...)`;
  - then `await filter_count(...)` as the G6 dry run (records refusals → 422 `invalid_segment`);
  - the render row gets `row.audience_filters = filters` before `store_render`.

  The order of the other S19 checks is unchanged.
- **`lifecycle.unschedule`.** From `(SCHEDULED,)` with the revision, **or** from `(PAUSED,)` with
  `unstarted=True` and no revision pin (a paused campaign's revision is not on the dialog). It
  keeps the fence bump, `drop_render` and the send-row delete. The refusal for a started paused
  campaign is 409 `invalid_transition`.
  - If `lifecycle.py` passes 280 lines, move `schedule` and `unschedule` into
    `campaigns/scheduling.py` and re-export them (moves only).
- **`progress.estimate`.** `recipients = await audience_count(...)`.
- **The new route:** `GET /lists/{list_type_key}/audience-count?audience=` (view) → `CountOut`.
  - 404 for an unreadable list.
  - An `audience` over 140 characters → 422 `invalid_audience`, checked in the handler so it
    never echoes.
- **The send API.** `POST /campaigns/{id}/unschedule` (`sending_api.py`) sends
  `expected_revision` only for `scheduled`. Its schema makes it optional (`int | None`). A
  missing one on a `scheduled` campaign → 422 `invalid_campaign`.

- [ ] **Step 1: Failing tests.**
  - `test_audience.py` (SQLite and Postgres):
    - `test_parse_audience_forms`: `all`; `tag:vip`; `segment:12`; refusals for `tag:`,
      `segment:0`, `segment:012`, `segment:abc`, `segment:99999999999` and `other:x`;
    - `test_tag_filters_and_unknown_tag`;
    - `test_segment_filters_mismatch_and_unknown`;
    - `test_segment_of_other_tenant_is_unknown` (Review Focus 4);
    - `test_audience_count`: `tag:vip` counts confirmed vip only.
  - `test_drafts.py::test_audience_validated_on_patch`: `tag:vip` is accepted; `tag:nope` →
    `unknown_tag`; `segment:<other list's>` → `segment_list_mismatch`; changing the list while
    the audience is a segment of the old list → `segment_list_mismatch`, and nothing is written.
  - `test_lifecycle.py`:
    - `test_schedule_snapshots_audience_filters`: the render row's `audience_filters` equals the
      segment's `filters`;
    - the refusal case `tag:x` now expects `unknown_tag`;
    - `test_schedule_refuses_filter_records_cannot_answer`: monkeypatch `count_subscribers` to
      raise `SubscriberFilterError("not_indexed")` → 422 `invalid_segment`, status `draft`, no
      render;
    - `test_unschedule_from_paused_before_start`: `paused` with `started_at` NULL → `draft`, no
      render, no send rows, `freeze_gen` bumped;
    - `test_unschedule_paused_after_start_is_409`.
  - `test_campaigns_api.py`: the existing `segment:1` case → `unknown_segment`.
  - `test_audience_api.py`: counts for `all` and `tag:vip`; 404 for an unreadable list; the
    long-audience 422 does not echo.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/campaigns tests/web/test_campaigns_api.py tests/web/test_audience_api.py tests/web/test_sending_api.py tests/web/test_route_guards.py tests/core/test_error_catalogue.py -q -p no:cacheprovider -n 8`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py` and
  `npx vitest run modules/newsletter/sm_newsletter/ui/utils/api.test.ts`.
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): tag and segment audiences, snapshotted at schedule`.

### Task 6: Freeze from the snapshot

**Files:**
- Create: `sm_newsletter/sending/freeze_pages.py` (move `_pages` out of `freeze.py`; moves first)
- Modify:
  - `sm_newsletter/sending/freeze.py`
  - `sm_newsletter/sending/freeze_fence.py` (`pause_unavailable` gains `code`, `detail`)
- Test: `tests/sending/test_freeze_audience.py` (new; `test_freeze.py` must pass unchanged)

**Interfaces:**
- Consumes: Task 2's `CampaignRender.audience_filters` and `PAUSE_AUDIENCE_UNAVAILABLE`; Task 5's
  snapshot.
- Produces:
```python
# freeze_fence.py
async def pause_unavailable(session, tenant_id, campaign_id, claim, now, *,
                            code: str = PAUSE_LIST_UNAVAILABLE, detail: str = "") -> None
# freeze_pages.py
class FilterRefused(Exception): reason: str                   # raised by write_pages
async def write_pages(factory, tenant_id, campaign_id, claim, list_key, filters, clock) -> bool
    # False once the claim is lost; SubscriberFilterError -> FilterRefused(reason) after rolling back that page
```
**`freeze` becomes (C1):**
1. `_ready` only answers whether the campaign is `scheduled` with a render row. It returns
   nothing to freeze with: no list, no audience.
2. Claim (unchanged).
3. After the claim, one statement reads **both** `Campaign.list_type_key` and
   `CampaignRender.audience_filters`, joined on the campaign. It is pinned to `(tenant_id, id)`
   and guarded by the claim: `status = 'scheduled'`, `freeze_owner = claim.owner` and
   `freeze_gen = claim.gen`. No row means the claim was lost or the campaign unscheduled → `_LOST`.
   ```python
   async def claimed_target(session, *, tenant_id: str, campaign_id: int, claim: FreezeClaim) -> tuple[str, list[str]] | None
       # freeze_fence.py; (list_type_key, audience_filters) under the claim, else None
   ```
   Then `subscription_lists` is checked against that list, as PR 4 does.
4. `write_pages(...)`. On `FilterRefused`:
   - `reindexing` → log WARNING and return `_LOST` (still `scheduled`; the claim expires);
   - `not_a_list` → `pause_unavailable(code=PAUSE_LIST_UNAVAILABLE)`;
   - anything else → `pause_unavailable(code=PAUSE_AUDIENCE_UNAVAILABLE, detail=reason)`.

   Both pauses are conditional on the claim, as PR 4's is, and return `_LOST`.
5. `_publish` is unchanged.

- [ ] **Step 1: Failing tests** in `test_freeze_audience.py` (SQLite and Postgres). Seed a list
  with `TAGS`: ada `vip`, bob `events`, cy no tags. Schedule through `lifecycle.schedule` (the
  `campaign_world` helpers) so the snapshot is real.
  - `test_tag_audience_queues_only_tagged`.
  - `test_segment_edited_after_schedule_keeps_snapshot`: segment `any vip`, schedule, update the
    segment to `any events`, `start_due` → rows for ada only.
  - `test_segment_deleted_after_schedule_still_freezes`: delete the segment row directly after
    scheduling → rows for ada.
  - `test_reschedule_picks_up_new_definition`: schedule, unschedule, edit, schedule, freeze →
    the new audience.
  - `test_filters_are_read_after_the_claim` (Review Focus 2):
    - wrap `freeze.claim_freeze` so that, before delegating, it runs `unschedule`, edits the
      segment and runs `schedule` in another session;
    - the claim then takes the new generation;
    - the rows match the **new** filters, all with the new `freeze_gen`.
  - `test_list_switch_between_ready_and_claim_queues_only_new_list` (C1): lists `news` (ada,
    bob) and `other` (cy, dee), with distinct subscribers. The campaign is scheduled on `news`.
    `freeze.claim_freeze` is wrapped so that, after `_ready`'s read and before delegating, it
    runs `unschedule`, a PATCH to `list_type_key="other"` and `schedule` in another session. The
    send rows are exactly cy and dee, with the new `freeze_gen`, and none of `news`'s
    subscribers.
  - `test_claimed_target_refuses_a_stale_claim` (C1): with a claim whose `gen` was bumped since,
    or whose owner was replaced, `claimed_target` returns `None` and `freeze` writes no rows.
  - `test_filter_refused_pauses_audience_unavailable`: wrap `iter_subscribers` to raise
    `SubscriberFilterError("not_indexed")` → `paused`, `paused_reason ==
    "audience_unavailable|not_indexed"`, `started_at` NULL.
  - `test_reindexing_leaves_scheduled`: reason `reindexing` → still `scheduled`, no rows, one
    WARNING.
  - `test_not_a_list_pauses_list_unavailable`.
  - `test_freeze_without_render_filters_column_value_is_all`: a render row with
    `audience_filters=[]` freezes the whole list (pre-PR-6 rows).
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/sending/test_freeze.py tests/sending/test_freeze_audience.py tests/sending/test_freeze_fence.py -q -p no:cacheprovider`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** First the move commit content (`_pages` → `freeze_pages.write_pages`,
  no behaviour change, `test_freeze.py` green), then the changes. `freeze.py` must end under 250
  lines.
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): freeze reads the scheduled audience snapshot after its claim`.

### Task 7: Suppression admin — listing, lookup, lift and the audit log

**Files:**
- Create:
  - `sm_newsletter/subscribers/__init__.py` (docstring)
  - `sm_newsletter/subscribers/suppressions.py`
  - `sm_newsletter/subscribers/lift.py`
  - `sm_newsletter/web/schemas/suppressions.py`
  - `sm_newsletter/web/endpoints/suppressions_api.py`
- Create (records, C2):
  - `modules/records/sm_records/public_submissions/row_lock.py`
- Modify (records, C2):
  - `modules/records/sm_records/contracts/newsletter_admin.py` (`lock_confirmation`,
    `ConfirmProof`)
  - `modules/records/sm_records/public_submissions/transition.py` (`lock=` on `transition`)
  - `modules/records/sm_records/public_submissions/opt_in.py` (`leave` passes `lock=True`)
  - `modules/records/docs/api-reference.md`
- Modify:
  - `core/errors_audience.py`
  - `web/endpoints/__init__.py`
  - locales (`errors.*`, including `errors.suppression_changed` in en and de, C3)
  - `tests/web/test_route_guards.py`
- Test:
  - `modules/records/tests/public_submissions/test_newsletter_contract_lock.py` (C2)
  - `tests/subscribers/__init__.py`
  - `tests/subscribers/test_suppressions.py`
  - `tests/subscribers/test_lift.py`
  - `tests/subscribers/test_lift_race.py` (C2)
  - `tests/web/test_suppressions_api.py`

**Records (C2): one row lock shared by the lift and every unsubscribe.**
```python
# sm_records/public_submissions/row_lock.py
async def lock_record(db: AsyncSession, record: Record) -> Record
    # the row reloaded under a lock held to the end of the transaction:
    # Postgres `SELECT … FOR UPDATE` (include_deleted, populate_existing);
    # SQLite a no-op `UPDATE <record table> SET version = version WHERE id, tenant_id` first,
    # which takes the database's write lock for the rest of the transaction (records' `_lock_one`
    # does the same for types), then the reload
# transition.py
async def transition(db, rtype, record, derive, *, settings, lock: bool = False) -> Outcome
    # lock=True: every attempt reloads through lock_record instead of _reload
# opt_in.leave: transition(..., lock=True), so the contract's `unsubscribe`, records' own
#   unsubscribe link and newsletter's /newsletter/u/ POST all take the row lock before deciding
# contracts/newsletter_admin.py
class ConfirmProof(SQLModel): uuid: str; confirmed_at: datetime
async def lock_confirmation(session, *, tenant_id: str, type_key: str, email: str) -> ConfirmProof | None
    # tenant- and list-pinned; the untrashed subscriber whose sm_email equals the normalised address,
    # locked with lock_record; a proof only when it is `confirmed` with a readable sm_confirmed_at,
    # else None (unknown, pending, unsubscribed, trashed, no such list). Must run inside the
    # caller's write transaction; the lock lasts until the caller commits or rolls back.
```
Records tests (`test_newsletter_contract_lock.py`, SQLite and the scratch Postgres database):
- `test_lock_confirmation_proof_for_confirmed_only`: ada gives a proof with her `confirmed_at`;
  cy (pending), an unknown address and a trashed one give `None`.
- `test_lock_confirmation_pins_tenant_and_list`.
- `test_unsubscribe_waits_for_a_held_lock` (Postgres only): session 1 takes
  `lock_confirmation(ada)` and holds its transaction. Session 2's `unsubscribe(ada)` runs as a
  task and has not finished after 0.3 s. Once session 1 commits, it completes with `True`.
- `test_leave_locks_before_deciding` (Postgres only): session 1 runs `unsubscribe(ada)` and
  holds its transaction open. Session 2's `lock_confirmation(ada)` waits, and once session 1
  commits it returns `None`.

**Interfaces (Produces):**
```python
# core/errors_audience.py adds
LiftNotAllowed(409, "lift_not_allowed"); OptOutStands(409, "opt_out_stands")
LiftEmailMismatch(422, "lift_email_mismatch"); SuppressionChanged(409, "suppression_changed")
# subscribers/suppressions.py
@dataclass(frozen=True)
class SuppressionRow: id: int; email_hash: str; reason: str; list_type_key: str; source: str; created_at: datetime
    @property
    def version(self) -> str: ...   # C3: created_at.isoformat(), the opaque row version the UI echoes back
FINGERPRINT_LEN = 12
async def visible_lists(session, *, tenant_id: str, roles: Roles) -> list[str]   # readable_lists
async def list_suppressions(session, *, tenant_id: str, roles: Roles, reason: str | None,
                            offset: int, limit: int) -> tuple[list[SuppressionRow], int, dict[str, int]]
    # newest first; rows with list_type_key "" or in visible_lists only; counts per reason over the same visibility
async def rows_for_email(session, *, tenant_id: str, roles: Roles, email: str) -> list[SuppressionRow]
def lift_block(row: SuppressionRow, *, confirmed_at: datetime | None) -> str | None
    # None = liftable; "lift_not_allowed" for complaint;
    # "opt_out_stands" for unsubscribed unless confirmed_at is not None and > row.created_at.
    # The lift passes the locked ConfirmProof's confirmed_at (C2); the subscriber detail (Task 8)
    # passes a display-only value from SubscriberHit (confirmed and untrashed, else None).
# subscribers/lift.py
NOTE_MAX = 500
async def subscriber_on_list(session, *, tenant_id: str, list_type_key: str, email: str) -> SubscriberHit | None
    # display only (Task 8): iter_subscribers(filters=[f"sm_email:eq:{normalise_email(email)}"], limit=1);
    # SubscriberFilterError -> None. Never used to decide a lift.
async def lift(session, *, tenant_id: str, roles: Roles, suppression_id: int, version: str, email: str,
               note: str, now: datetime) -> SuppressionLift
async def list_lifts(session, *, tenant_id: str, roles: Roles, offset: int, limit: int) -> tuple[list[SuppressionLift], int]
```
**`lift`**, in order (G12, G13, C2, C3). Everything runs in the request's one write
transaction:
1. `note` is stripped, 1–500 characters with no control characters other than `\n`, else
   `InvalidQuery("note: …")`. `version` must parse as an aware ISO datetime, else
   `InvalidQuery("version: …")`.
2. Read the row pinned `(id, tenant_id)`. It is `NotFound` when missing, or when its
   `list_type_key` is non-empty and not readable.
3. `row.created_at != parsed version` → `SuppressionChanged` (C3): the admin saw an older row.
4. `email_hash(email) != row.email_hash` → `LiftEmailMismatch`. This is checked before the
   reason, so the endpoint is no oracle for the kind of a row whose address the caller does not
   know.
5. `complaint` → `LiftNotAllowed`.
6. For `unsubscribed` only: `proof = await lock_confirmation(session, tenant_id=…,
   type_key=row.list_type_key, email=email)` (C2). The subscriber's row stays locked until this
   transaction ends, so a records unsubscribe cannot land between this check and the delete. Then
   `lift_block(row, confirmed_at=proof.confirmed_at if proof else None)` → `OptOutStands`.
7. Conditional `DELETE … WHERE id = :id AND tenant_id = :t AND created_at = :version` (the
   version from the request, C3). Zero rows → `SuppressionChanged`.
8. Insert `SuppressionLift(lifted_by=current_user_id.get(), suppressed_at=row.created_at,
   lifted_at=now, …)`, then `mark_written`.

Lock order is the record row, then the suppression row, the same order as the unsubscribe
page's transaction (records' `unsubscribe`, then `suppress`), so the two cannot deadlock.

**Routes** (`newsletter.manage` on each):

| Method, path | Answer |
|---|---|
| `GET /suppressions?reason=&offset=&limit=` | `SuppressionPage {items: SuppressionOut[], total, counts}` |
| `POST /suppressions/lookup` `{email}` | `list[SuppressionOut]` |
| `POST /suppressions/{suppression_id}/lift` `{version, email, note}` | `LiftOut` |
| `GET /suppressions/lifts?offset=&limit=` | `LiftPage` |

```python
class SuppressionOut(BaseModel): id: int; fingerprint: str; reason: str; list_type_key: str; source: str; created_at: datetime; version: str; liftable: bool
    # liftable = reason in LIFTABLE (the listing cannot know the records check; the lift decides)
class LiftOut(BaseModel): id: int; fingerprint: str; reason: str; list_type_key: str; source: str
    suppressed_at: datetime; lifted_at: datetime; lifted_by: str | None; note: str
```
- `reason` must be in `REASONS`, else `InvalidQuery`. `limit` is 1–100.

- [ ] **Step 1: Failing tests** (SQLite and Postgres). Seed rows with `suppress(...)`.
  - `test_suppressions.py`:
    - `test_list_newest_first_with_counts`;
    - `test_filter_by_reason`;
    - `test_restricted_list_rows_hidden` (an `unsubscribed` row of a narrowed list is absent
      from the listing, the counts and the lookup);
    - `test_rows_for_email_spelling_insensitive`;
    - `test_list_pins_the_tenant`.
  - `test_lift.py`:
    - `test_lift_hard_bounce_writes_audit`: the row is gone. The lift row has the hash, reason,
      `suppressed_at`, `lifted_by` and note. `suppressed()` no longer reports the address;
    - `test_lift_imported_cleaned`;
    - `test_complaint_never_lifts` (Review Focus 3);
    - `test_wrong_email_is_mismatch_even_for_complaint`;
    - `test_lift_unsubscribed_requires_later_confirmation`:
      - (a) the subscriber is still `unsubscribed` → `opt_out_stands`;
      - (b) the record was purged and a new single-opt-in signup is `confirmed` with
        `confirmed_at` later than the row → lifted;
      - (c) confirmed, but `confirmed_at` earlier than the row's `created_at` →
        `opt_out_stands`;
    - `test_lift_after_refresh_is_409`: take the row's `version`, then `suppress` the same
      address again (the refresh moves `created_at`), then lift with the old `version` →
      `suppression_changed`, and the row is still present (C3);
    - `test_lift_other_tenants_id_is_404`, with B unchanged;
    - `test_note_required_and_bounded`;
    - `test_reconcile_does_not_resurrect_lifted_unsubscribe`: after (b), `reconcile_async` adds
      nothing.
  - `test_lift_race.py` (C2; the race runs on Postgres and is skipped on SQLite, where the single
    writer serialises it; the ordering test runs on both):
    - `test_concurrent_unsubscribe_wins_and_lift_keeps_protection`:
      - setup: case (b)'s state (an `unsubscribed` suppression on `news`, and the address
        confirmed later);
      - the mirror handler is withheld: no `register_event_handlers`, and the bus has no
        subscriber;
      - task 1 runs records' contract `unsubscribe(…)` for that subscriber and holds its
        transaction open on an `asyncio.Event`, after `leave` has taken the row lock;
      - task 2 runs `lift(…)` and blocks in `lock_confirmation`;
      - then task 1 commits.

      Expected: the lift answers `OptOutStands`; the suppression row is still there; there is no
      lift row; records says `unsubscribed`.
    - `test_lift_first_then_unsubscribe_serialises`: the lift holds its transaction after
      `lock_confirmation`. A concurrent `unsubscribe` has not completed while the lift is open.
      After the lift commits, it completes. Expected: one lift row, records `unsubscribed`, and
      the next `reconcile_async` re-adds the suppression (the protection is restored by the
      ordinary opt-out path, never lost silently).
  - `test_suppressions_api.py`:
    - `test_lift_with_stale_version_is_409` (C3): GET the listing and keep the row's `version`;
      `suppress(...)` the same address with reason `hard_bounce` again (a new bounce refreshes
      it); POST the lift with the original `version` → 409 `suppression_changed`, and the row is
      still listed;
    - permissions (view-only → 403 on all four);
    - the lookup is a POST and the address is never in the response;
    - `fingerprint == hash[:12]`;
    - a lift round trip and the lifts page;
    - `reason=bogus` → 422 `invalid_query`.
- [ ] **Step 2: Run** `uv run --directory modules/records pytest tests/public_submissions/test_newsletter_contract_lock.py tests/public_submissions/test_newsletter_contract_writes.py tests/public_submissions/test_newsletter_contract_races.py -q -p no:cacheprovider`
  and `uv run --directory modules/newsletter pytest tests/subscribers tests/web/test_suppressions_api.py tests/web/test_route_guards.py tests/core/test_error_catalogue.py -q -p no:cacheprovider -n 8`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement**, records first (`row_lock.py`, `transition(lock=)`, `leave`, then
  `lock_confirmation`), then newsletter. Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2 on SQLite, then on Postgres: newsletter on `smpy_newsletter_test`,
  and records on a freshly created `smpy_newsletter_rec_test`, dropped afterwards (G18). Also
  run records' existing opt-in tests,
  `uv run --directory modules/records pytest tests/public_submissions -q -p no:cacheprovider -n 8 -k "opt_in or unsubscribe or confirm"`,
  on both backends. Expected: PASS.
- [ ] **Step 5: Commit** two commits: `feat(records): row lock for unsubscribe and lock_confirmation`,
  then `feat(newsletter): suppression admin with audited lifts`.

### Task 8: Subscriber browse and detail

**Files:**
- Create:
  - `sm_newsletter/subscribers/browse.py`
  - `sm_newsletter/subscribers/engagement.py`
  - `sm_newsletter/web/schemas/subscribers.py`
  - `sm_newsletter/web/endpoints/subscribers_api.py`
- Modify:
  - `sm_newsletter/campaigns/access.py` (`require_list`)
  - `web/endpoints/__init__.py`
  - `tests/web/test_route_guards.py`: `ALLOWED` gains `PERM_RECORDS_VIEW`
- Test:
  - `tests/subscribers/test_browse.py`
  - `tests/subscribers/test_engagement.py`
  - `tests/web/test_subscribers_api.py`
  - `tests/core/test_constants.py` (new: G16)

**Interfaces:**
- Consumes: Task 1 (`browse_subscribers`, `subscriber_status_counts`, `subscriber_admin_url`,
  `BROWSE_STATUSES`); Task 5 `audience_filters`; Task 7 `rows_for_email`, `lift_block`,
  `subscriber_on_list`.
- Produces:
```python
# campaigns/access.py
async def require_list(session, *, tenant_id: str, list_type_key: str, roles: Roles) -> None
    # NotFound unless it is one of readable_lists (no oracle)
# subscribers/browse.py
@dataclass(frozen=True)
class SubscriberRow: hit: SubscriberHit; suppressed: bool
@dataclass(frozen=True)
class BrowseResult: rows: list[SubscriberRow]; total: int; counts: dict[str, int]
async def browse(session, *, tenant_id: str, list_type_key: str, roles: Roles, status: str | None,
                 q: str | None, tag: str | None, segment_id: int | None, offset: int, limit: int) -> BrowseResult
    # filters = audience_filters("tag:…") and/or audience_filters("segment:…"), concatenated (AND)
    # counts use the same filters and q, without status; SubscriberFilterError -> InvalidSegment
@dataclass(frozen=True)
class SubscriberDetail: hit: SubscriberHit; engagement: Engagement; suppressions: list[tuple[SuppressionRow, str | None]]; records_url: str
async def detail(session, *, tenant_id: str, list_type_key: str, uuid: str, roles: Roles) -> SubscriberDetail
    # subscribers_by_uuid (trashed included, flagged); missing -> NotFound; suppressions = rows_for_email
    # each with lift_block(row, confirmed_at=<display-only: the hit's confirmed_at when confirmed and untrashed,
    #   from `hit` for this list or subscriber_on_list(...) for another, else None>)
# subscribers/engagement.py (G15: aggregates only, never a per-send list)
@dataclass(frozen=True)
class Engagement: campaigns_sent: int; last_sent_at: datetime | None; last_campaign_name: str | None
    opened_campaigns: int; clicked_campaigns: int
async def engagement(session, *, tenant_id: str, record_uuid: str) -> Engagement
    # one aggregate over newsletter_send pinned (tenant_id, record_uuid):
    #   COUNT(*) FILTER status='sent', MAX(sent_at), COUNT(opened_at), COUNT(first_clicked_at)
    #   (portable: SUM(CASE ...) rather than FILTER, for SQLite);
    # then the latest sent row's campaign name, Campaign pinned (id, tenant_id). No subscriber -> all zeros / None.
```
**Routes** (`bind_admin` first; reads need `PERM_VIEW` **and** `PERM_RECORDS_VIEW`, two
`RequiresPermission`s):
- `POST /lists/{list_type_key}/subscribers/search` with body `{status?, q?, tag?, segment?,
  offset?, limit?}` → `SubscriberPageOut {items: SubscriberOut[], total, counts, records_url}`
  (C5). The search text travels only in the body, so it never reaches an access log or a URL.
  There is no `GET …/subscribers` listing route. It is a read under the same `PERM_VIEW` +
  `PERM_RECORDS_VIEW` guards, and the API's CSRF check applies because it is a POST.
  - The body is parsed with `parse_payload(SubscriberSearchIn, …)`: `status` in
    `BROWSE_STATUSES`; `q` ≤ 200 characters; `tag` ≤ 100; `segment` a positive int; `limit`
    1–100; `offset` 0–100 000. Otherwise 422 `invalid_query`, without echoing.
- `GET /lists/{list_type_key}/subscribers/{uuid}` → `SubscriberDetailOut {subscriber, engagement:
  EngagementOut, suppressions: SuppressionOut-with-block[], records_url}`.
  - `uuid` must match `^[0-9a-f]{32}$`, else 404.

```python
class SubscriberOut(BaseModel): uuid: str; email: str; status: str; first_name: str | None; last_name: str | None
    tags: list[str]; confirmed_at: datetime | None; trashed: bool; suppressed: bool
class SubscriberSearchIn(BaseModel): status: str | None = None; q: str | None = None; tag: str | None = None
    segment: int | None = None; offset: int = 0; limit: int = 50
class SubscriberSuppressionOut(SuppressionOut): block: str | None   # None = liftable now (display only; the lift re-checks under its lock)
class EngagementOut(BaseModel): campaigns_sent: int; last_sent_at: datetime | None; last_campaign_name: str | None
    opened_campaigns: int; clicked_campaigns: int
```
- [ ] **Step 1: Failing tests** (SQLite and Postgres).
  - `test_browse.py`:
    - `test_browse_counts_and_status_filter`;
    - `test_search_tag_and_segment_combine`;
    - `test_suppressed_flag`;
    - `test_unreadable_or_non_list_is_404` (`restrict_list`, `set_list_kind`);
    - `test_detail_lists_suppressions_with_block`: a hard bounce → `block None`; an
      unsubscribed row with the subscriber still unsubscribed → `"opt_out_stands"`;
    - `test_detail_other_tenants_uuid_404` (Review Focus 4).
  - `test_engagement.py`:
    - `test_engagement_aggregates`: three campaigns' send rows seeded directly — `sent` and
      opened, `sent` and clicked (with `opened_at` set as PR 5 does), `failed` → `campaigns_sent
      == 2`, `opened_campaigns == 2`, `clicked_campaigns == 1`, `last_sent_at` and
      `last_campaign_name` the latest `sent` row's;
    - `test_engagement_empty_is_zeros`;
    - `test_engagement_pins_the_tenant` (the same `record_uuid` string in B's send rows is not
      counted);
    - `test_detail_returns_no_per_send_data`: the detail response's JSON has no `sends` key and
      no campaign ids (G15, the spec's non-goal).
  - `test_subscribers_api.py`:
    - `test_needs_records_view` (`newsletter.view` alone → 403; with `records.view` → 200);
    - `test_list_round_trip`;
    - `test_invalid_query_never_echoes`;
    - `test_search_is_a_post_body` (C5): `POST …/subscribers/search` with `{"q": "ada@"}` finds
      ada; `GET …/subscribers?q=ada@` is not a route (404 or 405); and with a recording
      middleware on the test app, `ada@` appears in no request's URL or query string, only in
      the body;
    - `test_bad_uuid_404`.
  - `test_constants.py`:
    `constants.PERM_RECORDS_VIEW == sm_records.core.constants.PERM_VIEW`.
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/subscribers tests/web/test_subscribers_api.py tests/web/test_route_guards.py tests/core/test_constants.py -q -p no:cacheprovider -n 8`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): subscriber list and detail through the records contract`.

### Task 9: Subscriber actions — tags and unsubscribe

**Files:**
- Create: `sm_newsletter/subscribers/actions.py`
- Modify:
  - `web/endpoints/subscribers_api.py`
  - `web/schemas/subscribers.py`
  - `core/errors_audience.py` (`NotSubscribed`)
  - locales (`errors.not_subscribed`)
  - `tests/web/test_route_guards.py`
- Test:
  - `tests/subscribers/test_actions.py`
  - `tests/web/test_subscriber_actions_api.py`

**Interfaces (Produces):**
```python
NotSubscribed(409, "not_subscribed")
async def set_subscriber_tags(app, session, *, tenant_id: str, list_type_key: str, uuid: str,
                              add: list[str], remove: list[str], roles: Roles) -> SubscriberHit
async def unsubscribe_subscriber(app, session, *, tenant_id: str, list_type_key: str, uuid: str,
                                 roles: Roles, now: datetime) -> SubscriberHit
```
- **`set_subscriber_tags`:**
  1. `require_list`;
  2. `list_fields` must have `TAGS_FIELD` as a `many` field, and every added value must be one of
     its choices, else `UnknownTag`. Removing a non-choice is allowed (a choice deleted since);
  3. at most 20 values each, none empty;
  4. records `set_tags(…, settings=app.state.sm_records.settings, bus=app.state.sm.event_bus)`.
     `SubscriberNotFound` → `NotFound`;
  5. `finalize_session(session)`.
- **`unsubscribe_subscriber`** (G14):
  1. `require_list`;
  2. records `unsubscribe(…, unless_confirmed_after=None, settings=…, bus=…)`.
  3. When it wrote: `suppress(reason=REASON_UNSUBSCRIBED, source=SOURCE_ADMIN,
     list_type_key=list, now=now)`, then `finalize_session`.
  4. When it did not: `subscribers_by_uuid`. Missing or trashed → `NotFound`; otherwise
     `NotSubscribed`.
  5. Return the subscriber read again.
- **Routes** (`bind_admin` first; G10 as ruled on 2026-11-05):
  - `POST /lists/{key}/subscribers/{uuid}/tags` `{add: [], remove: []}` → `SubscriberOut`:
    `PERM_EDIT` and `PERM_RECORDS_VIEW`;
  - `POST /lists/{key}/subscribers/{uuid}/unsubscribe` `{}` → `SubscriberOut`: `PERM_MANAGE`
    and `PERM_RECORDS_VIEW`.

- [ ] **Step 1: Failing tests** (SQLite and Postgres).
  - `test_actions.py`:
    - `test_add_and_remove_tags` (one `RecordUpdated` on a spy bus);
    - `test_unknown_tag_refused_nothing_written`;
    - `test_list_without_tags_field_refuses`;
    - `test_unsubscribe_writes_records_and_suppression_together`: records `unsubscribed`; a
      suppression with `source="admin"` and the list; one `SubscriptionChanged`;
    - `test_unsubscribe_pending_is_not_subscribed` (nothing written);
    - `test_unsubscribe_twice_second_is_409`;
    - `test_actions_pin_the_tenant`;
    - `test_restricted_list_actions_404`.
  - `test_subscriber_actions_api.py`:
    - tags: `newsletter.view` + `records.view` → 403; `newsletter.edit` without `records.view`
      → 403; `newsletter.edit` + `records.view` → 200;
    - unsubscribe: `newsletter.edit` + `records.view` → 403; `newsletter.manage` without
      `records.view` → 403; `newsletter.manage` + `records.view` → 200;
    - CSRF is required on both POSTs (no token → 403, as the other write tests check).
- [ ] **Step 2: Run** `uv run --directory modules/newsletter pytest tests/subscribers/test_actions.py tests/web/test_subscriber_actions_api.py tests/web/test_route_guards.py tests/core/test_error_catalogue.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2 on SQLite and Postgres. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): tag, untag and unsubscribe a subscriber`.

### Task 10: UI — client, types and the campaign audience picker

**Files:**
- Modify:
  - `ui/utils/types.ts`
  - `ui/utils/api.ts`
  - `ui/hooks/usePendingEdits.ts` (`MetaPatch` gains `audience`)
  - `pages/CampaignEditor.tsx`
  - `ui/components/sending/SendingPanel.tsx` (G8, the new paused code)
  - `locales/en.json`, `de.json`
- Create:
  - `ui/utils/audience.ts`
  - `ui/hooks/useAudienceCount.ts`
  - `ui/hooks/useListFields.ts`
  - `ui/components/editor/AudiencePicker.tsx`
- Test:
  - `ui/utils/audience.test.ts`
  - `ui/hooks/useAudienceCount.test.ts`
  - `ui/components/editor/AudiencePicker.test.tsx`
  - `ui/components/sending/SendingPanel.test.tsx`
  - `ui/utils/api.test.ts`

**Interfaces (Produces):**
```ts
// types.ts
export type RuleOp = 'is' | 'is_not' | 'any' | 'all' | 'none' | 'contains' | 'starts_with' | 'gt' | 'gte' | 'lt' | 'lte' | 'before' | 'since';
export interface FieldChoice { value: string; label: string }
export interface ListField { key: string; label: string; type: string; many: boolean; choices: FieldChoice[]; system: boolean; ops: RuleOp[] }
export interface Rule { field: string; op: RuleOp; value: string | string[] }
export interface Segment { id: number; name: string; list_type_key: string; rules: Rule[]; updated_at: string | null }
export type PausedCode = /* PR 4's */ | 'audience_unavailable';
export type SubscriberStatus = 'pending' | 'confirmed' | 'unsubscribed';
export interface Subscriber { uuid: string; email: string; status: SubscriberStatus; first_name: string | null; last_name: string | null;
  tags: string[]; confirmed_at: string | null; trashed: boolean; suppressed: boolean }
export interface SubscriberPage { items: Subscriber[]; total: number; counts: Record<SubscriberStatus, number>; records_url: string }
export interface Engagement { campaigns_sent: number; last_sent_at: string | null; last_campaign_name: string | null;
  opened_campaigns: number; clicked_campaigns: number }
export type SuppressionReason = 'hard_bounce' | 'complaint' | 'imported_cleaned' | 'unsubscribed';
export interface Suppression { id: number; fingerprint: string; reason: SuppressionReason; list_type_key: string; source: string;
  created_at: string; version: string; liftable: boolean; block?: string | null }
export interface SubscriberDetail { subscriber: Subscriber; engagement: Engagement; suppressions: Suppression[]; records_url: string }
export interface SuppressionPage { items: Suppression[]; total: number; counts: Partial<Record<SuppressionReason, number>> }
export interface Lift { id: number; fingerprint: string; reason: SuppressionReason; list_type_key: string; source: string;
  suppressed_at: string; lifted_at: string; lifted_by: string | null; note: string }
// api.ts adds
listFields(key), audienceCount(key, audience, signal?), listSegments(list?), getSegment(id),
createSegment(b), patchSegment(id, b), deleteSegment(id), previewSegment(b, signal?),
searchSubscribers(key, body, signal?) /* POST …/subscribers/search, C5 */, getSubscriber(key, uuid), tagSubscriber(key, uuid, b), unsubscribeSubscriber(key, uuid),
listSuppressions(p, signal?), lookupSuppressions(email), liftSuppression(id, { version, email, note }) /* C3 */, listLifts(p, signal?)
// unscheduleCampaign(id, expected_revision: number | null)   (G8)
// utils/audience.ts
export type AudienceChoice = { kind: 'all' } | { kind: 'tag'; tag: string } | { kind: 'segment'; segmentId: number };
export function parseAudience(raw: string): AudienceChoice      // unknown forms -> { kind: 'all' } only for 'all'; else as parsed
export function formatAudience(choice: AudienceChoice): string
// hooks
export const COUNT_DEBOUNCE_MS = 300;
export function useAudienceCount(listKey: string, audience: string): { count: number | null; error: string | null; loading: boolean }
export function useListFields(listKey: string): { fields: ListField[] | null; error: string | null }
// components/editor/AudiencePicker.tsx
export function AudiencePicker(props: { campaign: CampaignDetail; readOnly: boolean; onChange: (patch: MetaPatch) => void }): JSX.Element
```
- **`AudiencePicker`.** A `RadioGroup` (*whole list* / *a tag* / *a segment*).
  - *A tag* shows a `NativeSelect` of the `tags` field's choices, and is hidden when the list has
    no `tags` field.
  - *A segment* shows the list's segments.
  - Under it: "About {count} subscribers" (`useAudienceCount`, debounced, aborted on change).
  - A saved segment that no longer exists shows `audience.segment_missing`.
  - It calls `onChange({ audience })` through `saveMeta`, so audience edits share the editor's
    debounce, revision and A8 flush. `readOnly` disables it.
- **`CampaignEditor.tsx`.** Render it under `CampaignMeta`. If the file passes 280 lines, move
  `CampaignMeta` and `AudiencePicker` into `ui/components/editor/CampaignHeader.tsx`.
- **`SendingPanel.tsx`.**
  - *Unschedule* is also shown for `paused` with `started_at === null` (calling
    `unscheduleCampaign(id, null)`).
  - `sending.paused_code.audience_unavailable` is translated.
  - The send dialog's hint `sending.dialog.audience_frozen` says the audience is fixed once the
    campaign is scheduled (G6).

**Catalogue keys:**
- `audience.{title, all, tag, segment, tag_label, segment_label, count, count_loading, no_tags, no_segments, segment_missing}`
- `sending.paused_code.audience_unavailable`
- `sending.dialog.audience_frozen`

- [ ] **Step 1: Failing tests.**
  - `audience.test.ts`: round trips for all three forms.
  - `useAudienceCount.test.ts`, with fake timers: one request per debounce; an aborted stale
    request never overwrites a newer count.
  - `AudiencePicker.test.tsx`:
    - choosing a tag calls `onChange({audience: 'tag:vip'})`;
    - the tag option is hidden without a `tags` field;
    - a missing segment shows the warning;
    - read-only disables it;
    - the count is shown.
  - `SendingPanel.test.tsx`: a pre-start paused campaign shows *Unschedule* and posts
    `expected_revision: null`; a started paused campaign does not show it; `audience_unavailable`
    is translated.
  - `api.test.ts`: every new call's path, method and body. Two more:
    - `searchSubscribers` is a POST whose URL carries no query string, with `q` only in the
      JSON body (C5);
    - `liftSuppression` sends `version` (C3).
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/utils modules/newsletter/sm_newsletter/ui/hooks/useAudienceCount.test.ts modules/newsletter/sm_newsletter/ui/components/editor/AudiencePicker.test.tsx modules/newsletter/sm_newsletter/ui/components/sending`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2, `npx vitest run modules/newsletter/sm_newsletter/ui/hooks/useCampaignEditor.test.ts`, `npx tsc --noEmit -p modules/newsletter/tsconfig.json` and `npx biome check modules/newsletter`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): audience picker with a live count in the campaign editor`.

### Task 11: UI — the Segments screen

**Files:**
- Create:
  - `pages/Segments.tsx`
  - `ui/components/segments/SegmentTable.tsx`
  - `ui/components/segments/SegmentEditorDialog.tsx`
  - `ui/components/segments/RuleRow.tsx`
  - `ui/utils/rules.ts`
  - `ui/hooks/useSegmentPreview.ts`
- Modify:
  - `web/endpoints/views.py`: `GET /segments` (view) → `Newsletter/Segments` with
    `{…view_props, can_edit}`
  - `web/endpoints/menu.py`: Segments, `[PERM_VIEW]`, order 310, icon `filter`
  - `core/constants.py`: `_PAGE_SEGMENTS`, the `MENU_*_SEGMENTS` constants
  - locales (`menu.segments`, `segments.*`)
- Test:
  - `ui/utils/rules.test.ts`
  - `ui/components/segments/RuleRow.test.tsx`
  - `ui/components/segments/SegmentEditorDialog.test.tsx`
  - `ui/hooks/useSegmentPreview.test.ts`
  - `tests/web/test_views.py`
  - `tests/web/test_route_guards.py`

**Interfaces (Produces):**
```ts
// utils/rules.ts
export type ValueInput = 'choices' | 'choice' | 'text' | 'number' | 'date' | 'boolean';
export function valueInput(field: ListField, op: RuleOp): ValueInput   // many|any -> 'choices'; select is/is_not -> 'choice'; ...
export function emptyRule(field: ListField): Rule                      // first op of field.ops, value '' or []
export function ruleComplete(rule: Rule): boolean
// hooks/useSegmentPreview.ts
export function useSegmentPreview(listKey: string, rules: Rule[]): { count: number | null; error: string | null }
    // debounced COUNT_DEBOUNCE_MS; only complete rules are sent; errors via errorMessage(e, t)
// components
export function RuleRow(props: { rule: Rule; fields: ListField[]; onChange: (r: Rule) => void; onRemove: () => void; disabled: boolean }): JSX.Element
export function SegmentEditorDialog(props: { listKey: string; segment: Segment | null; fields: ListField[]; open: boolean;
  onOpenChange: (open: boolean) => void; onSaved: (s: Segment) => void }): JSX.Element
```
- **The page.** A list selector (`api.lists()`), the segment table (name, a rule summary, the
  update time; *Edit* and *Delete* with `can_edit`) and a *New segment* button.
- **Delete** asks first (`AlertDialog`). A 409 `segment_in_use` shows its translated text.
- **The editor.** Name, rows of field / condition / value (≤ 10; *Add rule* is disabled at 10)
  and the live count "About {count} subscribers match". It saves with `createSegment` or
  `patchSegment`. A 422 `invalid_segment` detail names the rule (`rules[i]`), and the matching
  row is highlighted.
- **Operator labels** are `segments.ops.<op>` through a `Record<RuleOp, string>`.

**Catalogue keys:**
- `menu.segments`
- `segments.{title, description, list_label, new, edit, delete, empty, name, rules, add_rule, remove_rule, field, op, value, count, saved, delete_confirm.{title, description, confirm, keep}}`
- `segments.ops.{is, is_not, any, all, none, contains, starts_with, gt, gte, lt, lte, before, since}`
- `segments.signup_field`
- `segments.bool.{true, false}`

- [ ] **Step 1: Failing tests.**
  - `rules.test.ts`: `valueInput` for every type and op; `ruleComplete`.
  - `RuleRow.test.tsx`: changing the field resets the op and the value; a `many` field offers
    exactly any/all/none; a date field renders `type="date"`.
  - `SegmentEditorDialog.test.tsx` (`fetch` mocked):
    - the preview count updates after an edit;
    - saving posts `{name, list_type_key, rules}`;
    - a 422 `rules[1]: …` highlights row 2;
    - *Add rule* is disabled at 10.
  - `useSegmentPreview.test.ts`: incomplete rules are not sent; debounce.
  - `test_views.py::test_segments_page_props` (component `Newsletter/Segments`, `can_edit`);
    `test_menu_has_segments` (where the existing menu test lives).
  - `test_route_guards.py`: `GET {VIEW}/segments`.
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/components/segments modules/newsletter/sm_newsletter/ui/utils/rules.test.ts modules/newsletter/sm_newsletter/ui/hooks/useSegmentPreview.test.ts` and `uv run --directory modules/newsletter pytest tests/web/test_views.py tests/web/test_route_guards.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement** with `@simple-module-py/ui` (`PageShell`, `Dialog`, `AlertDialog`,
  `NativeSelect`, `Input`, `Checkbox`, `Button`, `Badge`), as `Campaigns.tsx` and
  `TestSendDialog.tsx` do. Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2, `tsc` and `biome`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): segments screen with a rule editor and live count`.

### Task 12: UI — the Suppressions screen and the lift dialog

**Files:**
- Create:
  - `pages/Suppressions.tsx`
  - `ui/components/suppressions/SuppressionTable.tsx`
  - `ui/components/suppressions/LiftDialog.tsx`
  - `ui/components/suppressions/LiftLog.tsx`
  - `ui/hooks/useSuppressionList.ts`
- Modify:
  - `web/endpoints/views.py`: `GET /suppressions` (manage) → `Newsletter/Suppressions`
  - `web/endpoints/menu.py`: Suppressions, `[PERM_MANAGE]`, order 330, icon `shield`
  - `core/constants.py`
  - locales
- Test:
  - `ui/components/suppressions/LiftDialog.test.tsx`
  - `ui/components/suppressions/SuppressionTable.test.tsx`
  - `ui/hooks/useSuppressionList.test.ts`
  - `tests/web/test_views.py`
  - `tests/web/test_route_guards.py`

**Interfaces (Produces):**
```ts
export function LiftDialog(props: { suppression: Suppression; knownEmail?: string; open: boolean;
  onOpenChange: (open: boolean) => void; onLifted: () => void }): JSX.Element
export function useSuppressionList(): { items: Suppression[] | null; total: number; counts: SuppressionPage['counts'];
  reason: string; setReason: (r: string) => void; offset: number; setOffset: (n: number) => void; error: string | null; reload: () => void }
```
- **The page** has two tabs.
  - **Suppressed.** A reason filter with counts, a lookup form (an email typed, then
    `lookupSuppressions`, whose result replaces the table until it is cleared) and the table
    (fingerprint, reason, list or "all lists", source, date, and *Lift* when `liftable`).
  - **Lifted.** `LiftLog`, a paged table of lifts (fingerprint, reason, list, suppressed date,
    lift date, by, note).
- **`LiftDialog`** (G12), per reason:
  - `hard_bounce`: the email field is **never pre-filled**. The text says to lift only once the
    mailbox works again (`suppressions.lift.hard_bounce_warning`).
  - `imported_cleaned`: the email is pre-filled from `knownEmail`.
  - `unsubscribed`: pre-filled. A destructive-styled warning
    (`suppressions.lift.opt_out_warning`) explains that this person opted out, that the lift is
    allowed only because records shows them confirmed again afterwards, and that on a list
    without double opt-in anyone can type an address into the form.
  - `complaint`: never opened (the button is absent).

  A note is required (≤ 500). Confirm is disabled until both fields are filled. The 409 and 422
  codes (`lift_not_allowed`, `opt_out_stands`, `lift_email_mismatch`, `suppression_changed`)
  show their translated text.

**Catalogue keys:**
- `menu.suppressions`
- `suppressions.{title, description, tab_active, tab_lifted, reason_label, reason_all, lookup_label, lookup_submit, lookup_clear, all_lists, empty, fingerprint, reason, list, source, created, lift}`
- `suppressions.reasons.{hard_bounce, complaint, imported_cleaned, unsubscribed}`
- `suppressions.sources.{records_event, reconcile, unsubscribe_page, send, import, admin}`
- `suppressions.lift.{title, email_label, note_label, confirm, cancel, hard_bounce_warning, opt_out_warning, cleaned_hint, done}`
- `suppressions.log.{empty, suppressed_at, lifted_at, lifted_by, note}`

- [ ] **Step 1: Failing tests.**
  - `LiftDialog.test.tsx`:
    - a hard bounce has an empty email field even with `knownEmail`;
    - an unsubscribed lift shows the opt-out warning;
    - confirm is disabled until the email and note are filled;
    - a confirm posts `{version, email, note}`, with `version` taken from the row the dialog
      was opened on (C3);
    - a 409 `suppression_changed` shows its text and asks the page to reload the list;
    - a 409 `opt_out_stands` shows its text and calls no `onLifted`.
  - `SuppressionTable.test.tsx`: no *Lift* for a complaint; the reasons are translated.
  - `useSuppressionList.test.ts`: changing the reason resets the offset; only the newest
    response wins.
  - `test_views.py`: the page needs `newsletter.manage` (403 for view); props.
  - `test_route_guards.py`.
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/components/suppressions modules/newsletter/sm_newsletter/ui/hooks/useSuppressionList.test.ts` and `uv run --directory modules/newsletter pytest tests/web/test_views.py tests/web/test_route_guards.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2, `tsc` and `biome`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): suppressions screen with audited lifts`.

### Task 13: UI — the Subscribers screen

**Files:**
- Create:
  - `pages/Subscribers.tsx`
  - `ui/components/subscribers/SubscriberTable.tsx`
  - `ui/components/subscribers/SubscriberFilters.tsx`
  - `ui/components/subscribers/SubscriberSheet.tsx`
  - `ui/components/subscribers/TagEditor.tsx`
  - `ui/components/subscribers/EngagementSummary.tsx`
  - `ui/hooks/useSubscriberList.ts`
  - `ui/hooks/useSubscriber.ts`
- Modify:
  - `web/endpoints/views.py`: `GET /subscribers` (`PERM_VIEW` and `PERM_RECORDS_VIEW`) →
    `Newsletter/Subscribers` with `{…view_props, can_edit, can_manage}`; an optional `?list=` is passed as
    the `initial_list` prop
  - `web/endpoints/menu.py`: Subscribers, `[PERM_VIEW, PERM_RECORDS_VIEW]`, order 320, icon `users`
  - `core/constants.py`
  - locales
- Test:
  - `ui/hooks/useSubscriberList.test.ts`
  - `ui/components/subscribers/SubscribersPage.test.tsx` (it renders `pages/Subscribers.tsx`; a test file under `pages/` would break the pages rule)
  - `ui/components/subscribers/SubscriberSheet.test.tsx`
  - `ui/components/subscribers/TagEditor.test.tsx`
  - `ui/components/subscribers/SubscriberFilters.test.tsx`
  - `tests/web/test_views.py`
  - `tests/web/test_route_guards.py`

**Interfaces (Produces):**
```ts
export function useSubscriberList(listKey: string): { items: Subscriber[] | null; total: number; counts: SubscriberPage['counts'];
  recordsUrl: string; status: string; setStatus(s: string): void; q: string; setQ(q: string): void;
  tag: string; setTag(t: string): void; segment: string; setSegment(s: string): void;
  offset: number; setOffset(n: number): void; error: string | null; reload(): void }   // as useCampaignList: debounced q, newest request wins
export function useSubscriber(listKey: string, uuid: string | null): { detail: SubscriberDetail | null; error: string | null; reload(): void }
export function SubscriberSheet(props: { listKey: string; uuid: string | null; canEdit: boolean; canManage: boolean; onClose(): void; onChanged(): void }): JSX.Element
export function EngagementSummary(props: { engagement: Engagement }): JSX.Element
export function TagEditor(props: { tags: string[]; choices: FieldChoice[]; disabled: boolean;
  onSave(add: string[], remove: string[]): Promise<void> }): JSX.Element
```
- **The page.** The search text lives in component state only: no query parameter, no
  `router.get`, no history entry (C5). A list selector, then:
  - status tabs with counts (*All*, *Confirmed*, *Pending*, *Unsubscribed*);
  - `SubscriberFilters`: a search box, a tag select from the `tags` choices (`useListFields`)
    and a segment select (`listSegments(listKey)`);
  - the table: email, name, status badge, tags, a *Suppressed* badge, confirmed date;
  - paging, and an "Open in records" link (`records_url`).

  A row opens `SubscriberSheet`.
- **`SubscriberSheet`** (a `Sheet` or `Dialog`) shows:
  - the fields and status (and *In the trash* when trashed: no actions);
  - `TagEditor`, with `can_edit` and not trashed (G10);
  - *Unsubscribe* (`AlertDialog`), with `can_manage` and status `confirmed`;
  - **Engagement** (`EngagementSummary`, G15): campaigns sent, the last send's date and
    campaign, opened (count, with the "approximate" caption reused from PR 5's report key,
    `report.opens_caveat` or its PR 5 name) and clicked (count). No per-send list;
  - **Suppressions**, with each row's reason and *Lift* when `block === null` and `can_manage`. It opens
    `LiftDialog` with `knownEmail = subscriber.email`; the hard-bounce rule still empties the
    field. A blocked row shows `errors.<block>`'s text as the reason;
  - "Edit in records" (`records_url`).

  After each action it calls `reload` and `onChanged`.

**Catalogue keys:**
- `menu.subscribers`
- `subscribers.{title, description, list_label, search_label, search_placeholder, tag_label, tag_all, segment_label, segment_all, empty, email, name, status, tags, suppressed, confirmed_at, open_in_records, edit_in_records, trashed}`
- `subscribers.status.{all, pending, confirmed, unsubscribed}`
- `subscribers.detail.{title, engagement, campaigns_sent, last_sent, never_sent, opened, clicked, suppressions, suppressions_empty, tags_save, unsubscribe}`
- `subscribers.unsubscribe_confirm.{title, description, confirm, keep}`

- [ ] **Step 1: Failing tests.**
  - `useSubscriberList.test.ts`: each request is a POST to `…/subscribers/search` whose body
    carries `status`, `q` (debounced), `tag`, `segment` and `offset`. The request URL never
    contains the search text (C5). A filter change resets the offset, and only the newest
    response wins.
  - `SubscribersPage.test.tsx` (renders `pages/Subscribers.tsx`): typing a search never calls `router.visit`/`router.get`
    and never changes `window.location` (C5).
  - `SubscriberFilters.test.tsx`: the tag select is hidden without a `tags` field.
  - `TagEditor.test.tsx`: saving sends exactly the diff (`add`, `remove`); only choices are
    offered.
  - `SubscriberSheet.test.tsx`:
    - `canEdit` alone shows the tag editor but no *Unsubscribe* and no *Lift*; `canManage`
      alone shows *Unsubscribe* and *Lift* but a read-only tag list;
    - the engagement block shows the four aggregates and no per-campaign rows;
    - *Unsubscribe* asks, then posts;
    - a 409 `not_subscribed` is translated;
    - a hard-bounce *Lift* opens the dialog with an empty email;
    - an `opt_out_stands` row has no *Lift* and shows the reason;
    - a trashed subscriber has no actions.
  - `test_views.py`: the page needs both permissions; `initial_list` is passed through.
  - `test_route_guards.py`.
- [ ] **Step 2: Run** `npx vitest run modules/newsletter/sm_newsletter/ui/components/subscribers modules/newsletter/sm_newsletter/ui/hooks/useSubscriberList.test.ts` and `uv run --directory modules/newsletter pytest tests/web/test_views.py tests/web/test_route_guards.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `uv run python scripts/check_locales.py`.
- [ ] **Step 4: Run** Step 2, `tsc` and `biome`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(newsletter): subscribers screen with tags, unsubscribe and engagement`.

### Task 14: Docs, wiring and branch verification

**Files:**
- Create: `modules/newsletter/docs/audience.md`. It covers:
  - segments: the rules table (G4), AND only, "about" counts (G9), and "signed up" = records'
    `created_at` (import time for imported people);
  - audiences: G5, and the snapshot at schedule plus what unschedule refreshes (G6, G8);
  - the subscriber screen and its permissions (G10);
  - suppressions: the hashing, fingerprints, the lift rules (G12), the audit log, and why a
    complaint is never lifted.
- Modify:
  - `modules/newsletter/docs/index.md` (status PR 6; a link)
  - `modules/newsletter/docs/sending.md` (the `audience_unavailable` pause, and unschedule from a
    pre-start pause)
  - `modules/newsletter/README.md` (the screens)
  - `modules/records/docs/api-reference.md` (if Task 1 left anything)
  - `CLAUDE.md` (the paragraph below)
  - `docs/superpowers/specs/2026-11-03-newsletter-module-design.md`: append this plan's "Spec amendment"
    note as Amendments item 11
  - `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`: the PR 6 plan path, and "Notes for
    PR 7":
    - the tag-choices **read** shipped in PR 6 (`list_fields`); PR 7 adds only
      `add_tag_choices`;
    - the import must never emit `pending → confirmed` (PR 2);
    - imported people's "signed up" is the import time;
    - the e2e "send to a tag" uses the audience picker's *A tag*.
  - `host/tests/test_newsletter_wiring.py`: `test_people_screens_are_mounted`. On the built host
    app, `GET /admin/newsletter/segments`, `/subscribers` and `/suppressions` are routes, and the
    menu has the three entries with their permissions.

**The `CLAUDE.md` paragraph** (appended to the newsletter suppression rule) says:
1. An admin lift (`POST /api/newsletter/suppressions/{id}/lift`) is the only other way a
   suppression row is deleted. It needs `newsletter.manage`, the typed address (hash match) and a
   note, and writes `newsletter_suppression_lift`. It is never allowed for a `complaint`. An
   `unsubscribed` row lifts only while records shows that address confirmed on that list after
   the opt-out. That check and the delete run under records' row lock (`lock_confirmation`), which
   every unsubscribe also takes (`opt_in.leave` → `transition(lock=True)`). A new records path
   that unsubscribes must take it too.
2. A campaign's audience is resolved when it is scheduled and stored on the render snapshot.
   Freeze evaluates that snapshot, never the live segment.

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
    - `npx biome check modules/newsletter`
    - `npx tsc --noEmit -p modules/newsletter/tsconfig.json`
    - `npx vitest run modules/newsletter`, the newsletter UI tests only; not a full suite

  Expected: all pass. A WARNING at 280+ lines on a touched file means split it now.
- [ ] **Step 3: Migration check.** SQLite and Postgres (`smpy_newsletter_mig_check`, created and
  dropped), as in Task 2, Steps 4–5.
- [ ] **Step 4: Commit** `docs(newsletter): segments, audiences, subscribers and suppression lifts (PR 6)`.

---

## Amendments (Codex review 2026-11-05)

The Codex plan review raised five findings, and the team lead accepted all of them. Each is
folded into the tasks named. Where a ruling above says otherwise, the amendment wins.

- **C1 (P1, Task 6). Freeze reads the list and the filters together, under its claim.**
  - `_ready` only checks that the campaign is ready to freeze.
  - After `claim_freeze`, `claimed_target` reads `list_type_key` and the render's
    `audience_filters` in one statement, guarded by `status='scheduled'`,
    `freeze_owner = claim.owner` and `freeze_gen = claim.gen`.
  - A list switched by an unschedule, PATCH and reschedule between the two reads therefore
    cannot be frozen with the old list.
  - Tests: `test_list_switch_between_ready_and_claim_queues_only_new_list` (two lists with
    distinct subscribers) and `test_claimed_target_refuses_a_stale_claim`.
- **C2 (P1, Task 7). The opt-out lift holds records' row lock.**
  - Records gains `public_submissions/row_lock.lock_record`: `SELECT … FOR UPDATE` on
    Postgres, and on SQLite a no-op `UPDATE` that takes the write lock.
  - `transition(lock=True)` uses it on every attempt, and `opt_in.leave` passes it, so every
    unsubscribe path takes the row lock before deciding.
  - The contract gains `lock_confirmation(session, *, tenant_id, type_key, email) ->
    ConfirmProof | None`, which is tenant- and list-pinned and locks the same row.
  - The lift's eligibility check and its conditional delete run inside that lock, in the
    request's one transaction.
  - Tests:
    - records: a held lock delays `unsubscribe`, and a held `unsubscribe` delays
      `lock_confirmation` and turns it to `None` (Postgres);
    - newsletter: a real concurrent records unsubscribe, with the mirror withheld, makes the lift
      answer `opt_out_stands` and leaves the suppression in place (Postgres; on SQLite the
      single writer covers it).
- **C3 (P1, Tasks 7, 10 and 12). A lift names the row version it saw.**
  - `SuppressionOut.version` is the row's `created_at` in ISO form. The lift body is
    `{version, email, note}`, and both the early check and the conditional `DELETE` require
    `created_at = version`.
  - A mismatch is 409 `suppression_changed` (en and de).
  - API test: list the row, refresh it with a new bounce, lift with the original version → 409,
    and the row is still listed.
- **C4 (P2, Tasks 3 and 4). Numeric equality compiles to `eq`/`ne`.**
  - `is` maps to `eq` and `is_not` to `ne`. Every table row has its exact compiled term
    asserted.
  - `test_compiled_terms_execute_through_records` runs each one through `count_subscribers`
    against real records, with no mock.
- **C5 (P2, Tasks 8, 10 and 13). Subscriber search is a POST.**
  - `POST /lists/{key}/subscribers/search` takes `{status, q, tag, segment, offset, limit}` in
    the body. There is no GET listing.
  - The UI keeps the search text in component state: no query string, no navigation, no
    history entry.
  - Tests: on the server, the address appears only in a request body; on the client, the search
    request's URL has no query string and the page never navigates.
  - The suppression lookup stays a POST (G11).

## Spec coverage (self-review)

| Spec item | Task |
|---|---|
| Goal 2, `newsletter_segment` (name, list, records-grammar `filters`, ANDed; `in:` for any-of; editor rows over indexed fields incl. tags) | 3, 4, 11 |
| Campaign audience `all` / `segment:<id>` / `tag:<value>` (§Data model; goal 3) | 5, 10 |
| Audience frozen when sending starts; later signups not added (§Sending 1, "Calls made") | 5, 6 (G6 snapshots the definition, freeze the people) |
| Subscriber screen: search, status counts, tag/untag, unsubscribe; link to records (§The key decision, §Screens) | 1, 8, 9, 13 |
| Reading subscribers needs `records.view` and records' `allowed_roles` (§Permissions; amendment 9) | 8, 9 (G10) |
| Suppressed address shown with its reason on the subscriber screen; `newsletter.manage` lifts `hard_bounce`/`imported_cleaned` (§Data model) | 7, 8, 12, 13 |
| Deferred: lift of stale single-opt-in opt-outs and of a lost reconfirmation (PR 2); spec amendment below | 7 (G12), 14 |
| Non-goal "per-person activity timelines" respected: aggregates only | 8 (G15), 13 |
| Records' contract functions tested in records (§Testing) | 1 |
| Tenant isolation on every route and task (§Testing; anti-goal) | 1, 4, 5, 7, 8, 9 |
| en/de catalogues | 4, 5, 7, 9, 10–13 |
| Migration: one revision, single head, `alembic check` on both | 2, 14 |

**Out of PR 6, by roadmap:** `import_subscribers`, `add_tag_choices`, the Mailchimp import screen,
and the e2e spec (PR 7).

## Spec amendment (team lead, 2026-11-05)

This plan amends the spec's §Data model, "The subscriber screen shows a suppressed address with
its reason. An admin with `newsletter.manage` can lift a `hard_bounce` or `imported_cleaned`
suppression", as follows:

> An admin with `newsletter.manage` may also lift an `unsubscribed` suppression, **only** while
> records shows that address on the row's list as `confirmed`, untrashed, with `sm_confirmed_at`
> later than the suppression's `created_at`. Every lift needs the address typed (its hash must
> match the row's) and a note, and is recorded in `newsletter_suppression_lift`. A `complaint`
> is never lifted.

Why: two cases deferred from PR 2 have no other remedy.
- A stale opt-out on a single-opt-in list: records purged the old record, and a new signup was
  `None → confirmed`, which the mirror deliberately never clears.
- A double-opt-in confirmation whose clearing event was lost.

When the plan is committed, Task 14 appends this note to the spec's Amendments section as item 11.

## Resolved questions (team lead, 2026-11-05)

The spec is binding over the brief.
1. **Tags follow the spec.** Adding or removing a subscriber's tags needs `newsletter.edit`, plus
   `records.view` and list access. The admin unsubscribe stays at `newsletter.manage` (G10,
   Task 9).
2. **The spec's non-goal holds.** There is no per-event activity list. The subscriber detail
   shows only:
   - how many campaigns were sent;
   - the last send's date and campaign;
   - how many were opened and how many clicked;
   - the current suppressions.

   See G15, Task 8 and Task 13.
3. **Lifting `unsubscribed` rows is allowed**, under G12's records check (the spec amendment
   above).

G1–G18 are otherwise accepted, including G8's amendment to S14.
