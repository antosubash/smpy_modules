# Pagebuilder feature parity with IIASA.GeoWiki

**Status:** Phases 0–3 done — the widget count matches at **56** and the
three diverged primitives are aligned (§9–§12). Remaining: Phase 4
(`conversion/`), Phase 5 (`translation/`).
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

Sections 1–8 are the original survey, kept as the baseline the work was planned
against. Where something has since been done, the row or heading says so and
points at the section that records it.

| | GeoWiki | Ours (at survey) | Ours (now) |
|---|---|---|---|
| Widgets registered | 55 | 20 | **56** — §11 |
| Widget source lines | 8,416 | 4,645 | ~8,400 |
| Shared `_shared/` primitives | 10 | 11 (`social-icon.tsx` extra) | same |
| Shared `_internal/` primitives | 6 | 6 | same |
| `fields/` (file picker, checkbox) | yes | already ported | same |
| `utils/` (`cn`, `parse-list`, `decorative-image`) | yes | already ported | same |
| `--pb-*` theme tokens | yes | 17, in `static/widgets-base.css` | same |
| HTML ⇄ Puck conversion | yes (355 lines) | **no** | still no — Phase 4 |
| Content translation extract/apply | yes (272 lines) | **no** | still no — Phase 5 |
| `migrateContent` on load | yes (36 lines) | **no** | yes — §9 |

The good news is that the *foundation* is already here. `_shared/`,
`_internal/`, `fields/` and the `--pb-*` token layer are line-for-line ports.
The gap is almost entirely widgets plus three self-contained subsystems.

## 2. Gap A — 36 missing widgets — **closed, see §11**

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

Our `Columns` block — now on slot fields, §10 — overlaps GeoWiki's four-widget
`Container` / `Row` / `Column` / `Grid` family. Porting all four alongside
`Columns` gives authors five confusable ways to make a two-column row. Options:

- **(a) Port the family, keep `Columns`.** Full parity; costs a palette with
  redundant ways to do the same thing.
- **(b) Port `Container` + `Grid` only.** Covers what `Row`/`Column` do without
  duplicating `Columns`. Not literal parity, and the smallest change.
- **(c) Replace `Columns` with the family + a stored-data migration.** Closest
  to GeoWiki, but it's now the *most* expensive option, not the cheapest.

**Resolved as (a)** by the instruction to port all widgets — `Container`,
`Row`, `Column` and `Grid` all landed alongside `Columns`, no migration needed.
The palette does now offer more than one route to a two-column row; if that
proves confusing in use, the cheap follow-up is to move the redundant ones into
a `_hidden` category rather than delete them, since stored pages may reference
them.

(For the record, the recommendation had moved from (c) to (b) before this:
(c)'s appeal was sharing a migration with the `DropZone`→slots work, and once
that work was done and its migration written, (c) stopped amortising against
anything.)

## 3. Gap B — three primitives that diverged — **closed, see §12**

> Both migrations this section calls for turned out to be avoidable; §12 says
> why. Kept as written for the reasoning that led there.

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

### `migrate-content.ts` (36 lines) — **done, see §9**
Runs Puck's `migrate()` on load, guarded so modern payloads skip the walk and a
zone that can't convert can't blank the page. Small, high-value, and a
prerequisite for §3's migrations.

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

**Phase 0 — safety net. ✅ done (§9).** `migrateContent` ported and wired into
all four load paths. `is-puck-content.ts` deliberately *not* ported: it checks
whether a stored *string* is Puck JSON, and our data arrives from Inertia
already parsed. It earns its place with Phase 4, when HTML content becomes
possible — porting it now would be speculative.

**Phase 1 — primitives. ✅ done (§12).** Neither planned migration was needed:
Heading keeps its own `level` spelling, and Text gets rich text through the
markdown renderer rather than Puck's HTML-storing field. The "highest-risk
phase" ended up the one that touched no stored data at all.

