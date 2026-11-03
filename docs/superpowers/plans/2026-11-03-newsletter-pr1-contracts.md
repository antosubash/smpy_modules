# Newsletter PR 1 — records and news contracts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the coming newsletter module a stable, tenant-pinned way to read and change records' newsletter subscribers, and to find and snapshot news articles, without touching either module's tables.

**Architecture:** Two new contract modules, `sm_records.contracts.newsletter` and `news.contracts.articles`. They are thin functions over existing services: records' `walk_records`/`build_query`, `subscribe.find`, `opt_in.leave` and `update_record`, and news' `content.card.base`/`to_read`. Each pins `tenant_id` itself, the way `pagebuilder.contracts.search` does, and returns plain DTOs, never ORM rows.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy async, pytest (SQLite; Postgres opt-in through `pg_support.py`).

**Spec:** `docs/superpowers/specs/2026-11-03-newsletter-module-design.md` (§ "Records changes this needs", the news-contract paragraph). Roadmap: `docs/superpowers/plans/2026-11-03-newsletter-roadmap.md`.

## Global Constraints

- Contracts are the **only** import path another module may use; DTOs are plain `SQLModel`/`BaseModel`, never ORM rows (`CLAUDE.md`, `docs/module-layout.md`).
- **Tenant pinned inside each function.** Every function takes `tenant_id: str` and runs under `simple_module_db.tenant_context(tenant_id)` itself. A read also adds `Record.tenant_id == tenant_id` (or `NewsArticle.tenant_id`) as a `WHERE`. Without that, a host with nothing bound reads every tenant.
- An invalid `tenant_id` (`simple_module_db.is_valid_tenant_id` false) raises `ValueError` before any SQL runs.
- Writes go through records' existing services (`opt_in.leave`, `record_service.update_record`). Never a bare `commit()`. The caller finishes with `simple_module_db.finalize_session` (or records' `events.commit`), so `SubscriptionChanged`/`RecordUpdated` publish after the commit. Write functions take `bus: Any | None = None` and call `sm_records.core.events.attach(session, bus)` when one is given.
- Subscriber hits **never** carry `sm_nonce`, consent fields or IP hashes.
- `limit` is an `int` in `1..MAX_SUBSCRIBER_BATCH` (`MAX_SUBSCRIBER_BATCH = 1000`). `bool` and anything else raise `ValueError`, as in `pagebuilder.contracts.search._checked_limit`.
- 300-line cap per file. Records' architecture rule 1 applies: no FastAPI import in a service or contract.
- Docs: records' `docs/api-reference.md` gets a "Newsletter contract" subsection; news' `docs/` gets an "Article contract" note.

## Review Focus

1. **A wrong tenant reads nothing:** a subscriber or article that exists in tenant `a` is invisible to a call naming `b`, including when no tenant is bound upstream. Tested in Tasks 1 and 4.
2. **Trashed and non-confirmed subscribers never appear** in `iter_subscribers`/`count_subscribers`: pending, unsubscribed and in-trash records are excluded. Tested in Task 1.
3. **A re-signup after the cutoff is not unsubscribed** by `unsubscribe(unless_confirmed_after=…)`, and a second call is a no-op that emits no second event. Tested in Task 2.
4. **A filter on an unindexed or unknown field** raises `SubscriberFilterError` with records' reason (`unknown`, `not_indexed`, `reindexing`, `malformed`), rather than returning everyone. Tested in Task 1.
5. **Unpublished or trashed articles:** only *published, not trashed* articles are found or carded. Drafts never leak into a newsletter. Tested in Task 4.

---

### Task 1: Records — subscriber reads (`iter_subscribers`, `count_subscribers`, `subscribers_by_uuid`)

**Files:**
- Create: `modules/records/sm_records/contracts/newsletter.py` (DTOs, errors, the public functions; delegates to the service below)
- Create: `modules/records/sm_records/public_submissions/campaign_reads.py` (the queries)
- Test: `modules/records/tests/public_submissions/test_newsletter_contract_reads.py`

