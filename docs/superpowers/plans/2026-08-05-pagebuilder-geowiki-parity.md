# Pagebuilder feature parity with IIASA.GeoWiki

**Status:** plan — nothing implemented.
**Date:** 2026-08-05
**Source of truth for the target:** `/home/anto/Repos/IIASA.GeoWiki/frontend/packages/pagebuilder`
(package `@geowiki/pagebuilder`, on Puck `0.21.3`).
**This side:** `modules/pagebuilder/` on Puck `0.22.4`.

## What parity does and doesn't mean here

GeoWiki's pagebuilder is a *widget library*: 55 widgets, HTML/Markdown
conversion, and content translation, with no CMS around it. Ours is a *CMS
module*: 20 widgets, but with revisions, scheduling, SEO, a media library with
folders, a site-layout editor, and a review workflow — none of which GeoWiki
has.

So "parity" is one-directional. It means **closing the widget and
content-pipeline gap**, not converging the two products. Everything in
§5 stays as-is.

## 1. Measured inventory

| | GeoWiki | Ours |
|---|---|---|
| Widgets registered | 55 | 20 |
| Widget source lines | 8,416 | 4,645 |
| Shared `_shared/` primitives | 10 | 11 (`social-icon.tsx` extra) |
| Shared `_internal/` primitives | 6 | 6 |
| `fields/` (file picker, checkbox) | yes | yes — already ported |
| `utils/` (`cn`, `parse-list`, `decorative-image`) | yes | yes — already ported |
| `--pb-*` theme tokens | yes | yes — 17 tokens in `static/widgets-base.css` |
| HTML ⇄ Puck conversion | yes (355 lines) | **no** |
| Content translation extract/apply | yes (272 lines) | **no** |
| `migrateContent` on load | yes (36 lines) | **no** |

The good news is that the *foundation* is already here. `_shared/`,
`_internal/`, `fields/` and the `--pb-*` token layer are line-for-line ports.
The gap is almost entirely widgets plus three self-contained subsystems.

## 2. Gap A — 36 missing widgets

Shared today (19): Heading, Text, Image, Button, Spacer, PageHeader, Hero,
EyebrowSection, MediaObject, CallToAction, FeatureCards, Faq, Stats,
ArticleCards, ContactCards, ContactForm, LogoCloud, Tags, Divider.

Missing, grouped by what they're for, with GeoWiki's line count:

**Layout (4)** — Container 99, Row 74, Column 63, Grid 59
**Text & content (8)** — SectionIntro 148, Markdown 147, DefinitionList 145,
ProseSection 120, Table 89, List 56, Quote 55, Html 42
**Media (4)** — Gallery 140, Video 109, Carousel 95, Iframe 48
**Interactive (2)** — Tabs 100, Accordion 68
**Sections & marketing (12)** — Timeline 472, Leaderboard 230, Steps 221,
Newsletter 220, StoryCards 186, FeatureShowcase 134, FeatureGrid 121,
FeatureCard 106, Testimonial 103, SocialBanner 91, CenteredHero 53
(palette-hidden), SignupBanner 50
**Actions & utility (6)** — ColoredActionList 124, AppStoreBadges 100,
SimpleActionList 98, Alert 47, UnderConstruction 41, Welcome 38

≈ 3,700 lines of widget code.

### Layout needs a decision, not a port

Our single `Columns` block (48 lines, legacy `DropZone`) overlaps GeoWiki's
four-widget `Container` / `Row` / `Column` / `Grid` family. Porting all four
alongside `Columns` gives authors five confusable ways to make a two-column
row. Options:

- **(a) Port the family, keep `Columns` as a deprecated alias.** Full parity;
  costs a palette that's briefly confusing and a later removal.
- **(b) Port `Container` + `Grid` only.** Covers what `Row`/`Column` do via
  slot fields without duplicating `Columns`. Not literal parity.
- **(c) Replace `Columns` with the family + a stored-data migration.** Cleanest
  end state, and it composes with the `DropZone`→slot-field work already
  identified in the perf plan (that migration is needed anyway).

**(c) is the recommendation** precisely because it shares a migration with work
already queued. Doing (a) now means writing that migration twice.

## 3. Gap B — three primitives that diverged (needs data migration)

These are not missing; they're *different*, and two differ in stored prop
values, so porting them is a breaking change to existing page data.

### Heading — data-incompatible
Ours stores `level: 'h1'…'h6'`; GeoWiki stores `level: '1'…'6'`. Ours also
lacks rich-text rendering, the `--pb-heading-color` / `--pb-display-*` token
styling, and the `container mx-auto px-4 py-2` wrapper every GeoWiki widget
uses for horizontal rhythm. **Requires a migration mapping `hN` → `N`.**

### Text — data-incompatible
Ours is a plain `textarea` string with `whitespace-pre-line`. GeoWiki's is a
Puck `richtext` field (HTML, `contentEditable: true`, headings disabled) plus a
`size` prop we don't have. **Requires a migration wrapping existing plain text
in `<p>…</p>` with escaping.**

Confirmed: `richtext` is still a supported field type in Puck 0.22.4, so this
is portable as-is.

### Button — additive only, no migration
Ours has 4 props; GeoWiki's has 7. Missing: `size`, `color` (CSS override),
`indent` (12-column grid alignment), the `outline` variant, rich-text labels,
`--pb-button-radius`, and the optional trailing arrow. All are additive with
defaults, so existing data keeps working.

### Note on the alignment classes
`Heading.tsx:44` and `Text.tsx:22` build classes by interpolation —
`` `text-${align}` ``. Tailwind's scanner cannot see those. They currently
work only because `text-left`, `text-right` and `text-center` each appear
literally elsewhere in scanned module source (3, 3 and 21 files
respectively). It is not broken today, but it is load-bearing coincidence —
the port to GeoWiki's explicit `ALIGN_CLASS` lookup maps removes the hazard as
a side effect.

