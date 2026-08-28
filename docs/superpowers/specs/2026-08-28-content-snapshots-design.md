# Content snapshots — import / export with approval — design

Date: 2026-08-28
Status: approved pending review

## Context

`pagebuilder` already manages change *within* a page well: `PageRevision` is an
append-only audit row written on every status transition, `diff.py` computes a
block-level diff keyed on Puck's `props.id`, revisions can be restored, and a
workflow moves a page through draft → submitted → approved → published /
unpublished / scheduled, gated by `pagebuilder.edit` / `.publish` / `.approve`.

What has no story is change to **the site as a whole**. The only tool for
moving content in bulk is `canopy_atlas/seed/`: a one-way HTTP bootstrap that
logs in, uploads `static/gca/images/*.jpg`, rewrites asset paths, and blind-PUTs
`seed/content/*.json` over any page matching on slug. It is fine for standing a
site up once. Afterwards it is a liability:

- edits made in the admin never flow anywhere — there is no export at all;
- re-running it silently overwrites those edits, with no plan and no dry run;
- there is no way to move content between hosts (dev → staging → prod);
- there is no restore point, so no way to undo a bad bulk change.

This design adds a **Content › Import / Export** admin section: server-kept
snapshots of the whole site, downloadable and uploadable as a `.zip`, where
restoring is staged for approval and is itself reversible.

## Decisions taken during brainstorming

Four forks were settled with the repo owner before this was written; they are
recorded because each closes off a design space someone will otherwise reopen.

1. **Repo ↔ DB round-trip** is the problem being solved — not editorial UX
   (the backend for that already exists) and not release-shipped content.
2. **Snapshot / restore, not plan / apply.** The database is the source of
   truth; a snapshot is a checkpoint. Restore always wins. No drift detection,
   no three-way merge — git and the snapshot list provide history.
3. **Self-contained bundles.** A snapshot carries the media binaries, so it
   restores onto an empty host. Not media-by-reference.
4. **UI, not CLI.** No `python -m` entry point. Bundle-level atomic approval,
   not per-page approval through the existing `PendingReview` queue, because a
   restore is one act and half-applying it leaves the site incoherent.

## Scope

**In:** snapshot capture, a server-side snapshot store with shared
content-addressed media blobs, `.zip` download and upload, a computed restore
plan, an approval gate before anything is applied, an automatic pre-restore
snapshot, and the two admin pages that drive all of it.

**Out (deliberately):**

- **News articles and any other module's content.** A snapshot is *pagebuilder
  content only*: pages (including templates), redirects, layout, media. A
  per-module contribution hook was considered and rejected for v1 — see Rejected
  alternatives.
- **Branding**, for the same reason and one more. `pagebuilder` currently has
  *no* Python dependency on the branding module — not one import — and capture
  runs in-process, so putting `app_name` / `primary_color` / `design_pack` in the
  bundle would force every pagebuilder host to install branding to get a feature
  that has nothing to do with it. Three fields are not worth a new hard
  dependency between two distributable modules. The per-module contribution hook
  is the mechanism that should eventually bring branding *and* news in together,
  through a seam rather than a coupling. Until then, re-pick the colour and
  design pack in Settings → Branding after restoring onto a fresh host.
- **Trashed pages, revision history, and scheduled-job state.** A snapshot is
  the site as it stands, not its past. `PageRevision` / `LayoutRevision` rows
  stay host-local; restoring history from another host would fabricate an audit
  trail that never happened there.
- **A `PageRevision` per restored page.** Every other mutation path appends one,
  so this is a deliberate exception rather than an oversight. The `pre_restore`
  snapshot already holds the previous state of *every* page, stored once with
  its media deduplicated by digest; writing one revision row per page would
  duplicate that whole before-state N times and recover nothing the snapshot
  cannot. The restore stays fully audited at the level it actually happens:
  who approved it, when, which snapshot, and the plan they saw. The cost is
  that a page's own history panel does not explain a change a bulk restore
  made — surfacing "restored from snapshot #N" there is the v2 fix, and it is
  a read-side change, not more rows.
