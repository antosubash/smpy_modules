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
| `snapshot_root` | `var/pagebuilder/snapshots` | Snapshot + blob storage directory |
| `snapshot_max_upload_bytes` | `209715200` | Ceiling on an uploaded bundle (200 MB) |
| `snapshot_max_extracted_bytes` | `1073741824` | Ceiling on what a bundle may expand to (1 GB) |
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
`/pending`, `/layout`, `/media`, `/trash`, `/content`, `/content/review`.

**Admin API** (under `/api/pagebuilder`): pages CRUD, workflow transitions,
revisions and diffs, layout and its revisions, uploads, snapshots and imports.

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

## The editor's language

Separate from the page's. The section above is about what the *site*
publishes; this is about what the *editor* speaks, and the two are configured
in different places — `content_locales` for one, the host's
`SM_I18N_SUPPORTED_LOCALES` for the other.

Every editor string lives in `pagebuilder/locales/en.json`, registered by
`PagebuilderModule.locale_dirs()` under the `pagebuilder` namespace, so a key
reads `pagebuilder.<section>.<name>` in the merged catalogue the host ships to
the browser. Add a language by adding `pagebuilder/locales/<tag>.json` with the
same shape; the framework's `SM013`–`SM016` diagnostics report a file that has
drifted from the default.

The frontend derives its key tree from that JSON at compile time —
`pagebuilder/utils/i18n.ts` — rather than from the framework's generated
`keys`, which only carries the namespaces of modules that live in the
framework's own monorepo. The upshot is that `tsc` rejects a key the catalogue
does not define, and `pagebuilder/utils/i18n.test.ts` rejects an entry nothing
references, a plural missing a form, and a placeholder nothing fills.

**Block labels are keys, resolved at the screen.** A Puck config is a
module-scope constant — the palette is assembled before the app has rendered
anything — so a block cannot call a hook where its labels are written. What it
holds instead is the key, and `components/localizeConfig.ts` resolves the whole
assembled config once inside `PageEditor` and `LayoutEditor`: component labels,
field labels (including the ones nested in an `array` or `object` field),
select options, category titles and the viewport switcher. Because it walks the
*assembled* config, a block another module registered is localized on the same
pass, provided that module's labels are catalogue keys too.

`defaultProps` stay literal on purpose. They are the seed *content* a block is
inserted with and are then saved into the document, so translating them at
render time would rewrite what a visitor is served in whatever language the
author happened to be working in.

## Multi-tenancy

Every pagebuilder table is tenant-owned (the framework's `MultiTenantMixin`),
so one host can run several sites. Slugs, redirects, media filenames and the
one-pending-import rule are unique **per tenant**, and each tenant has its own
site layout, media directory (`<media_root>/<tenant>/`) and snapshot blob store.

Which tenant a request acts for depends on the host:

- **Single-tenant** (`multi_tenant` off) — everything is tenant `"default"`,
  where the migration also files every row that predates tenancy. A host that
  pins `default_tenant` to anything else is refused at startup.
- **Multi-tenant** (`multi_tenant` on) — the tenant the framework resolved.
  With the `tenants` module, anonymous visitors are resolved by subdomain
  (`subdomain_base`); members by their membership. A public page, sitemap or
  media request with no tenant answers 404 — the same as an unknown slug — and
  an editor with no tenant gets 403. Custom domains are not supported yet.

The scheduler publishes due pages tenant by tenant, each in its own session.
Requires framework `0.0.35` or later, and the host migration that adds
`tenant_id` (`make migration` picks it up like any other model change).

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

**Languages.** A bundle identifies a page by `(locale, slug)`, not by slug
alone — the same pair the database is unique on — so a site publishing `about`
in two languages captures and restores as two pages rather than one silently
overwriting the other. Each document carries its `locale` and its
`translation_group`, so counterparts stay linked as one document after a
restore. A parent and a redirect both resolve within their own language, so a
breadcrumb or a retired address never crosses into another one.

Pages in a language the target host does not publish are restored and kept, not
discarded: nothing routes `/fr/p/…` until `fr` is added to `content_locales`,
at which point they simply start serving. Bundles written before languages
existed (`format_version` 1) still restore — every page in one is read as the
default content locale, which is what the schema guaranteed at the time.

## Contracts

DTOs other modules may depend on are exported from `pagebuilder.contracts`.
Everything else in the package is internal and may change without a major
version bump.

## Licence

MIT
