# simple_module_pagebuilder

Drag-and-drop visual page builder for [simple_module](https://github.com/antosubash/simple_module_python)
apps. Pages are composed from a reusable block library using
[Puck](https://puckeditor.com) and stored as JSON; published pages are served
at `/p/{slug}`.

## Features

- **Visual editor** — Puck-based drag-and-drop with a block library (heading,
  text, image, button, columns, spacer) and a media picker.
- **Site layout** — a shared header/footer layout, edited the same way, wrapped
  around every public page.
- **Media library** — uploads with magic-byte content sniffing, folder
  organisation, and server-generated WebP thumbnails.
- **Revisions** — every status transition snapshots the page, with a diff view
  and restore-as-draft.
- **Approval workflow** — edit → submit for review → approve / reject, gated by
  three separate permissions.
- **Scheduled publishing** — set `publish_at` / `unpublish_at`; a background
  poller flips status at the due time.
- **SEO** — per-page meta description, canonical URL, OG image, JSON-LD, plus
  `/sitemap.xml` and `/robots.txt`.

## Installation

```bash
uv add simple_module_pagebuilder
```

Then add it to your host's `pyproject.toml` dependencies. The module is
discovered at boot through the `simple_module` entry point — no registration
code required.

Its frontend ships inside the wheel. Pull its JS dependencies into your host's
client app and regenerate the page manifest with:

```bash
smpy host sync-js-deps --host-client-app=host/client_app
smpy host gen-pages --host-dir=host/client_app
```

## Migrations

This module ships **no** migrations — that is the framework convention. Its
SQLModel tables are picked up by your host's `build_module_metadata()`, so
after installing it run:

```bash
make migration msg="add pagebuilder"
make migrate
```

Add `branch_labels = ("pagebuilder",)` to that first generated revision so the
module can later be removed on its own with
`alembic downgrade pagebuilder@base`.

## Permissions

| Permission | Grants |
|---|---|
| `pagebuilder.edit` | Draft, save, submit for review, restore a revision |
| `pagebuilder.publish` | Publish and unpublish directly |
| `pagebuilder.approve` | Approve or reject a submitted page |

`DEFAULT_ROLE_MAP` in `pagebuilder.permissions` suggests three roles —
`pagebuilder_editor`, `pagebuilder_publisher`, `pagebuilder_approver` —
cumulatively mapped to those permissions.

## Settings

All settings use the `SM_PAGEBUILDER_` env prefix.

| Setting | Default | Purpose |
|---|---|---|
| `public_route_prefix` | `/p` | Where published pages are served |
| `requires_auth` | `true` | Gate the admin surface behind authentication |
| `csrf_protect` | `true` | Require a CSRF token on mutating admin requests |
| `media_root` | `var/pagebuilder/media` | Upload storage directory |
| `media_url_prefix` | `/media/pagebuilder` | Public URL prefix for uploads |
| `media_max_bytes` | `10485760` | Per-upload size ceiling |
| `media_thumbnail_widths` | `320,640,1280,1920` | Widths generated as WebP |
| `media_webp_quality` | `82` | WebP encoder quality |
| `public_csp` | see `settings.py` | CSP header on public pages |
| `public_cache_max_age` | `60` | `max-age` on public pages |
| `public_base_url` | `None` | Absolute base for canonical URLs and the sitemap |
| `site_name` | `None` | OpenGraph site name |
| `sitemap_enabled` | `true` | Serve `/sitemap.xml` |
| `robots_enabled` | `true` | Serve `/robots.txt` |
| `scheduler_enabled` | `true` | Run the scheduled publish/unpublish poller |
| `scheduler_interval_seconds` | `30` | Poll interval |

## Routes

**Admin views** (under `/pagebuilder`): `/`, `/new`, `/{page_id}/edit`,
`/pending`, `/layout`, `/media`.

**Admin API** (under `/api/pagebuilder`): pages CRUD, workflow transitions,
revisions and diffs, layout and its revisions, uploads.

**Public**: `/p/{slug}`, `/sitemap.xml`, `/robots.txt`.

## Contracts

DTOs other modules may depend on are exported from `pagebuilder.contracts`.
Everything else in the package is internal and may change without a major
version bump.

## Licence

MIT
