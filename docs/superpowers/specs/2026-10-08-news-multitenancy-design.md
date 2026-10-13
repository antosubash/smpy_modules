# News multi-tenancy — design

Supersedes closed #39 (its scope described the pre-#29 architecture: `page_id`,
the pagebuilder slug claim and the page-orphan sweep no longer exist).

## Goal & scope

Make the `news` module tenant-scoped the way pagebuilder became in #53, so a
host can run `SM_MULTI_TENANT=true` with News enabled and each tenant sees only
its own articles, taxonomy and redirects.

**In**
- `MultiTenantMixin` on all six news tables; every natural unique key gains a
  leading `tenant_id`.
- A tenant bound at every news entry point (admin API, Inertia views, admin
  search, public routers, feeds, sitemap).
- Scheduler ticks per tenant.
- One host migration adding `tenant_id`, backfilled to `"default"`.
- A multi-tenant e2e path that includes News, and removal of the stale
  "News is left out" notes (CLAUDE.md, billing-tenant spec header,
  running-the-stack skill).

**Out**
- Per-tenant news *settings* and content locales — they stay host-global, as
  pagebuilder's do.
- Turning multi-tenancy on in the demo host by default (`.env.example` keeps
  `SM_MULTI_TENANT=false`).
- Per-tenant isolation of a module's schema in alembic (upstream #333).

## Finding that reshapes the task

CLAUDE.md and the billing e2e header say news' *startup reconcile* breaks strict
isolation. That reconcile was deleted in #29; nothing in `on_startup` touches the
database today. Under strict mode news does not crash — its non-tenant tables are
never filtered — it **silently shares every article across tenants**. That data
leak is what this design fixes; the docs are corrected as part of it.

`ai` has no tables, so it is not a blocker either.

## Approach

Copy pagebuilder's pattern into news, as a news-owned `news/tenancy.py`.

