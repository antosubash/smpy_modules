# simple_module_images

Image collections for SimpleModule hosts. A collection holds images whose
**originals are immutable**; everything derived from them (EXIF and location,
renditions, quality metrics, an optionally anonymised display copy, map tiles)
is produced by pipeline steps that run as background tasks. Collections are
private to their owner, shared with chosen users, internal to the organisation
or public.

This release is the module skeleton: registrations, permissions, settings,
tenancy and the test harness. Collections, uploads, the pipeline and the
screens arrive in the following releases. Design:
`docs/superpowers/specs/2026-10-28-images-module-design.md` in the source repo.

## Install

```bash
pip install simple_module_images
```

Add `simple_module_images` to your host's dependencies; for an in-repo checkout,
resolve it from the workspace:

```toml
[tool.uv.sources.simple_module_images]
workspace = true
```

A plain install pulls no torch, ultralytics or OpenCV. Heavy processors are
extras, imported only inside the step that needs them:

| Extra | Adds |
| --- | --- |
| `quality` | OpenCV: resolution, blur and exposure metrics |
| `anonymize` | torch, ultralytics: YOLO face and plate detection, blurred into a display copy (the original is kept); weights from `anonymize_weights_path` or a pinned, checksummed download on first use |
| `map` | PMTiles support for the map view (also needs the `tippecanoe` binary) |
| `ai` | `simple_module_ai`: prompt-based image analysis |
| `billing` | `simple_module_billing`: storage and request metering |
| `pagebuilder` | `simple_module_pagebuilder`: an image gallery block |

The module needs the framework's `settings` module, and from the next release
`file_storage`, `sharing` and `background_tasks`. Migrations live in the
consuming host (`make migration`), never in the wheel.

## Usage

The console is at `/admin/images`, the JSON API under `/api/images` and public
collections at `/images/c/{slug}`. Every router binds a tenant: a single-tenant
host uses `default`, a multi-tenant host the organisation the framework
resolved (403 `tenant_required` for the console, 404 for public routes when
none).

### Permissions

| Permission | Allows |
| --- | --- |
| `images.view` | See collections and images the access policy admits |
| `images.create` | Create collections and upload images |
| `images.publish` | Make a collection public or internal |
| `images.manage` | Manage every collection regardless of owner |
| `images.originals.view` | Download the immutable original |
| `images.settings` | Edit the module's settings |

### Settings

Stored in the database and edited on the Settings screen; there is no
`SM_IMAGES_*` environment variable. System scope: one configuration for every
tenant. Fields marked as needing a restart (`tippecanoe_path`,
`anonymize_weights_path`, `public_asset_base_url`) are read once at boot.

| Setting | Default |
| --- | --- |
| `max_image_bytes` | 50 MiB |
| `batch_max` | 50 |
| `upload_body_max_bytes` | 100 MiB |
| `direct_upload_threshold` | 20 MiB |
| `zip_max_bytes` / `zip_max_entries` | 2 GiB / 10 000 |
| `zip_max_entry_bytes` / `zip_max_total_bytes` / `zip_max_ratio` | 200 MiB / 8 GiB / 200 |
| `geojson_max_features` / `geojson_max_bytes` | 1 000 000 / 2 GiB |
| `download_concurrency_per_domain` / `download_concurrency_total` / `download_timeout` | 4 / 32 / 60 s |
| `thumbnail_sizes` | marker 64, small 160, medium 400, large 1024 |
| `dedupe_by_hash` | off |
| `tippecanoe_path`, `anonymize_weights_path` | `tippecanoe`, empty |
| `map_rebuild_threshold_pct` / `map_rebuild_threshold_abs` | 5 / 100 |
| `public_asset_base_url` | empty |
| `janitor_grace_days`, `step_output_max_bytes`, `step_lease_seconds` | 7, 65 536, 1 800 |

### Routes

Upload routes (`/api/images/collections/{id}/images`, `.../imports`,
`.../imports/zip` and `/api/images/uploads/`) carry a request-body ceiling of
`upload_body_max_bytes` plus multipart framing; the rest use the host's global
limit. Public exemptions are `GET`/`HEAD` only, under `/images/c/` and
`/api/images/public/`.

### Map

- `GET /api/images/collections/{id}/points?bbox=minx,miny,maxx,maxy&limit=&cursor=`
  (anonymous twin: `/api/images/public/c/{slug}/points`) answers a GeoJSON
  `FeatureCollection`. Each point carries only `id`, `captured_at` and
  `group_id`; an image whose display mutator has not settled is not a point.
  `limit` is clamped to 5000; follow `next_cursor` for the rest.
- `GET|HEAD …/collections/{id}/map.pmtiles` (twin: `/api/images/public/c/{slug}/map.pmtiles`)
  serves the collection's PMTiles archive with `Range`, checking access on
  every request. It is a 404 until a map is built.
- `images.build_map` (queue `images`) builds the archive with `tippecanoe`.
  A rebuild starts once the changes since the last build reach
  `map_rebuild_threshold_abs` or `map_rebuild_threshold_pct` percent of its
  points. A move or a removal does not wait for the threshold. A visibility
  change withdraws the archive in the same transaction and builds a fresh one.
- The `images.tippecanoe` health check is degraded while the binary cannot be
  found. Points keep working.
