# Content bundle format

A **bundle** is what **Download** on the Import / Export screen produces and
what **Upload bundle…** accepts: a `.zip` holding one snapshot of a site's
pagebuilder content. This document is the format's contract. The reader and
writer are `pagebuilder/snapshots/manifest.py` (the manifest) and
`archive.py` / `validate.py` (the rest of the zip); if they and this page
disagree, that is a bug in one of them.

## Layout

```
manifest.json            what wrote the bundle, and what it contains (below)
layout.json              {"header_data", "footer_data"}
redirects.json           [{"from_slug", "locale", "to_slug"}]
pages/<slug>.json        one page in the default content locale
pages/<locale>__<slug>.json   one page in any other locale
media/index.json         {bundle_name: {"sha256", "original_filename",
                          "content_type", "folder"}}
media/blobs/<sha256>     the bytes of each media file
```

Page documents carry `slug`, `locale`, `title`, `status`, `draft_data`,
`published_data`, `parent_slug`, `translation_group` and every authored column
on `Page`. Media URLs inside content are written as `asset://<bundle_name>`
sentinels and resolved against the destination host's media library on
restore. Pages and redirects name each other by `(locale, slug)`, never by id.

Server-side, a snapshot is the same tree minus `media/blobs/`; the bytes live
once per tenant in the shared blob store.

## The manifest

```json
{
  "format": "simple-module.content-bundle",
  "format_version": 2,
  "format_minor": 2,
  "created_at": "2026-10-22T09:00:00+00:00",
  "source": {
    "module": "pagebuilder",
    "package": "simple_module_pagebuilder",
    "version": "0.0.11"
  },
  "tenant": "default",
  "contents": [
    {
      "section": "pagebuilder",
      "version": 1,
      "required": true,
      "paths": ["layout.json", "redirects.json", "pages/", "media/"],
      "counts": {"pages": 12, "redirects": 4, "media": 9}
    }
  ],
  "pages": [{"slug", "locale", "title", "status", "parent_slug"}],
  "layout": {"header": 3, "footer": 2},
  "counts": {"pages": 12, "redirects": 4, "media": 9},
  "missing_media": []
}
```

| Key | Meaning |
|---|---|
| `format` | Always `simple-module.content-bundle`. Optional when reading (bundles from before minor 1 lack it); present, it must match. |
| `format_version` | The **major** version, an integer. Readers refuse a major they do not know. |
| `format_minor` | Additive changes within a major. Informational; never checked. |
| `created_at` | When the snapshot was captured (UTC, ISO 8601). |
| `source` | The module and package version that wrote the bundle. Informational. |
| `tenant` | The tenant the content was captured from, or `null`. A label, not a constraint: restoring into another tenant or host is what bundles are for. |
| `contents` | The sections in the bundle (below). |
| `pages`, `layout`, `counts`, `missing_media` | The pagebuilder section's summary, used to draw the snapshot list without opening the documents. |

### Versions

| Major | What changed | Read by this build |
|---|---|---|
| 1 | The original layout. Pages keyed by slug alone. | yes — every page is read as the default content locale, which is what the schema guaranteed when it was written |
| 2 | Pages and redirects keyed by `(locale, slug)`; non-default locales get a `<locale>__` file prefix. | yes — this is what it writes |