Rejected alternatives:
- **Import `pagebuilder.tenancy`.** Pagebuilder is optional for news (#29), so
  news cannot depend on it.
- **Move the helper into the framework.** That is the right long-term home, but
  it needs a framework release. It goes on the follow-up list instead.

## Design

### Models (`news/models/`)
`MultiTenantMixin` (from `simple_module_db.mixins`) goes on `NewsArticle`,
`NewsArticleRevision`, `NewsArticleRedirect`, `NewsCategory`, `NewsTag` and
`NewsArticleTag`.

The unique keys change as follows:

| Table | Old unique key | New unique key |
|---|---|---|
| news_articles | `ix_news_articles_locale_slug` (locale, slug) | `ix_news_articles_tenant_locale_slug` (tenant_id, locale, slug) |
| news_articles | `ix_news_articles_group_locale` (translation_group, locale) | `ix_news_articles_tenant_group_locale` (tenant_id, translation_group, locale) |
| news_article_redirects | (locale, from_slug) | `ix_news_article_redirects_tenant_locale_from_slug` (tenant_id, locale, from_slug) |
| news_categories | `name` unique, `slug` unique | `uq_news_categories_tenant_name`, `uq_news_categories_tenant_slug` |
| news_tags | `name` unique, `slug` unique | `uq_news_tags_tenant_name`, `uq_news_tags_tenant_slug` |

Child rows (revisions, article_tags) carry `tenant_id` too. It is stamped at
flush, and it lets strict mode filter them directly.

### `news/tenancy.py` (≈ pagebuilder's, trimmed)
- `DEFAULT_TENANT = "default"` and `TENANT_REQUIRED`.
- `detect_mode` / `configure(app)` / `mode_of(app)`. Single mode means no
  `TenantMiddleware`, or a `fixed` tenant. `configure` runs first in
  `on_startup`, and refuses a fixed tenant other than `"default"`.
- `bind_admin`: in single mode it binds `"default"`. In multi mode it binds the
  request's tenant, or returns 403 `tenant_required`.
- `bind_public`: in single mode it binds `"default"`. In multi mode it binds the
  tenant `TenantMiddleware` resolved, or returns a 404 identical to an unknown
  slug.
- `search_tenant()` replaces `integrations/pagebuilder._search_tenant`, so
  there is one helper.

### Router wiring
- **Admin API routers** (`endpoints/api/*`): `Depends(bind_admin)` on the
  parent `api` router in `endpoints/api/__init__.py`, after the auth
  dependency and before `get_db`. Router-level dependencies run before
  endpoint dependencies, so the commit happens inside the tenant scope.
- **Views** (`router`, `admin_router` in `views.py`): `bind_admin`.
- **Public routers** (per-locale, default-locale alias, `_feeds`,
  `_sitemap`): `bind_public` on `public_router(locale)` and on the alias
  router.
- **Guard test** (copied from pagebuilder's `test_tenancy_routes.py`): every
  route under news' prefixes depends on `bind_admin` or `bind_public`.

### Scheduler (`news/scheduler.py`)
The tick splits into three steps, as in pagebuilder:
1. `_due_tenants`: `with all_tenants()`, select the distinct `tenant_id` of
   articles that are due to publish or unpublish (the same predicates as
   `content/_claims.py`).
2. For each tenant, `tenant_context(tid)` with its own session, calling
   `process_due`, then commit.
3. One tenant's failure is logged and the loop continues to the next.

Single-tenant hosts run the same path, because all their rows are
`"default"`.

### Migration (`host/migrations/versions/<rev>_news_tenant_id.py`)
This mirrors `c493630090f0`:
1. Drop the old uniques.
2. Add a nullable `tenant_id` and backfill it with the literal `'default'`.
3. Make it NOT NULL via `batch_alter_table`. No server default is left
   behind.
4. Add `ix_<t>_tenant_id` and the new composite uniques.

Downgrade refuses, before any DDL, if two tenants share an old key.

### Tests
- A news `tenant_fixture.py` (autouse `"default"` binding plus an
  `unbound_tenant` marker) and `tenant_app.py` (`HeaderTenant`,
  `multi_client`, `tenant_strict=True`), both copied from pagebuilder. The
  existing ~49 test files then keep passing unchanged.
- New tests:
  - `test_tenancy_core`
  - `test_tenancy_isolation`: tenant A cannot list, read, edit, publish or
    delete B's article, category or tag. The same slug works in both tenants.
  - `test_tenancy_public`: a public article, feed and sitemap are per tenant,
    and an unknown tenant gets a 404.
  - `test_tenancy_routes`: the guard test.
  - `test_scheduler_tenancy`: due work runs in both tenants, and one failure
    is isolated.
- A host migration test in the style of `test_news_upgrade_from_007.py`:
  rows survive the upgrade as `"default"`.
- E2E: the `billing-tenant` spec's documented command keeps all modules, News
  included. A new `news-tenant.spec.ts` (same opt-in flag) creates an article
  in tenant A and checks tenant B cannot see it. A **new CI job, `E2E
  (multi-tenant)`**, runs both specs with `E2E_MULTI_TENANT=1`, so they are no
  longer skipped in CI. It runs only those two specs, which keeps it to a few
  minutes.

### Docs
- CLAUDE.md: replace the "demo host is single-tenant" deferred item, and
  extend the "Every pagebuilder entry point binds a tenant" rule to news.
- Update the billing-tenant spec header and running-the-stack skill line 50.

## Decisions made (override any at approval)

1. News gets its own `tenancy.py` instead of importing pagebuilder's or
   waiting on the framework.
2. Categories and tags become unique per tenant. Two tenants may both have
   "Sport".
3. The backfill tenant is the literal `"default"`, matching pagebuilder.
4. Settings and locales stay host-global.
5. In multi mode, a public request with no resolved tenant gets a 404. There
   is no fallback to the default tenant.
6. The multi-tenant e2e runs as a separate, small CI job, rather than flipping
   the whole e2e suite to multi-tenant.
7. The demo `.env` default stays single-tenant.

## Risks

- **Process-global caches.** `news.settings` and `news.locales` are
  process-global. If any of them caches *rows* (counts, categories), it would
  leak across tenants. Implementation audits `counts.py` / `authors.py` for
  caching first.
- **Raw SQL or `all_tenants` reads.** The claims use conditional UPDATEs. If
  any of them bypasses ORM criteria, it has to filter on `tenant_id`
  explicitly. The isolation tests cover this.
- **The CI job needs a tenant in the e2e host.** If creating a second
  organisation in the browser is not scriptable through the existing
  bootstrap, the news-tenant spec seeds it via the API. That is a small
  deviation, not a design change.
