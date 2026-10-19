# News operations

## Install

1. Add the package to the host (exact framework pin in the host, ranges in
   modules):

   ```toml
   dependencies = ["simple_module_news"]
   ```

   It needs `simple_module_core`, `_db`, `_hosting`, `_inertia` and
   `_settings` (`>=0.0.35,<0.1`), which it pulls in itself. Nothing else is
   required.

2. Migrations live in the host. Autogenerate after installing, read the
   revision, then apply:

   ```bash
   make migration msg="news"
   make migrate          # alembic upgrade heads
   ```

   News creates `news_articles`, `news_article_revisions`,
   `news_article_redirects`, `news_categories`, `news_tags` and
   `news_article_tags`. A `branch_labels = ("news",)` on its first revision
   names it, but does **not** make `alembic downgrade news@base` remove news
   alone: autogenerate chains every revision onto one history, so that walks
   everything beneath it.

3. Grant permissions. `news.view`, `news.edit` and `news.publish` are
   registered in a **News** group; give authors `news.view` + `news.edit` and
   editors who may publish `news.publish` as well.

4. Start the app. On startup news detects the tenancy mode, settles its
   content languages, mounts the public routes under `public_route_prefix`
   (one mount per language), exempts them from login, and starts the
   scheduler if `scheduler_enabled` is on.

### Optional: the `pagebuilder` extra

```bash
pip install "simple_module_news[pagebuilder]"
```

This pulls in `simple_module_pagebuilder>=0.0.8,<0.1`. Where both modules run:

- the **News feed (live articles)** block joins pagebuilder's palette (group
  **Feeds**), with **Heading**, **Category filter (blank = all)**, **How
  many**, **Columns (desktop)**, **View-all link label** and **View-all link
  URL**. It lists published, in-feed articles in the language of the page it
  sits on;
- **Search everything** gains **Pages** and **Media** sections;
- the site's article languages become pagebuilder's `content_locales` (see
  below).

The `>=0.0.8` floor exists because the feed block's labels are i18n keys that
pagebuilder's own `localizeConfig` resolves, added in 0.0.8. On an older
pagebuilder nothing crashes, but every label in the block's palette entry
shows as a raw dotted key. The range stays `0.0.x` because the repo publishes
at `0.0.x`.

Without the extra, news never imports pagebuilder (every import sits behind
`news/integrations/pagebuilder.py` and is deferred), the extra search sections
are simply absent, and articles publish in one language. **Frontend:** the feed block's registration lives in
`news/pagebuilder-blocks.ts` (with `components/NewsFeed.tsx`), the only files
that import `@simple-module-py/pagebuilder` (a declared *optional* peer
dependency). The host's block glob matches `puck-blocks.ts`, which news does
not ship; pagebuilder's own `puck-blocks.ts` globs every sibling's
`pagebuilder-blocks.ts`. On a host without pagebuilder nothing imports those
files, so news builds with no exclusion to configure. The registration needs a
pagebuilder that ships that glob (the release after 0.0.11); on an older one
the page editor simply has no news feed block.

## Settings

Stored in the database: edit them on the Settings screen, or headlessly with
`scripts/set_setting.py news <field> <value>` from the repo root. News reads
**no** environment variables — the settings class drops every env, `.env` and
secrets source, so an `SM_NEWS_*` line does nothing.

| Field | Default | Notes |
|---|---|---|
| `public_route_prefix` | `/news` | Where articles serve. **Restart required.** |
| `public_base_url` | — | Origin for canonical URLs, `og:url`, the feed and the sitemap. Blank derives it from the request — set it behind a proxy that rewrites `Host`. Leave blank on a multi-tenant host (startup warns otherwise). |
| `site_name` | — | `og:site_name`, and the archive heading / feed title (falls back to "News"). |
| `twitter_handle` | — | `twitter:site`. |
| `public_cache_max_age` | `300` | Seconds an article may sit in a shared cache. Archive pages use the smaller of this and 60. |
| `public_cache_swr` | `60` | `stale-while-revalidate` on articles; `0` omits it. |
| `public_csp` | — | `Content-Security-Policy` on the article page; blank sends none. |
| `scheduler_enabled` | `true` | Run the in-process publish/unpublish loop. **Restart required.** |
| `scheduler_interval_seconds` | `30` | How often it looks for due articles. **Restart required.** |

Fields marked restart-required are read once in `on_startup` and the Settings
screen says so; the rest apply on save.

```bash
python scripts/set_setting.py news public_route_prefix /blog
python scripts/set_setting.py news scheduler_enabled false
```

### Content languages

The languages articles can be written in are **not** a news setting. With
pagebuilder installed they are its `content_locales` / `default_content_locale`
(so pages and articles share one list):

```bash
python scripts/set_setting.py pagebuilder content_locales '["en","de"]'
```