**Phase 2 — widget bulk. ✅ done (§11).** Landed as one change rather than the
four planned batches: the port turned out to be mechanical once the shared
primitives were confirmed present, so splitting it would have added review
surface without reducing risk. Coverage came as a catalogue-wide render test
instead of a per-widget e2e page.

**Phase 3 — layout family. ✅ done (§10 + §11).** `Columns`→slots in §10;
`Container` / `Row` / `Column` / `Grid` with the rest of the bulk.

**Phase 4 — conversion.** Port `conversion/` plus its 5 test files. Needs no
server changes: it is pure data transformation.

**Phase 5 — translation.** Port `translation/`. Blocked on the §8 decision.

## 8. Open questions

1. ~~**Is the widget bulk actually wanted, or only a subset?**~~ **Answered:
   all of them.** Done — §11.
2. ~~**Layout: option (a), (b) or (c)?**~~ **Resolved as (a)** by the above —
   see §2.
3. **Where does translated page content live?** GeoWiki's `translation/` is
   pure functions with no persistence; this repo would need a table and an
   Alembic revision in `host/migrations/versions/` under a `pagebuilder` branch
   label. That's a schema decision, not a port.
4. ~~**Does `Text` becoming rich text change the public-page CSP?**~~
   **Answered by not creating the question** — Text renders parsed markdown,
   never stored HTML, so there is no sanitisation boundary to confirm. §12.

## 9. Phase 0 as built, and what it turned up

`components/migrateContent.ts` + tests, wired into `PageEditor` (draft load)
and all three `PublicPage` renders (page, layout header, layout footer).
Migration happens on the way *in*, so a draft nobody edits is never rewritten.

Writing the test for the success path is what surfaced the finding above:
**it has no success path today.** `migrate()` converts a legacy zone only into
a *slot field of the same name*, and grepping the whole module turns up zero
`type: 'slot'` fields — `Columns` is the only nesting block and it still
renders `<DropZone zone={\`col-${idx}\`} />`. Every populated `zones` map
therefore throws:

```
Could not migrate DropZone "C1:col-0" to slot field.
No slot exists with the name "col-0".
```

The catch path is the live path, not a defensive corner. That doesn't make
Phase 0 pointless — containing that throw is exactly what stops one bad zone
from blanking a page, and the legacy-root branch does migrate cleanly — but it
does move the `Columns`→slots port from "cleanup" to "the thing that unblocks
this." The tests assert the current limitation explicitly rather than skipping
it, so whoever does Phase 3 gets a failing expectation pointing at the work.

## 10. `Columns` on slot fields, and the rendering-mode decision

`Columns` now declares its slot *inside* its array field —
`columns: { width: number; content: Slot }[]` — so the column count stays
author-controlled. A top-level slot per column would have capped the block at
however many were declared.

Puck's built-in zone→slot conversion can't reach a slot nested in an array: it
only matches a zone against a top-level field of the same name. The escape
hatch is `migrateDynamicZonesForComponent`, which hands the block its props
plus its zones (keyed `col-0`, `col-1`, …) and takes whatever props come back.
`migrateColumnsZones` in `migrateContent.ts` does that fold, and §9's failing
expectation is now a passing one.

One deliberate choice inside it: the result is sized to cover **both** the
stored `columns` array and the zone indices. A page saved after a column was
deleted still carries that column's zone, and silently dropping author content
during a migration is the one failure here that can't be undone — so the
orphan resurfaces in a real column instead. There's a test for exactly that.

### Rendering mode: staying client-only

Switching the public viewer to Puck's `@puckeditor/core/rsc` entry was measured
and then **reverted on your instruction** to keep everything client-rendered:

| | root entry (current) | `/rsc` entry |
|---|---|---|
| public `/p/{slug}` | 1115 kB | 600 kB (**−46%**) |
| editor | 1132 kB | 1134 kB |
| shared | 478 kB | 478 kB |

