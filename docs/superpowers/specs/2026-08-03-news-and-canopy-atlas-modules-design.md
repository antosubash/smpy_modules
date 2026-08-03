# News and Canopy Atlas modules — design

**Date:** 2026-08-03
**Status:** implemented. Sections marked *As built* record where the
implementation departed from this design and why.

## Goal

Split the Global Canopy Atlas site out of `pagebuilder` into its own
distributable module, and add a news module, so that GCA-specific work has a
home and `pagebuilder` goes back to being a generic CMS.

Today `pagebuilder` ships `gca-pack.css`, and the GCA seed lives in
`scripts/gca/` with its images under `host/static/gca/`. A module published as
`simple_module_pagebuilder` should not carry one site's brand.

## Decomposition

Four steps. Each ends with a green suite and is shippable on its own.

| Step | Deliverable |
|---|---|
| 0 | Framework: `DesignPackRegistry` in core, `design_pack` in branding |
| 1 | `simple_module_canopy_atlas` shell — pack, seed, assets move here |
| 2 | Block registry in `pagebuilder` |
| 3 | `simple_module_news` |
| 4 | Atlas map — **out of scope, its own spec** |

Step 4 is described under "Out of scope" only far enough to show the earlier
steps do not box it in.

## Global constraints

- 300-line cap on every `.py` / `.ts` / `.tsx`, enforced by
  `scripts/check_file_size.py`. No exemptions under `modules/`.
- Published modules depend on the framework with **ranges**
  (`simple_module_core>=0.0.25,<0.1`); the host pins **exactly**
  (`simple_module_hosting==0.0.25`).
- Migrations live in `host/migrations/versions/`, never in a module. A module's
  first revision carries `branch_labels = ("<module>",)`.
- Nothing goes under `modules/*/*/pages/` unless it is a real Inertia page —
  `import.meta.glob` derives the page name from that path.
- One version across the repo; `scripts/bump_version.py` is the only thing that
  edits versions, and CI runs `--check-current`.
- Python entry points run from the repo root.

## Step 0 — framework changes

These land in `/Volumes/ext1/GitHub/simple_module_python`, not this repo.

### `simple_module_core`: `DesignPackRegistry`

A new registry beside `MenuRegistry`, `PermissionRegistry` and
`PublicRouteRegistry`, with the matching `ModuleBase` hook:

```python
@dataclass(frozen=True)
class DesignPack:
    value: str   # slug; the site root class is f"{value}-root"
    label: str   # shown in the branding dropdown


class DesignPackRegistry:
    def register(self, pack: DesignPack) -> None: ...
    def all(self) -> list[DesignPack]: ...


class ModuleBase:
    def register_design_packs(self, registry: DesignPackRegistry) -> None: ...
```

The host calls the hook during module registration and stores the populated
registry on `app.state.design_packs`.

`value` must match `^[a-z0-9][a-z0-9-]*$`. Registering the same `value` twice
is an error, not a silent overwrite — two modules claiming one root class would
produce whichever stylesheet loaded last.

### `simple_module_branding`: `design_pack`

- `BrandingSettings.design_pack: str = ""` (`""` = no pack, base tokens only).
- `BrandingOut.design_pack`, `BrandingUpdate.design_pack`.
- `branding_payload()` gains `"designPack": settings.design_pack or None`.
- `SharedProps["branding"]` in `@simple-module-py/ui` gains
  `designPack: string | null`.
- `Manage.tsx` renders a `<Select>` whose options are "None (base tokens)" plus
  the registry contents, supplied to the page as a `designPacks` prop by the
  branding view.
- `PUT /api/branding/` rejects a `design_pack` that is not registered. The
  check lives in the endpoint, where `request.app.state.design_packs` is
  reachable; the settings validator only enforces the slug shape.

### What the registry does not do

It supplies the dropdown, not the stylesheet. A pack's CSS still reaches the
bundle through the host's `styles.css` importing it by package specifier,
exactly as `gca-pack.css` does today. The registry's job is to stop an
administrator selecting a pack no installed module provides.

### Release gate

This host pins `simple_module_branding==0.0.25`. Steps 0 and 1 develop against
`make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python`, and
nothing merges until the framework cuts a release and the host's pins move to
it. CI runs `scripts/bump_version.py --check-current`, so this is a hard gate.

