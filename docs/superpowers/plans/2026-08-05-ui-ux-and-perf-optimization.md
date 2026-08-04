# UI/UX and performance plan — post Puck 0.22 upgrade

Written 2026-08-05, against the tree at `worktree-deps-upgrade` (Puck 0.22.4,
vite 8, TS 7). Every number below was measured from `host/static/dist` after a
production `npm run build`, by walking `.vite/manifest.json` transitively.

## Where the bytes go today

| Surface | Transitive JS | What it is |
|---|---:|---|
| Shared entry (`main.tsx`) | **478 kB** | paid by *every* page, login included |
| `/users/login` | 496 kB | shared + 18 kB |
| **Public page `/p/{slug}`** | **1112 kB** | shared + 489 kB `puckConfig` + Puck runtime |
| Editor `/pagebuilder/{id}/edit` | 1130 kB | shared + the same `puckConfig` |

The finding that matters: **a public page costs 98% of what the full editor
costs.** A reader who never edits anything downloads essentially the editor.

That is not a vague suspicion. The chunk public readers receive,
`assets/puckConfig-*.js` (489 kB), literally contains the media-picker UI:

```
$ grep -c "Pick from library or paste a URL" host/static/dist/assets/puckConfig-*.js
1
```

## Why — measured, not guessed

There are two doors into the editor runtime, and **the bundle only shrinks when
both are shut**. This was verified by building each variant:

| Change | Public bundle |
|---|---:|
| baseline today | 1112 kB |
| `Render` from `@puckeditor/core/rsc` only | 1114 kB — **no effect** |
| `DropZone` removed from `Columns` only | 1112 kB — **no effect** |
| **both together** | **597 kB — −46%** |

Editor stays 1130 kB throughout, so the saving is not stolen from authors.

Do not try these one at a time and conclude the idea failed. Either change on
its own leaves a live path to the editor runtime, and the win looks like zero.

**Door 1 — `PublicPage` imports the editor entry.**
`import { Render } from '@puckeditor/core'` is the *editor* entry. Puck 0.22
ships a render-only one, `@puckeditor/core/rsc`, exporting just `Render`:

| Path | Puck chunks pulled |
|---|---:|
| `@puckeditor/core/rsc` | 15 + 3 + 12 = **~30 kB** |
| `@puckeditor/core` | the above **plus** `chunk-WH6PO5ND` **418 kB**, `chunk-KJQTOPIV` 65 kB, … |

**Door 2 — `Columns.tsx` imports `DropZone`, a runtime value.** It is the *only*
value import of Puck outside the two editor pages:

```
$ grep -rn "from '@puckeditor/core'" --include=*.tsx modules/ | grep -v "import type"
pages/PageEditor.tsx:      import { type Data, Puck } …     # editor, fine
pages/LayoutEditor.tsx:    import { type Data, Puck } …     # editor, fine
components/blocks/Columns.tsx: import { …, DropZone } …     # ← reaches every reader
```

`puckConfig` imports `ColumnsBlock`, so `DropZone` welds the editor runtime to
the config, and the config is what `<Render>` needs. Every other widget imports
Puck as `import type`, which erases at build time.

Closing door 2 properly means migrating `Columns` from `DropZone` to a **slot
field**. Puck has treated `DropZone` as legacy since 0.20 and slots are the
data-driven replacement. Note the consequence: the upgrade itself needed **no**
data migration, but this does — existing pages store `Columns` content under
zone keys, so it needs `migrate()` with `migrateDynamicZonesForComponent`.
Budget for a migration and a backup, and cover it with a test that loads a
pre-migration page.

**Also worth doing — `puckConfig.tsx` fuses edit-time and render-time.** Each
widget's `ComponentConfig` carries both `fields` (editor-only — field
definitions, the custom image picker, the checkbox field, the media adapter)
and `render`. This is what keeps the picker UI in the reader's chunk. Fixing
the two doors above removes the Puck runtime; this removes the remaining
editor-only *app* code from the 597 kB.

The repo already points at the fix: **6 of ~20 widgets** split `-render.tsx`
(pure render + types) from `-widget.tsx` (fields + config). `article-cards`,
`call-to-action`, `contact-form`, `faq`, `feature-cards`, `media-object` are
done; `hero`, `page-header`, `eyebrow-section`, `stats`, `tags`, `divider`,
`logo-cloud`, `contact-cards`, `site-header`, `site-footer` are not.

## Performance work, in priority order

### P1 — Get the editor runtime off public pages  ·  measured −46%, ship as one unit

**A and B must land together** to show any benefit (see the table above).

**A. Render-only entry.** In `PublicPage.tsx`, import `Render` from
`@puckeditor/core/rsc`. One line. The public-viewer e2e specs cover the
behaviour.

**B. `Columns` from `DropZone` to a slot field.** The real work, and the only
part carrying risk, because stored page data changes shape. Steps:

1. Redefine `Columns` with a slot field per column instead of
   `<DropZone zone={...} />`.
2. Write the data migration with `migrate()` +
   `migrateDynamicZonesForComponent`, mapping `col-{idx}` zones onto slots.
3. Run it over `draft_data` *and* `published_data`, plus stored revisions —
   a restore of an old revision must not resurrect the old shape.
4. Add a regression test that loads a pre-migration fixture and renders it.

Ship A and B in one PR, and measure before/after with the script below.