**Interfaces:**
- Produces (in `sm_records.contracts.newsletter`):

```python
MAX_SUBSCRIBER_BATCH = 1000

class SubscriberHit(SQLModel):
    uuid: str
    email: str
    locale: str
    status: str               # "pending" | "confirmed" | "unsubscribed"
    confirmed_at: datetime | None
    first_name: str | None = None
    last_name: str | None = None
    tags: list[str] = []
    trashed: bool = False

class SubscriberFilterError(ValueError):
    reason: str               # "unknown" | "not_indexed" | "reindexing" | "malformed" | "not_a_list"

async def iter_subscribers(session, *, tenant_id: str, type_key: str,
                           filters: Sequence[str] = (), after: int = 0,
                           limit: int = 500) -> tuple[list[SubscriberHit], int | None]
    # confirmed, not trashed, matching every "field:op:value" term; ordered by record id;
    # returns (hits, next_after) — next_after None when exhausted
async def count_subscribers(session, *, tenant_id: str, type_key: str,
                            filters: Sequence[str] = ()) -> int
async def subscribers_by_uuid(session, *, tenant_id: str, type_key: str,
                              uuids: Sequence[str]) -> dict[str, SubscriberHit]
    # any status, trash included (trashed=True); unknown uuids absent; len(uuids) <= MAX_SUBSCRIBER_BATCH
```

- `first_name`/`last_name`/`tags` are read from the record's `data` keys of those names when the type declares them, else `None`/`[]`.
- `type_key` naming a type whose `public_submissions.kind != "subscription"`, or no such type, raises `SubscriberFilterError("not_a_list")`.
- Filters are parsed with records' own term parser (`records/_grammar.py` `_parse_filter`, given `RecordsSettings()` defaults for its limits; expose a non-FastAPI `parse_term(raw, settings)` there if `_parse_filter` needs one). `sm_status:eq:confirmed` is always added. `QueryError` maps to `SubscriberFilterError(reason)`.

- [ ] **Step 1: Write the failing tests.** Use the existing `newsletter` fixture and `tests/support/newsletter_http` helpers (`signup`, `follow`, `links_in`) to make 3 subscribers: one confirmed with `tags=["a"]`, one confirmed with `tags=["b"]`, one left pending. Add the `tags` multiselect field (indexed, choices `a`,`b`) to `list_fields()`'s copy in the test. Then open `newsletter.db_state.session_factory()`.
  - `test_iter_returns_only_confirmed_untrashed`: `iter_subscribers(..., tenant_id="default", type_key=LIST)` returns the 2 confirmed hits, `next_after is None`. Trash one through the admin API and it drops to 1.
  - `test_iter_filters_by_tag`: with `filters=["tags:eq:a"]` it returns 1, and `count_subscribers` with the same filter is `1`. `["tags:in:a,b"]` gives 2.
  - `test_iter_pages_by_after`: `limit=1` gives a non-`None` `next_after`, and the second call with it returns the other hit, then `None`.
  - `test_bad_filter_raises_reason`: `["nope:eq:x"]` raises `SubscriberFilterError` with `.reason == "unknown"`, and `["tags:eq"]` gives `"malformed"`.
  - `test_wrong_tenant_sees_nothing`: `tenant_id="other"` gives `([], None)` and a count of `0`, and `tenant_id="bad tenant!"` raises `ValueError`.
  - `test_by_uuid_any_status`: it returns all 3 (one `status="pending"`), an unknown uuid is absent, and the hit has no attribute `sm_nonce`.
  - `test_limit_checked`: `limit=0`, `limit=1001` and `limit=True` raise `ValueError`.
  - `test_not_a_list`: a `form`-kind type key raises `SubscriberFilterError("not_a_list")`.
