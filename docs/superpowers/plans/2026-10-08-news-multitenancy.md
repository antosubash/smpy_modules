# News multi-tenancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every news table is tenant-scoped, and every news entry point binds a
tenant, so a multi-tenant host can run News without tenants sharing articles.

**Architecture:** This is a port of pagebuilder's #53 pattern (commit
`c493630090f0`). The parts are:
- a news-owned `news/tenancy.py`
- `MultiTenantMixin` on the models
- router-level `bind_admin`/`bind_public` dependencies
- a scheduler that runs per tenant
- one host migration that backfills `'default'`

The pagebuilder files named in each task are the reference implementation.
Read them first.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, alembic, pytest
(asyncio_mode=auto), Playwright, simple_module_db 0.0.35 (`tenant_context`,
`all_tenants`, `current_tenant_id`, `is_valid_tenant_id`, `MissingTenantError`,
`mixins.MultiTenantMixin`), simple_module_hosting (`middleware.TenantMiddleware`).

**Spec:** `docs/superpowers/specs/2026-10-08-news-multitenancy-design.md`

## Global Constraints

- Commands run from the repo root. Run tests with
  `cd modules/news && ../../.venv/bin/python -m pytest -q`; host tests with
  `.venv/bin/python -m pytest host/tests -q`.
- **300-line cap** on every `.py`/`.ts`/`.tsx`, checked by
  `python scripts/check_file_size.py`. Two files are already near it:
  - `modules/news/news/models/_article.py` (288 lines)
  - `modules/news/tests/conftest.py` (288 lines)

  Put new test helpers in new files, never in `conftest.py`.
- News must **not import `pagebuilder`** outside `news/integrations/`, because
  pagebuilder is optional.
- `DEFAULT_TENANT = "default"` is a constant, and the migration repeats the
  literal.
- Published modules use range pins only. Do not touch dependency specifiers.
- Never add files under `modules/*/*/pages/`.
- Commit after each task with `feat(news-multitenancy): <task>`. Every commit
  message ends with
  `Claude-Session: https://claude.ai/code/session_017uTbtobjCKQYnAxF5tgK8t`.

## Review Focus

1. **Feed-block API reads.** `constants.PUBLIC_READ_PREFIXES` are API GETs
   that anonymous visitors hit. Under multi mode, an anonymous request with a
   subdomain tenant must get *that tenant's* articles. Test:
   `test_tenancy_public.py::test_anonymous_api_read_scoped`.
2. **Bulk Core statements.** These are the `sa_update`/`sa_delete` calls in
   `category_service`, `tag_service`, `redirects`, `content/_claims.py` and
   `content/_fresh.py`. Renaming a category in tenant A must not rename
   tenant B's articles' `category` string. Test:
   `test_tenancy_isolation.py::test_category_rename_stays_in_tenant`.
3. **The same slug in two tenants**, for an article, category or tag, must
   create cleanly. A redirect in A must not resolve in B. Test:
   `test_tenancy_isolation.py::test_same_slugs_in_two_tenants`.
4. **Sitemap and RSS** in tenant B must not list tenant A's articles. Test:
   `test_tenancy_public.py::test_feed_and_sitemap_per_tenant`.
5. **Scheduler.** A due article in tenant B publishes even when tenant A's
   tick raises. Test:
   `test_scheduler_tenancy.py::test_one_tenant_failing_does_not_stop_others`.

---

### Task 1: `news/tenancy.py` + test harness

**Files:**
- Create: `modules/news/news/tenancy.py`. Copy
  `modules/pagebuilder/pagebuilder/tenancy.py` and make these changes:
  - `_PACKAGE = "news"`.
  - Logger `simple_module.news`.
  - Messages say `news:` instead of `pagebuilder:`.
  - `_NOT_FOUND = "Article not found"`. Check that this matches what
    `endpoints/public/_article.py` raises for an unknown slug, and use that
    exact string.
  - Add `search_tenant()` and include it in `__all__`:
    ```python
    def search_tenant() -> str:
        """The tenant a cross-module read runs in: the bound one, else the
        single-tenant host's. A host with multi_tenant off binds none, and
        an unfiltered read there would be every tenant's rows."""
        from simple_module_db import current_tenant_id
        return current_tenant_id.get() or DEFAULT_TENANT
    ```
  - `configure` stores the mode on `app.state.news` if that exists.
    Otherwise it sets `app.state.news_tenancy`. Use the same attribute in
    `mode_of`. Check first how news keeps its app-state namespace with
    `grep -rn "app.state" modules/news/news`.