**C. Render-only config** *(follow-up, independent of A/B)*. Finish the
`-render.tsx` split for the remaining ~14 widgets, then add `publicPageConfig`
beside `getPuckConfig()` mapping each block to `{ render }` only — no `fields`,
so no picker, gallery or `mediaApi` for readers. Route it through the existing
block-registry seam so a module contributing blocks can supply a render-only
variant too; otherwise a registering module silently puts its fields back.

### P2 — Trim the 478 kB every page pays  ·  medium impact

`host/client_app/blocks.ts` registers blocks with **eager** globs, imported
from `app.tsx`, the app entry:

```ts
import.meta.glob('../../modules/*/*/puck-blocks.ts', { eager: true });
```

So a visitor on the login screen runs page-builder block registration. The
eagerness is deliberate and the comment explains why (a page-builder page reads
the config while rendering, and Inertia resolves pages too late). The fix is
therefore *not* to make it lazy — it is to make registration cheap: have
`puck-blocks.ts` register **render** references and lazy field factories, so
eager registration costs a module map rather than the whole widget surface.

Worth confirming first that the 422 kB `main` chunk is genuinely needed —
it is *not* full of unused UI-kit libraries (recharts, embla, day-picker, cmdk,
vaul all absent, so tree-shaking is working). Most of it is React + Inertia +
i18n + the used parts of the UI kit.

### P3 — Chunking and headers  ·  low effort

- The build warns `puckConfig` exceeds 500 kB. P1 likely dissolves this; if not,
  split by category (`sections`, `collections`, `forms`) via
  `build.rolldownOptions.output.codeSplitting`.
- Public responses already emit ETag, Cache-Control and CSP, and conditional
  GET returns 304 (covered by `public-viewer-headers.spec.ts`). No work needed.
- Backend queries are clean — the news list is a single JOIN with a subquery
  count and a grouped category aggregate. No N+1 to chase.
- Image variants (w320/w640, WebP, `srcset` + `sizes`) already generated.

## UI/UX work

### U1 — Decide on Puck 0.21's navigation rail  ·  needs a product call

0.21 replaced the stacked left sidebar with a rail: **Blocks / Outline** as
separate tabs (plus a mobile-only **Fields**). Authors who knew the old layout
will find the outline where the palette used to be. This upgrade takes the new
default; `legacySideBarPlugin` restores the old shell if you would rather not
retrain people yet. Either is one line in `PageEditor`/`LayoutEditor` — the
decision is yours, not technical.

### U2 — Accessibility gaps worth fixing  ·  real user impact

- **The rail is not keyboard reachable.** Its items render as
  `<li><div cursor:pointer>` with no button role — confirmed in a Playwright
  a11y snapshot, where they appear as `generic`, not controls. A keyboard or
  screen-reader user cannot switch to the Outline. This is upstream Puck;
  report it, and consider a local `overrides` shim in the meantime.
- **The field panel renders twice** (desktop sidebar + mobile drawer, one
  hidden). It is what made a placeholder lookup match two elements during the
  upgrade. Confirm the hidden copy is `display:none` rather than merely visually
  hidden — if it is only offscreen, duplicate form controls reach the a11y tree.

### U3 — Close the i18n gap  ·  known deferred work, now measurable

`CLAUDE.md` flags pagebuilder's copy as hardcoded English. It is broader than
that: **neither `pagebuilder` nor `news` ships a `locales/` directory**, while
the framework's own modules do (`branding/locales/en.json`). Every label,
button and empty state in both modules is untranslatable today. Extract to
`locales/en.json` per module and route through `@simple-module-py/i18n`, which
the host already configures and hot-swaps on navigation.

### U4 — Editor polish  ·  small

- `puckConfig.tsx` sets three viewports (360/768/1280). 0.21 added a full-width
  default; since we pass viewports explicitly the old behaviour is preserved.
  Consider adding full-width back deliberately — authors building full-bleed
  sections currently cannot preview them edge to edge.
- 21 Biome warnings remain, all pre-existing: unused imports in
  `*-render.tsx`/`media-object-text.tsx`/`MediaLibrary.tsx` (auto-fixable) and
  non-null assertions in the e2e helpers. `biome check --write` clears most.

## Suggested sequence

1. **P1-A + P1-B together** — the −46% is already measured; the work is the
   `Columns` slot migration and its data migration, not the discovery.
2. **U2** rail accessibility — cheap, and it is a correctness issue.
3. **U3** i18n — independent, parallelisable with anything.
4. **P1-C** render-only config — the wider refactor, once P1 is banked.
5. **P2**, **P3**, **U4** — after P1 has moved the numbers.

U1 blocks nothing but should be answered before authors meet the new rail.

## How to verify

Re-run this after each change; it prints the transitive weight per surface:

```python
import json, os
m = json.load(open('host/static/dist/.vite/manifest.json')); base = 'host/static/dist/'
def closure(k, seen=None):
    seen = seen or set(); stack = [k]
    while stack:
        x = stack.pop()
        if x in seen or x not in m: continue
        seen.add(x); stack += m[x].get('imports') or []
    return seen
for label, key in [('public', '../../modules/pagebuilder/pagebuilder/pages/PublicPage.tsx'),
                   ('editor', '../../modules/pagebuilder/pagebuilder/pages/PageEditor.tsx'),
                   ('shared', 'main.tsx')]:
    kb = sum(os.path.getsize(base + m[k]['file']) for k in closure(key)
             if m[k].get('file') and os.path.exists(base + m[k]['file'])) / 1024
    print(f'{label:8} {kb:7.0f} kB')
```

Guard rails already in place: `make lint`, 16 vitest, 219 pytest and 46
Playwright e2e all pass on the upgraded tree, so any regression from this work
should surface immediately.