- [ ] **Step 2: Run them to see them fail.** Run `cd modules/records && ../../.venv/bin/python -m pytest -q tests/public_submissions/test_newsletter_contract_reads.py`. Expected: `ModuleNotFoundError: sm_records.contracts.newsletter`.
- [ ] **Step 3: Implement** `campaign_reads.py` (`walk`-style keyset query through `records.index.query.build_query` plus `Record.id > after`, `tenant_id` pinned, `NOT_TRASHED`; by-uuid lookup with `include_deleted=True`) and the contract module that wraps it in `tenant_context`.
- [ ] **Step 4: Run the tests to see them pass.** Same command. Expected: all pass.
- [ ] **Step 5: Commit.** Run `git commit -m "feat(records): newsletter contract — subscriber reads"`.

### Task 2: Records — `unsubscribe` and `set_tags`

**Files:**
- Modify: `modules/records/sm_records/contracts/newsletter.py`
- Create: `modules/records/sm_records/public_submissions/campaign_writes.py`
- Test: `modules/records/tests/public_submissions/test_newsletter_contract_writes.py`

**Interfaces:**
- Consumes: Task 1's DTOs and errors.
- Produces:

```python
async def unsubscribe(session, *, tenant_id: str, type_key: str, uuid: str,
                      unless_confirmed_after: datetime | None,
                      settings: RecordsSettings, bus: Any | None = None) -> bool
    # True if this call unsubscribed; False if unknown, trashed, already unsubscribed,
    # or sm_confirmed_at > unless_confirmed_after (a re-signup since the mail)
async def set_tags(session, *, tenant_id: str, type_key: str, uuid: str,
                   add: Sequence[str] = (), remove: Sequence[str] = (),
                   settings: RecordsSettings, bus: Any | None = None) -> SubscriberHit
    # raises SubscriberNotFound(LookupError) for unknown/trashed;
    # a value outside the field's choices surfaces records' ValidationFailed unchanged
```

- `unsubscribe` is `opt_in.leave(..., still=lambda row: not row.is_deleted and confirmed_at(row) <= cutoff)`. `confirmed_at` is parsed from `data["sm_confirmed_at"]` (ISO string, aware UTC). `None` cutoff means unconditional.
- `set_tags` is an `update_record` with `expected_version=record.version`, retried once on `Conflict`. The tag set keeps the stored order with new tags appended and duplicates dropped.

- [ ] **Step 1: Write the failing tests.**
  - `test_unsubscribe_suppresses_and_emits_once`: on a confirmed subscriber, with a bus whose `SubscriptionChanged` handler collects events, `unsubscribe(..., unless_confirmed_after=None)` returns `True`. After `finalize_session` the record's `sm_status == "unsubscribed"`, exactly one event `("confirmed","unsubscribed")` was published, and a second call returns `False` with no new event.
  - `test_resignup_after_cutoff_is_kept`: confirm, take `cutoff = now`, unsubscribe through the link, sign up and confirm again. `unsubscribe(..., unless_confirmed_after=cutoff)` returns `False` and the status stays `confirmed`.
  - `test_unsubscribe_wrong_tenant_is_false`: `tenant_id="other"` returns `False` and the record is unchanged.
  - `test_set_tags_adds_and_removes`: from `["a"]`, `add=["b","a"], remove=[]` gives `["a","b"]`; `remove=["a"]` gives `["b"]`.
  - `test_set_tags_unknown_choice_refused`: `add=["zzz"]` raises records' `ValidationFailed`, and nothing is written.
  - `test_set_tags_missing_raises`: an unknown uuid raises `SubscriberNotFound`.
- [ ] **Step 2: Run them to see them fail.** Run `../../.venv/bin/python -m pytest -q tests/public_submissions/test_newsletter_contract_writes.py`. Expected: `ImportError: cannot import name 'unsubscribe'`.
- [ ] **Step 3: Implement** `campaign_writes.py` and export both functions from the contract.
- [ ] **Step 4: Run the tests to see them pass.** Same command. Expected: all pass.
- [ ] **Step 5: Commit.** Run `git commit -m "feat(records): newsletter contract — unsubscribe and tags"`.

### Task 3: Records — docs and the import-layout pin

