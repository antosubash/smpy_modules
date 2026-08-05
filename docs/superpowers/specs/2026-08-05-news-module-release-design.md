# News module — release readiness — design

**Date:** 2026-08-05
**Status:** proposed
**Module:** `modules/news` → `simple_module_news`

## Goal

Get `simple_module_news` to a state where it can be published to PyPI in the
next lockstep release, and where the API it exposes is correct enough that a
consuming host can build on it without discovering the sharp edges itself.

The module is architecturally sound — an article is a `pagebuilder` page, and
the sidecar carries only what a page has no concept of. That design is not
under review here. What is under review is the correctness of the write path,
the durability of the orphan guard, and the release plumbing, none of which
would survive a first external install.

## What is already good

Recorded so the implementation does not redo it:

- **e2e coverage.** `tests/e2e/news-admin.spec.ts` and `news-feed.spec.ts`
  cover the sidebar route, inline category editing, the page-delete cascade,
  block-palette registration, exclusion from the site-layout palette, category
  filtering, the empty-feed state, and anonymous access. No new e2e specs are
  required by this design.
- **Registration tests.** `tests/test_module.py` pins routes, permissions,
  menu placement, and the anonymous-read surface including the assertion that
  writes stay behind `news.edit`.
- **Model tests.** `tests/test_models.py` pins the table shape, the one-article-
  per-page constraint, the absent foreign key, and the listing indexes.
- **Repo checks.** `check_metadata`, `check_readmes`, `check_hardcoded_strings`
  and the 300-line cap all pass today and must still pass after.

## Findings

### F1 — `POST /articles` returns 404 for the article it just created

`endpoints/api.py:39` reads the new article back by listing the first
`MAX_LIMIT` (100) articles and scanning them in Python for a matching
`page_id`.

A newly attached article is undated, and `list_articles` orders
`published_at DESC NULLS LAST`. Undated articles therefore sort *after* every
dated one. On a site with 100 or more dated articles the new row is not in the
first page, the scan finds nothing, and the endpoint raises
`404 Article's page not found.`

The row has already been written. The client sees a failure for a write that
succeeded. `PUT /articles/{id}` shares the same helper and the same fault.

### F2 — `PUT` silently clears the publication date

`contracts/schemas.py:55` declares `published_at: datetime | None = None`, so
a request body of `{"category": "Events"}` is indistinguishable from
`{"category": "Events", "published_at": null}`. `service.py:132` then assigns
the field unconditionally.

The result is that any partial update erases the article's date. The comment
directly above that line states the opposite — "it is only applied when the
caller sent the field — the endpoint decides that" — and the endpoint does not
decide that. The admin UI happens to always send both fields, so the bug is
invisible from the browser and live for every API consumer.

### F3 — the service commits, so the endpoint cannot roll back

`service.py` calls `await db.commit()` in `create`, `update` and `delete`.
Every other service in this repo — `pagebuilder`'s `MediaService`,
`LayoutService`, `_workflow`, `_revisions` — calls `db.flush()` and lets the
framework's request-scoped `get_db` commit on the way out.

`get_db` (`simple_module_db/deps.py:17`) already commits when the session has
pending writes, so the explicit commit is redundant. It is also harmful: it
compounds F1. In `attach_article` the sequence is `service.create` → **commit**
→ `_read_one_by_page` → `HTTPException(404)`. The exception cannot undo the
commit, so the API reports a failure for a row that is now durable.

### F4 — the orphan guard is best-effort with no reconciliation

This is the finding that drives the design.

`page_id` carries no database foreign key, by necessity: `create_module_base`
gives every module its own `MetaData`, so a cross-module `ForeignKey` cannot
resolve its target. The module compensates with a `PageDeleted` subscription
that deletes the article row.

That compensation is not durable:

- `EventBus.publish` (`simple_module_core/events.py:71`) gathers handlers with
  `return_exceptions=True` and turns any failure into a `logger.error` call.
  Handler failure does not propagate.
- `pagebuilder`'s `delete` (`service/__init__.py:136`) deliberately commits the
  page deletion *before* publishing, to avoid a SQLite lock against the still
  open write transaction.

