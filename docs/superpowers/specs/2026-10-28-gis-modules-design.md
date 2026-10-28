# GIS modules (`simple_module_geodata`, `simple_module_maps`) — design

Date: 2026-10-28
Status: draft, awaiting approval

## Context

Several of the maintainer's apps build their own geospatial layer:

- **`smpy_gis`** (`~/Repos/smpy_gis/modules/gis`, framework 0.0.16). It has an
  upload → analyze → convert → publish pipeline (tippecanoe → PMTiles,
  rio-cogeo → COG, FlatGeobuf/GeoParquet on demand), Dataset/Representation,
  Layer/Map/MapLayer and Collection models, a pure style composer and legend
  deriver, and read-only OGC API Features/Tiles, STAC 1.0 and TileJSON 3.0
  endpoints. It is the cleanest codebase, with about 200 tests. Its gaps:
  - permissions are registered but never enforced, and nothing is scoped to
    an owner;
  - there is no tenancy;
  - settings are env-only, and it uses its own aioboto3 client rather than
    the framework's `file_storage`;
  - presigned upload is stubbed, `IngestJob` is never written, and COG/FGB
    sources do not render in the viewer.
- **gis-data-portal** is the large production FastAPI/Celery app that is
  being ported onto the framework; #99 and #101 were its earlier gaps. It is
  more mature in places:
  - resumable chunked browser → MinIO uploads;
  - tuned tippecanoe zoom policy and GDAL warp;
  - legends with jenks/quantile/equal/unique classification and SLD/QML
    import;
  - the `images/access.py` own > edit > view ranking;
  - a typed overlay model (wms, xyz, geojson, cog, pmtiles) in validation.

  Its gaps: no OGC/STAC, presigned URLs that expire after one hour (so embeds
  and the mobile client break mid-session), dataset CRUD without owner
  checks, and the pmtiles protocol registered in six places.
- `geowiki_map` and laco_wiki's datasets/legends are further copies.

The framework now covers most of the plumbing both apps wrote by hand:

| Framework piece | Version | What it gives |
|---|---|---|
| `file_storage` | 0.0.3x | `StorageBackend.get_range`, `presigned_get_url`, `DirectUploadBackend` (`create_multipart`, `presign_part`, `complete_multipart`, `abort_multipart`), DB-backed S3/MinIO settings |
| `sharing` | 0.0.38 | `sharing_resource_share`, `share_exists_for(...)` for `OwnedResourcePolicy`, grant/revoke API and admin page |
| `background_tasks` | — | Celery + Redis, `enqueue_after_commit`, `heartbeat()`, `stuck_after`, admin retry UI |
| `mail` | 0.0.4x | not needed in v1 |

This design turns the generic parts of both apps into **two published
modules**. It uses `smpy_gis` as the code base and takes specific pieces from
the portal. Domain features stay in the apps.

## Goals

1. Any host can catalogue geodata, upload it (directly to object storage,
   resumably), and have it converted to web-native formats in the
   background.
2. Datasets are private, unlisted or public; owned and shareable; tenant
   scoped; and every rule is enforced in SQL.
3. Tile and asset URLs never expire under a viewer. This applies to
   embedded maps, a mobile session and QGIS alike.
4. The catalogue speaks the standards external tools read: OGC API
   Features, OGC API Tiles (discovery), STAC 1.0 and TileJSON 3.0.
5. Styled multi-layer maps, with a legend, a public viewer, an iframe embed
   and a pagebuilder block. One MapLibre setup is shared by everything that
   draws a map.
6. Both modules can replace `smpy_gis`'s `gis` module and the portal's
   datasets, uploads, conversion, processing, legends and projects features.

## Non-goals (v1)

- PostGIS or geometry stored in the database. Extents are four float
  columns, as in both apps, so SQLite keeps working.