Worth recording accurately for whenever this is revisited: `/rsc` is **not** a
server-rendering mode. It is a render-only entry that runs client-side exactly
like the root one — the name means it is *compatible* with server components
(it pulls in no editor hooks), not that it requires them. The saving is pure
tree-shaking: drag-and-drop, the field inspector and tiptap are dropped from a
page a visitor cannot edit. Nothing about the app's rendering model changes.

The `Columns`→slots port was the prerequisite either way, and it has landed —
so the switch is now a two-line change (`PublicPage`'s `Render` import and
`migrateContent`'s `migrate` import) whenever it's wanted. Both were verified
green on the full 46-test e2e suite before reverting.

## 11. All 36 widgets ported

Answering §8 Q1 with "port all widgets", so the layout question in §2 resolved
to option (a) as a side effect — `Container` / `Row` / `Column` / `Grid` all
landed alongside the existing `Columns`.

**The count now matches: 56 blocks on both sides.**

The port itself was mechanical, because the earlier work had already brought
across everything the widgets *depend on*. Only three import paths differ, and
one of those was a file we already had under a different name:

| GeoWiki | here |
|---|---|
| `../utils` | `../../utils/widgetUtils` |
| `../fields` | `../../fields` |
| `../conversion/markdown` | `../../utils/markdown` (same file) |

Three things needed judgement rather than a rewrite rule:

**Image fields.** GeoWiki declares them as plain text and swaps in the picker
centrally via `IMAGE_FIELDS` / `ARRAY_IMAGE_FIELDS` in `createPuckConfig`. This
module inlines `createImageField(mediaLibraryAdapter, …)` at the field instead,
so 12 fields across 11 widgets were converted by hand. One deliberate
divergence: GeoWiki patches `Leaderboard.top.avatarUrl` but not
`Leaderboard.rows.avatarUrl` — same avatar, same widget, and a picker on one
with a raw text box on the other is a worse editor, not a more faithful one, so
both are wired.

**Timeline.** At 472 lines it was the only widget over the 300-line cap, split
the way `media-object` already was: `timeline-layout.ts` (types + marker
geometry), `timeline-render.tsx`, `timeline-widget.tsx` (fields).

**The catalogue.** 56 entries would have pushed `puckConfig.tsx` well past the
cap, so the list moved to `widgetCatalog.ts`, leaving the config file with the
root definition and registry merge — the parts that don't grow. The props type
is now *derived* rather than hand-listed:

```ts
type PropsOf<T> = T extends ComponentConfig<infer P> ? P : never;
export type CatalogProps = {
  [K in keyof typeof catalogComponents]: PropsOf<(typeof catalogComponents)[K]>;
};
```

That replaces what would have been a second 56-entry list to keep in step, and
it fixes the slot problem from §10 generally: the old `WidgetProps` helper read
a block's props off its *render* signature, where Puck has already rewritten
`Slot` to `SlotComponent`. `PropsOf` reads them off the config, which carries
the stored form. Verified by type probe that it recovers real unions rather
than collapsing to `never` — an invalid heading level is still a compile error.

Categories were extended with **Interactive** (Accordion, Tabs) and **Utility**
(Html, Alert, SocialBanner, UnderConstruction, Welcome), and `CenteredHero` is
palette-hidden as it is upstream. `catalogCategories` is typed against the
catalogue's own keys, so a category naming a block that doesn't exist is a
compile error rather than an entry that silently never appears.

### Coverage

`widgetCatalog.test.tsx` renders **every** block with its own `defaultProps`
through `renderToStaticMarkup` — no jsdom needed, and it is what an author gets
the instant they drag one in. Plus three structural invariants: every block
filed under exactly one category, every block labelled, every field given a
default. Unit tests went 22 → 81.

That last invariant caught a real (if cosmetic) gap: the six original blocks
had no `label` while all 50 ported ones did. Puck falls back to the raw key, so
nothing was broken — but the palette was inconsistent, and it is now.

### Cost

| | before | after |
|---|---|---|
| public `/p/{slug}` | 1115 kB | 1179 kB |
| editor | 1132 kB | 1196 kB |
| shared | 478 kB | 478 kB |

**+64 kB for 36 widgets** — they share the `_shared` / `_internal` primitives
that were already in the bundle. For context, the `/rsc` switch from §10 is now
worth more than it was: it would take the public page to roughly 664 kB, well
under where it started.

## 12. The three primitives, and two places I didn't follow upstream

Button, Heading and Text now carry everything GeoWiki's do. Two of the three
deviate from upstream in how the data is *stored*, deliberately, and both
deviations mean **no migration was needed** — §3 planned two and neither
happened.

### Button — full port, plus defaults for old data

Gains `outline`, `size`, `color`, `indent`, rich-text labels, the theme-driven
radius and the optional trailing arrow. `primary`/`ghost` now read the branding
ramp (`bg-primary-700`) instead of the hardcoded `bg-blue-600`, so the block
follows Settings → Branding like the other 55.

`size`, `color` and `indent` are defaulted **in the render signature**, not
only in `defaultProps`. `defaultProps` applies to a block dropped now; every
Button already on a page predates these fields and arrives with them undefined.
Upstream doesn't default `size` either — it presumably had no such data.

### Heading — port the rendering, keep the enum

Gains rich text, the `--pb-heading-color` / `--pb-display-*` tokens and the
container wrapper, and its hardcoded `font-bold` is gone so design packs can
actually reach it.

**`level` stays `h1`…`h6` rather than upstream's `1`…`6`.** §3 called this
"data-incompatible, requires a migration" — but the enum is an internal
representation no author ever sees. Adopting the other spelling would mean
migrating every stored Heading to change nothing visible. Parity is in what the
block can express, not in how the value is spelled.

This also removes the §3 alignment hazard: `text-${align}` is now a lookup map,
so it no longer depends on those class names happening to appear literally in
other files.

### Text — rich text, without stored HTML

Gains the `size` prop and renders through `RichTextBlock`, so authors get bold,
italic, code, links, bullets and paragraphs.

**It stays a `textarea`, not Puck's `richtext` field.** That was §8 Q4 — "does
Text becoming rich text change the public CSP?" The answer is to not create the
question. Puck's `richtext` stores HTML and hands it to Puck to render;
`RichTextBlock` parses light markdown into React elements and never builds
anything from stored markup (it also drops `javascript:` hrefs). Same expressive
range for the author, no injection surface.

That matters more here than upstream. Pages reach the public viewer through a
review workflow, so not every author is fully trusted; and the CSP that would
otherwise be the backstop is `SM_PAGEBUILDER_PUBLIC_CSP` — operator-tunable,
documented as safe to empty. Relying on it to contain stored HTML would be
betting on a setting whose whole purpose is to be changed. It also keeps this
block consistent with the other 50, which all render copy this way.

### A test that didn't test anything

The first version of the backward-compatibility test asserted the rendered HTML
didn't contain the string `"undefined"`. It passed with the default deliberately
removed — `cn()` drops undefined values silently, so a Button missing `size`
renders with *no* size classes rather than a broken one. The assertion is now
that the expected class is present, and that version does fail when the default
is taken away. Worth stating because the failure mode is invisible: nothing
crashes, the button is just unstyled.

## 13. Measurement

Re-run the parity count with:

```bash
G=/home/anto/Repos/IIASA.GeoWiki/frontend/packages/pagebuilder/src
grep -cE '^\t[A-Z][A-Za-z]+: [A-Z]' $G/config/puck-config.ts   # GeoWiki widget count
grep -cE '^    [A-Z][A-Za-z]+: [A-Z]' \
  modules/pagebuilder/pagebuilder/components/puckConfig.tsx     # ours
```

Today: 55 vs 20.
