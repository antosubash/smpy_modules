# News architecture

Design records (repo root): `docs/superpowers/specs/2026-08-05-news-module-release-design.md`
and `docs/superpowers/specs/2026-10-08-news-multitenancy-design.md`. This page
describes the code as it is.

## Boundaries

News depends on the framework only (`core`, `db`, `hosting`, `inertia`,
`settings`). It once stored an article as a pagebuilder page plus a sidecar
row; it now owns the whole document, and pagebuilder is an optional
neighbour reached through exactly two files:

| Seam | Used for |
|---|---|
| `integrations/pagebuilder.py` | `available()`; Pages and Media search sections; "see all" links into `/pagebuilder/…` |
| `integrations/locales.py` | borrowing pagebuilder's `content_locales` / `default_content_locale` |
| `pagebuilder-blocks.ts` + `components/NewsFeed.tsx` (frontend) | registering the **News feed** block in pagebuilder's palette |

Every Python import of `pagebuilder` is deferred into a function and guarded,
so importing news (or its migrations) never imports it — `test_module.py`
checks this in a subprocess. `ModuleMeta.depends_on` lists only the
`Settings` module.

## Data

| Table | Key | Holds |
|---|---|---|
| `news_articles` | `id`; unique `(tenant_id, locale, slug)`; unique `(tenant_id, translation_group, locale)` | headline, slug, `locale`, `translation_group`, `draft_data`, `published_data`, `status`, SEO (`meta_description`, `og_image`, `canonical_url`, `index_in_search`, `json_ld`), `rejection_note`, `deleted_at`, `category`, `pinned`, `show_in_feed`, `author`, `published_at`, `publish_at`, `unpublish_at` |
| `news_article_revisions` | `id`, FK `article_id` | one row per status transition: `event`, `note`, title, summary, image, `data` |
| `news_article_redirects` | unique `(tenant_id, locale, from_slug)`, FK `article_id` | old slugs that 301 to the current one |
| `news_categories` | unique `(tenant_id, name)`, `(tenant_id, slug)` | display order (`position`) and URL slug for a category *name* |
| `news_tags` / `news_article_tags` | unique name/slug per tenant; composite PK | tags and their links |

Every table uses `MultiTenantMixin`. Notable choices:

- **`category` is a string on the article**, not a foreign key.
  `news_categories` only adds ordering and a slug to a name articles already
  carry, so renaming a category is a bulk update, deleting one reassigns its
  articles, and a category typed but never formalised still lists.
- **`author` is free text**, not a user reference: a byline outlives the
  account. Author archives are resolved by slugging stored bylines
  (`authors.py`); there is no author table.
- **`translation_group`** is a generated uuid hex, not a pointer to an
  "original": translations are siblings, so deleting one orphans none.
- **`locale` is fixed** for an article's lifetime; there is no update path for
  it, because slugs and redirects are scoped per locale.

## Draft and published

`draft_data` is what the canvas edits and autosaves. `publish`/`approve` copy
it into `published_data`, the only body the public viewer serves.
`unpublish` keeps `published_data` (the last thing readers saw). An article
is *live* when `status = published` and `published_data` is not null;
`has_unpublished_changes` is live and `draft_data != published_data`,
compared rather than inferred from a timestamp. The preview renders
`draft_data` through the same `PublicArticle` screen as the viewer
(`endpoints/public/_render.py`).

Concurrent edits: every write carrying `expected_updated_at` is refused with
409 if it differs (`content/_fresh.ensure_fresh`), and status transitions use
a compare-and-set on the status (`claim_status`) so two reviewers cannot both
approve.

## Workflow (`content/_workflow.py`)

| Action | From | To | Revision | Also |
|---|---|---|---|---|
| `submit_for_review` | `draft` | `submitted_for_review` | `submit` | — |
| `approve` | `submitted_for_review` | `published` | `approve` | snapshot; clears `publish_at` and an elapsed `unpublish_at` |
| `reject` | `submitted_for_review` | `draft` | `reject` (note) | sets `rejection_note`; clears `publish_at` |
| `publish` | any | `published` | `publish` | snapshot; no-op if already live, identical and nothing scheduled |
| `unpublish` | `published` | `draft` | `unpublish` | clears both schedule times |
| `trash` / `restore` | — | unchanged | none | `deleted_at`; restore clears elapsed schedule times |
| `purge` | trashed only (endpoint) | deleted | — | removes redirects, revisions, tag links |

`rejection_note` is cleared on every other transition. Revisions are the
audit log; `restore_revision` copies one back into the draft and never
publishes. `NOT_TRASHED` (`deleted_at IS NULL`) is applied by every read
except the trash listing.

## Permissions and visibility

