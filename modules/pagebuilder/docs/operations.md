# PageBuilder operations

## Install

1. Add the package to the host (exact framework pin in the host, ranges in
   modules):

   ```bash
   uv add simple_module_pagebuilder
   ```

   The module is discovered through the `simple_module` entry point. It depends
   on the framework's **Settings** module, which must be installed too.

2. Pull its frontend into the host's client app and regenerate the page
   manifest:

   ```bash
   smpy host sync-js-deps --host-client-app=host/client_app
   smpy host gen-pages --host-dir=host/client_app
   ```

3. Migrations live in the host; the module ships none. Autogenerate, read the
   revision, then apply:

   ```bash
   make migration msg="add pagebuilder"
   make migrate
   ```

   Give the first pagebuilder revision `branch_labels = ("pagebuilder",)` so it
   can be named. **That does not make it removable on its own:** autogenerate
   chains every revision off the current head, so `alembic downgrade
   pagebuilder@base` walks every revision beneath it, other modules' included.

4. Start the app. On startup pagebuilder checks the tenancy mode, exempts its
   public paths from authentication, mounts one public router per content
   language plus `/sitemap.xml` and `/robots.txt`, mounts the media directory,
   and starts the scheduler. It logs `pagebuilder.media_root: <path>`.

Grant the permissions `pagebuilder.edit`, `pagebuilder.publish` and
`pagebuilder.approve`, or the suggested roles `pagebuilder_editor`,
`pagebuilder_publisher` and `pagebuilder_approver`.

## Settings

Stored in the database and edited on the **Settings** screen (PageBuilder), or
headless with:

```bash
python scripts/set_setting.py pagebuilder <field> <value> [<field> <value> …]
```

Pagebuilder reads **no** environment variables. The settings class drops every
env, `.env` and secrets source, so an `SM_PAGEBUILDER_*` line does nothing. A
value comes from the store or from the default below, and is validated at boot.

Fields marked ● are read once, in `on_startup`, because they decide which routes
are mounted and what is exempt from login. Changing one needs a restart, and the
Settings screen says so. Everything else is read per request and applies on save.

| Field | Default | Notes |
|---|---|---|
| `public_route_prefix` ● | `/p` | Pages serve at `{prefix}/{slug}` |
| `content_locales` ● | `["en"]` | Languages a page may be written in; JSON array |
| `default_content_locale` ● | `en` | Served unprefixed; must be in `content_locales` or boot fails |
| `requires_auth` | `true` | Require a signed-in user on `/pagebuilder/*` and `/api/pagebuilder/*`. Turn off only behind an authenticating proxy. |
| `csrf_protect` | `true` | Require the framework's `X-CSRF-Token` on mutating admin requests |
| `media_root` ● | `var/pagebuilder/media` | Relative paths anchor to the project root (`SM_PROJECT_ROOT`, else the nearest dir with `pyproject.toml`, `.env` or `alembic.ini`), never the cwd |
| `media_url_prefix` ● | `/media/pagebuilder` | Where media is served |
| `media_max_bytes` | `10485760` | 10 MB per upload |
| `media_allowed_content_types` | jpeg, png, gif, webp | SVG is excluded on purpose (stored XSS); add it only with your own sanitiser |
| `media_thumbnail_widths` | `320, 640, 1280, 1920` | WebP widths; empty disables thumbnails |
| `media_webp_quality` | `82` | 0–100 |
| `snapshot_root` | `var/pagebuilder/snapshots` | Snapshots and their shared blob store; anchored like `media_root` |
| `snapshot_max_upload_bytes` | `209715200` | 200 MB per uploaded bundle |
| `snapshot_max_extracted_bytes` | `1073741824` | 1 GB expanded; guards against zip bombs |
| `public_csp` | see below | `Content-Security-Policy` on public pages; empty disables |
| `public_cache_max_age` | `60` | `max-age` on public pages |
| `public_cache_swr` | `600` | `stale-while-revalidate`; `0` omits it |
| `public_base_url` | — | e.g. `https://example.com`, no trailing slash. Base for canonical, `og:url`, `hreflang` and the sitemap. **Set it behind a proxy.** |
| `site_name` | — | `og:site_name` |
| `twitter_handle` | — | `twitter:site`, with the `@` |
| `sitemap_enabled` ● | `true` | Serve `/sitemap.xml`; turn off when the host aggregates its own |
| `robots_enabled` ● | `true` | Serve `/robots.txt` |
| `robots_body` | — | Replaces the default `User-agent: *` / `Allow: /` / `Sitemap:` body, e.g. to lock out crawlers on staging |
| `seo_cache_max_age` | `300` | `max-age` on the sitemap and robots.txt |
| `scheduler_enabled` ● | `true` | In-process scheduler; safe in every process (each page is claimed before it flips), turn off if you'd rather an external worker called `PagesService.process_due` |
| `scheduler_interval_seconds` ● | `30` | Tick interval |

