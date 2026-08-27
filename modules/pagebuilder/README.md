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
- **Multilingual content** — a page can exist in several languages, each with
  its own slug, draft and approval state. See below.

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

Stored in the database and edited under **Settings → PageBuilder**. There is
no `SM_PAGEBUILDER_*` environment variable: the settings class drops every env
source, so a value can only come from the store or from the default below.
Headless deployments write them with `scripts/set_setting.py`.

Fields marked ● are read once while the app boots — they decide which routes
are mounted and what the auth layer exempts — so changing one needs a restart.
The Settings screen says so next to the input.

| Setting | Default | Purpose |
|---|---|---|
| `public_route_prefix` ● | `/p` | Where published pages are served |
| `content_locales` ● | `["en"]` | Languages a page may be authored in |
| `default_content_locale` ● | `en` | The language served at the unprefixed URL |
| `requires_auth` | `true` | Gate the admin surface behind authentication |
| `csrf_protect` | `true` | Require a CSRF token on mutating admin requests |
| `media_root` ● | `var/pagebuilder/media` | Upload storage directory |
| `media_url_prefix` ● | `/media/pagebuilder` | Public URL prefix for uploads |
| `media_max_bytes` | `10485760` | Per-upload size ceiling |
| `media_thumbnail_widths` | `320,640,1280,1920` | Widths generated as WebP |
| `media_webp_quality` | `82` | WebP encoder quality |
| `public_csp` | see `settings.py` | CSP header on public pages |
| `public_cache_max_age` | `60` | `max-age` on public pages |
| `public_base_url` | `None` | Absolute base for canonical URLs and the sitemap |
| `site_name` | `None` | OpenGraph site name |
| `sitemap_enabled` ● | `true` | Serve `/sitemap.xml` |
| `robots_enabled` ● | `true` | Serve `/robots.txt` |
| `scheduler_enabled` ● | `true` | Run the scheduled publish/unpublish poller |
| `scheduler_interval_seconds` ● | `30` | Poll interval |

## Routes

**Admin views** (under `/pagebuilder`): `/`, `/new`, `/{page_id}/edit`,
`/pending`, `/layout`, `/media`.

**Admin API** (under `/api/pagebuilder`): pages CRUD, workflow transitions,
revisions and diffs, layout and its revisions, uploads.

**Public**: `/p/{slug}`, `/{locale}/p/{slug}` (one mount per non-default
content locale), `/sitemap.xml`, `/robots.txt`.

## Multilingual content

Off by default: with one content locale nothing changes, no locale-prefixed
route is mounted, and every existing URL is exactly what it was.

```bash
python scripts/set_setting.py pagebuilder \
  content_locales '["en","de","fr"]' default_content_locale en
```

Or on the Settings screen, which is the same store. Either way it takes effect
at the next boot: the languages decide how many public routers are mounted.

These are *content* languages, deliberately separate from the host's
`SM_I18N_SUPPORTED_LOCALES`, which decides what language the admin console
speaks. A site can translate its content without translating its console, or
the reverse.

**A translation is an ordinary page.** It has its own row, slug, draft,
revisions, schedule and approval state; what makes two pages translations of
each other is a shared `translation_group`. Publishing one never publishes
another, and there is no "master" — deleting the English page leaves the German
one intact.

**Addresses.** The default locale keeps the bare prefix (`/p/about`) so adding
a language strands no link that already exists; every other locale is prefixed
(`/de/p/about`). `/{default}/p/{slug}` permanently redirects to the bare form,
so one document never answers at two URLs. Slugs are unique *per language*, so
`/p/about` and `/de/p/about` can both be "about".

**Discovery.** A published page emits `hreflang` links for every published
counterpart plus `x-default`, and the sitemap lists each language at its own
address with `xhtml:link` alternates — so a crawler finds a translation nothing
links to yet.

**Authoring.** Two ways in, because "we need this in German" is a thought an
author has while scanning the page list as often as while editing the page:

* the page list's **Translate** row action duplicates the page into a language
  it does not have yet — it asks the server which languages are still free
  (the list is paged, so a counterpart may be on a page the browser has not
  loaded), offers a *Copy this page's content* choice, and opens the editor on
  the result;
* the editor's **Languages** tab lists the site's locales, shows which ones the
  page exists in and where each serves, and starts the ones it does not.

Both call `POST /api/pagebuilder/pages/{id}/translations`. A new translation inherits
the layout, nav membership and the source's title (untranslated, so what still
needs doing is obvious), starts as a draft, and never inherits `canonical_url`.
Its breadcrumb parent is the parent's own counterpart, so a trail never crosses
languages. A page's own language is fixed for its lifetime — moving one would
strand its slug and orphan the redirect pointing at it.

## Contracts

DTOs other modules may depend on are exported from `pagebuilder.contracts`.
Everything else in the package is internal and may change without a major
version bump.

## Licence

MIT