The framework work goes on a branch off `origin/main` at `v0.0.25` — the same
commit this host already has installed. It is not pushed or released here;
cutting the release is the maintainer's call.

## Step 1 — `simple_module_canopy_atlas` shell

Scaffolded with `make new-module name=canopy_atlas`.

- Python package `canopy_atlas`, distribution `simple_module_canopy_atlas`,
  npm `@simple-module-py/canopy-atlas`.
- `ModuleMeta(name="CanopyAtlas", route_prefix="/api/canopy-atlas",
  view_prefix="/canopy-atlas", depends_on=["PageBuilder"])`.
- No tables, so no migration.

### What moves

| From | To |
|---|---|
| `modules/pagebuilder/pagebuilder/static/gca-pack.css` | `canopy_atlas/static/gca-pack.css` |
| `scripts/gca/content/*.json` (12 pages + `_layout.json`) | `canopy_atlas/seed/content/` |
| `scripts/gca/seed_pages.py` | `canopy_atlas/seed/__main__.py` |
| `host/static/gca/images/*.jpg` (8) | `canopy_atlas/static/gca/images/` |
| `host/static/gca/logo-*.svg`, `partners/*.svg` (9) | `canopy_atlas/static/gca/` |

Everything else stays in `pagebuilder`: `widgets-base.css`, all 20 blocks, and
the `SiteHeader` / `SiteFooter` chrome widgets. They are generic sections — the
GCA-ness lives entirely in the tokens — and `news` reuses `ArticleCards`
without depending on this module.

### Static assets

```python
def static_mounts(self) -> dict[str, Path]:
    return {"/canopy-atlas/static": Path(files("canopy_atlas") / "static")}
```

**A module static mount is not automatically public.** Without a
`PublicRouteRegistry` entry, `AuthMiddleware` 302s every logo to the login
page. Register `"/canopy-atlas/static/"` — with the trailing slash, because
public-route rules match with `str.startswith` and `/canopy-atlas/static`
without it would also exempt any sibling path sharing that prefix. This is the
same bug that shipped once already with `/p` matching `/pagebuilder/`.

### Seeding

`python -m canopy_atlas.seed` replaces `scripts/gca/seed_pages.py` and keeps
its behaviour:

- uploads the eight photographs into pagebuilder's media library, idempotent by
  `original_filename`, and rewrites `/gca/images/*.jpg` in the content to the
  returned media URLs, so every photograph stays swappable from the editor;
- rewrites the SVG brand and partner marks to `/canopy-atlas/static/gca/...`
  (they stay files, not media — the media library rejects SVG because it can
  carry script and is served same-origin);
- sets branding's app name, primary colour **and `design_pack="gca"`**;
- publishes the 12 pages and the site layout.

Existing installs need a re-seed: the asset URLs in stored page data change
from `/static/gca/...` to `/canopy-atlas/static/gca/...`.

### `designPack` leaves the page

The per-page `designPack` root prop is removed, in favour of the site-wide
branding setting:

- `puckConfig`'s root loses the `designPack` radio and its default;
- `emptyData`'s root props lose it;
- `PublicPage` reads `branding.designPack` from shared props and wraps the
  document in `` `${pack}-root` ``, replacing the current dig into
  `data.root.props.designPack`;
- seeded content drops the prop.

**The pack applies to the public site only** — `PublicPage` and, later, the
atlas route. Not the admin. GCA's pack remaps shadcn tokens and forces a
1440px container; those rules were authored for the reader-facing site, and
putting `gca-root` on `<html>` would restyle the Puck editor's own chrome.

Consequence for the existing suite: `widgets.spec.ts` currently asserts two
`.gca-root` elements (the page root's own plus PublicPage's hoisted one). With
the page root's copy gone there is exactly one, and the page-editor preview no
longer renders inside a pack at all — the same known gap the layout editor
already has, now shared by both editors and documented in one place.

## Step 2 — block registry in `pagebuilder`

So that a module can contribute a Puck block without `pagebuilder` importing
it. The framework has no frontend registry — `MenuRegistry` and friends are all
backend — so this is new.

### API

