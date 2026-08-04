# PageBuilder UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pagebuilder admin feel like part of the app — persistent navigation, one unambiguous publish action, and the shared UI primitives.

**Architecture:** Three independent changes to `modules/pagebuilder`, each verified by the existing Playwright suite before the next begins. No server-side changes; no API changes.

**Tech Stack:** React 19, Inertia.js, `@simple-module-py/ui` (shadcn-based), Puck 0.19, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-03-pagebuilder-ux-design.md`

## Global Constraints

The e2e suite selects by **accessible role and name**. These must survive verbatim:

- `getByRole('heading', {name: 'Pages'})` and `{name: 'Media library'}`
- Buttons named exactly: `Edit`, `Delete`, `Publish`, `Save draft`, `SEO`, `New page`, `Media library`, `Unpublish`, `Copy URL`, `Browse media`, `Image`, and `History (N)` matching `/history \(\d+\)/i`
- **`View` is an `<a>`** — `getByRole('link', {name: /^view$/i})`. Never a `<button>`.
- `PageList` keeps semantic `<tr>` rows — `page.locator('tr', {hasText: title})`
- Status text stays exactly lowercase `published` — `getByText('published', {exact: true})`
- Media picker keeps `role="dialog"` named "Media library picker"
- Fields named `alt`, `width`, `height` keep their roles (`textbox`, `spinbutton`)

Every existing `data-testid` stays: `diff-summary`, `autosave-status`, `schedule-publish-at`, `schedule-unpublish-at`, `schedule-save`, `schedule-error`, `media-dropzone`, `upload-list`, `upload-row`, `compare-{id}`, `json-ld-error`.

Other constraints:

- **No new files under `modules/pagebuilder/pagebuilder/pages/`** — a `.tsx` there registers an Inertia page.
- **300-line cap** on every `.py`/`.ts`/`.tsx` (`scripts/check_file_size.py`, no exemptions).
- Run all commands from the repo root: `/Volumes/ext1/emdash/worktrees/simple_module_python_modules/features/init-i8ghw`.

**Import paths** (as used by `users/pages/Users/Index.tsx`):

```tsx
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Card } from '@simple-module-py/ui/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@simple-module-py/ui/components/ui/table';
```

`Button` renders a real `<button>`; `Badge` renders a `<span>`. Roles and accessible names are preserved by construction as long as the visible text is unchanged.

**Verification loop** used at the end of every task:

```bash
make kill >/dev/null 2>&1
npm run build 2>&1 | tail -3
npm run test:e2e 2>&1 | grep -E "passed|failed|✘" | tail -3
make kill >/dev/null 2>&1
uv run python scripts/check_file_size.py
npx biome check .
```

---

### Task 1: App shell and navigation

Gives `PageList`, `PendingReview`, and `MediaLibrary` the sidebar, the user menu, and a consistent page header.

**Files:**
- Modify: `modules/pagebuilder/pagebuilder/pages/PageList.tsx`
- Modify: `modules/pagebuilder/pagebuilder/pages/PendingReview.tsx`
- Modify: `modules/pagebuilder/pagebuilder/pages/MediaLibrary.tsx`
- Modify: `modules/pagebuilder/pagebuilder/components/media/MediaHeader.tsx`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: all three pages export a `.layout` property; their `<h1>` now comes from `PageShell`.

- [ ] **Step 1: Wrap PageList**

Replace the outer `<div className="max-w-5xl mx-auto p-8">` and its header block with `PageShell`, and add the layout export at the bottom of the file.

```tsx
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import type React from 'react';
```

```tsx
  return (
    <PageShell
      title="Pages"
      description="Compose, review, and publish site pages."
      actions={
        <>
          <button type="button" onClick={() => router.visit('/pagebuilder/pending')} className="px-4 py-2 rounded border hover:bg-gray-50 font-medium">
            Pending review
          </button>
          <button type="button" onClick={() => router.visit('/pagebuilder/layout')} className="px-4 py-2 rounded border hover:bg-gray-50 font-medium">
            Site layout
          </button>
          <button type="button" onClick={() => router.visit('/pagebuilder/media')} className="px-4 py-2 rounded border hover:bg-gray-50 font-medium">
            Media library
          </button>
          <button type="button" onClick={() => router.visit('/pagebuilder/new')} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded font-medium">
            New page
          </button>
        </>
      }
    >
      {/* existing empty-state / table markup, unchanged */}
    </PageShell>
  );
}