- **Deleting live pages absent from a bundle.** Restore never deletes; pages on
  the site but not in the snapshot are left alone and reported. No `--prune`
  equivalent until there is a demonstrated need.
- **Drift detection and merge.** Excluded by decision 2 above.
- **Migrating `canopy_atlas.seed` onto this.** The seed keeps working untouched.
  Shipping GCA content as a bundle instead of a seed is a separate decision once
  this lands.
- **Retention policy / auto-pruning.** Manual delete only. Silently discarding
  someone's restore point is worse than disk usage, and §Blob store makes the
  disk cost small.
- **Scheduling snapshots.** No cron, no automatic daily capture.
- **i18n.** Repo-wide convention — see CLAUDE.md; this module is not translated
  and must not be converted piecemeal.

**Boundary rule:** the snapshot subsystem serialises and restores *content
state*. It does not interpret content. It never reaches inside a Puck block's
props beyond rewriting asset URLs, and it owns no editorial policy — approval
reuses the module's existing permissions rather than inventing its own.

## Architecture: one store, three sources

Everything the section lists is a **snapshot** row. The only thing that differs
is where it came from:

| source        | created by                                          |
|---------------|-----------------------------------------------------|
| `manual`      | the user clicking **Take snapshot**                 |
| `upload`      | a `.zip` brought in from another host               |
| `pre_restore` | automatically, immediately before a restore applies |

A restore stages a **pending import** that points at one snapshot. Unifying the
three sources is what keeps the subsystem small: *upload a bundle from prod* and
*roll back to yesterday* become the same code path, differing only in which
snapshot row the pending import references.

### Bundle format

The on-disk and in-zip layout generalises the existing `seed/content/` shape —
`_manifest.json` → `manifest.json`, `_layout.json` → `layout.json`,
`<slug>.json` → `pages/<slug>.json` — so the format is already familiar and the
GCA content could be converted mechanically later.

```
manifest.json        format_version, created_at, source, note, counts,
                     [{slug, title, status}]
layout.json          header_data, footer_data
redirects.json       [{from_slug, to_slug}]
pages/<slug>.json    slug, title, status, draft_data, published_data,
                     parent_slug, and every authored column on Page —
                     meta_title, meta_description, og_image,
                     canonical_url, index_in_search, json_ld,
                     show_in_header_nav, show_in_footer, is_template,
                     publish_at, unpublish_at
media/index.json     bundle_name -> {sha256, original_filename, folder,
                     content_type}
media/blobs/<sha256> the bytes (zip only; server-side these live in the
                     shared blob store, not per snapshot)
```

`format_version` is checked on upload and on restore. An unknown version is
rejected with a clear message rather than partially understood.

**Server-side, a snapshot is that same tree minus the blobs:**
`snapshot_root/snapshots/<id>/` holds `manifest.json`, `layout.json`,
`redirects.json`, `pages/*.json` and `media/index.json`, while the bytes live once
in the shared `snapshot_root/blobs/`. Download zips the two together; upload
splits them apart again. Keeping the documents as files rather than table
columns keeps multi-megabyte page JSON out of Postgres.

Pages carry **both** `draft_data` and `published_data`. A page whose draft
differs from what is published has work in flight; capturing only the draft and
publishing it on restore would quietly ship someone's unfinished edit.

### Identity across hosts: slugs, never ids

Primary keys are host-local. Two rows reference a page by id and both would be
meaningless in a bundle, so both serialise as slugs:

- **`Page.parent_id`** (breadcrumb parent) → `parent_slug`.
- **`PageRedirect.page_id`** → `to_slug`.

Restore therefore runs in **two passes**: upsert every page first, then resolve
`parent_slug` and rebuild redirects once all slugs exist. A single pass cannot
work — a parent may appear later in the manifest than its child, and a redirect
may point at a page the bundle creates in the same apply.

A `parent_slug` naming a page that is in neither the bundle nor the live site
resolves to `None` rather than failing: `Page.parent_id` is already
`ondelete="SET NULL"` precisely because a missing parent must not destroy a
child. A redirect whose `to_slug` is unresolvable is dropped and reported in the
plan — an unresolvable redirect is a 404 generator, not a nullable field.