```ts
// pagebuilder/components/blockRegistry.ts
export interface BlockRegistration {
  blocks: Record<string, ComponentConfig<never>>;
  /** Palette group. Omitted blocks land in Puck's "Other". */
  category?: { key: string; title: string };
  /** Register into the layout palette too. Default false. */
  layout?: boolean;
}

export function registerPuckBlocks(registration: BlockRegistration): void;
export function registeredBlocks(): BlockRegistration[];
export function registryVersion(): number;
```

`puckConfig` becomes `getPuckConfig()` and `layoutPuckConfig` becomes
`getLayoutPuckConfig()`, each memoised **on `registryVersion()`** rather than
unconditionally, so a registration that arrives after the first read is not
silently dropped. Three call sites change: `PageEditor`, `PublicPage`,
`layoutPuckConfig`.

### How registration happens

Each module ships `<pkg>/puck-blocks.ts` whose import has the side effect of
calling `registerPuckBlocks`. The host imports them all eagerly:

```ts
// host/client_app/blocks.ts — hand-written, mirrors styles.css
import.meta.glob('../../modules/*/*/puck-blocks.ts', { eager: true });
import.meta.glob(
  '../../.venv/lib/python3.12/site-packages/*/puck-blocks.ts',
  { eager: true },
);
```

`app.tsx` imports `./blocks` before anything else, so every block is registered
before the first render, and `getPuckConfig()` is only ever called from inside
a component.

Two globs because workspace modules and wheel-installed modules live in
different trees — the same split `modules.generated.ts` already uses for pages
and `styles.css` uses for CSS. This file is hand-written for the same reason
`styles.css`'s module imports are: `gen-pages` emits page globs and `@source`
entries, not block imports. Automating it belongs in the framework CLI later.

## Step 3 — `simple_module_news`

Scaffolded with `make new-module name=news`. Python package `news`,
distribution `simple_module_news`, npm `@simple-module-py/news`.
`ModuleMeta(depends_on=["PageBuilder"])`, and
`simple_module_pagebuilder>=0.1,<0.2` in `pyproject.toml` with
`[tool.uv.sources] simple_module_pagebuilder = { workspace = true }`.

### Model

```python
class NewsArticle(Base, AuditMixin, table=True):
    __tablename__ = "news_articles"

    id: int | None = Field(default=None, primary_key=True)
    page_id: int = Field(
        sa_column=Column(Integer, nullable=False, unique=True, index=True)
    )
    category: str = Field(default="", max_length=80, index=True)
    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
```

Everything else is the `Page`: title, slug, body, excerpt
(`meta_description`), cover image (`og_image`), approval workflow, revisions
and SEO. A sidecar rather than columns on `Page` keeps `pagebuilder` a generic
CMS that knows nothing about news.

**As built — `page_id` carries no database foreign key**, which this spec
originally assumed it would. `create_module_base` gives every module its own
`MetaData`, so a cross-module `ForeignKey` cannot resolve its target table and
SQLAlchemy raises `NoReferencedTableError` when the mapper configures. There is
therefore no `ON DELETE CASCADE` to rely on, and no `depends_on` needed on the
migration either.

That is not a small loss, and the reasoning that first covered it — "the
listing inner-joins the page, so an orphan is invisible" — is wrong. SQLite
reuses a deleted row's id, so an orphan does not dangle: it re-attaches to the
next page created, and the listing shows one article's title under another's
metadata.

Two guards replace the cascade, and between them no orphan can exist:

- `pagebuilder` publishes a `PageDeleted` event and `news` subscribes, dropping
  the row. The event is published *after* the delete commits — a subscriber
  runs on its own session, and on SQLite an open write transaction on the
  request's session makes it fail with "database is locked". The bus logs a
  handler failure rather than raising, so without the commit the row survives
  silently while the endpoint returns 204.
- `POST /articles` 404s when the page does not exist, closing the path where an
  API caller creates the orphan directly.

The remaining cost is that every listing is a join.

### API — `/api/news`

| Route | Behaviour |
|---|---|
| `GET /articles?limit&offset&category` | Joins `Page`; ordered `published_at DESC NULLS LAST, id DESC`. Anonymous callers see published pages only. Returns `{items, total}`. |
| `GET /categories` | Distinct categories with counts, published-only for anonymous. |
| `POST /articles` | `{page_id, category, published_at}` — attaches metadata to an existing page. 409 if that page already has an article row. |
| `PUT /articles/{id}` | Updates category / published_at. |
| `DELETE /articles/{id}` | Detaches. Does **not** delete the page. |

