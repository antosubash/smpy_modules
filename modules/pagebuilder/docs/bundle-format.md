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
  "format_minor": 1,
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
      "paths": ["layout.json", "redirects.json", "pages/", "media/"]
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
a build that predates it still restores bundles written after it.

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

Reading rules:

- A manifest without `contents` (every bundle before minor 1) is read as the
  `pagebuilder` section alone, which is exactly what those bundles hold.
- The `pagebuilder` section must be present, at version 1. It owns the
  root-level paths in the layout above, which it has always used.
- A **required** section this build does not know is refused (422): restoring
  half of what the bundle says belongs together would be worse than not
  restoring it.
- An **optional** section this build does not know is ignored. Its `paths`
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

### Adding a section (not built)

Nothing writes a second section yet. The shape exists so another module's
content can join a bundle later (#80) without a major bump: a module would
contribute a section such as

```json
{"section": "news", "version": 1, "required": false, "paths": ["news/"]}
```

with its documents under `news/`, and an older host would restore the
pagebuilder content and skip the rest. Whether a contributed section is
`required` is that module's call. The contribution hook itself — how a module
registers a section and takes part in the restore's transaction — is the open
design question #80 tracks.