**Trashed pages are never captured.** Capture applies the module's own
`NOT_TRASHED` filter, so a snapshot holds exactly what the site serves.
Restoring one therefore never resurrects something an editor binned. Templates
(`is_template`) *are* captured — a template is an ordinary page carrying a flag,
and a site without its starting points is not fully restored.

**Redirects are captured** because they are the site's promise to links already
out in the world. A restore that silently dropped them would convert every old
bookmark into a 404 — exactly the failure `PageRedirect` exists to prevent.

### Portable asset references

Media URLs are `f"{media_url_prefix}/{filename}"` where the filename is a UUID
assigned at upload — host-specific by construction. Serialising those verbatim
would produce a bundle whose images 404 on any other host.

So capture rewrites every media URL found in page and layout content
to a sentinel `asset://<original_filename>`, and restore rewrites the sentinel
back to whatever URL that file was given on *this* host. This is the inverse of
`canopy_atlas.seed.uploads.rewrite_asset_paths`, generalised and made
bidirectional.

Passing through untouched: module static-mount URLs (`/canopy-atlas/static/…`),
external absolute URLs, and in-site links like `/gca/contact`. Only URLs that
resolve to a row in the media library are rewritten — the mapping is built from
the media table, not guessed from string shape.

A sentinel naming an entry missing from `media/index.json` is a malformed bundle
and fails validation at upload, not at apply time.

**Duplicate names.** `original_filename` is a label, not a key — nothing stops a
library holding two different files both called `hero.jpg`. Capture therefore
writes a *bundle name*, disambiguating collisions as `hero.jpg`, `hero~2.jpg`,
and records the true `original_filename` beside it in the index. The sentinel
carries the bundle name, so it stays readable in a diff while remaining
unambiguous. Deterministic ordering (by media id) keeps the suffixes stable
across repeated captures, which is what makes the round-trip test meaningful.

**Two different keys, deliberately.** `sha256` identifies *blobs in the snapshot
store*, so unchanged media is stored once across many snapshots. Restoring into
the media library matches on `original_filename` instead — the same rule the GCA
seed already uses, so re-running is idempotent and page content keeps pointing
at the same asset. This is why `MediaAsset` needs no new content-hash column:
each concern uses the key that suits it, and neither leaks into the other.

### Thumbnails are never stored

`MediaAsset.variants` holds server-generated webp derivatives at
`media_thumbnail_widths`. Bundles carry only the original bytes; on restore the
blob goes back through the normal upload pipeline, which regenerates variants
against the *current* settings. This keeps bundles substantially smaller and
prevents a snapshot from restoring derivatives that no longer match the host's
thumbnail configuration.

### Blob store: content-addressed and shared

Media blobs are stored once per `sha256` under `snapshot_root/blobs/<sha256>`
and referenced by every snapshot that contains them. Ten snapshots of a site
whose photographs have not changed cost one copy of the photographs.

Without this, every snapshot of the GCA site is another ~4 MB and the feature
becomes unusable on any real site — which would push people back to the seed.

Deleting a snapshot deletes only the blobs no surviving snapshot references.

### Restore is reversible

Applying a pending import **always takes a `pre_restore` snapshot first**. This
is the difference between a feature that can be handed to a site owner and one
that cannot: "Approve & apply" is alarming precisely because it overwrites nine
pages, and it stops being alarming when the previous state is one click away.

The apply itself runs in a single transaction: media upserted by
`original_filename`, pages upserted by slug, then the second pass wiring
`parent_slug` and redirects, then the layout. Any failure rolls back
and the pending import stays pending, so a half-restored site is not a reachable
state.

## Data model

Three tables, SQLModel in the module; the migration goes in
`host/migrations/versions/` on pagebuilder's existing branch label, per
CLAUDE.md.

- **`pagebuilder_snapshots`** — `note`, `source`
  (`manual` | `upload` | `pre_restore`), `format_version`, `manifest` (JSON:
  counts + page list, enough to render the list row without opening blobs),
  `size_bytes`, plus `AuditMixin` for created_at / created_by.