So if `_drop_article` fails for any reason — a transient database error, a lock,
a bug — the page is already gone, the article row survives, nothing retries,
and the only trace is a log line.

The listing's inner join hides the orphan, which is why this is not an outage.
But SQLite reuses a deleted row's id. When the next page is created it can take
the dead page's id, the orphaned article re-attaches to it, and the feed renders
one article's title, category and date against another article's page. At that
point the row is no longer invisible — it is wrong.

The model docstring claims "the row itself is inert until something detaches
it". Under id reuse that is not true, and the docstring must be corrected along
with the behaviour.

### F5 — `simple_module_news` is not in the publish matrix

`.github/workflows/release.yml:142` lists a single package:

```yaml
matrix:
  package:
    - simple_module_pagebuilder
```

The `build` job runs `uv build --all-packages`, so a news wheel *is* built and
uploaded as an artifact. It is then never published. A release would appear to
succeed and ship nothing.

The file's own header comment says "Every new module must be added to the
`publish-pypi` matrix below." It was not.

`simple_module_canopy_atlas` has the same gap. It is out of scope for this
spec — flagged, not fixed, because it is a different module with its own
release-readiness questions.

### F6 — smaller release-plumbing gaps

- The root `README.md` module table lists only `modules/pagebuilder`. News and
  canopy_atlas are missing.
- Root `pyproject.toml` `testpaths` is
  `["host/tests", "modules/pagebuilder/tests", "scripts/tests"]`. The Makefile's
  `test-py` loop iterates `modules/*/tests` so CI does run the news suite, but a
  bare `uv run pytest` from the repo root silently skips it.
- No `locales/en.json`. All TSX copy is hardcoded English. `CLAUDE.md` records
  this as known deferred work for pagebuilder; news has the same gap.

### F7 — no Python tests for `service.py` or `endpoints/api.py`

F1, F2 and F3 all live in the untested gap between the model tests and the e2e
suite. The e2e specs exercise the happy path through a browser; nothing
exercises the service or endpoint contracts directly, which is why a 404 on
successful creation and a date-clearing PUT both survived review.

## Design

### D1 — read the article back by the key that identifies it

Replace the scan in `_read_one_by_page` with a targeted query. The helper's
stated purpose — "re-read through the listing join so every response has one
shape" — is right; the implementation is what is wrong.

Add to `service.py`:

```python
async def get_read_by_page(
    db: AsyncSession, page_id: int, *, include_drafts: bool = True
) -> ArticleRead | None:
    """One article in listing shape, found by page rather than by scanning."""
    stmt = _base(include_drafts, None).where(NewsArticle.page_id == page_id)
    row = (await db.execute(stmt)).first()
    return _to_read(*row) if row else None
```

This reuses `_base`, so the response shape and the join semantics stay
identical to the listing by construction rather than by convention. The
endpoint keeps its 404 for the genuine case — the page is gone, so there is no
slug or title to return — and loses the false one.

`_read_one_by_page` becomes a thin wrapper that raises when the query returns
`None`, or disappears into the two call sites. Implementation's choice.

### D2 — make `PUT` a real partial update

Use Pydantic's `model_fields_set` at the endpoint to distinguish an omitted
field from an explicit null, and pass only what the caller sent.

`service.update` changes signature to accept a sentinel rather than a bare
`datetime | None`:

```python
class _Unset:
    """Sentinel type — `published_at` omitted, as distinct from sent as null."""

UNSET: Final = _Unset()

async def update(
    db: AsyncSession,
    article: NewsArticle,
    *,
    category: str | None = None,
    published_at: datetime | None | _Unset = UNSET,
) -> NewsArticle:
    if category is not None:
        article.category = category
    if not isinstance(published_at, _Unset):
        article.published_at = published_at  # None here means "undate it"
    ...
```

The sentinel is a typed singleton rather than a bare `object()` so the
signature stays checkable — `datetime | None | _Unset` is a real union, and
`isinstance` narrows it. It is exported as `UNSET` because the endpoint is the
component that decides, and therefore has to name it.