A **major** bump is for a change an older reader would *misread*. A **minor**
bump is for keys an older reader can safely ignore; minor 1 added `format`,
`format_minor`, `source`, `tenant` and `contents` and changed nothing else, so
a build that predates it still restores bundles written after it. Minor 2
added `contents[].counts` and sections contributed by other modules (#80),
which a minor-1 reader already skips as unknown optional sections.

A manifest with no `format_version` at all is read as major 1. Every bundle this
module has written carries one; the rule exists so a hand-assembled bundle in
the v1 shape is checked against v1's rules instead of being refused outright.

An unknown major is refused on upload with **422** and a message naming the
version and the ones this build reads. The same check runs again when a restore
is requested, against the version recorded on the snapshot row — an uploaded
bundle keeps the major it arrived with.

### Sections

`contents` lists what the bundle carries, one entry per section:

| Key | Meaning |
|---|---|
| `section` | Name, `[a-z][a-z0-9_]*`. Unique within the bundle. |
| `version` | The section's own integer version, independent of the format's. |
| `required` | Default `true`. Whether restoring the bundle without this section would leave the site incoherent. |
| `paths` | The files and directories (`dir/`) the section owns. |
| `counts` | Optional (minor 2). Per-kind integer totals, for the snapshot list. |

Reading rules:

- A manifest without `contents` (every bundle before minor 1) is read as the
  `pagebuilder` section alone, which is exactly what those bundles hold.
- The `pagebuilder` section must be present, at version 1. It owns the
  root-level paths in the layout above, which it has always used.
- A **required** section this build does not know is refused (422): restoring
  half of what the bundle says belongs together would be worse than not
  restoring it.
- A section this host *does* know (pagebuilder's, or one a module registered)
  at a version it cannot read is refused (422), even when optional: a restore
  that silently left out content the operator expected is worse.
- An **optional** section this build does not know is ignored — extracted,
  kept and downloaded again with the bundle, never read. Its `paths`
  must all sit under `<section>/`, so its files can never be read as pages,
  and its name may not be one pagebuilder uses at the root: `pagebuilder`,
  `pages`, `media`, `blobs`, `layout`, `redirects` and `manifest` are
  reserved.
- Every declared path is relative, uses forward slashes and has no empty,
  `.` or `..` component. `news/../pages/` is refused as written, not
  normalised and then compared.
- The `pagebuilder` section's `paths` may only name its own root-level paths.
- Every file in the archive other than `manifest.json` must belong to exactly
  one section: a file no section claims, or one two sections claim, is a 422.
  Files an OS adds when a bundle is re-zipped by hand (`__MACOSX/`,
  `.DS_Store`, `Thumbs.db`, `desktop.ini`) are skipped, not extracted.

### Contributed sections

Another module adds a section through `pagebuilder.contracts.bundle` (#80):
it registers a `BundleSection` from its `on_startup`, and pagebuilder calls it
to capture into `<section>/`, validate on upload, plan beside the pages and
apply after them, inside the approve request's one transaction. A section
that fails rolls the whole restore back, including the media files the restore
had already written for it (#250). The rules a
contributor follows are in that module's docstring. The section's manifest
entry is written by pagebuilder:

```json
{"section": "news", "version": 1, "required": false, "paths": ["news/"],
 "counts": {"articles": 42}}
```

A host without the contributor restores the pagebuilder content and reports
the section as skipped; a bundle without the section (an older one, or one from
a host without the contributor) leaves that module's content as it is.

#### The contract in brief

`BundleSection` (in `pagebuilder.contracts.bundle`) is a Protocol: `name`,
`version`, `readable_versions`, `required`, `label_key`, `count_label_keys`,
optional `capture_permissions`/`apply_permissions`, and four calls —
`capture(CaptureContext) -> SectionCapture(counts)`, `validate(ValidateContext)`
(sync, no database), `plan(RestoreContext) -> SectionPlan(lines, overwrites)`
and `apply(RestoreContext) -> SectionApplied(counts, applied)`. Each context
carries the request's session and bound tenant (`check_tenant()` before and
after every call), the section's directory, and the helpers a contributor needs
(`write_json`, `read_json`, `to_portable`/`from_portable` for media URLs,
`check_media`, `invalid()` for a 422, `conflict()` for a 409). A contributor
flushes and never commits, never opens a session and never resolves a tenant;
raising aborts the whole restore, pages included. The full rules are the
module's docstring; `api-reference.md` lists the exports.

#### News' section

News registers `news`, version 1, optional. Its files live under `news/`:
`articles/<slug>.json` (or `<locale>__<slug>.json` outside the default
language), `categories.json`, `tags.json`, `redirects.json` and
`tag_redirects.json`. It carries every non-trashed article with its draft and
published bodies, dates, byline, category and tags, and media as `asset://`
sentinels; never revisions, `created_by`/`updated_by`, rejection notes or ids.
The news README ("Content bundles") has the matching rules.

#### How the plan names a section

A staged plan gains four keys beside `pages`, `layout` and `redirects`:

```json
"sections": [{"section": "news", "label_key": "news.bundle.title", "version": 1,
              "overwrites": 1,
              "lines": [{"label_key": "news.bundle.plan.overwritten", "count": 1,
                         "tone": "warning",
                         "items": [{"title": "Hello", "slug": "hello",
                                    "locale": "en", "note_key": null}]}]}],
"denied":  [{"section": "news", "label_key": "news.bundle.title",
             "reason_key": "pagebuilder.plan.section_denied",
             "permissions": ["news.edit", "news.publish"]}],
"skipped": [{"section": "shop", "version": 1}],
"absent":  [{"section": "news", "label_key": "news.bundle.title"}]
```

A section entry may also carry `redacted` or `details_unavailable` (see
Permissions below), and an `absent` one `omitted` with the permissions the
capture lacked. Every label is the contributor's own catalogue key; the review
screen (`ImportPlanSummary` → `SectionPlan`) resolves them at render against
the host's merged catalogue, so pagebuilder renders a section it has never
heard of, falling back to the section's name. The section's `overwrites` add
to the headline's overwrite count.

`GET /api/pagebuilder/snapshots` (and both Import / Export screens) also return
`sections: [{section, label_key, count_label_keys}]` for every section
registered here, so the list labels each row's `contents[].counts`; a section
this host does not register is listed by its raw name and count kinds. The
approve response's `sections` holds each section's apply counts, labelled the
same way, and a page's restore marker
(`GET /pages/{id}/revisions` → `restores[].sections`) counts the rows the same
restore wrote in each section — counts only, never which rows.

#### Permissions

A contributor may name the permissions its section needs, in its own
vocabulary (`capture_permissions` and `apply_permissions` on `BundleSection`,
both empty by default). Pagebuilder checks them for the acting user with the
framework's own permission resolution, the one `RequiresPermission` uses, on
top of `pagebuilder.publish` / `pagebuilder.approve`:

- **Capture.** A snapshot a user takes leaves the section out unless they hold
  every capture permission, and records why in a top-level `omitted` list:

  ```json
  "omitted": [{"section": "news", "label_key": "news.bundle.title",
               "reason": "permission", "reason_key": "pagebuilder.plan.section_omitted",
               "permissions": ["news.edit"]}]
  ```

  A restore of that bundle lists the section under `plan.absent` with
  `"omitted": true`. That means "not in this bundle", and a restore never
  deletes, so the module's content stays as it is. The automatic `pre_restore`
  snapshot has no user behind it and always captures every section.
- **Download.** Downloading a bundle that carries such a section needs its
  capture permissions (403 `Permission required: …` otherwise). When a bundle
  is captured or uploaded, this host writes what each section needs onto the
  snapshot row (`host_download_permissions` in the *stored* manifest, never in
  `manifest.json`; a bundle's own copy of the key is ignored). That record
  still applies after the contributor is disabled. A section the host did not
  know when the bundle arrived has unknown needs, and **only a holder of
  `pagebuilder.approve` may download that bundle**. This denies by default, and
  the same applies to rows from before the record existed.
- **Restore.** A section is applied only if the user who stages the restore
  holds every apply permission (otherwise the section is not even planned, so
  its rows are not shown) and the approver still does at approval. A skipped
  section is listed with `reason_key` `pagebuilder.plan.section_denied` and the
  missing `permissions`, under `plan.denied` at staging and under
  `denied_sections` in the approve response. The pages restore either way.
  A section left out at staging stays out, even when the approver could apply
  it, and approval does not re-plan it, so its rows cannot block the pages with
  a 409. To include it, stage the restore again as someone who holds the
  permissions.
- **Reading a staged plan.** A section's plan lines name its rows, so the
  `PendingImport.plan` column stores only their counts and tones. The column
  is audited and visible to everyone who can use Import / Export. The items
  live in a host-side file, `<snapshot_root>/imports/<import id>/sections.json`.
  Every response that carries a plan (pending import, review screen, staging,
  reject) puts them back only for a reader who holds the section's capture
  permissions. Anyone else gets the counts and `redacted: true` with
  `reason_key` `pagebuilder.plan.section_redacted`. Items are only ever served from
  that file. Inline items in a stored plan are cleared at the serving boundary,
  and stripped again when approval writes the audited plan. If the file is
  missing or unreadable, an allowed reader gets the counts with
  `details_unavailable: true` (`note_key`
  `pagebuilder.plan.section_details_unavailable`) and a warning is logged. The section's `applied`
  record holds only identities (id and `created_at`) and counts, and is
  served as counts to such a reader. `/imports/pending` and the review screen
  need `pagebuilder.publish` or `pagebuilder.approve`. The Import / Export
  screen is open to every pagebuilder role, but it carries the pending restore
  only for those readers.

News asks for `news.edit` to capture and download, and for `news.edit` plus
`news.publish` to restore.