- **`pagebuilder_snapshot_media`** — `snapshot_id`, `sha256`, `bundle_name`,
  `original_filename`, `folder`, `content_type`. The join that makes blob
  sharing and reference-counted deletion work without opening any file.
- **`pagebuilder_pending_imports`** — `snapshot_id`, `plan` (JSON), `status`
  (`pending` | `approved` | `rejected`), `decided_at`, `decided_by`, `note`,
  plus `AuditMixin`.

The documents themselves are files under `snapshot_root` — see Bundle format.
The tables hold only what the UI lists and what blob GC needs.

## The plan

Requesting a restore computes a plan and stores it on the pending import. The
plan classifies every item:

- pages: `new` / `overwritten` / `unchanged`, with a block-level summary for
  overwritten pages reusing `diff.py`'s `props.id` pairing;
- layout: changed or not, with header / footer block counts;
- media: how many blobs are new versus already present;
- redirects: added / removed, and any dropped for an unresolvable target;
- pages live on this site but absent from the bundle, listed as untouched.

The plan is what the approver reads. It is computed once, at request time, and
§Permissions and concurrency keeps it honest.

## API surface

All under the module's existing `/api/pagebuilder` prefix, in a new
`endpoints/api/snapshots.py`. No new endpoints are needed on the read side:
capture reads through the existing services in-process rather than making HTTP
calls back into the app.

```
GET    /snapshots                      list
POST   /snapshots                      take one now  (note in body)
GET    /snapshots/{id}/download        stream .zip
DELETE /snapshots/{id}                 delete + drop unreferenced blobs
POST   /snapshots/upload               multipart .zip -> snapshot(source=upload)
POST   /snapshots/{id}/restore         compute plan, stage pending import
GET    /imports/pending                the one pending import + plan, or null
POST   /imports/{id}/approve           apply atomically
POST   /imports/{id}/reject            discard  (note in body)
```

## Admin UI

Sidebar item **Import / Export** in the existing Content group, `order=230`
(after Media library at 220), registered in `register_menu_items`. Following the
comment already there, the item is not role-gated — the views require
authentication and the write endpoints carry the permission dependencies.

Two Inertia pages, both real pages (CLAUDE.md: nothing else goes under
`pages/`):

- **`ContentSnapshots.tsx`** — Take snapshot / Upload bundle actions, and the
  snapshot list showing date, author, note, contents summary, size, with
  Download / Restore / Delete. A banner links to any pending import.
- **`ContentImportReview.tsx`** — the plan, grouped pages / redirects / layout /
  media, an explicit count of what will be overwritten, and Approve & apply /
  Reject.

Supporting components go in `components/snapshots/` and hooks in `hooks/` —
never under `pages/` — and every file stays under the 300-line cap enforced by
`scripts/check_file_size.py`.

## Permissions and concurrency

No new permissions. Reusing the existing three:

- take / download / upload / delete / request restore — `pagebuilder.publish`
- approve or reject a pending import — `pagebuilder.approve`

**Self-approval is allowed**, matching the page workflow: `_workflow.approve`
carries no submitter check, and imports should not be stricter than pages
without a deliberate decision to tighten both.

**At most one pending import exists at a time.** A second restore request is
refused while one awaits a decision. A plan computed against content that has
since changed misrepresents what apply will do, and the cheapest way to keep the
plan honest is to keep it singular.

## Settings

Two additions to `PagebuilderSettings` (`SM_PAGEBUILDER_*`):

- `snapshot_root: Path = Path("var/pagebuilder/snapshots")` — resolved through
  the same project-root anchoring as `media_root`. A cwd-relative default is
  what caused issue #14, where two differently-launched processes read and wrote
  different media directories against one database.
- `snapshot_max_upload_bytes: int = 200 * 1024 * 1024`.

## Rejected alternatives

- **Plan/apply with drift blocking (Terraform-shaped).** Refuse to overwrite a
  page whose DB copy changed since the last export. Rejected: it presumes the
  repo is the source of truth, and the owner's model is that the database is.