and the endpoint decides, which is what the existing comment already promised:

```python
await service.update(
    db,
    article,
    category=body.category,
    published_at=(
        body.published_at if "published_at" in body.model_fields_set else service.UNSET
    ),
)
```

`PUT {"category": "x"}` now leaves the date alone. `PUT {"published_at": null}`
still undates the article, which must remain possible — an undated article is a
real state, not an error.

This is a behaviour change to a published API surface. The module has never
been published, so there is no compatibility obligation; the README table gains
a note that `PUT` is a partial update.

### D3 — flush, do not commit

Replace the three `await db.commit()` calls in `service.py` with
`await db.flush()`, matching every other service in the repo and letting
`get_db` own the transaction boundary.

`create` and `update` keep their `await db.refresh(article)` — after a flush the
row has its server defaults and generated id, which is what the caller needs.

The consequence that matters: `attach_article` raising 404 after a failed
read-back now rolls the row back with it. With D1 in place that path should be
unreachable, but the transaction boundary should be correct regardless of
whether any given endpoint has a bug.

The one caller that is *not* inside a request — the `PageDeleted` handler in
`module.py:81` — opens its own session via `app.state.sm.db.session_factory()`
and is not covered by `get_db`. It must commit explicitly. The handler becomes
responsible for its own transaction:

```python
async with app.state.sm.db.session_factory() as db:
    article = await service.get_by_page(db, event.page_id)
    if article is not None:
        await service.delete(db, article)
        await db.commit()
```

This is the reason `service.delete` cannot simply keep committing: it has two
callers with different transaction ownership, and the service is the wrong
place to decide.

### D4 — reconcile orphans at startup

The event handler stays as the fast path. It handles the overwhelmingly common
case immediately and correctly.

Add a sweep that runs once at startup and deletes every `news_articles` row
whose `page_id` has no corresponding page:

```python
async def reconcile_orphans(db: AsyncSession) -> int:
    """Delete article rows whose page is gone. Returns how many.

    The PageDeleted subscription is the fast path, but it is best-effort:
    EventBus.publish logs handler failures instead of raising, and pagebuilder
    commits the page deletion before publishing. A dropped event therefore
    leaves a row behind permanently, and SQLite reuses the deleted page's id —
    so the orphan does not stay invisible, it re-attaches to whatever page is
    created next and lists one article's metadata under another's page.
    """
    orphaned = select(NewsArticle.id).where(
        ~select(Page.id).where(Page.id == NewsArticle.page_id).exists()
    )
    result = await db.execute(
        sa_delete(NewsArticle).where(NewsArticle.id.in_(orphaned))
    )
    return result.rowcount or 0
```

wired into a new `on_startup` on `NewsModule`:

```python
async def on_startup(self, app: FastAPI) -> None:
    async with app.state.sm.db.session_factory() as db:
        dropped = await service.reconcile_orphans(db)
        await db.commit()
    if dropped:
        logger.warning("Dropped %d orphaned news article(s) at startup", dropped)
```

**Why startup and not periodic or transactional.** The window that matters is
between a dropped event and the next page creation that reuses the id. A
process restart is a natural, cheap boundary at which to close it, it needs no
scheduler, and it costs one indexed anti-join against a table that holds one row
per article. Logging at `warning` when it finds anything is deliberate: a
non-zero count means an event was lost, which is worth surfacing rather than
silently repairing.

Rejected alternatives:

- **Durable handler** — retry with backoff, or an outbox table. Correct in the
  general case, but it is real machinery for a single-subscriber in-process bus,
  and the framework offers nothing to build it on. Pre-1.0, the cost is not
  justified by the risk.
- **Validate `page_id` on every read** — the listing's inner join already makes
  orphans invisible, so this adds a query per request and closes no window that
  the sweep does not close better.

### D5 — correct the docstrings that are now wrong

Three comments assert behaviour the code will no longer have, or never had:

- `models.py:48` — "The row itself is inert until something detaches it." Not
  true under id reuse. Restate as: orphans are invisible to every listing, and
  the startup sweep removes them before id reuse can make them visible again.
