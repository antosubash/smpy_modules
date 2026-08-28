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
- **Content snapshots** — capture the whole site, download or upload it as a
  `.zip`, and restore behind an approval gate. See below.

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

## Usage

Once installed and migrated, sign in and open `/pagebuilder`:

1. **Create a page** — `/pagebuilder/new`. Give it a title; the slug is derived
   from it and stays editable.
2. **Compose it** — drag blocks from the Puck sidebar. Images come from the
   media library, which uploads and thumbnails them for you.
3. **Publish it** — publish directly with `pagebuilder.publish`, or submit for
   review if your role only carries `pagebuilder.edit`. Reviewers work through
   `/pagebuilder/pending`.
4. **Schedule it** — set `publish_at` / `unpublish_at` instead of publishing
   now, and the poller flips the status at the due time.
5. **View it** — the page is live at `/p/{slug}`, wrapped in the site layout
   from `/pagebuilder/layout`.

Every transition writes a revision, so `/pagebuilder/{id}/edit` can compare any
two revisions and restore either one as a draft.

## Contributing blocks from another module

A module ships Puck blocks by calling `registerPuckBlocks` from its
`puck-blocks.ts`; the host imports every module's registration eagerly at app
start, so the registry is populated before the first render.

Because registration is eager, a block that statically imports a heavy render
component puts that component's whole dependency graph in the entry chunk —
on every page of the site, for every visitor. Measured on a consuming site, a
map block's static import put maplibre-gl (1 MB minified, 62% of the bundle)
in front of visitors who never opened the map. Register heavy blocks with
`lazyBlock` instead, which keeps fields and defaults eager but loads the
component the first time a page actually renders the block:

```tsx
import { lazyBlock } from '@simple-module-py/pagebuilder/pagebuilder/components/lazyBlock';
import { registerPuckBlocks } from '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry';

registerPuckBlocks({
  blocks: {
    AtlasMap: lazyBlock(
      () => import('./components/AtlasMap').then((m) => m.AtlasMapEmbed),
      { label: 'Atlas map', fields: { /* … */ }, defaultProps: { /* … */ } },
      (props) => <div className={heightClass[props.height]} aria-busy="true" />,
    ),
  },
});
```

Light blocks (text, cards, lists) can keep their static imports — the split
only pays for itself when the component drags in something big.

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
| `snapshot_root` | `var/pagebuilder/snapshots` | Snapshot + blob storage directory |
| `snapshot_max_upload_bytes` | `209715200` | Ceiling on an uploaded bundle (200 MB) |
| `snapshot_max_extracted_bytes` | `1073741824` | Ceiling on what a bundle may expand to (1 GB) |
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
`/pending`, `/layout`, `/media`, `/trash`, `/content`, `/content/review`.

**Admin API** (under `/api/pagebuilder`): pages CRUD, workflow transitions,
revisions and diffs, layout and its revisions, uploads, snapshots and imports.

**Public**: `/p/{slug}`, `/sitemap.xml`, `/robots.txt`.

## Content snapshots

**Content › Import / Export** captures the site as a restore point. Every entry
in that list is a snapshot; they differ only in where they came from —
`manual` (you took it), `upload` (a bundle from another host), or `pre_restore`
(taken automatically before a restore).

**What a snapshot holds:** every non-trashed page including templates, page
redirects, the site layout, and the media library's files.

**What it deliberately does not hold:**

- *Branding.* `pagebuilder` has no Python dependency on the branding module,
  and capture runs in-process. Bundling three fields would force every
  pagebuilder host to install branding for a feature unrelated to it. Re-pick
  the colour and design pack in Settings → Branding after restoring onto a
  fresh host.
- *Another module's content*, news articles included, for the same reason.
- *Trashed pages, revision history and audit trails.* A snapshot is the site as
  it stands, not its past; restoring history from another host would fabricate
  an audit trail that never happened here.

A restore also does **not** write a `PageRevision` per page, unlike every other
mutation path. The `pre_restore` snapshot already holds the previous state of
every page, once, with media deduplicated by digest — a revision row per page
would duplicate that whole before-state and recover nothing extra. The restore
itself stays audited: who approved it, when, from which snapshot, and the plan
they were shown.

**Restoring is staged, never immediate.** Choosing Restore computes a plan —
what is created, what is overwritten, what is unchanged — and parks it for
approval. Taking a snapshot, uploading and staging need `pagebuilder.publish`;
only `pagebuilder.approve` can apply one. One import is pending at a time,
because a plan computed against content that has since changed no longer
describes what applying would do.

**Restoring is reversible and never deletes.** Applying takes a `pre_restore`
snapshot first, so the previous state is one restore away. A page live on the
site but absent from the bundle is left alone and reported in the plan.

**Portability.** Media URLs embed a host-local filename, so bundled content
stores `asset://<name>` sentinels instead and they resolve to whatever URL each
host assigns. `Page.parent_id` and `PageRedirect.page_id` travel as slugs and
are resolved in a second pass, since a parent may sort after its child and a
redirect may target a page the same restore creates.

## Contracts

DTOs other modules may depend on are exported from `pagebuilder.contracts`.
Everything else in the package is internal and may change without a major
version bump.

## Licence

MIT