`news.publish` is separate from `news.edit` so a host can enforce review;
every publish-class route requires both. Listing reads are registered as
anonymous public routes (`PUBLIC_READ_PREFIXES`, GET only), and
`endpoints/api/_deps.may_see_drafts` is the single rule for whether a caller
sees drafts — it reads the resolved permission set (wildcard or `news.edit`).
The taxonomy and search routes sit under `/taxonomy` and `/search` precisely
so they are *not* under the anonymous prefixes.

## Scheduling (`scheduler.py`, `content/_claims.py`)

The loop runs per process. Each tick reads the distinct tenants with due
work under `all_tenants()`, then per tenant opens a session under
`tenant_context` and calls `ArticlesService.process_due(now)`, always
committing. `process_due` first retires missed windows (both times past →
both cleared, still a draft), then for each candidate **claims** it with one
conditional `UPDATE … SET publish_at = NULL WHERE id = :id AND status = …
AND publish_at <= :now` and acts only if a row was updated. Row claims work
on SQLite and Postgres alike and need no lease table; a crash mid-flip rolls
the claim back. A failed flip releases the claim and logs a warning.

## Tenancy (`tenancy.py`)

`configure(app)` (in `on_startup`) detects `SINGLE` or `MULTI` from the built
middleware stack and refuses a fixed default tenant other than `"default"`.
Router dependencies bind the tenant before `get_db`, so the commit happens
while it is bound:

- `bind_admin` — every API and admin view router. SINGLE → `default`; MULTI →
  the resolved tenant, else **403 `tenant_required`**.
- `bind_public` — every public router. SINGLE → `default`; MULTI → the
  resolved tenant, else 404 with the same message as an unknown slug.
- `search_tenant()` — cross-module reads of pagebuilder's tables pin
  `tenant_id` explicitly, falling back to `default`.

Public responses add `Vary: Cookie` (plus the tenant header) in MULTI mode
via `vary_on_tenant`, since the same URL can serve different tenants.

## Public surface (`endpoints/public/`)

`boot.mount_public_routers` mounts one router per content locale at
`{locale prefix}{public_route_prefix}`; `boot.exempt_public_routes` exempts
each from auth (prefix with trailing slash, plus the bare path exactly).
Inside one router, fixed paths (`feed.xml`, `sitemap.xml`, `/`,
`/category/…`, `/tag/…`, `/author/…`) are registered before the `/{slug}`
catch-all — the order is load-bearing. The sitemap hangs off the default
locale only and lists every language. `_head.py` writes title, meta, OG,
Twitter, canonical, `hreflang`, `robots` and JSON-LD into the server-rendered
shell, and `_lang.py` rewrites `<html lang>`, because the host has no SSR.
The article body itself is rendered client-side.

## Settings

`NewsSettings` keeps only init kwargs as a source (no env, `.env` or
secrets) and is registered with `register_module_settings` under the package
`news`. Boot-time fields (`public_route_prefix`, `scheduler_enabled`,
`scheduler_interval_seconds`) carry `requires_restart` and are read from
`app.state.news.settings` in `on_startup`, after hydration. Per-request code
reads the process-global `settings.active()`, republished on
`SettingsReloaded`. Content languages live in `news.locales`, published once
at startup from pagebuilder's hydrated settings or falling back to `en`.

## Console i18n

Strings live in `news/locales/en.json` under the `news` namespace
(`locale_dirs()`). The frontend derives its key tree from that JSON
(`utils/i18n.ts`) so `tsc` rejects an unknown key. Puck block labels hold
keys resolved at render (`components/body/localizeConfig.ts`); the feed
block's are resolved by pagebuilder's own `localizeConfig`, hence the
`>=0.0.8` floor on the extra.

## File map

| File | Responsibility |
|---|---|
| `module.py`, `boot.py` | framework hooks; startup mounting and auth exemptions |
| `settings.py`, `locales.py` | DB-backed settings, URL builders; content languages |
| `tenancy.py` | mode detection and tenant binding |
| `models/` | tables |
| `content/` | `ArticlesService`: create/update, slugs, workflow, trash, revisions, claims |
| `service.py`, `query_filters.py`, `card.py`, `counts.py` | listing reads and the `ArticleRead` shape |
| `category_service.py`, `tag_service.py`, `authors.py`, `redirects.py` | taxonomy, bylines, old slugs |
| `search_service.py` | admin search |
| `scheduler.py` | the polling loop |
| `integrations/` | the only pagebuilder seam |
| `endpoints/api/`, `endpoints/views.py`, `endpoints/public/` | JSON API, admin screens, reader routes |
| `pages/`, `components/`, `hooks/`, `utils/` | React screens (only real Inertia pages under `pages/`) |
| `pagebuilder-blocks.ts` | News feed block registration (needs pagebuilder; loaded only by pagebuilder's `puck-blocks.ts`) |
