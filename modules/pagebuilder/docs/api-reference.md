# PageBuilder API reference

All admin routes are JSON under `/api/pagebuilder`. Every one of them runs three
router-level dependencies, in this order:

1. **Authentication** — `401 Not authenticated` without a signed-in user, unless
   the `requires_auth` setting is off (read per request).
2. **Tenant binding** (`tenancy.bind_admin`) — single-tenant host: tenant
   `"default"`; multi-tenant host: the tenant the framework resolved, or
   `403 tenant_required`.
3. **CSRF** — every `POST`/`PUT`/`PATCH`/`DELETE` needs the session token in an
   `X-CSRF-Token` header, else `403 Invalid or missing CSRF token` (when
   `csrf_protect` is on). The admin views expose it as the Inertia shared prop
   `csrf.token` and in a JS-readable cookie (`pagebuilder_csrf` by default).

"Permission" below is the extra `RequiresPermission` check on top; **auth** means
any signed-in user. Errors are `{"detail": "<message>"}`; the table is at the end.

## Pages

### `GET /api/pagebuilder/pages` — auth

Query: `search` (title or slug, case-insensitive, wildcards literal), `status`
(`draft` | `submitted_for_review` | `published`; empty = no filter), `locale`,
`limit` (1–200, default **unbounded**), `offset`. Newest first, trashed pages
excluded.

```json
{"items": [PageRead, …], "total": 42}
```

`PageRead`:

```json
{"id": 7, "slug": "about", "locale": "en", "translation_group": "9f…",
 "title": "About", "status": "published", "has_published": true,
 "meta_title": null, "meta_description": "…", "og_image": null,
 "canonical_url": null, "index_in_search": true, "rejection_note": null,
 "publish_at": null, "unpublish_at": null, "parent_id": null,
 "is_template": false, "show_in_header_nav": true, "show_in_footer": false,
 "deleted_at": null, "created_at": "…", "updated_at": "…"}
```

### Literal list routes

| Route | Permission | Returns |
|---|---|---|
| `GET /pages/trash` | `pagebuilder.edit` | trashed pages, most recently binned first |
| `GET /pages/templates` | auth | pages with `is_template`, by title |
| `GET /pages/pending` | `pagebuilder.approve` | pages in `submitted_for_review` |

All three return `{"items": [PageRead], "total": n}`.

### `GET /api/pagebuilder/locales` — auth

`{"locales": ["en", "de"], "default": "en"}` — the configured content languages.

### `POST /api/pagebuilder/pages` — `pagebuilder.edit` → 201

```json
{"title": "About", "slug": "about", "locale": "de",
 "meta_title": null, "meta_description": null, "og_image": null,
 "canonical_url": null, "index_in_search": true, "json_ld": null,
 "show_in_header_nav": false, "show_in_footer": false,
 "draft_data": {}, "publish_at": null, "unpublish_at": null,
 "parent_id": null, "is_template": false, "copy_from_page_id": null}
```

Only `title` (1–300) and `slug` (`^[a-z0-9][a-z0-9-]*$`, ≤200) are required.
`locale` omitted means the default content locale; an unconfigured one is 422.
`copy_from_page_id` seeds `draft_data` from that page's draft and is not stored.
The page starts as a `draft` in a translation group of its own. Returns
`PageDetail`. Slug taken in that language → `409 Slug already in use in <locale>`.

### `GET /api/pagebuilder/pages/{id}` — auth

`PageDetail` = `PageRead` plus:

```json
{"draft_data": {…}, "published_data": {…} | null, "json_ld": {…} | null,
 "translations": [{"id": 7, "locale": "en", "slug": "about", "title": "About",
                   "status": "published", "trashed": false}, …]}
```

`translations` lists every page in the group, this one and trashed ones included,
ordered by locale. A trashed page is 404 here.

### `PUT /api/pagebuilder/pages/{id}` — `pagebuilder.edit`

Partial update: any of `title`, `slug`, `meta_title`, `meta_description`,
`show_in_header_nav`, `show_in_footer`, `og_image`, `canonical_url`,
`index_in_search`, `json_ld`, `draft_data`, `parent_id`, `is_template`. There is
no `locale`: a page's language cannot change. A slug change records a redirect
from the old slug (same locale). Returns `PageDetail`.

### `POST /api/pagebuilder/pages/{id}/translations` — `pagebuilder.edit` → 201

```json
{"locale": "de", "slug": null, "title": null, "copy_content": true}
```

Creates a draft sibling in the same `translation_group` and returns **its**
`PageDetail`. `slug` defaults to the source's (or `-2`, `-3`… if taken in that
language); `title` to the source's. Inherits meta description, social image,
indexing, template flag and nav flags; never `canonical_url`; `parent_id` is the
parent's counterpart in that language, or none. Errors: 422 unconfigured locale;
409 `This page is already in <locale>.`; 409 `A <locale> translation already
exists.` with header `X-Existing-Page-Id`; 409 slug taken.

### Trash