- Modify: `modules/news/news/integrations/pagebuilder.py`. Delete
  `_search_tenant` and call `news.tenancy.search_tenant()` at its call sites.
- Create: `modules/news/tests/tenant_fixture.py`. Copy pagebuilder's
  `tests/tenant_fixture.py` and import `DEFAULT_TENANT` from `news.tenancy`.
- Modify: `modules/news/pyproject.toml` `[tool.pytest.ini_options]`. Add
  `pythonpath = ["tests"]` and `addopts = "-p tenant_fixture"`.
- Test: `modules/news/tests/test_tenancy_core.py`.

**Interfaces produced:**
- `news.tenancy.DEFAULT_TENANT: str`
- `TENANT_REQUIRED`
- `TenancyMode{SINGLE,MULTI}`
- `detect_mode(app)`, `configure(app) -> TenancyMode`, `mode_of(app)`
- `resolve_admin(request) -> str`
- `resolve_public(request) -> str | None`
- `async bind_admin(request)` and `async bind_public(request)`, both
  generator deps yielding `str`
- `search_tenant() -> str`

- [ ] **Step 1: Write the failing tests.** Port
  `modules/pagebuilder/tests/test_tenancy_core.py` and import from
  `news.tenancy`. Add one test for `search_tenant`:
  ```python
  @pytest.mark.unbound_tenant
  def test_search_tenant_falls_back_to_default():
      assert tenancy.search_tenant() == "default"
      with tenant_context("acme"):
          assert tenancy.search_tenant() == "acme"
  ```
- [ ] **Step 2: Run the tests and confirm they fail.** Run
  `pytest tests/test_tenancy_core.py -q`. Expected: `ModuleNotFoundError:
  news.tenancy`.
- [ ] **Step 3: Implement** the files above.
- [ ] **Step 4: Run the tests and confirm they pass.** Run
  `pytest tests/test_tenancy_core.py tests/test_integrations.py tests/test_search.py -q`.
  Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 2: Models carry `tenant_id`; uniques per tenant

**Files:**
- Modify: `modules/news/news/models/_article.py`,
  `models/_revision.py`, `models/_redirect.py` and `models/_taxonomy.py`.
- Test: `modules/news/tests/test_tenancy_models.py`.

**Changes:**
- Add `MultiTenantMixin` (`from simple_module_db.mixins import AuditMixin,
  MultiTenantMixin`) after `AuditMixin` on all six classes. On
  `NewsArticleRedirect` and `NewsArticleTag`, which have no `AuditMixin`, use
  `(Base, MultiTenantMixin, table=True)`.
- `NewsArticle.__table_args__`:
  - Replace `ix_news_articles_locale_slug` with
    `Index("ix_news_articles_tenant_locale_slug", "tenant_id", "locale", "slug", unique=True)`.
  - Replace `ix_news_articles_group_locale` with
    `Index("ix_news_articles_tenant_group_locale", "tenant_id", "translation_group", "locale", unique=True)`.
  - Keep the docstrings and update them to say "per tenant and locale".
  - If `_article.py` would go over 300 lines, shorten the comments rather
    than splitting the file.
- `NewsArticleRedirect`: replace its unique index with
  `ix_news_article_redirects_tenant_locale_from_slug` on
  (`tenant_id`, `locale`, `from_slug`).
- `NewsCategory` and `NewsTag`:
  - Remove `unique=True` from `name` and `slug`, and keep `index=True`.
  - Add `__table_args__`:
    - Categories: `Index("uq_news_categories_tenant_name", "tenant_id", "name", unique=True)` and
      `Index("uq_news_categories_tenant_slug", "tenant_id", "slug", unique=True)`.
    - Tags: the same with the `uq_news_tags_` prefix.
  - Check whether the existing column indexes are named `ix_news_categories_name`
    etc. (the default SQLModel naming), because the migration relies on that.