PageList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
```

Buttons keep their raw Tailwind here — Task 3 converts them. Changing layout and styling in one step would make a selector break impossible to attribute.

`PageShell` already renders `<h1>Pages</h1>`, so delete the old `<h1>` rather than nesting a second one.

- [ ] **Step 2: Verify PageList alone**

```bash
npm run build 2>&1 | tail -2
npx playwright test tests/e2e/pagebuilder.spec.ts 2>&1 | grep -E "passed|failed|✘" | tail -3
make kill >/dev/null 2>&1
```

Expected: build clean, 4 specs pass. A failure on `getByRole('heading', {name: 'Pages'})` means two `<h1>`s exist — remove the leftover.

- [ ] **Step 3: Wrap PendingReview**

Same shape. Its heading is `Pending review`; no e2e spec asserts on it, but keep the text identical anyway.

```tsx
  return (
    <PageShell
      title="Pending review"
      description="Pages submitted for approval."
      actions={
        <button type="button" onClick={() => router.visit('/pagebuilder')} className="px-4 py-2 rounded border hover:bg-gray-50 font-medium">
          ← All pages
        </button>
      }
    >
      {/* existing message + table markup, unchanged */}
    </PageShell>
  );
}

PendingReview.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
```

- [ ] **Step 4: Wrap MediaLibrary**

`MediaLibrary` renders its header through `components/media/MediaHeader.tsx`, which owns the `<h1>Media library</h1>` and the file input. Keep the file input — the e2e uses it — but move the heading to `PageShell`.

In `MediaHeader.tsx`, delete the `<h1>` and the wrapping flex `<div>`, leaving only the actions:

```tsx
export function MediaHeader({ fileInputRef, onFilesSelected }: Props) {
  return (
    <>
      <button
        type="button"
        onClick={() => router.visit('/pagebuilder')}
        className="px-4 py-2 rounded border hover:bg-gray-50 font-medium"
      >
        ← Pages
      </button>
      <label className="px-4 py-2 rounded font-medium cursor-pointer text-white bg-blue-600 hover:bg-blue-700">
        Upload
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={onFilesSelected}
        />
      </label>
    </>
  );
}
```

In `MediaLibrary.tsx`, replace the outer `<div className="max-w-7xl mx-auto p-8">` with `PageShell` and pass `<MediaHeader …/>` as `actions`:

```tsx
    <PageShell
      title="Media library"
      description="Images available to every page."
      maxWidth="full"
      actions={<MediaHeader fileInputRef={fileInputRef} onFilesSelected={onFileInputChange} />}
    >
      {/* existing grid layout, unchanged */}
    </PageShell>
```

```tsx
MediaLibrary.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
```

`maxWidth="full"` because the asset grid wants the width; `PageShell` defaults to `screen-xl`.

- [ ] **Step 5: Full verification**

```bash
npm run build 2>&1 | tail -2
npm run test:e2e 2>&1 | grep -E "passed|failed|✘" | tail -3
make kill >/dev/null 2>&1
uv run python scripts/check_file_size.py
npx biome check .
```

Expected: 22 passed, no oversized files, biome clean.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Give the pagebuilder admin pages the app shell

PageList, PendingReview and MediaLibrary now render inside
AuthenticatedLayout with a PageShell header, so the sidebar and user menu
persist. The editors stay full-bleed by design."
```

---

### Task 2: One publish action in the editor