| Route | Permission | Effect |
|---|---|---|
| `DELETE /pages/{id}` | `pagebuilder.edit` | 204. Moves to trash (`deleted_at`). Publishes nothing. |
| `POST /pages/{id}/restore` | `pagebuilder.edit` | `PageDetail`, status `draft`, `published_data` kept. 404 unless trashed. |
| `DELETE /pages/{id}/purge` | `pagebuilder.edit` | 204. Removes the row, revisions and redirects, un-parents children, commits, then publishes `PageDeleted`. 404 unless trashed. |

## Workflow

Each returns `PageRead`. Bodies marked *note* take `{"note": "…"}` (≤2000,
optional; send `{}` or no body).

| Route | Permission | Body | Transition |
|---|---|---|---|
| `POST /pages/{id}/publish` | `pagebuilder.publish` | note | any → `published`; draft copied to published; clears `publish_at` and `rejection_note` |
| `POST /pages/{id}/unpublish` | `pagebuilder.publish` | note | → `draft`; clears `unpublish_at` |
| `POST /pages/{id}/submit` | `pagebuilder.edit` | note | `draft` → `submitted_for_review`, else 409 |
| `POST /pages/{id}/approve` | `pagebuilder.approve` | note | `submitted_for_review` → `published`, else 409 |
| `POST /pages/{id}/reject` | `pagebuilder.approve` | `{"note": "…"}` required, 1–2000 | `submitted_for_review` → `draft`, sets `rejection_note`, else 409 |
| `POST /pages/{id}/schedule` | `pagebuilder.publish` | `{"publish_at"?, "unpublish_at"?}` | sets timestamps only |

Every transition except `schedule` writes a revision with event `publish`,
`unpublish`, `submit`, `approve` or `reject`. For `schedule`, an absent key leaves
that field alone, `null` clears it, `{}` is a no-op; naive datetimes are UTC; both
set with `publish_at >= unpublish_at` is
`422 publish_at must be strictly before unpublish_at`.

## Revisions

| Route | Permission | Returns |
|---|---|---|
| `GET /pages/{id}/revisions` | auth | `{"items": [PageRevisionRead]}`, newest first |
| `GET /pages/{id}/revisions/{rev}` | auth | `PageRevisionRead` + `data` |
| `GET /pages/{id}/revisions/{before}/diff/{after}` | auth | `RevisionDiffResponse` |
| `POST /pages/{id}/revisions/{rev}/restore` | `pagebuilder.edit` | `PageDetail`; copies title, meta description, social image and blocks into the draft |

`PageRevisionRead`: `id`, `page_id`, `title`, `meta_description`, `og_image`,
`event`, `note`, `created_at`, `created_by`. The diff names direction
explicitly because a restored revision can have a higher id and older content:

```json
{"before_id": 3, "after_id": 5,
 "metadata": {"title": {"before": "A", "after": "B"}},
 "blocks": {"added": [{"id": "…", "type": "Hero", "fields": []}],
            "changed": [{"id": "…", "type": "Text", "fields": ["text"]}],
            "removed": []}}
```

A revision that belongs to another page is 404.

## Site layout

| Route | Permission | Body / returns |
|---|---|---|
| `GET /layout` | auth | `LayoutDetail` (`id`, `header_data`, `footer_data`, timestamps); created empty on first read |
| `PUT /layout` | `pagebuilder.edit` | `{"header_data"?, "footer_data"?, "note"?}`; `null`/absent leaves a slot alone. An unchanged save writes no revision. |
| `GET /layout/revisions` | auth | `{"items": [{"id", "layout_id", "note", "created_at", "created_by"}]}` |
| `GET /layout/revisions/{id}` | auth | revision + `header_data`, `footer_data` |
| `POST /layout/revisions/{id}/restore` | `pagebuilder.edit` | `LayoutDetail` |

## Media

### `GET /api/pagebuilder/uploads` — auth

Query: `search`, `content_type`, `folder` (absent = all, empty = unfiled, else
exact path), `min_size_bytes`, `max_size_bytes`, `cursor`, `offset`, `limit`
(1–200, default 60). Newest first. `offset` takes precedence over `cursor` and
adds `total`.

```json
{"items": [{"id": 4, "filename": "3f…a1.jpg", "original_filename": "hero.jpg",
            "content_type": "image/jpeg", "size_bytes": 482113,
            "url": "/media/pagebuilder/default/3f…a1.jpg", "width": 2400,
            "height": 1600, "folder": "marketing/heros", "alt_text": "",
            "caption": "", "credit": "",
            "variants": {"w640": {"filename": "…", "url": "…", "content_type": "image/webp",
                                 "width": 640, "height": 427, "size_bytes": 31022}},
            "created_at": "…"}],
 "next_cursor": 3, "folders": ["marketing/heros"], "total": null}
```

### `POST /api/pagebuilder/uploads` — `pagebuilder.edit` → 201