- [ ] **Step 1: Write the failing test.** In `test_tenancy_models.py`, use
  the `db_state` fixture and seed under two tenants:
  ```python
  pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]

  async def test_same_slug_and_category_in_two_tenants(db_state):
      for tenant in ("a", "b"):
          with tenant_context(tenant):
              async with db_state.session_factory() as s:
                  s.add(NewsCategory(name="Sport", slug="sport"))
                  s.add(NewsTag(name="Live", slug="live"))
                  await make_article(s, slug="hello", locale="en")
                  await s.commit()
      with tenant_context("a"):
          async with db_state.session_factory() as s:
              rows = (await s.execute(select(NewsArticle))).scalars().all()
              assert [r.tenant_id for r in rows] == ["a"]

  async def test_duplicate_slug_in_one_tenant_still_rejected(db_state):
      with tenant_context("a"):
          async with db_state.session_factory() as s:
              s.add(NewsCategory(name="Sport", slug="sport"))
              s.add(NewsCategory(name="Sport", slug="sport"))
              with pytest.raises(IntegrityError):
                  await s.commit()
  ```
  First read `tests/factories.py` to get `make_article`'s real signature, and
  adapt the call to it.
- [ ] **Step 2: Run the test and confirm it fails.** Expected: IntegrityError
  on the second tenant's "sport", or no `tenant_id` attribute.
- [ ] **Step 3: Implement** the model changes.
- [ ] **Step 4: Run the whole news suite.** Run `pytest -q`. Everything must
  pass, because the autouse fixture binds `"default"`. If a test seeds rows
  outside the fixture's context (in a different task or thread), wrap it in
  `tenant_context(DEFAULT_TENANT)`.
- [ ] **Step 5: Commit.**

### Task 3 (HARD): Bind a tenant at every entry point

**Files:**
- Modify:
  - `modules/news/news/endpoints/api/__init__.py`: `router =
    APIRouter(dependencies=[Depends(bind_admin)])`.
  - `modules/news/news/endpoints/views.py`: `router` and `admin_router` get
    `dependencies=[Depends(bind_admin)]`.
  - `modules/news/news/endpoints/public/__init__.py` (`public_router`) and
    `public/_article.py` (`default_locale_alias_router`):
    `APIRouter(dependencies=[Depends(bind_public)])`.
    - The sitemap is included inside `public_router`, so check that it
      inherits the binding.
    - The alias router only 301s. Bind it anyway, because the guard test
      requires it, and it costs nothing.
  - `modules/news/news/module.py`: `tenancy.configure(app)` is the first
    statement in `on_startup`.
- Create: `modules/news/tests/tenant_app.py`. Port pagebuilder's
  `tests/tenant_app.py`:
  - `HeaderTenant` (verbatim).
  - `multi_client(user, *, mount_public=False)`, built on news'
    `_build_app(user, mount_public=...)`:
    1. Add `HeaderTenant`, then `TenantMiddleware`.
    2. Assert `tenancy.configure(app) is TenancyMode.MULTI`.
    3. Set `app.state.sm.db.tenant_strict = True`.
    4. Yield an `httpx.AsyncClient(transport=ASGITransport(app), base_url="http://test")`.
    5. Dispose the engine.

    `mount_public=True` calls `on_startup`, which calls `configure` again
    after the middleware is added. That's fine.
  - `as_tenant(t)`.
  - `create_article(client, headers, slug, title, **extra) -> dict`, which
    POSTs to the articles API. Find the payload shape in `tests/factories.py`
    or `test_api*.py`.
- Test files (new):
  - `test_tenancy_routes.py`: port the pagebuilder guard.
    - Prefixes are `meta.route_prefix`, `meta.view_prefix`,
      `constants.ADMIN_SEARCH_PREFIX` and the public prefix.
    - Build with `mount_public=True` so the public routers exist.
    - Allow-list only what reads no rows. It is expected to be empty.
  - `test_tenancy_isolation.py`, using the admin `user` from conftest's
    editor fixture:
    - `test_tenant_cannot_see_or_edit_other_tenants_article`: A creates an
      article. In B, GET, PUT, publish and DELETE on it all return 404, and
      B's list is empty.
    - `test_same_slugs_in_two_tenants`: the same article slug, category and
      tag in A and B all return 201. After a slug rename in A, the old slug
      resolves in A only.
    - `test_category_rename_stays_in_tenant`: A and B both have category
      "Sport" with one article each. After A renames it to "Football", B's
      article still reads "Sport".
    - `test_admin_without_tenant_is_403`: in multi mode with no `x-tenant`,
      the response is 403 `tenant_required`.
  - `test_tenancy_public.py`, with `mount_public=True`:
    - `test_public_article_per_tenant`: A publishes `hello`. It is a 200 in
      A, and a 404 in B and with no tenant.
    - `test_feed_and_sitemap_per_tenant`: B's `/feed.xml` and
      `/sitemap.xml` don't contain A's article.
    - `test_anonymous_api_read_scoped`: with an anonymous user, a GET on a
      `PUBLIC_READ_PREFIXES` route with `x-tenant: b` doesn't return A's
      article.