## 4. Gap C — three missing subsystems

### `conversion/` (~355 lines) — HTML ⇄ Puck
`blocks-to-html` 58, `html-to-blocks` 111, `markdown` 163, `is-puck-content`
19, `types` 4. Lets a page be authored as HTML/Markdown and round-tripped
through the visual editor. Self-contained and well covered by GeoWiki's tests
(5 test files including a round-trip suite). **Port the tests with it.**

### `translation/` (~272 lines) — content i18n
`extract` 155, `apply` 45, `translatable-fields` 72. Walks Puck data,
extracts translatable strings (with a key-based denylist plus the
`IMAGE_FIELDS`/`ARRAY_IMAGE_FIELDS` exclusion), and applies translations back.

This is *content* i18n — distinct from the UI i18n that `CLAUDE.md` already
lists as deferred (pagebuilder's TSX copy is hardcoded English with no
`locales/en.json`). They're independent; content i18n has no server side here
yet, so it needs a storage decision (see §7).

### `migrate-content.ts` (36 lines)
Runs Puck's `migrate()` on load and drops components no longer in the config,
so stale page data can't crash the editor. Small, high-value, and a
prerequisite for §3's migrations. **Do this first.**

## 5. Not gaps — ours only, keep as-is

Site header/footer widgets, `LayoutEditor`, revision history + diff, schedule
panel, SEO settings panel, media library with folders / filters / upload
queue, design packs, and the `PendingReview` workflow. GeoWiki has none of
these. Nothing in this plan should regress them.

## 6. Constraints the port must respect

1. **300-line cap** (`scripts/check_file_size.py`, no exemption under
   `modules/`). Of the missing widgets only **Timeline (472)** exceeds it;
   Leaderboard 230, Steps 221 and Newsletter 220 are close enough to exceed
   after formatting. Timeline must be split the way `media-object` already was
   (`-widget` / `-render` / `-layout`).
2. **Never add a file under `modules/*/*/pages/`** unless it is a real Inertia
   page — `import.meta.glob` derives page names from that path.
3. **Published-module pin policy** — widgets must not import `@geowiki/shared`.
   `cn` already comes from `@simple-module-py/ui/lib/utils`; keep it that way.
4. **Puck version skew** — GeoWiki is on 0.21.3, we're on 0.22.4. Port against
   0.22's `Config<{components, root}>` object-params generic form, not the
   positional form GeoWiki still uses.
5. **Registry + categories** — `blockRegistry.ts` and `basePageConfig.categories`
   both need extending for ~36 new names. GeoWiki hides `CenteredHero` behind a
   `_hidden` category; mirror that.
6. **Migrations live in `host/migrations/versions/`**, never in a module — only
   relevant if translation storage (§7) lands.

## 7. Suggested sequence

Each phase is independently shippable and independently revertable.

**Phase 0 — safety net.** Port `migrate-content.ts` and `is-puck-content.ts`.
Wire `migrateContent` into `PageEditor` and `PublicPage` load paths. Nothing
user-visible; makes every later phase safe by guaranteeing unknown components
degrade instead of crashing. *~55 lines + tests.*

**Phase 1 — primitives.** Port Heading, Text and Button to GeoWiki's versions
with their `hN`→`N` and plain-text→`<p>` migrations registered through Phase 0's
machinery. Highest-risk phase; smallest diff. *~300 lines + 2 migrations.*

**Phase 2 — widget bulk, in four batches.** Text & content (8) → media (4) →
interactive (2) → sections/actions (18, Timeline split). Each batch is a
self-contained PR: widgets + registry + category + a rendering test per widget.
*~3,400 lines.*

**Phase 3 — layout family.** Whichever of §2's options is chosen. Sequenced
last because option (c) shares its migration with the `DropZone`→slot-field
change from the perf plan, and doing both at once halves the data risk.

**Phase 4 — conversion.** Port `conversion/` plus its 5 test files. Needs no
server changes: it is pure data transformation.

**Phase 5 — translation.** Port `translation/`. Blocked on the §8 decision.

## 8. Open questions

1. **Is the widget bulk actually wanted, or only a subset?** 36 widgets is the
   dominant cost of this plan. Several (Welcome, UnderConstruction,
   Leaderboard, AppStoreBadges) look specific to GeoWiki's product rather than
   generally useful in a distributable module. A named subset would cut Phase 2
   substantially.
2. **Layout: option (a), (b) or (c)?** Recommendation is (c) — see §2.
3. **Where does translated page content live?** GeoWiki's `translation/` is
   pure functions with no persistence; this repo would need a table and an
   Alembic revision in `host/migrations/versions/` under a `pagebuilder` branch
   label. That's a schema decision, not a port.
4. **Does `Text` becoming rich text change the public-page CSP?** Rich text
   renders stored HTML. `public-viewer-headers.spec.ts` asserts a CSP on
   `/p/{slug}`; the sanitisation boundary needs confirming before Phase 1
   ships, not after.

## 9. Measurement

Re-run the parity count with:

```bash
G=/home/anto/Repos/IIASA.GeoWiki/frontend/packages/pagebuilder/src
grep -cE '^\t[A-Z][A-Za-z]+: [A-Z]' $G/config/puck-config.ts   # GeoWiki widget count
grep -cE '^    [A-Z][A-Za-z]+: [A-Z]' \
  modules/pagebuilder/pagebuilder/components/puckConfig.tsx     # ours
```

Today: 55 vs 20.