**Files:**
- Modify: `modules/records/docs/api-reference.md` (add `### Newsletter contract` under § Newsletter lists: each function, its tenant rule, that hits carry no nonce, and that writes publish only after `finalize_session`)
- Modify: `modules/records/docs/code-layout.md` (`public_submissions/` row mentions `campaign_reads`/`campaign_writes`)
- Test: `modules/records/tests/core/test_layout.py` (if it pins the contracts list, add `newsletter`)

- [ ] **Step 1:** Run `../../.venv/bin/python -c "import sm_records.contracts.newsletter, sm_records.public_submissions.campaign_reads, sm_records.public_submissions.campaign_writes"` in a fresh interpreter. Expected: exit 0 (no import cycle, per `module-layout.md`).
- [ ] **Step 2:** Write the docs. Run `make lint` from the repo root. Expected: passes, including `check_file_size`, `check_rules` and `check_locales`.
- [ ] **Step 3: Commit.** Run `git commit -m "docs(records): newsletter contract"`.

### Task 4: News — `news.contracts.articles`

**Files:**
- Create: `modules/news/news/contracts/articles.py`
- Test: `modules/news/tests/contracts/test_articles_contract.py` (create `tests/contracts/__init__.py` if absent; reuse news' existing fixtures for seeding published, draft and trashed articles, found with `grep -rn "def .*article" modules/news/tests/support modules/news/tests/conftest.py`)

**Interfaces:**
- Produces:

```python
MAX_ARTICLE_SEARCH_LIMIT = 50

class ArticleCard(BaseModel):
    id: int
    title: str
    excerpt: str          # ArticleRead.excerpt
    image_url: str        # ArticleRead.cover_image_url ("" when none)
    path: str             # ArticleRead.url — site-relative, locale-prefixed; caller prefixes public_base_url
    locale: str
    published_at: datetime | None

async def search_articles(session, *, tenant_id: str, pattern: str, limit: int = 20,
                          locale: str | None = None) -> list[ArticleCard]
    # published + not trashed; title ILIKE pattern (caller escapes, "\" escape char,
    # same rule as pagebuilder.contracts.search); newest published_at first
async def get_article_card(session, *, tenant_id: str, article_id: int) -> ArticleCard | None
    # None for unknown, draft, trashed or other-tenant
```

- Built from `news.content.card.base(include_drafts=False, category=None)` and `card.to_read(row)`, with `NewsArticle.tenant_id == tenant_id` pinned. A strict session's `MissingTenantError` answers `[]`/`None`, as in pagebuilder's search.

- [ ] **Step 1: Write the failing tests.**
  - `test_search_finds_published_only`: seed a published "Spring update", a draft "Spring draft" and a trashed "Spring old". `pattern="%Spring%"` returns only the published one, its `path` starts with `/` and contains its slug.
  - `test_search_wrong_tenant_empty`: `tenant_id="other"` returns `[]`.
  - `test_card_none_for_draft_and_unknown`: `get_article_card` on the draft, a trashed article and id `999999` all return `None`. On the published one it returns `title == "Spring update"`.
  - `test_limit_checked`: `0`, `51` and `True` raise `ValueError`.
- [ ] **Step 2: Run them to see them fail.** Run `cd modules/news && ../../.venv/bin/python -m pytest -q tests/contracts/test_articles_contract.py`. Expected: `ModuleNotFoundError: news.contracts.articles`.
- [ ] **Step 3: Implement** `articles.py`.
- [ ] **Step 4: Run the tests to see them pass.** Same command. Expected: all pass. Then run `make lint`. Expected: passes.
- [ ] **Step 5: Commit.** Run `git commit -m "feat(news): article contract for newsletter cards"`. Add one paragraph to news' docs (the module's `docs/` page that lists its contracts or integrations), stating that the contract pins the tenant and that `path` is site-relative.

### Task 5: Branch-level verification

- [ ] Run `~/.claude/bin/wait-for-headroom`, then the records and news suites only: `cd modules/records && PYTEST_WORKERS=8 ../../.venv/bin/python -m pytest -q -n 8` and the same in `modules/news`. Expected: all pass. The full-repo suites run once, in `/ship` (memory: full suites once at ship end).
