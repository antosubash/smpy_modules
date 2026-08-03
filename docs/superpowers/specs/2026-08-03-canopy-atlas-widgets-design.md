# Canopy Atlas widgets and content — design

**Date:** 2026-08-03
**Status:** Approved

## Goal

Port the widget library and page content behind IIASA GeoWiki's Global Canopy
Atlas (GCA) into `modules/pagebuilder`, so the demo host can serve the GCA site
from our own page builder.

## Decisions taken

| Question | Decision |
|---|---|
| What "tenant" means here | **Single-site.** GCA becomes the demo host's site content. No `tenant_id`, no migration, no query scoping. Real multi-tenancy is deferred until something needs two sites at once. |
| Where the widgets live | **`modules/pagebuilder`.** The existing block library grows from 6 blocks to ~20; every consuming host gets the richer set. |
| First-pass scope | **All 14 widgets** GCA's content uses. |

## Source

- `IIASA.GeoWiki/frontend/packages/pagebuilder` — the widget library (55+
  widgets; GCA uses 17, of which we already have 3).
- `IIASA.GeoWiki/frontend/packages/gca` — the tenant: brand assets, nav, site
  layout, and 14 pages of content-as-code.

The content is stored in the **same Puck shape we already use**
(`{root, content: [{type, props}], zones}`), so it ports directly once the
widgets exist.

## Dependency surface

The decisive finding: the widgets are self-contained. Across all 14 they import
only `@puckeditor/core`, `react`, `lucide-react`, and their own local helpers —
**no `@geowiki/ui`**. `lucide-react` already reaches us through
`@simple-module-py/ui`, and `primary-100`…`primary-900` already exist in our
theme, so `text-primary-700` resolves.

Two adaptations:

- `@puckeditor/core` → `@measured/puck`. Same library under its newer package
  name; `ComponentConfig` is API-compatible with our 0.19.3.
- The base package's `ContactForm`, `Stats`, and `ArticleCards` are the
  **presentational** variants. GeoWiki overrides them with data-driven ones in
  its app layer. Presentational is what we want — no backend decisions.

## What gets ported

### 1. Support layer (~1,200 lines) — first, nothing renders without it

`_internal/`: `rich-text` (256), `accent-text`, `link-arrow`,
`disclosure-chevron`, `solid-icons`, `eyebrow-split-section`.

`_shared/`: `section`, `heading`, `cta-button`, `background-media`,
`content-media`, `eyebrow-text`, `text-link`, `empty-placeholder`.

Plus `utils/parse-list`, `utils/decorative-image`, `fields/checkbox-field`, and
`conversion/markdown` (163).

### 2. Design tokens

The widgets are driven by a `--pb-*` custom-property layer: display
font/weight/tracking, a heading scale (`--pb-heading-xl/lg/md`), body leading,
eyebrow treatment, split-grid columns, card metrics.

GeoWiki layers a per-tenant **design pack** over app-level defaults. We mirror
that with two files in the module: a base token layer, and a GCA pack (185
lines) that overrides it. Loading the pack is what makes the pages look like
GCA rather than generic.

### 3. The 14 widgets (~4,000 lines)

`PageHeader` (133), `Hero` (324), `MediaObject` (743), `CallToAction` (388),
`EyebrowSection` (58), `FeatureCards` (474), `Faq` (331), `Tags` (91),
`LogoCloud` (129), `ContactCards` (178), `ContactForm` (395), `Divider` (56),
`Stats` (208), `ArticleCards` (181).

Six exceed our 300-line cap and are split as they land: `MediaObject`,
`FeatureCards`, `ContactForm`, `CallToAction`, `Faq`, `Hero`. Splits are
behaviour-preserving extractions, and no new file goes under `pages/`.

### 4. GCA content (14 pages, 1,893 lines)

`home`, `who-we-are`, `our-process`, `our-statements`, `outputs`,
`how-to-use-the-data`, `data-map`, `faqs`, `contact`, `privacy`, `terms`,
`news-index`, `news-article`. Seeded as real pagebuilder pages, published, and
rendering at `/p/{slug}`.

## Assets

`frontend/packages/gca/data/gca/` in GeoWiki holds `logo-main.svg`,
`logo-reversed.svg`, seven partner SVGs (Leverhulme, UKRI, ERC, Bristol, ESA,
IIASA, GEO-TREES), and eight content photographs under `images/`:

`atlas-map`, `biodiversity`, `canopy-aerial`, `canopy-up`, `collaboration`,
`forest-aerial-river`, `governance-diagram`, `hero-lidar`.

All of them are copied into the demo host's static directory. GeoWiki's
`seed-images.ts` uploads the photographs into its file store at seed time;
`scripts/gca/seed_pages.py` does the equivalent here, uploading them into the
media library and rewriting the content's `/gca/images/*.jpg` paths to the
resulting `/media/pagebuilder/*` URLs. Every photograph on a seeded page is
therefore swappable from the editor's image picker.

The brand and partner marks stay on `/static`: they are SVG, which the media
library rejects because SVG can carry script.

## Constraints

- 300-line cap on every `.py`/`.ts`/`.tsx`, no exemptions.
- No new files under `modules/*/*/pages/` — the path defines the Inertia page
  name.
- The existing 22 Playwright specs must stay green; the 6 current blocks
  (`Heading`, `Text`, `Image`, `Button`, `Columns`, `Spacer`) keep their names
  and props so existing pages keep rendering.
- Tailwind classes in the new directories are covered by the scan glob widened
  in `9eca286`.

## Delivery

Ported in reviewable slices, each committed with the suites green:

1. Support layer + design tokens
2. Widgets in batches, splitting the oversized ones as they land
3. Assets
4. Content seed + browser verification of the rendered pages

This is a large port. Delivering it as one commit would be unreviewable.

## Out of scope

- Multi-tenancy (`tenant_id`, scoped queries).
- The data-driven widget variants (live news, live stats, form submission).
- GCA's site chrome — nav and `GcaSiteLayout`. Our pagebuilder has its own Site
  layout feature (header/footer), which is where that would go later.
- The CanopyMap / MapLibre widget: it needs `@geowiki/maplibre` and is a
  separate subsystem.