Without pagebuilder the site is monolingual (`en`). The default language
serves at `/news/…`; every other at `/{locale}/news/…`; `/{default}/news/x`
301s to `/news/x`. Read at startup, so a change needs a restart. Narrowing the
list later leaves existing articles in the removed language unreachable (no
route is mounted) and out of the sitemap; nothing deletes them.

## The scheduler

An in-process loop wakes every `scheduler_interval_seconds`, finds tenants
with work, and per tenant publishes drafts whose **Go live** (`publish_at`)
has passed and unpublishes articles whose **Come down** (`unpublish_at`) has
passed. A process that was down catches up on the next tick; a draft whose
whole window passed while nothing ran is left a draft with both times
cleared (logged as `news.scheduler.window_missed`).

It is safe with several workers or replicas: each due article is claimed with
one conditional `UPDATE` before it is flipped, so exactly one process acts.
Every replica still polls, and each uses its own clock. To poll from one place
instead, set `scheduler_enabled` to `false` everywhere and call
`ArticlesService(session).process_due(now)` per tenant from a cron job or
worker (inside `tenant_context`, then commit).

Log lines: `news.scheduler.flipped`, `news.scheduler.publish_failed` /
`unpublish_failed` (one article skipped, retried next tick),
`news.scheduler.tenant_failed`, `news.scheduler.tick_failed`.

## Multi-tenant hosts

Every news table carries `tenant_id`, and news binds a tenant at each entry
point rather than relying on one being set:

- **Single-tenant host** (no `TenantMiddleware`, or one fixed to `default`):
  everything runs in tenant `default`. A host fixed to any *other* default
  tenant is refused at startup — existing rows are filed under `default`.
- **Multi-tenant host**: each request runs in the tenant the framework
  resolved (subdomain for visitors, membership for members). An admin or API
  request with none gets **403 `tenant_required`**; a public request with none
  gets the same 404 as an unknown article. The scheduler ticks each tenant in
  its own transaction.

The mode is read from the built middleware stack, so changing `multi_tenant`
needs a restart; startup warns if the setting is on but the middleware is not.
Slugs, categories, tags and redirects are unique per tenant.

## Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| `/news/{slug}` is 404 for an article you can see in the list | it is a draft, pending review or trashed; or it is in another language (`/de/news/…`) | Publish it; check its language badge. |
| Article is live at its URL but missing from `/news/`, RSS and feed blocks | **Show in feed blocks** is off | Turn it on in the article screen. |
| Article is missing from the sitemap | **Allow search engines to index it** is off, or its language was removed from `content_locales` | Check the Search & sharing card / the locales setting. |
| Scheduled article did not go live | `scheduler_enabled` off; time not reached plus one interval; it was sent back, unpublished or published by hand (cancels **Go live**); both times passed while no scheduler ran | Check the setting and the `news.scheduler.*` logs. |
| Changed `public_route_prefix` but URLs did not move | restart-required field | Restart the app. |
| `SM_NEWS_…` in the environment has no effect | news reads no env vars | Use the Settings screen or `scripts/set_setting.py news …`. |
| Every admin request returns 403 `tenant_required` | multi-tenant host, request resolved no tenant | Select an organisation / use its subdomain. |
| Startup fails: "the host pins every request to default_tenant=…" | host's fixed default tenant is not `default` | Unset it, set it to `default`, or turn `multi_tenant` on. |
| Canonical / feed links point at the wrong host | `public_base_url` unset behind a proxy, or set on a multi-tenant host | Set it (single-tenant) or clear it (multi-tenant). |
| Author cannot publish; Publish answers 403 | they hold `news.edit` only | Grant `news.publish`, or have them **Submit for review**. |
| "Slug already in use" for a URL nobody seems to use | a trashed article still claims it | Restore and rename it, or **Delete for good** from Trash. |
| "This article already has a de translation (check the trash)" | a draft or trashed sibling in that language exists | Open it from **Languages**, or purge it. |
| Saving says "This article was changed somewhere else" | another tab or person saved first | Reload and redo the change. |
| News feed block labels show as `news.feed.…` keys | pagebuilder older than 0.0.8 | Upgrade pagebuilder. |
| Frontend build fails resolving `@simple-module-py/pagebuilder` | a hand-written import of news' `pagebuilder-blocks.ts` on a host without pagebuilder | Do not import it; pagebuilder's `puck-blocks.ts` loads it only when pagebuilder is installed. |
| Search everything shows no Pages / Media | pagebuilder not installed | Expected. |

## Data and deletion

**Move to trash** is a soft delete (`deleted_at`); the URL stays claimed and
**Restore** brings the article back as it was. **Delete for good** (purge)
and **Delete** remove the row together with its revisions, redirects and tag
links.
Trash is never emptied automatically. Deleting a category moves its articles,
it never deletes them.