**Files:**
- Modify: `modules/pagebuilder/pagebuilder/pages/PageEditor.tsx`

**Interfaces:**
- Consumes: `usePageWorkflow` from Task 0 (already exists — `handleSave`, `handlePublish`).
- Produces: no new exports.

- [ ] **Step 1: Establish what Puck's header holds**

Before changing anything, look at the running editor and record which controls live in Puck's header versus the canvas bar below it.

```bash
make kill >/dev/null 2>&1
make dev > /tmp/devserver.log 2>&1 &
until curl -sf -o /dev/null http://localhost:8000/users/login; do sleep 1; done
```

Open `http://localhost:8000/pagebuilder/1/edit` and note: the panel-toggle icons, the centred title, undo/redo, and the blue Publish. The viewport switcher and zoom sit in a separate bar and are unaffected.

- [ ] **Step 2: Suppress Puck's header**

`Overrides` (in `@measured/puck/dist/walk-tree-*.d.ts`) declares `header: RenderFunc<{actions: ReactNode; children: ReactNode}>` and `headerActions: RenderFunc<{children: ReactNode}>`.

Try `headerActions` first — it is the narrower cut:

```tsx
        <Puck
          config={puckConfig}
          data={form.data}
          viewports={editorViewports}
          iframe={{ enabled: true }}
          overrides={{ headerActions: () => null }}
          onChange={form.setData}
        />
```

Reload the editor and check whether undo/redo survived.

- If undo/redo **survived**: done — the outer toolbar is now the only Publish.
- If undo/redo **went with it**: revert to overriding `header` instead and re-expose the actions Puck passes in, minus its Publish:

```tsx
          overrides={{
            header: ({ actions }) => (
              <div className="flex items-center justify-end gap-2 border-b px-4 py-2">{actions}</div>
            ),
          }}
```

If `actions` itself contains Puck's Publish button, keep `header` overridden to `() => null` and accept the loss, but **say so in the commit message** — losing undo/redo is a real cost and must not be silent.

- [ ] **Step 3: Drop the dead onPublish**

With Puck's header gone, `onPublish` is unreachable from the UI. Remove it:

```tsx
          onChange={form.setData}
```

If the build complains that `onPublish` is required, keep it wired to `workflow.handleSave` and add a one-line comment saying it is unreachable and only satisfies the prop type.

- [ ] **Step 4: Verify exactly one Publish exists**

```bash
npm run build 2>&1 | tail -2
npm run test:e2e 2>&1 | grep -E "passed|failed|✘" | tail -3
make kill >/dev/null 2>&1
```

Expected: 22 passed. `getByRole('button', {name: /^publish$/i})` is unscoped, so had two elements matched, Playwright's strict mode would already be failing — one match after this change is strictly safer.

- [ ] **Step 5: Confirm in the browser**

Reload `/pagebuilder/1/edit`, screenshot it, and **look at the screenshot**. Confirm: one title field, one Publish button, undo/redo present or explicitly accounted for, and the canvas gained the vertical space.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Give the editor one unambiguous publish action

Puck's header duplicated the title and its prominent Publish was wired to
handleSave — it saved a draft while the real publish sat in the outer
toolbar. Suppressed via Puck's overrides API so the toolbar is the single
source of truth."
```

---

### Task 3: Adopt the shared UI primitives

**Files:**
- Modify: `modules/pagebuilder/pagebuilder/components/StatusBadge.tsx`
- Modify: `modules/pagebuilder/pagebuilder/pages/PageList.tsx`
- Modify: `modules/pagebuilder/pagebuilder/pages/PendingReview.tsx`
- Modify: `modules/pagebuilder/pagebuilder/components/media/{MediaHeader,MediaFilters,MediaGrid,MediaFolderSidebar}.tsx`
- Modify: `modules/pagebuilder/pagebuilder/components/editor/PageEditorToolbar.tsx`

**Interfaces:**
- Consumes: the `PageShell` wrappers from Task 1.
- Produces: no API change. `StatusBadge` keeps its `{status}` prop and its rendered text.

- [ ] **Step 1: Convert StatusBadge**

The status text is asserted exactly (`getByText('published', {exact: true})`), so `LABELS` is untouched. Only the wrapper changes.

```tsx
import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { PageStatus } from '../utils/api';