Read routes are public (registered with `PublicRouteRegistry` so the feed block
works on an anonymous page view); write routes require `news.edit`.
Permissions `news.view` / `news.edit` register through `PermissionRegistry`.

An item is `{id, page_id, slug, title, excerpt, cover_image_url, category,
published_at, url}` where `url` is `/p/{slug}`.

### Admin

One menu entry, "News", in the existing "Content" group. One Inertia page at
`/news/`: the article list with inline category and date editing, and a "New
article" action that creates a `Page` through pagebuilder's API, attaches an
article row, then redirects into pagebuilder's editor for the body. Each row
links to that editor.

### Public surface

None. An article **is** a page, so it already serves at `/p/{slug}` with the
existing ETag, `Cache-Control`, CSP, SEO and site layout. A second viewer would
mean duplicating all of it.

The index is a pagebuilder page holding the feed block.

### `NewsFeed` block

Registered from `news/puck-blocks.ts`. Fields: heading, category filter, limit,
columns, and a "view all" label/link. It fetches `/api/news/articles` and
renders through pagebuilder's existing ArticleCards presentation.

That presentation has to be importable without its Puck config, so
`article-cards-widget.tsx` splits into config and render, following the
`faq-widget.tsx` / `faq-render.tsx` precedent already in the module.

States: loading, empty (an editor-visible hint, nothing on the public page),
and error (same as empty on the public page).

### Seeding articles

`canopy_atlas`'s seed probes `GET /api/news/articles`. When news is installed
it creates the article pages, attaches their rows, and points the home page's
news strip and the `news-index` page at `NewsFeed`; when it is not, it leaves
today's hand-authored `ArticleCards`. `canopy_atlas` therefore does not depend
on `news`.

## Testing

Python tests live in `modules/<name>/tests/`, following pagebuilder's layout.

**`canopy_atlas`:** the static mount is reachable anonymously; the pack
registers; the seed is idempotent (running it twice does not duplicate uploads
or pages).

**`news`:** article CRUD; the cascade — deleting a page removes its article
row; anonymous listing excludes draft pages; category counts; ordering with
null `published_at`; 409 on a duplicate attach.

**`pagebuilder`:** registry unit tests — a registered block appears in
`getPuckConfig()`, a registration after the first read invalidates the memo,
and a duplicate block name is an error.

**e2e:** the branding dropdown switches the public site's pack; `NewsFeed`
appears in the palette and renders live articles on a published page; an
article page serves at `/p/{slug}`.

The existing `widgets`, `branding` and `site-chrome` specs are the regression
net for the extraction. They must stay green, and `widgets.spec.ts`'s
`.gca-root` count assertion changes from 2 to 1.

## Risks

1. **Framework release gate.** Steps 0–1 cannot merge until the framework
   releases and the host's `==` pins move. Everything before that runs on
   `make link-framework`.
2. **Cross-branch foreign key.** If `depends_on = ("pagebuilder",)` is missing
   from the news branch's first revision, `alembic upgrade heads` can order the
   news table before `pagebuilder_pages` exists. It fails loudly, but only on a
   clean database — not on a developer machine that already has the table.
3. **Re-seed required.** Asset URLs and the removed root prop both change what
   is stored in page data.
4. **Vite globbing into site-packages** for `puck-blocks.ts` is unproven for
   this file name, though `modules.generated.ts` already globs that tree for
   pages.
5. **300-line cap** will bite the news admin page and the registry-aware
   `puckConfig`. Split by responsibility, not by layer.

## Out of scope — step 4, the atlas map

Its own spec. The shape, only to show this design does not box it in:
`/atlas` as a full-screen public route with the layout header and no footer,
MapLibre over `canopyatlas:GCA_extended_public` at
`geoserver.iiasa.ac.at/geoserver/canopyatlas/ows` queried directly from the
browser, with a filter panel, area select and CSV/shapefile/GeoJSON download.

The route carries its own CSP so `connect-src` for GeoServer and `img-src` for
basemap tiles never widen `PagebuilderSettings.public_csp`, which every `/p/`
page uses. GeoWiki's implementation is roughly 1,500 lines of TSX, so the
300-line cap will drive the file split.

Nothing in steps 0–3 constrains it: the pack it needs is already registered by
`canopy_atlas`, and the site header it reuses already comes from the layout.