- **Three-way merge per block.** Track the base revision each file was exported
  from and auto-merge non-conflicting blocks. Rejected as far more machinery for
  a case that stays unresolvable anyway — Puck block props are opaque blobs, so
  two edits inside one block cannot be merged automatically regardless.
- **Per-page approval through the existing `PendingReview` queue.** Maximum
  reuse, but layout, redirects and media have no per-item workflow, so they would
  have to apply immediately on upload — approving pages one at a time while the
  header and footer have already changed underneath them.
- **Per-module contribution hook** letting `news` add its articles to the
  bundle. Genuinely useful and the likely v2, but it turns a concrete format
  into an extension point before there is a second implementor, and the pending
  import's atomic transaction would have to span modules.
- **A CLI (`python -m pagebuilder.content`).** Explicitly not wanted.
- **Files only, no server-side store.** Simplest, but gives no history in the
  UI, and restore points would be only as good as wherever the zips were filed.
- **Server-side snapshots with no zip.** Loses host-to-host movement and any
  off-box copy if the database is lost.

## Testing

The load-bearing property is **round-trip fidelity**: take a snapshot, restore
it onto a wiped database, take another, and the manifest and every page document
must be identical. Everything else supports that.

- `asset://` rewriting both directions: content with no media; a URL not in the
  library (must pass through); a static-mount URL (must pass through); a
  sentinel missing from `media/index.json` (must fail validation at upload).
- Duplicate `original_filename`: two different files both named `hero.jpg` get
  distinct bundle names, both restore, and the suffixes are stable across two
  consecutive captures.
- Trashed pages are absent from a capture, and restoring does not resurrect
  them; templates *are* captured.
- `parent_slug` survives a round-trip when the parent sorts after the child in
  the manifest; an unresolvable parent restores as `None` rather than failing.
- Redirects round-trip by slug; one whose target is unresolvable is dropped and
  named in the plan.
- Plan classification: new / overwritten / unchanged, and pages present live but
  absent from the bundle reported as untouched.
- Blob sharing: two snapshots of unchanged media store one blob; deleting one
  snapshot keeps blobs the other still references.
- Thumbnails regenerate on restore rather than arriving from the bundle.
- Approval gating: `pagebuilder.publish` alone cannot approve; a second restore
  request is refused while one is pending.
- Atomicity: a failure mid-apply rolls back with the pending import still
  pending and the site unchanged.
- The `pre_restore` snapshot is taken before apply and can itself be restored.
- Format version: an unknown `format_version` is rejected on upload.
- e2e: snapshot the seeded GCA site, wipe it, upload the zip, approve, and
  confirm the photographs render on `/p/home`.

## Constraints this design must respect

From CLAUDE.md, each of which has bitten this repo before:

- 300-line cap on every `.py` / `.ts` / `.tsx`, `modules/` included — hence the
  file split below rather than one `snapshots.py`.
- The migration lives in `host/migrations/versions/`, never in the module.
- Nothing new under `pagebuilder/pages/` that is not a real Inertia page.
- No `==` framework pin in a published module.
- Versions are lockstep and only `scripts/bump_version.py` edits them.

## File layout

```
modules/pagebuilder/pagebuilder/
  snapshots/
    format.py        bundle layout constants, manifest schema, format_version
    assets.py        asset:// rewriting, both directions
    blobs.py         content-addressed store, reference-counted delete
    archive.py       zip read / write / validate
    capture.py       live content -> snapshot
    plan.py          snapshot vs live -> plan
    apply.py         atomic restore
    service.py       orchestration + DB rows
  endpoints/api/snapshots.py
  models/_snapshot.py          3 tables, re-exported from models/__init__.py
  contracts/schemas.py         + schemas
  settings.py                  +2 settings
  module.py                    + menu item
  pages/ContentSnapshots.tsx
  pages/ContentImportReview.tsx
  components/snapshots/SnapshotList.tsx
  components/snapshots/UploadBundleDialog.tsx
  components/snapshots/ImportPlanSummary.tsx
  hooks/useSnapshots.ts
  utils/api.ts                 + client calls

host/migrations/versions/<rev>_pagebuilder_snapshots.py
```