// Text is asserted verbatim by the e2e suite — "published" must stay
// lowercase and unabbreviated.
const LABELS: Record<PageStatus, string> = {
  published: 'published',
  submitted_for_review: 'pending review',
  draft: 'draft',
};

const VARIANTS: Record<PageStatus, 'default' | 'secondary' | 'outline'> = {
  published: 'default',
  submitted_for_review: 'secondary',
  draft: 'outline',
};

export function StatusBadge({ status }: { status: PageStatus }) {
  return <Badge variant={VARIANTS[status]}>{LABELS[status]}</Badge>;
}
```

- [ ] **Step 2: Verify the badge alone**

```bash
npm run build 2>&1 | tail -2
npx playwright test tests/e2e/pagebuilder.spec.ts 2>&1 | grep -E "passed|failed|✘" | tail -3
make kill >/dev/null 2>&1
```

Expected: 4 passed. A failure on `getByText('published', {exact: true})` means `Badge` added surrounding whitespace or an icon — check the rendered text.

- [ ] **Step 3: Convert PageList**

Buttons → `Button`; the table → `Table` primitives. **`View` stays an `<a>`.**

```tsx
      actions={
        <>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/pending')}>
            Pending review
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/layout')}>
            Site layout
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/media')}>
            Media library
          </Button>
          <Button onClick={() => router.visit('/pagebuilder/new')}>New page</Button>
        </>
      }