- A server-side tile renderer: titiler, raster XYZ tiles, WMS/WFS/WMTS
  serving, or the OGC Tiles z/x/y "core". PMTiles and COG are read by the
  client through range requests. A raster XYZ endpoint for `flutter_map` is
  the first follow-up once mobile needs one.
- Processing workflows, sampling, crowd validation, the image/photo
  pipelines, ML jobs, Earth Engine. These are portal-specific, or are later
  modules built on these two. Sampling is the most likely next one.
- Full ISO 19115 metadata, ltree category trees, DuckDB attribute queries.
- Offline maps on mobile.

## Anti-goals

These would make the work a failure even if it technically ran:

- A tile or asset URL that expires while it is still displayed (the
  portal's one-hour presigns).
- A permission that is registered but not enforced (`smpy_gis`), or any
  list or count that returns rows the caller cannot open.
- An unfiltered read on a host with `multi_tenant` off (CLAUDE.md, #38/#112).
- Lossy conversion passed off as data. The portal scales non-Byte rasters to
  Byte; here the COG keeps the source data type.
- App styling leaking in: no Tract design system, no GeoWiki or portal
  branding.
- Domain concepts in a generic module: LUCAS, validators, sampling designs.

## Module split

| Module | Package | Owns | Depends on |
|---|---|---|---|
| `geodata` | `sm_geodata` | datasets, files, representations, upload sessions, analyze/convert pipeline, visibility/ownership/sharing, collections, tags, search, asset serving, TileJSON, OGC API, STAC, the shared map *preview* and MapLibre protocol setup | framework `file_storage`, `background_tasks`, `sharing`, `settings`; optional `billing` |
| `maps` | `sm_maps` | layers (dataset-backed or external overlay), styles, legends and classification, map documents, basemap registry, viewer/editor/embed, pagebuilder `MapEmbed` block | `geodata` (through `sm_geodata.contracts` only); optional `pagebuilder` |

Why two modules and not one or six:
- A host can run a data catalogue with no map authoring. The portal's
  public catalogue and the STAC/QGIS users need only `geodata`.
- Maps are a separate authoring product, with their own permissions and
  their own publish step.
- Splitting further (storage, OGC and styles as their own modules) would
  multiply lockstep releases, migrations and CI legs, and would buy no
  independent consumer today.
- OGC/STAC lives in `geodata` because it is a read view over exactly the
  catalogue's tables. A `geodata` setting switches it off.

`maps` reads `geodata` only through `sm_geodata.contracts`, as news reads
pagebuilder (#130). The caller names the tenant and the contract pins
`tenant_id` itself.

## 1. `geodata`

### 1.1 Data model

`Base = create_module_base("geodata")`, `geodata_` prefix. Every table uses
`AuditMixin` and `MultiTenantMixin`; owner-facing tables also use
`SoftDeleteMixin`.

| Table | Key fields |
|---|---|
| `geodata_dataset` | `id`, `owner_id`, unique `(tenant_id, slug)`, `name`, `description`, `kind` (vector/raster/unknown), `status` (awaiting_upload/analyzing/converting/ready/failed), `error_code`, `error_message`, `visibility` (private/unlisted/public), `bbox_minx..maxy` (EPSG:4326), `crs`, `feature_count`, `geometry_type`, `attribute_schema` JSON (sampled fields, types, ≤50 distinct values), `raster_info` JSON (bands, dtype, nodata, pixel size), `metadata` JSON (license, attribution, keywords, temporal extent, lineage, source URL; validated by a pydantic schema), `published_at` |
| `geodata_source_file` | `dataset_id`, `storage_key`, `original_filename`, `size_bytes`, `content_type`, `role` (primary/sidecar). A shapefile is several rows; the portal's sidecar completeness check is ported |
| `geodata_representation` | `dataset_id`, unique `(dataset_id, format)`, `format` (pmtiles/cog/fgb/geoparquet), `storage_key`, `size_bytes`, `status` (pending/building/ready/failed), `progress_pct`, `error_message`, `extra` JSON (min/max zoom, source layer, output CRS) |
| `geodata_upload_session` | `dataset_id`, `storage_key`, `upload_id`, `part_size`, `total_size`, `completed_parts` JSON, `expires_at`, `status` (open/completed/aborted) |
| `geodata_collection` | unique `(tenant_id, slug)`, `owner_id`, `name`, `description`, `visibility` |
| `geodata_collection_item` | `(collection_id, dataset_id)`, `sort_order` |
| `geodata_tag` / `geodata_dataset_tag` | `(tenant_id, name)` unique. This is the only tag store: no JSON tag list on the dataset (the portal has both, and they drift) |

- **Progress** lives on `geodata_representation`. `smpy_gis`'s `IngestJob`,
  which nothing writes, is dropped, and task history is the framework's
  `background_tasks` admin.
- **Storage keys** are
  `geodata/<tenant_id>/<dataset_id>/{source,rep}/<name>`.
- **Dataset ids** are UUIDs, so a key never collides across tenants or
  renames.

### 1.2 Access

- **Policy.** `OwnedResourcePolicy(Dataset.owner_id,
  bypass_perm="geodata.datasets.manage",
  share_exists=share_exists_for("geodata.dataset", Dataset.id))`, registered
  as resource type `geodata.dataset`. Collections get the same policy as
  `geodata.collection`. `view` and `edit` shares come from the framework's
  `sharing` module.
- **Permissions:**
  - `geodata.datasets.view` (the console);
  - `geodata.datasets.create`;
  - `geodata.datasets.publish` (set unlisted/public);
  - `geodata.datasets.manage` (bypass: every dataset in the tenant);
  - `geodata.collections.manage`;
  - `geodata.settings` (this module's settings).
- **Visibility.** private: owner, shares and bypass only. unlisted:
  reachable by slug or id, never listed. public: listed in the public
  catalogue and STAC. Anonymous reads go through `tenancy.bind_public` and
  give 404 for anything that isn't visible, never 403.
- **Tenancy** follows the repo rule exactly. The module gets its own
  `sm_geodata.tenancy`, mirroring `sm_records.tenancy`: admin gives 403
  `tenant_required` with the `{"detail","code"}` envelope, public gives 404,
  and a resolved upstream tenant always wins. Public answers for a tenant
  are never shareable-cached across tenants.
- **Every list, count, search and OGC/STAC collection listing** goes
  through the policy in SQL. Tests assert that the counts match the rows a
  user can open.

### 1.3 Upload

From the portal's `uploads`, rebuilt on `file_storage.DirectUploadBackend`:

1. `POST /api/geodata/datasets` creates the dataset (`awaiting_upload`) and
   returns its id.
2. `POST /api/geodata/datasets/{id}/uploads` takes `{filename, size,
   content_type}`:
   - checks the size limit, the allowed extensions and the optional billing
     quota;
   - calls `create_multipart`;
   - returns `{session_id, part_size, parts: [{n, url}]}` from `presign_part`.
3. The browser PUTs the parts straight to object storage. That needs CORS
   on the bucket, which `file_storage.cors` already documents.
4. `POST …/uploads/{session}/complete` with the ETags calls
   `complete_multipart`, writes `geodata_source_file` and enqueues analyze
   after commit.
5. Resume: `GET …/uploads/{session}` lists completed parts (`list_parts`).
   Abort with `DELETE`. Sessions past `expires_at` are aborted by the
   janitor.
6. **The filesystem backend** (dev and tests) has no presigning. The
   backend's own `write_part` path is used through
   `PUT /api/geodata/uploads/{session}/parts/{n}`, so the client code is the
   same either way.

**URL ingest:** `POST /api/geodata/datasets/from-url`. It is ported from
`smpy_gis` with its SSRF guard (`url_safety.py`), streams into storage, and
is off by default (`url_ingest_enabled`), with an optional host allowlist.

### 1.4 Pipeline

These are Celery tasks in `sm_geodata/tasks.py`, autodiscovered by
`background_tasks`, enqueued with `enqueue_after_commit`, using `heartbeat()`
inside long steps.

| Task | Queue | Does |
|---|---|---|
| `geodata.analyze` | default | Vectors: pyogrio for extent, CRS, count, geometry type and attribute schema (5k-row sample). Rasters: rasterio for bands, dtype, nodata and extent → 4326. Sets `kind`, then enqueues convert |
| `geodata.convert` | `geodata_heavy` | Per auto format (below) → write the representation, report progress |
| `geodata.build_representation` | `geodata_heavy` | On-demand FGB/GeoParquet (`POST …/representations`) |
| `geodata.janitor` | beat | Hard-deletes soft-deleted datasets past the grace period (rows locked, storage objects removed, then rows); aborts expired upload sessions; removes orphaned prefixes. Dry-run flag, delete cap |

- **Auto formats.** Vectors always get PMTiles. They also get FGB when OGC
  API Features is enabled, because the Features reader range-reads FGB
  through GDAL `/vsicurl/`, as in `smpy_gis`. Rasters get COG.
- **Converters** keep `smpy_gis`'s `Converter` ABC
  (`convert(source, workdir, progress) -> ConversionResult`).
- **tippecanoe** runs as a subprocess, with the portal's zoom policy:
  zooms picked from feature count, `--drop-densest-as-needed` and
  `--extend-zooms-if-still-dropping`. Input is GeoJSONSeq, reprojected to
  4326 by pyogrio.
- **COG** is built with rio-cogeo (`web_optimized`, EPSG:3857) **keeping the
  source dtype and nodata**.
- **Failure states.** A failed step sets `status=failed` with an `error_code`
  from a fixed set (unsupported_format, unreadable, missing_sidecar,
  conversion_failed, too_large), and the dataset screen shows its
  translation. `POST …/reprocess` re-runs from analyze.
- **Python dependencies:** `pyogrio`, `rasterio`, `rio-cogeo`, `pyproj`,
  `shapely`, and `geopandas` only where a converter needs it. All of them
  ship wheels with GDAL bundled.
- **The one system binary is `tippecanoe`.** The worker needs it on `PATH`;
  a setting holds its path, and the health check reports when it is
  missing.

### 1.5 Serving assets

**Asset route.**
`GET /api/geodata/assets/{dataset_id}/{format}` (and a public twin under
the public prefix):
- streams through `StorageBackend.get_range` and honours `Range`,
  `If-Range` and `HEAD`;
- checks access on every request, through the policy for console callers
  and through visibility for public ones.

This is what makes the URLs **stable**:
- TileJSON, styles and embeds carry a permanent URL, with no presigned
  expiry.
- Public representations are sent with
  `Cache-Control: public, max-age=31536000, immutable`. A representation's
  key changes whenever it is rebuilt, so the URL is content-versioned with
  `?v=<rep.updated_at>`.
- Private and unlisted ones are sent `private, no-store`.

**Offload switch.** The cost is that the app process carries the tile
bytes. The setting `public_asset_base_url`, empty by default, switches
public representations to a direct bucket or CDN URL for hosts that publish
a public prefix. The publish step then copies the object there, as
`smpy_gis` does. Unlisted and private always use the app route.

**TileJSON 3.0.** `GET /api/geodata/datasets/{id}/tilejson` returns a
`pmtiles://` URL pointing at the asset route, plus bounds, zooms and
`vector_layers` from the attribute schema. Mobile and QGIS read this.

### 1.6 Catalogue, search and standards

**Console.** Under `/geodata`:
- datasets list (search, filters, tags, collection);
- the upload wizard (multipart with progress and resume);
- the dataset detail page (metadata form, representations with status and
  rebuild, map preview, visibility, shares through the framework's share
  UI, delete);
- collections.

**Public catalogue.** `/geodata/catalog` lists public datasets and
collections, and has a dataset page with a preview map and downloads.

**Search.** `GET /api/geodata/search?q=&bbox=&kind=&tag=&collection=` does
text search over name, description and tags (ILIKE, portable), plus a bbox
intersection on the four columns.

**Standards.** `geodata` ports `smpy_gis`'s `ogc/` slice:
- OGC API Features: landing, conformance, collections, items with
  `bbox`/`limit`/`offset`, and single item. It is read from the FGB
  representation by GDAL `/vsicurl/` against the asset route.
- OGC API Tiles: discovery and TileJSON.
- STAC 1.0: catalog, collections and items. Assets point at the asset
  route.

All of these serve public datasets only, under
`/api/geodata/{ogc,stac}/…`, with `bind_public`. They are anonymous through
the framework's public-route mechanism; `smpy_gis`'s monkey-patch of
`PUBLIC_PATHS` is not ported, and the module declares them the way
pagebuilder's public routes do. The `ogc_enabled` setting turns them off.
The compliance tests (pystac, jsonschema) come along.

### 1.7 Frontend shared with `maps`

`sm_geodata/components/map/` ships:
- `registerProtocols()`: pmtiles and `@geomatico/maplibre-cog-protocol`,
  registered once and idempotent. This replaces the portal's six copies and
  fixes `smpy_gis`'s unregistered `cog://`.
- `MapPreview`: one dataset, auto-styled by geometry type, fit to bbox.
- `MapCanvas`: takes a style object, and has a legend slot.

These are the primitives. `maps` imports them; no other module registers a
protocol. The libraries are `maplibre-gl` 5, `pmtiles` and
`@geomatico/maplibre-cog-protocol`.

### 1.8 Settings, events, contracts, billing

**Settings** are DB-backed with `register_module_settings` at SYSTEM scope,
with no env sources, like pagebuilder and ai:
- `max_upload_bytes`, `allowed_extensions`, `part_size_bytes`,
  `upload_session_ttl`;
- `url_ingest_enabled`, `url_ingest_allowlist`;
- `tippecanoe_path`, `max_zoom_cap`;
- `ogc_enabled`, `public_asset_base_url`;
- `janitor_grace_days`, `janitor_delete_cap`.

Anything read at boot (route prefixes, `ogc_enabled`) is read from
`app.state.sm_geodata.settings` in `on_startup` and marked `_RESTART`.
Object storage itself is `file_storage`'s configuration: one bucket, with
geodata keys under `geodata/`.

**Events**, published after commit: `DatasetReady`, `DatasetFailed`,
`DatasetVisibilityChanged`, `DatasetDeleted`.

**Contracts** (`sm_geodata.contracts`, every call names its tenant):
- `get_dataset`, `list_datasets` (policy-filtered for a given user);
- `asset_url(dataset, format)`;
- `tilejson(dataset)`;
- `sample_attribute(dataset, field, limit)`, for legend classification:
  reads the FGB or GeoParquet representation, or the source;
- `raster_stats(dataset, band)`.

**Billing** is an optional extra (`billing = ["simple_module_billing>=…"]`,
with a floor comment). When it is installed, the counter
`geodata.storage_bytes` is checked with `RequiresQuota` when an upload
starts, consumed on complete, and released on hard delete. Commits follow
the billing invariants: `finalize_session`, never `commit()`. Without
billing, only `max_upload_bytes` applies.

## 2. `maps`

### 2.1 Data model

`maps_` prefix, `AuditMixin`, `MultiTenantMixin`, `SoftDeleteMixin`.

| Table | Key fields |
|---|---|
| `maps_layer` | unique `(tenant_id, slug)`, `owner_id`, `name`, `source_type` (dataset/xyz/wms/pmtiles_url/cog_url/geojson_url), `dataset_id` (when dataset), `source_config` JSON (URL, layers, attribution; validated per type), `style_spec` JSON (partial MapLibre layer: paint/layout/filter plus `_sm.{cluster,label}`, as in `smpy_gis`), `legend` JSON, `visibility` |
| `maps_map` | unique `(tenant_id, slug)`, `owner_id`, `name`, `description`, `basemap_id`, `center_lon/lat`, `zoom`, `bearing`, `pitch`, `legend_config` JSON, `visibility`, `published_at` |
| `maps_map_layer` | `(map_id, layer_id)`, `sort_order`, `opacity`, `visible`, `hidden_from_legend` |

- **Overlay types** are the portal's validation overlay model, made a
  first-class layer source. This is what lets a map mix catalogue data
  with WMS or XYZ services.
- **External URLs** are validated with the same SSRF/scheme rules as URL
  ingest. They are only rendered client-side; the server never fetches
  them.

### 2.2 Access

- **Policy:** `OwnedResourcePolicy` plus `sharing` for `maps.layer` and
  `maps.map`.
- **Permissions:** `maps.view`, `maps.create`, `maps.publish`,
  `maps.manage` (bypass) and `maps.settings`.
- **Visibility** works as in `geodata`.
- **Publishing a map** means its dataset layers must be readable by the
  map's audience. `smpy_gis` silently promotes private datasets to unlisted;
  that is **not** carried over. Publish is refused with a list of the
  datasets that are not visible enough, and the editor offers a one-click
  "make these unlisted". The dataset owner must hold `geodata.datasets.publish`
  for that.
- **The public style endpoint** drops any layer that has become invisible
  since. It never leaks a private dataset.

### 2.3 Styles and legends

**Composition** ports `smpy_gis`'s pure `compose.py` and `legend.py`:
- map plus ordered layers → full MapLibre `style.json`, with basemap,
  cluster and label sub-layers, opacity and `metadata.legend`;
- legend entries derived from `match`/`case`/`interpolate`/`step`
  expressions.

The frontend `lib/style.ts` editor modes (categorical, graduated, filter
rules) come with it.

**Classification**, from the portal:
`POST /api/maps/layers/{id}/classify {field, method: unique|quantile|equal|jenks, classes, ramp}`.
- It samples through `geodata.contracts.sample_attribute` (or
  `raster_stats`) and returns a style expression plus legend.
- Colour ramps are a fixed palette list in code.
- `jenkspy` is used for jenks.

**Raster layers** become a colour-ramp fragment for the COG protocol, from
the same classification.

**Import:** SLD and QGIS QML import (`POST …/layers/{id}/import-style`),
from the portal's `style_parsers/`. This comes in the last phase.

### 2.4 Basemaps

A DB-backed setting holds a list of
`{id, label, style_url | tiles[], attribution, max_zoom}`.
- Defaults: OpenStreetMap raster tiles, with their usage-policy attribution,
  and "none".
- No Google or Bing: those are ToS-sensitive, and the portal's list has
  them.
- A host adds its own entries (for example a MapTiler key) on the Settings
  screen.

### 2.5 Screens and embedding

**Console:**
- layers list and layer editor (source, style modes, classify, legend
  preview);
- maps list and map editor (add/reorder layers, opacity, basemap, initial
  view, legend config, publish).

The `smpy_gis` editors (one is 1196 lines) are split to fit the 300-line
cap.

**Public:**
- `/maps/{slug}`: full-screen viewer with legend and layer toggles;
- `/maps/{slug}/embed`: chrome-less, for an `<iframe>`, served with a
  `frame-ancestors` CSP from the setting `embed_allowed_origins` (empty
  means any origin, since public maps are public);
- `GET /api/maps/public/{slug}/style.json`: lets any MapLibre client,
  including mobile, open a published map.

**Pagebuilder block:** `MapEmbed`, registered through `pagebuilder-blocks.ts`
as records does. Its props are a map picker, height and an interactive
toggle. It renders `MapCanvas` with the public style. It is an optional
`pagebuilder` extra with a floor comment.

## 3. Repo-wide consequences

- **Redis and Celery.** This repo has not used either until now. `geodata`
  depends on `background_tasks`:
  - **The demo host** adds the dependency, a worker entry point and a
    `make worker` target. It uses the shared `dev-services` Redis.
  - **Unit and e2e tests** run Celery with `task_always_eager`, so CI needs
    no Redis.
  - **The CI and e2e images** install `tippecanoe`. Tests that need it
    skip cleanly when it's absent locally, but CI must not skip them; a
    marker plus a CI assertion enforces that.
  - **CLAUDE.md**'s "This repo does not use Redis or Celery" line is
    updated.
- **Framework floor.** `simple_module_*>=0.0.41,<0.1`. That needs roadmap
  step 1, the 0.0.41 bump, to land first; `sharing` needs 0.0.38 regardless.
  The host adds `simple_module_file_storage`, `simple_module_background_tasks`
  and `simple_module_sharing` at the lockstep framework pin.
- **Migrations.** Host revisions under `host/migrations/versions/` with
  `branch_labels = ("geodata",)` and `("maps",)`. After autogenerate, the
  history ends in one head, and `alembic check` passes on SQLite and
  Postgres.
- **Repo conventions apply to both modules.** Each ships en and de
  catalogues with a compile-time `keys` tree (as `news/utils/i18n.ts`
  does), and follows the 300-line cap, the `pages/` rule and standalone e2e
  specs.
- **Docs.** Each module gets `modules/<m>/docs/`, covering the pipeline,
  access, serving, standards endpoints, styles and embedding, plus a
  migration note for `smpy_gis` and portal data.

## 4. Phasing

Each phase is one or more PRs, each releasable:

1. **Bump the framework to 0.0.41.** Roadmap step 1; a prerequisite.
2. **`geodata` core.** Models, settings, tenancy, policy, sharing,
   dataset/collection/tag CRUD and console screens (no pipeline yet), docs
   skeleton.
3. **Upload.** Multipart sessions, the filesystem fallback, URL ingest,
   analyze, billing quota.
4. **Conversion.** PMTiles, COG and FGB/GeoParquet, progress, reprocess,
   janitor; demo host worker and Redis; tippecanoe in CI.
5. **Serving.** Asset route, TileJSON, shared map components, dataset
   preview, public catalogue, search.
6. **Standards.** OGC API Features and Tiles, STAC, compliance tests.
7. **`maps` core.** Layers (dataset and external sources), style editor,
   compose and legend, map documents, viewer, embed, public `style.json`,
   basemap registry.
8. **`maps` extras.** Classification, raster ramps, pagebuilder `MapEmbed`,
   SLD/QML import.

Adoption happens outside this repo, after phase 6 for `geodata` and phase 8
for `maps`:
- `smpy_gis` replaces its `gis` module;
- the portal replaces datasets, uploads, conversion, processing, legends and
  projects;
- gaps found during adoption are filed here.

## 5. Calls made without the maintainer

The maintainer asked for a draft from `smpy_gis` and gis-data-portal with
generic modules. Every choice below is mine:

- Two modules, `geodata` and `maps`, with OGC/STAC inside `geodata`.
- `smpy_gis` is the code base; from the portal come resumable upload, the
  zoom policy, classification, SLD/QML import and the overlay types.
- `file_storage` replaces the private S3 client; framework `sharing`
  replaces bespoke share tables.
- An access-checked range route instead of presigned URLs, with an
  opt-in public offload.
- COG keeps the source dtype, unlike the portal.
- A map's publish step refuses rather than auto-promoting datasets.
- Tags only, with no category tree; ISO-ish metadata as validated JSON.
- Celery is eager in tests, with a real worker on the demo host.
- No server-side tiles in v1.
