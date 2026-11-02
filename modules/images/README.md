# simple_module_images

Image collections for SimpleModule hosts. A collection holds images whose
**originals are immutable**; everything derived from them (EXIF and location,
renditions, quality metrics, an optionally anonymised display copy, map tiles)
is produced by pipeline steps that run as background tasks. Collections are
private to their owner, shared with chosen users, internal to the organisation
or public.

Imports take single files, batches, large direct uploads, ZIP archives and
GeoJSON sources of up to a million located images. Groups, AI prompts with a
review queue, a map (GeoJSON points and PMTiles) and a public gallery are
included. Design:
`docs/superpowers/specs/2026-10-28-images-module-design.md` in the source repo;
the guides are in [`docs/`](docs/index.md).

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

A plain install pulls no onnxruntime or OpenCV. Heavy processors are
extras, imported only inside the step that needs them:

| Extra | Adds |
| --- | --- |
| `quality` | OpenCV: resolution, blur and exposure metrics |
| `anonymize` | onnxruntime: YuNet face and YOLOv9 plate detection (MIT models), blurred into a display copy (the original is kept); weights from `anonymize_weights_path` or a pinned, checksummed download on first use |
| `ai` | `simple_module_ai`: prompt-based image analysis |
| `billing` | `simple_module_billing`: storage and request metering |
| `pagebuilder` | `simple_module_pagebuilder`: an image gallery block |

The map view needs no extra: its PMTiles archive is built by the `tippecanoe`
binary (`tippecanoe_path`), which must be on the worker's machine.

**Models and licences.** The `anonymize` extra installs only onnxruntime
(MIT). The step downloads two MIT-licensed ONNX models on first use, pinned by
SHA-256: **YuNet** (faces; Shiqi Yu, via
[OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4/models/face_detection_yunet))
and **YOLOv9 licence-plate detector** (ankandrew,
[open-image-models](https://github.com/ankandrew/open-image-models)). Their
copyright notices are in this module's `NOTICE`. Recall is unverified, and
weights are cached under `~/.cache/simple_module_images/models` unless
`anonymize_weights_path` points at `face.onnx` and `plate.onnx`. See
[docs/index.md](docs/index.md#anonymize-models-and-licences).

The module needs the framework's `settings`, `sharing`, `file_storage` and
`background_tasks` modules. Migrations live in the consuming host
(`make migration`), never in the wheel.

Image processing runs in Celery workers (`make worker`, `worker-imports`,
`worker-heavy`, `worker-gpu`, `beat`) or inline with
`SM_BG_TASKS_TASK_ALWAYS_EAGER=true`. A plugin that adds steps ships an
`images_extensions.py` and must be installed in the web process and every
worker. See [docs/worker.md](docs/worker.md) and
[docs/writing-a-plugin.md](docs/writing-a-plugin.md).

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

### Settings

The module's settings are governed by the framework's `settings.edit`, as every
other module's are; images has no settings permission of its own.

Stored in the database and edited on the Settings screen; there is no
`SM_IMAGES_*` environment variable. System scope: one configuration for every
tenant. Fields marked as needing a restart (`tippecanoe_path`,
`public_asset_base_url`) are read once at boot; workers pick up the rest within
about 30 seconds.

| Setting | Default |
| --- | --- |
| `max_image_bytes` | 50 MiB |
| `batch_max` | 50 |
| `upload_body_max_bytes` | 100 MiB |
| `direct_upload_threshold` | 20 MiB |
| `max_open_uploads_per_tenant` | 20 |
| `zip_max_bytes` / `zip_max_entries` | 2 GiB / 10 000 |
| `zip_max_entry_bytes` / `zip_max_total_bytes` / `zip_max_ratio` | 200 MiB / 8 GiB / 200 |
| `geojson_max_features` / `geojson_max_bytes` / `geojson_max_feature_bytes` | 1 000 000 / 2 GiB / 60 MiB |
| `download_concurrency_per_domain` / `download_concurrency_total` (per download task) / `download_timeout` | 4 / 32 / 60 s |
| `thumbnail_sizes` | marker 64, small 160, medium 400, large 1024 |
| `dedupe_by_hash` | off |
| `tippecanoe_path`, `anonymize_weights_path` | `tippecanoe`, empty |
| `map_rebuild_threshold_pct` / `map_rebuild_threshold_abs` | 5 / 100 |
| `map_style_url` (basemap; empty = flat, no third-party request) | `https://tiles.openfreemap.org/styles/positron` |
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
  points (both at least 1). A move does not wait for the threshold. A visibility
  change, a removed point (an image trashed or its location cleared) and a
  pipeline save that changes the redaction gate withdraw the archive in the
  same transaction and build a fresh one. An archive is stamped with the
  redaction gate it was built under, and is a 404 under any other (for
  example once a mutator plugin is removed) until `images.reconcile` rebuilds it.
- The `images.tippecanoe` health check is degraded while the binary cannot be
  found. Points keep working.
- The points are drawn over the basemap `map_style_url` names (OpenFreeMap's
  Positron by default; its origin is added to the CSP). Viewers' browsers
  fetch its tiles from that host, so it sees their IP and the area they view;
  set it to empty for a flat background with no third-party request. A style
  that cannot be fetched falls back to the flat background.

## Documentation

| Page | For |
| --- | --- |
| [docs/index.md](docs/index.md) | Concepts, install, permissions, every setting |
| [docs/access.md](docs/access.md) | Visibility, shares, originals, withheld images |
| [docs/imports.md](docs/imports.md) | Uploads, direct upload and bucket CORS, ZIP, GeoJSON, limits |
| [docs/pipeline.md](docs/pipeline.md) | Steps, leases, AI prompts, groups, presets, review, storage metering |
| [docs/writing-a-plugin.md](docs/writing-a-plugin.md) | Steps, presets and result views from another module |
| [docs/worker.md](docs/worker.md) | Workers, beat, timeouts, tuning, recovery times |
| [docs/migrating-from-portal.md](docs/migrating-from-portal.md) | Moving off the portal's feature |