```

```tsx
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Slug</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pages.items.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.title}</TableCell>
                <TableCell className="font-mono text-sm text-muted-foreground">{p.slug}</TableCell>
                <TableCell>
                  <StatusBadge status={p.status} />
                  <ScheduledBadge
                    status={p.status}
                    publishAt={p.publish_at}
                    unpublishAt={p.unpublish_at}
                  />
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                </TableCell>
                <TableCell className="text-right space-x-2">
                  {p.status === 'published' && (
                    <a
                      href={`/p/${p.slug}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-primary hover:underline"
                    >
                      View
                    </a>
                  )}
                  <Button variant="link" size="sm" onClick={() => router.visit(`/pagebuilder/${p.id}/edit`)}>
                    Edit
                  </Button>
                  <Button
                    variant="link"
                    size="sm"
                    className="text-destructive"
                    disabled={busy === p.id}
                    onClick={() => handleDelete(p.id)}
                  >
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
```

`TableRow` renders a `<tr>`, so `locator('tr', {hasText: title})` still matches.

- [ ] **Step 4: Verify PageList**

```bash
npm run build 2>&1 | tail -2
npx playwright test tests/e2e/pagebuilder.spec.ts 2>&1 | grep -E "passed|failed|✘" | tail -3
make kill >/dev/null 2>&1
```

Expected: 4 passed. Watch specifically for the `tr` locator and the `View` link.

- [ ] **Step 5: Convert PendingReview**

Same treatment — its Approve/Reject/`← All pages` buttons become `Button`, its table becomes the `Table` primitives. No e2e spec covers this page, so verify it by eye in Task 4's browser pass.

- [ ] **Step 6: Convert the media components**

- `MediaHeader.tsx` — `← Pages` becomes `Button variant="outline"`. **Leave the `<label>`-wrapped file input as raw markup**: `Button` renders a `<button>`, which cannot wrap a file input the way the label does.
- `MediaFilters.tsx` — the four inputs become `Input`; keep the `htmlFor`/`id` pairs added earlier.
- `MediaGrid.tsx` — each tile becomes a `Card`; `Copy URL` and `Delete` become `Button variant="link" size="sm"`. Keep the exact label `Copy URL`.
- `MediaFolderSidebar.tsx` — folder entries become `Button variant="ghost"`; keep the `htmlFor`/`id` on the upload-folder input and switch it to `Input`.

- [ ] **Step 7: Convert PageEditorToolbar**

Every button becomes `Button` with `size="sm"`. Preserve these labels exactly: `Save draft`, `SEO`, `History (N)`, `Publish`, `Unpublish`, `Submit for review`, `Approve`, `Reject`. Keep `View` as an `<a>`. Keep `data-testid="autosave-status"` on the status span.

- [ ] **Step 8: Full verification**

```bash
npm run build 2>&1 | tail -2
npm run test:e2e 2>&1 | grep -E "passed|failed|✘" | tail -3
make kill >/dev/null 2>&1
uv run python scripts/check_file_size.py
npx biome check .
uvx ruff check .
```

Expected: 22 passed, no oversized files, biome and ruff clean. If a component crossed 300 lines, extract the sub-block that grew — never add an exemption.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Adopt the shared UI primitives across the pagebuilder admin

Button, Badge, Card, Input and Table from @simple-module-py/ui replace
hand-rolled Tailwind, so pagebuilder matches Users and Dashboard. Accessible
names, the semantic tr rows, the lowercase status text and every data-testid
are unchanged — the e2e suite selects on all of them."
```

---

### Task 4: Browser verification

**Files:** none — this task only observes.

- [ ] **Step 1: Start the app**

```bash
make kill >/dev/null 2>&1
make dev > /tmp/devserver.log 2>&1 &
until curl -sf -o /dev/null http://localhost:8000/users/login; do sleep 1; done
```

- [ ] **Step 2: Walk every changed surface**

Log in as `admin@example.com` / `changeme1`, then visit and screenshot each of:

- `/dashboard/` — Content group present in the sidebar
- `/pagebuilder/` — sidebar persists, table styled, `View`/`Edit`/`Delete` present
- `/pagebuilder/pending` — sidebar persists
- `/pagebuilder/media` — sidebar persists, grid uses cards
- `/pagebuilder/1/edit` — one title, one Publish, undo/redo accounted for

**Read every screenshot.** A blank frame or a missing sidebar is a failure, not a rendering delay.

- [ ] **Step 3: Confirm the public surface is untouched**

```bash
for u in /p/launch-announcement /sitemap.xml /robots.txt; do
  printf "%-28s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000$u)"
done
for u in /pagebuilder/ /api/pagebuilder/pages; do
  printf "%-28s %s\n" "$u" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000$u)"
done
```

Expected: `200 200 200` then `302 401`. This restyle must not have moved the auth boundary.

- [ ] **Step 4: Stop the app and confirm a clean tree**

```bash
make kill
git status --short   # expect no stray screenshots or .playwright-mcp/
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| 1. App shell and navigation | Task 1 |
| 2. One publish action (incl. the undo/redo open question) | Task 2 Steps 1–2 |
| 3. Shared UI primitives (full swap table) | Task 3 |
| e2e selector constraints | Global Constraints + per-step verification |
| Verification (e2e after each page, lint, browser pass) | Tasks 1–4 |
| Out of scope (PublicPage, Puck canvas, favicon, HEAD 405) | Not implemented, by design |

**Type consistency:** `StatusBadge` keeps its `{status: PageStatus}` prop across Tasks 1 and 3. `MediaHeader`'s props (`fileInputRef`, `onFilesSelected`) are unchanged in Task 1 Step 4 and Task 3 Step 6. `PageShell` takes `title`, `description`, `actions`, `maxWidth` — matching its declaration in `@simple-module-py/ui/src/components/PageShell.tsx`.

**Deliberate ordering:** Task 1 changes layout only and Task 3 changes styling only, on the same files. Combining them would make a selector regression impossible to attribute to either cause.