- [ ] **Step 1:** Write `tenant_app.py` and the three test files. Run them
  and confirm they fail: the guard should list unbound routes, and the
  isolation tests should see cross-tenant rows.
- [ ] **Step 2:** Add the dependencies and the `configure` call.
- [ ] **Step 3:** Run the new tests plus the full news suite. Fix any test
  that now 403s or 404s because its app has no tenant. In SINGLE mode that
  should not happen, so investigate before patching.
- [ ] **Step 4:** For each `sa_update`/`sa_delete` in the services named in
  Review Focus 2, confirm the isolation test covers it, or add an explicit
  `.where(Model.tenant_id == ...)` if the framework does not filter it.
- [ ] **Step 5:** Commit.

### Task 4: Scheduler runs per tenant

**Files:**
- Modify: `modules/news/news/scheduler.py`. Reference:
  `modules/pagebuilder/pagebuilder/scheduler.py` (lines ~95–135).
  - Add `async def _due_tenants(factory, now) -> list[str]`. Under
    `with all_tenants():`, on its own session that is closed before
    returning, it runs `select(NewsArticle.tenant_id).where(<due>).distinct()`.
    The `<due>` predicate must match what `process_due` and
    `retire_missed_windows` in `content/_claims.py` select (publish due,
    unpublish due, missed window). If those predicates are inline, extract
    them into named functions in `_claims.py` and use them in both places,
    so the definition of "due" lives in one place.
  - Change `tick(factory)` so that for each tenant it runs
    `with tenant_context(tid): await self._tick_tenant(factory, now)`.
    Catch `Exception` per tenant and log
    `logger.exception("news.scheduler.tenant_failed", extra={"tenant_id": tid})`.
  - `_tick_tenant` is the current body of `tick`: it always commits, and the
    existing docstring explains why. Keep that docstring.
- Test: `modules/news/tests/test_scheduler_tenancy.py`. Copy the structure of
  pagebuilder's `tests/test_scheduler_tenancy.py`:
  - Mark it `unbound_tenant`.
  - Use `db_state` with `tenant_strict = True`.
  - Seed a due article (`publish_at` in the past, status draft) in A and in
    B.
  - `test_due_work_runs_in_every_tenant`: after `await Scheduler().tick(factory)`,
    both are published and the revisions carry the right `tenant_id`.
  - `test_one_tenant_failing_does_not_stop_others`: monkeypatch
    `ArticlesService.process_due` to raise when
    `current_tenant_id.get() == "a"`. B is still published.

- [ ] **Step 1:** Write the tests and confirm they fail (`MissingTenantError`
  under strict mode).
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Run `pytest tests/test_scheduler*.py -q` and the full
  suite. Expected: PASS.
- [ ] **Step 4:** Commit.

### Task 5 (HARD): Host migration

**Files:**
- Create: `host/migrations/versions/<rev>_news_tenant_id.py`.
  - Set `down_revision = "c493630090f0"`. First confirm with
    `.venv/bin/alembic heads` that this is the main-line head. The billing
    and tenants branches are separate labelled heads.
  - Use a fresh 12-hex revision id.
  - Copy `c493630090f0_pagebuilder_tenant_id.py` exactly in structure:
    `TABLES` (the six news tables), then `KEYS`:
    ```
    (news_articles, ix_news_articles_locale_slug, [locale, slug], ix_news_articles_tenant_locale_slug, [tenant_id, locale, slug])
    (news_articles, ix_news_articles_group_locale, [translation_group, locale], ix_news_articles_tenant_group_locale, [tenant_id, translation_group, locale])
    (news_article_redirects, ix_news_article_redirects_locale_from_slug, [locale, from_slug], ix_news_article_redirects_tenant_locale_from_slug, [tenant_id, locale, from_slug])
    (news_categories, ix_news_categories_name, [name], uq_news_categories_tenant_name, [tenant_id, name])
    (news_categories, ix_news_categories_slug, [slug], uq_news_categories_tenant_slug, [tenant_id, slug])
    (news_tags, ix_news_tags_name, [name], uq_news_tags_tenant_name, [tenant_id, name])
    (news_tags, ix_news_tags_slug, [slug], uq_news_tags_tenant_slug, [tenant_id, slug])
    ```
  - Check the real old index names in the earlier news migrations
    (`grep -n "create_index\|UniqueConstraint\|unique" host/migrations/versions/52d927feccb3* ...`).
    If name and slug uniqueness is a `UniqueConstraint` rather than a unique
    index, drop it via `batch_alter_table(...).drop_constraint`.
  - The categories and tags models keep a non-unique `index=True` on
    `name` and `slug`. Recreate `ix_news_categories_name` etc. as
    non-unique, so the autogenerate diff is empty.
  - No partial indexes are involved.
  - Downgrade uses the same `_shared_keys` refusal.