Default `public_csp`:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' https: data:; font-src 'self' data:; connect-src 'self';
frame-ancestors 'none'; base-uri 'self'; form-action 'self'
```

Widen it for analytics, web fonts, embedded videos (`frame-src`) or iframes.

## Adding languages

```bash
python scripts/set_setting.py pagebuilder \
  content_locales '["en","de","fr"]' default_content_locale en
```

Then restart. With one language nothing changes: no prefixed route is mounted
and every address stays as it was. With several, `/de/p/…` and `/fr/p/…` are
mounted and exempted from login, and `/en/p/x` 301s to `/p/x`. These are
*content* languages, separate from the host's `SM_I18N_SUPPORTED_LOCALES`
(what language the admin console speaks).

Removing a language does not delete its pages: they stay in the database and
the admin list, but nothing serves them until the language is added back.

## Tenancy

Every pagebuilder table is tenant-owned. Slugs, redirects, media filenames and
the one-pending-import rule are unique per tenant, and each tenant has its own
layout, media directory (`<media_root>/<tenant>/`) and snapshot blob store.

- **Single-tenant** (no `TenantMiddleware`, or one fixed to `default`) —
  everything runs in tenant `"default"`, which is where the tenancy migration
  filed pre-existing rows. A host whose `default_tenant` is anything else is
  **refused at startup**.
- **Multi-tenant** (`SM_MULTI_TENANT=true`) — the tenant the framework resolved:
  subdomain for visitors (with the `tenants` module, `subdomain_base`), the
  membership for members. A public page, sitemap or media request with no
  tenant answers 404, identical to an unknown slug; an admin request with none
  gets 403 `tenant_required`. Public responses add `Vary: Cookie` (and the
  tenant header, if configured), because the same URL can serve different
  tenants. Custom domains are not supported.

The mode is read off the built middleware stack: changing `multi_tenant` needs
a restart, and a warning is logged if the setting is on but the stack has no
`TenantMiddleware`.

## Public pages: caching and CSP

A published page response carries:

| Header | Value |
|---|---|
| `ETag` | weak, from the page's id and `updated_at`, the layout's `updated_at`, the representation (HTML or Inertia JSON) and the nav list. An `If-None-Match` hit is a 304. |
| `Cache-Control` | `public, max-age=<public_cache_max_age>, stale-while-revalidate=<public_cache_swr>` |
| `Vary` | `X-Inertia`, plus the tenant headers on a multi-tenant host |
| `Content-Language` | the page's locale |
| `Content-Security-Policy` | `public_csp`, unless empty |

Because the nav list is in the ETag, publishing or renaming a page flagged for
the header changes every other page's tag too. Media is served
`public, max-age=31536000, immutable` (names are random per upload) and a
missing file is a plain-text 404, never the app shell.

## The scheduler

An in-process loop, every `scheduler_interval_seconds`: it finds the tenants with
work and, for each in its own session and tenant context, publishes drafts whose
`publish_at` has passed, unpublishes pages whose `unpublish_at` has passed, and
purges trashed pages older than 30 days. A failing tenant is logged
(`pagebuilder.scheduler.tenant_failed`) and the others continue. A missed tick
catches up on the next.

Running it in several processes (`uvicorn -w N`, `replicas > 1`, or alongside
an external job calling `process_due`) is safe: each due page is *claimed* with
one conditional `UPDATE` that clears the timestamp it acts on, so whichever
process runs second matches nothing and a page flips exactly once. A process
that dies mid-tick rolls its claims back with its transaction, and the page is
due again on the next tick anywhere. A page that cannot be flipped (it was
purged in between) has its claim handed back for a later tick and is logged as
`pagebuilder.scheduler.publish_failed` / `unpublish_failed` with its id.

A draft whose `publish_at` *and* `unpublish_at` both passed while no scheduler
was running is not published and taken down again: both times are cleared, the
page stays a draft, and `pagebuilder.scheduler.window_missed` is logged.
Publishing, approving or rejecting a page by hand likewise clears an
`unpublish_at` that has already passed, so it does not take the page straight
back down on the next tick; a future one is kept.

## Storage

| Path | Holds |
|---|---|
| `<media_root>/<tenant>/` | uploads and their WebP variants |
| `<snapshot_root>/snapshots/<id>/` | one directory per snapshot (pages, layout, redirects, media index) |
| `<snapshot_root>/blobs/<tenant>/` | media bytes shared across snapshots, by SHA-256 |

Files written before per-tenant storage are moved into the `default` tenant's
directory at startup, and their old flat URLs are still recognised as the same
asset. At startup the module also warns if media rows point at files missing
from disk. Back up both directories with the database: a restore of one without
the other leaves pages pointing at missing images.

## Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| `/p/{slug}` 404 | not published, trashed, or wrong language prefix | Page status and language; a German page is at `/de/p/…`. |
| `/p/{slug}` redirects to login | public routes not exempted | Check startup ran (`pagebuilder.media_root` logged); `public_route_prefix` changed without a restart |
| `/de/p/…` 404 although the page is published | `de` not in `content_locales`, or not restarted since adding it | Set it and restart |
| Boot fails: `default_content_locale … is not in content_locales` | inconsistent settings | Fix with `scripts/set_setting.py` |
| Boot fails: `pins every request to default_tenant=…` | host fixed to another tenant | Unset `default_tenant`, set it to `default`, or turn multi-tenancy on |
| Admin API 403 `tenant_required` | multi-tenant host, no organisation selected | Select an organisation / use its subdomain |
| Every POST 403 `CSRF token missing or invalid` | client not sending `X-CSRF-Token`, or the session changed | Reload the screen; scripted clients read the token from the `csrf_token` prop of any pagebuilder screen |
| Images 404 on public pages | `media_root` differs between processes, or files not deployed | Compare the logged `pagebuilder.media_root`; set an absolute path or `SM_PROJECT_ROOT` |
| Upload 415 | type not allowed, or contents don't match the declared type | Re-export the image; add the type to `media_allowed_content_types` |
| Canonical or sitemap URLs show an internal host | proxy rewrites `Host` | Set `public_base_url` |
| Scheduled page did not publish | scheduler off, page not a draft, page in trash, or its unpublish time had also passed | `scheduler_enabled`; the page's status; a `window_missed` / `publish_failed` log line; publish manually |
| Embedded video or font blocked on public pages | `public_csp` | Widen it on the Settings screen (applies on save) |
| Snapshot upload 413 / 422 | over a size cap, or not a valid bundle | Raise `snapshot_max_upload_bytes` / `snapshot_max_extracted_bytes`; the 422 message names the problem |
| **Restore…** refused: "An import is already awaiting approval" | one staged restore at a time | Approve or reject the pending one at `/pagebuilder/content/review` |
| Header nav lists a page twice | layout link and page address differ | The layout's link must match the page's address (`/p/about`, `/de/p/about`) |
