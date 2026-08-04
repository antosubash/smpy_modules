# PageBuilder UX improvements — design

**Date:** 2026-08-03
**Status:** Approved

## Why

Driving the running app surfaced three problems that no test covers, because
all three are about what the user sees rather than what the server returns.

1. **Navigation dead-end.** Every first-party page ends with
   `Page.layout = (page) => <AuthenticatedLayout>{page}</AuthenticatedLayout>`.
   No pagebuilder page sets `.layout`, so entering pagebuilder from the
   dashboard drops the sidebar and user menu — the only way back is the
   browser's back button.
2. **Two Publish buttons that do different things.** `PageEditor.tsx` wires
   Puck's `onPublish` to `handleSave`, so Puck's prominent blue **Publish**
   saves a *draft*. The real publish is the smaller button in the outer
   toolbar. Puck's header also renders a stale "Untitled page" beside the
   live title field, and the two stacked bars cost ~110px above the canvas.
3. **Visually a different product.** Pagebuilder hand-rolls Tailwind
   (`px-4 py-2 rounded border`) while Users and Dashboard use the shared
   `Button` / `Card` / `Table` / `Badge` primitives.

## Constraints

The e2e suite selects by **accessible role and name**, not CSS. That makes it
a genuine regression net for a restyle, and it fixes hard requirements:

- `PageList` keeps semantic `<tr>` rows — `locator('tr', {hasText: title})`.
- Page status renders as exactly lowercase `published` —
  `getByText('published', {exact: true})`.
- These accessible names survive verbatim: `Edit`, `Delete`, `Publish`,
  `Save draft`, `SEO`, `History (N)`, `New page`, `Media library`,
  `Copy URL`, `Browse media`, `Image`, `alt`, `width`, `height`.
- **`View` stays an `<a>`** — `getByRole('link', {name: /^view$/i})`.
- The media picker keeps `role="dialog"` with the accessible name
  "Media library picker".
- Every existing `data-testid` stays: `diff-summary`, `autosave-status`,
  `schedule-publish-at`, `schedule-unpublish-at`, `schedule-save`,
  `schedule-error`, `media-dropzone`, `upload-list`, `upload-row`,
  `compare-{id}`, `json-ld-error`.
- The 300-line cap (`scripts/check_file_size.py`) still applies, with no
  exemptions — extracted components must respect it.

## 1. App shell and navigation

`PageList`, `PendingReview`, and `MediaLibrary` gain:

```tsx
PageList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
```

and use `PageShell` from `@simple-module-py/ui/components/PageShell` for the
title + actions row. `PageShell` renders `<h1>{title}</h1>`, so the
`heading` selectors keep matching; its `actions` slot takes the existing
buttons.

`PageEditor` and `LayoutEditor` deliberately stay full-bleed. They are
immersive canvases and a persistent sidebar would compete with Puck's own
panels. Their existing "← All pages" link remains the way out.

## 2. One publish action in the editor

The outer toolbar becomes the single source of truth for title, status, and
publish. Puck's own header is suppressed through its supported `overrides`
API (`Overrides` declares both `header` and `headerActions`).

**Open implementation detail, to be settled against the running editor:**
undo/redo lives in Puck's header. Overriding the whole `header` removes it,
trading one UX problem for another. Overriding only `headerActions` may
remove the Publish button while keeping undo/redo, or may take undo/redo with
it — the slot's exact contents are a runtime question.

The requirement, whichever mechanism is used:

- exactly one control labelled `Publish`, and it publishes;
- exactly one title field;
- undo/redo still reachable;
- `getByRole('button', {name: /^publish$/i})` still resolves to one element.

Once Puck's header is gone, `onPublish` is unreachable from the UI. It stays
wired to `handleSave` only if Puck requires the prop; otherwise it goes.

## 3. Shared UI primitives

Replace hand-rolled Tailwind with `@simple-module-py/ui` primitives across
`PageList`, `PendingReview`, `MediaLibrary`, and the extracted editor
components:

| Current | Becomes |
|---|---|
| `<button className="px-4 py-2 rounded border …">` | `<Button variant="outline">` |
| `<button className="… bg-blue-600 text-white">` | `<Button>` |
| hand-rolled table markup | `Table` / `TableHeader` / `TableBody` / `TableRow` / `TableCell` |
| status `<span>` in `StatusBadge` | `Badge`, text unchanged |
| `<input className="border rounded …">` | `Input` |
| bordered `<div>` panels | `Card` |

`StatusBadge` keeps emitting lowercase status text. `Button` renders a real
`<button>` and `Badge` a `<span>`, so roles and names are preserved by
construction.

## Verification

The e2e suite runs after **each** page is converted, not once at the end, so
a broken selector points at a single file. Then:

- `make e2e` — 22 specs
- `make test-py` — 167 module + 13 host/script tests
- `make lint` — ruff, biome, file size, metadata, version sync
- A browser pass over each changed page, reading the screenshots

## Out of scope

- Restyling the public viewer (`PublicPage.tsx`) — it renders author-composed
  content and the site layout feature already governs its framing.
- The Puck canvas itself.
- The missing favicon (host scaffold, not this module).
- `HEAD /p/{slug}` returning 405 — pre-existing, unrelated to UX.