- Test: `host/tests/test_news_tenant_migration.py`. Model it on
  `host/tests/test_news_upgrade_from_007.py`:
  1. Upgrade to `c493630090f0` and insert a category, a tag, an article
     with a redirect and a revision, and an article_tag.
  2. Upgrade to head and assert every row's `tenant_id == "default"`.
  3. Insert the same slug under tenant "b" with raw SQL, and check it
     succeeds.
  4. Downgrade one step and confirm it raises `RuntimeError`.
  5. Delete the "b" row, downgrade, and confirm it succeeds.
- Also add an **autogenerate-is-empty check**:
  - If one exists already (`grep -rn "compare_metadata\|autogenerate" host/tests`),
    extend it.
  - Otherwise run `.venv/bin/alembic upgrade heads` on a scratch SQLite DB,
    then `alembic check`, and confirm it reports no new operations.

- [ ] **Step 1:** Write the host test and confirm it fails (no revision).
- [ ] **Step 2:** Write the migration.
- [ ] **Step 3:** Run `.venv/bin/python -m pytest host/tests -q` and
  `alembic check`. Expected: PASS, with no drift.
- [ ] **Step 4:** If `SM_TEST_DATABASE_URL` Postgres is available
  (dev-services), run the host test against it too. Otherwise note that CI's
  Postgres job covers it.
- [ ] **Step 5:** Commit.

### Task 6: Multi-tenant e2e, CI job, docs

**Files:**
- Create: `tests/e2e/news-tenant.spec.ts`. Copy `billing-tenant.spec.ts`'s
  opt-in guard (`test.skip(!process.env.E2E_MULTI_TENANT, ...)`) and its
  tenant/organisation setup.
  1. As the bootstrap admin in tenant/org A, create and publish an article
     through the UI or API. Follow `article-helpers.ts`.
  2. Switch to or create org B (do whatever billing-tenant does to get an
     active organisation). B's news list doesn't show the article.
  3. The public URL under B's host/subdomain returns 404.

  If subdomains cannot be addressed from Playwright, assert on the admin
  list only and note it.
- Modify: `tests/e2e/billing-tenant.spec.ts` header. Remove the "News is left
  out … startup reconcile" text, and drop `SM_MODULES_ENABLED` from the
  documented command.
- Modify: `.github/workflows/ci.yml`. Add a job `e2e-multi-tenant` named
  `E2E (multi-tenant)`:
  - Copy the `e2e` job's setup steps.
  - `timeout-minutes: 20`.
  - `env: E2E_MULTI_TENANT: "1"`.
  - Run `npm run test:e2e -- billing-tenant news-tenant`.
- Modify `CLAUDE.md`:
  - Extend "Every pagebuilder entry point binds a tenant (#38)" to say news
    does too (its own `news.tenancy`). "Code outside pagebuilder that reads
    its tables (news' search) pins `tenant_id` itself" stays true.
  - Replace the "demo host is single-tenant" deferred bullet with: the demo
    host defaults to single-tenant, multi-tenant e2e runs in its own CI job,
    and all modules are tenant-aware.
- Modify: `.claude/skills/running-the-stack/SKILL.md` line ~50. Drop "without
  News".
- Modify: `docs/releasing.md`. Change the PyPI trusted-publisher "Repository
  name" to `smpy_modules` (the actual repo; check with
  `gh repo view --json name`).

- [ ] **Step 1:** Write the spec. Run it locally:
  `E2E_MULTI_TENANT=1 npx playwright test news-tenant billing-tenant`.
  Expected: PASS. This needs `npx playwright install chromium` once.
- [ ] **Step 2:** Make the CI and docs edits.
- [ ] **Step 3:** Run `make lint` and `python scripts/check_file_size.py`.
- [ ] **Step 4:** Commit.

## Parallelism

Tasks 1→2→3→4 run in order:
- Task 2 needs the fixture from Task 1.
- Task 3 needs the models from Task 2.
- Task 4 touches `_claims.py`, which Task 3 may touch.

Task 5 depends only on Task 2's index names, so it can run in parallel with
Tasks 3–4, because their files don't overlap. Task 6 runs last.