Multipart: `file`, optional `folder`. Returns `MediaAssetRead`. The declared type
must be in `media_allowed_content_types` and match the sniffed magic bytes (415
otherwise); over `media_max_bytes` is 413. Stored under a random name with the
sniffed extension; WebP variants generated for each configured width below the
original's.

### One asset — all `pagebuilder.edit`

| Route | Effect |
|---|---|
| `GET /uploads/{id}` | `{"asset": MediaAssetRead, "used_in": [{"page_id", "title", "slug", "status", "draft_only"}], "used_in_total": n}` (first 20 pages) |
| `PUT /uploads/{id}` | `{"alt_text"?, "caption"?, "credit"?}` (≤500/500/200); returns the same detail shape |
| `DELETE /uploads/{id}/checked` | 204, or `409 Still used on N page(s): …. Detach it there first.` |
| `DELETE /uploads/{id}` | 204, unconditionally: removes the row, file and variants |

Usage counts non-trashed pages whose draft or published data contains the
asset's URL (current or pre-tenancy flat URL).

## Snapshots and imports

| Route | Permission | Body / returns |
|---|---|---|
| `GET /snapshots` | auth | `{"items": [SnapshotRead]}` |
| `POST /snapshots` | `pagebuilder.publish` | `{"note"?}` → 201 `SnapshotRead` |
| `GET /snapshots/{id}/download` | `pagebuilder.publish` | `application/zip`, `content-snapshot-{id}.zip` |
| `POST /snapshots/upload` | `pagebuilder.publish` | multipart `file` → 201 `SnapshotRead`; 413 over `snapshot_max_upload_bytes`; 422 invalid bundle |
| `DELETE /snapshots/{id}` | `pagebuilder.publish` | 204 |
| `POST /snapshots/{id}/restore` | `pagebuilder.publish` | 201 `PendingImportRead`; writes nothing to the site; 409 if one is pending |
| `GET /imports/pending` | auth | `PendingImportRead` or `null` |
| `POST /imports/{id}/approve` | `pagebuilder.approve` | `ImportApplyResponse` |
| `POST /imports/{id}/reject` | `pagebuilder.approve` | `{"note"?}` → `PendingImportRead` |

`SnapshotRead`: `id`, `note`, `source` (`manual` | `upload` | `pre_restore`),
`format_version`, `manifest`, `size_bytes`, `created_at`, `created_by`.
`PendingImportRead`: `id`, `snapshot_id`, `plan`, `status` (`pending` |
`approved` | `rejected`), `note`, `created_*`, `decided_at`, `decided_by`.
`ImportApplyResponse`: `pages_created`, `pages_updated`, `media_added`,
`redirects`, `redirects_dropped` (slugs). Deciding an import twice is 409
`Import already decided`. Self-approval is allowed.

## Public routes

Anonymous, `GET`/`HEAD` only, mounted at startup from the settings:

| Route | Notes |
|---|---|
| `{public_route_prefix}/{slug}` | default content locale, e.g. `/p/about` |
| `/{locale}{public_route_prefix}/{slug}` | each other content locale, e.g. `/de/p/about` |
| `/{default}{public_route_prefix}/{slug}` | multilingual sites only: 301 to the unprefixed URL |
| `/sitemap.xml` | when `sitemap_enabled` |
| `/robots.txt` | when `robots_enabled` |
| `{media_url_prefix}/{tenant}/{file}` | uploaded media, `max-age=31536000, immutable` |

An old slug answers 301 to the page's current address. See
[operations.md](operations.md#public-pages-caching-and-csp) for headers.

## For other modules

**Contracts.** DTOs are exported from `pagebuilder.contracts`; anything else in
the package may change without a major version.

**`PageDeleted(page_id, slug)`** (`pagebuilder.contracts.events`) is published
on the event bus when a page is *purged* — not when it is trashed, since a
restore would otherwise come back without what other modules dropped. A module
that keys rows to a page id must handle it: there is no cross-module foreign key,
and SQLite reuses ids.

## Errors

| Status | Detail | When |
|---|---|---|
| 401 | `Not authenticated` | no user and `requires_auth` on |
| 403 | `tenant_required` | multi-tenant host, admin request with no tenant |
| 403 | `Invalid or missing CSRF token` | mutating request without the header |
| 403 | (framework) | missing permission |
| 404 | `Page not found` / `Revision not found` / `Asset not found` / `Snapshot not found` / `Import not found` | unknown id, trashed page, other tenant's row |
| 409 | `Slug already in use in <locale>` | create, update |
| 409 | `Cannot submit/approve/reject a page in '<status>' status` | workflow |
| 409 | translation exists / page already in that locale | translations |
| 409 | `Still used on …` | checked media delete |
| 409 | `An import is already awaiting approval` / `Import already decided` | imports |
| 413 | `File exceeds N bytes` / `Bundle exceeds N bytes` | uploads |
| 415 | content-type not allowed, or sniffed type mismatch | media upload |
| 422 | validation; unconfigured locale; schedule order; unsupported bundle format | various |