- `service.py:130` — the "endpoint decides that" comment becomes true under D2
  and should point at the sentinel.
- `endpoints/api.py:41` — the "Drafts are included" rationale survives, but the
  reference to listing-then-scanning does not.

### D6 — release plumbing

1. Add `simple_module_news` to the `publish-pypi` matrix in `release.yml`.
2. Add the news row to the root `README.md` module table.
3. Add `modules/news/tests` to root `pyproject.toml` `testpaths`.
4. Add `modules/news/news/locales/en.json` and route the TSX copy through it,
   matching whatever convention the other first-party modules use.

Item 4 is the one with a real chance of expanding: if no other module in this
repo has a locales file to copy, the convention has to come from the framework
repo. If that turns out to be unsettled, item 4 is dropped from this spec and
recorded in `CLAUDE.md` alongside the existing pagebuilder i18n note, rather
than inventing a convention during a release-prep change.

**Not automatable — needs the maintainer.** PyPI Trusted Publishing must be
configured once for the `simple_module_news` project name before the matrix
entry can succeed, per the header comment in `release.yml`:

| Field | Value |
|---|---|
| PyPI project name | `simple_module_news` |
| Owner | `antosubash` |
| Repository name | `simple_module_python_modules` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Without this the release job fails at the publish step with an OIDC error.

### D7 — the tests that should have caught this

A new `modules/news/tests/test_service.py` and `test_api.py`, using the
`build_test_app` fixture from the `simple_module_test` plugin the existing
suite already relies on.

Minimum cases, each mapped to a finding:

| Test | Finding |
|---|---|
| attaching returns the article when >100 dated articles exist | F1 |
| `PUT {"category": ...}` leaves `published_at` unchanged | F2 |
| `PUT {"published_at": null}` undates the article | F2 |
| a failed attach leaves no committed row | F3 |
| `reconcile_orphans` deletes a row whose page is gone | F4 |
| `reconcile_orphans` leaves a row whose page exists | F4 |
| listing still hides an orphan before the sweep runs | F4 |

The first case is the important one and needs the fixture to create enough
dated pages to push an undated article past the first page of results. It fails
against today's code, which is the point.

## Scope

**In:** everything above, for `modules/news` only.

**Out:**
- `simple_module_canopy_atlas`'s identical publish-matrix gap. Flagged in F5;
  it is a separate module needing its own readiness pass.
- The admin UX. `prompt()`/`confirm()` in `NewsList.tsx`, the missing category
  filter, and the fixed 100-row page are real, but they are product work rather
  than release blockers, and none of them can corrupt data.
- Any change to `pagebuilder` or the framework. This design deliberately fits
  inside the module: `reconcile_orphans` reads `Page` through the import news
  already has, and needs no new event, no cross-module FK, and no framework
  hook that does not already exist.

## Verification

- `make test-py` — new service and API suites green, existing suites unchanged.
- `make e2e` — the existing news specs must still pass untouched. If any of
  them needs editing, the change broke a contract and the edit needs
  justification, not acceptance.
- `make lint` — ruff, biome, typecheck, `check_metadata`, `check_readmes`,
  `check_hardcoded_strings`, `check_file_size`.
- `uv build --package simple_module_news` produces a wheel.
- `module.py` and `service.py` stay under the 300-line cap. `module.py` is 95
  lines today and gains `on_startup`; `service.py` is 142 and gains
  `get_read_by_page` and `reconcile_orphans`. Both have room.

## Risks

- **D2 changes API semantics.** Mitigated by the module being unpublished.
  Anything running against a workspace checkout of news that relies on `PUT`
  clearing the date would break — nothing in this repo does.
- **D4's sweep is a delete that runs unattended at boot.** Its predicate is an
  anti-join on `page_id`, the same condition the listing's inner join already
  uses to hide the row, so a row it deletes is already unreachable through
  every code path. The `warning` log makes an unexpected non-zero count
  visible rather than silent.
- **D6.4 (i18n) may not have a convention to follow.** Explicitly droppable
  without blocking the release; see D6.
