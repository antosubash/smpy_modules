# Images module (`simple_module_images`) — design

Date: 2026-10-28
Status: draft, awaiting approval

## Context

gis-data-portal's `images` feature is its most active area: about 17k LOC of
backend, 8k of frontend and 212 tests. It manages collections of photos with
locations:

- **Import:** single, batch and base64 upload; ZIP through a presigned PUT;
  and streaming GeoJSON imports of up to 1M features. The GeoJSON imports
  have checkpoint/resume, dedupe on `(collection, external_source,
  external_id)`, per-domain rate limits and backpressure.
- **A per-image pipeline:** EXIF geolocation → quality (cv2) → anonymization
  (MTCNN faces, YOLOv8 plates) → thumbnails ∥ LLM classification. It has an
  atomic run claim, error isolation between steps, and retry/restart in
  chunks.
- **Custom AI pipelines:** a per-collection instruction plus a JSON Schema,
  run for each image.
- **Bags:** groups of photos of one site with roles, such as the five LUCAS
  directional shots. A bag has a consolidation call, plus a cross-check
  function looked up by preset.
- **A clustered point map** of image locations, built as PMTiles by
  tippecanoe.
- **Sharing:** ranked collection access, owner > manage > contribute > view.

Almost all of it is generic. The LUCAS-specific part is confined to about
six places:
- `pipeline_presets.py` (the `_LUCAS` preset, its vocabularies, schemas and
  prompts);
- `constants_bag.py`;
- `cross_check._lucas_cross_check`;
- the `point/north/east/south/west` role order hardcoded in `crud_bag.py:62`;
- the LUCAS filename pattern and button in `GeoJsonImportDialog.tsx`;
- the land-use prompt in `classification_schema.py`.

It also has defects a generic version must not carry:
- **Anonymization overwrites the original** object in place, so an
  un-blurred copy can't be restricted; it is gone.
- **Deleting a collection** removes only database rows; its objects stay in
  MinIO.
- **The SSRF guard** checks IP literals and a hostname blocklist, but does
  not resolve DNS.
- **ZIP extraction** has no size or bomb limits.
- **HEIC** is accepted, but `pillow-heif` is not installed, so the pipeline
  fails on HEIC files.
- **A skipped geolocation step** re-runs on retry, and EXIF can overwrite
  coordinates from an API.
- **Thumbnails** are served as one-hour presigned MinIO URLs.
- **Pipeline steps are five hardcoded column pairs**, so a new step means a
  migration.
- **`source_type`/`source_config`** (Mapillary, Street View) have no code
  behind them.
- **"Public" means any logged-in user.** There is no anonymous access and
  no admin bypass.
- **AI results are read-only.** There is no review or correction.

This design extracts the feature as **one published module, `images`**, built
on the framework's `file_storage`, `sharing` and `background_tasks` and on
this repo's `ai` module. The LUCAS logic stays in the portal as a small
plugin registered through extension points.

## Goals

1. Any host can keep photo collections with location, capture time and
   camera metadata, and import them at the portal's scale: 1M-feature
   GeoJSON, resumable, idempotent.
2. A pipeline of **registered steps**. Each host and each collection
   chooses which steps run. A new step (in this module, an extra, or a host
   plugin) needs no schema change.
3. **Originals are never destroyed.** Anonymization writes a display
   derivative, and access to the original is a separate right.
4. AI steps run through `sm_ai.contracts`: the host's one AI configuration,
   metered by billing when installed. They are never the portal's own
   provider layer.
5. Groups (the portal's bags) and presets/cross-checks are generic
   mechanisms, so LUCAS becomes *data plus a plugin*, not code here.
6. People can review and correct AI results, keeping the model's answer
   alongside the correction.
7. The portal can replace its `images` feature with this module plus a
   LUCAS plugin, and migrate its data.

## Non-goals (v1)

- External source connectors (Mapillary, Street View, custom APIs). The
  unused `source_type`/`source_config` fields are dropped, not ported.
- Video, image editing or cropping, CMS renditions. Pagebuilder's media
  library serves page assets; this module serves field data.
- Face *recognition* or identity of any kind. Detection exists only to blur.
- Training or fine-tuning models, or GPU scheduling beyond a dedicated
  queue.
- Reverse geocoding.

## Anti-goals

- Any step that overwrites the original object.
- An image, thumbnail or map URL that expires while it is still displayed.
- A list, count, map tile or point endpoint that shows an image the caller
  cannot open.
- An unfiltered read on a single-tenant host (CLAUDE.md, #38/#112).
- LUCAS vocabularies, prompts, role names or filename patterns anywhere in
  this module.
- Torch, ultralytics or cv2 pulled in by a plain `pip install
  simple_module_images`.

## 1. Data model

`Base = create_module_base("images")`, `images_` prefix. Every table uses
`AuditMixin` and `MultiTenantMixin`; collections and images also use
`SoftDeleteMixin`.

| Table | Key fields |
|---|---|
| `images_collection` | unique `(tenant_id, slug)`, `owner_id`, `name`, `description`, `visibility` (private/internal/public), `pipeline_config` JSON (enabled steps plus per-step params; see §3), `preset_id`, `group_roles` JSON (ordered role list, e.g. `["point","north","east","south","west"]`), stats `image_count`, `located_count`, `bbox_*`, `map_built_at`, `map_image_count` |
| `images_image` | `collection_id`, `storage_key` (original, immutable), `display_key` (null = original is the display copy), `filename`, `content_type`, `size_bytes`, `width`, `height`, `sha256`, `lat`, `lng`, `altitude`, `heading`, `location_source` (manual > import > exif: higher precedence is never overwritten), `captured_at`, `camera_make`, `camera_model`, `orientation`, `external_source`, `external_id`, `properties` JSON (import properties), `group_id`, `group_role` |
| `images_rendition` | `(image_id, size)` unique; `size` from the `thumbnail_sizes` setting (default `marker 64, small 160, medium 400, large 1024`); `storage_key`, `width`, `height`. Always generated from the display copy |
| `images_step_run` | `(image_id, step)` unique; `status` (pending/running/completed/skipped/failed), `attempts`, `error_code`, `error_message`, `started_at`, `finished_at`, `step_version`, `output` JSON (the step's structured result: quality metrics, anonymization regions and counts, classification labels). Replaces `ImagePipelineStatus_DB` and its five column pairs |
| `images_group` | `collection_id`, unique `(collection_id, key)`, `name`, `description` |
| `images_prompt` | the portal's custom pipelines, generalised: `collection_id`, `name`, `scope` (image/group), `instruction`, `output_schema` JSON Schema (null = text), `inputs` (for group scope: images/results/both), `auto_run`, `preset_id` |
| `images_prompt_result` | `(prompt_id, image_id | group_id)` unique; `status`, `result_text`, `result_data`, `model_name`, `error`, `cross_check` JSON, and the **review** fields `review_status` (unreviewed/accepted/corrected/rejected), `reviewed_data`, `reviewed_by`, `reviewed_at`. A re-run replaces the model output and resets the review to `unreviewed`; the previous reviewed value is kept in `history` JSON (last 5) |
| `images_import_job` | `collection_id`, `kind` (geojson_url/geojson_base64/zip), `status`, `mapping` JSON (url, image, lat, lng, datetime, external_id and group-key properties; filename pattern), counters, `source_key`, `checkpoint_index`, `errors` JSON (capped), `auto_run_prompts` |
| `images_download` | one row per GeoJSON feature in URL mode: `job_id`, `feature_index`, `url`, `external_id`, `status`, `attempts`, `last_error`, `lat`, `lng`, `captured_at`, `group_key`, `group_role`, `image_id` |

- **Dedupe** is a unique partial index on `(collection_id, external_source,
  external_id) WHERE external_id IS NOT NULL`, ported as is together with
  the portal's three-layer dedupe and its IntegrityError re-check. A
  content hash `sha256` is added so direct uploads can dedupe as well
  (setting `dedupe_by_hash`, off by default).
- **Storage keys:** `images/<tenant>/<collection>/<image>/original.<ext>`,
  `…/display.jpg`, `…/r/<size>.jpg`, `images/<tenant>/<collection>/map.pmtiles`,
  `images/<tenant>/imports/<job>/…`. A single layout replaces the
  portal's two.

## 2. Access

**Visibility levels:**
- **private:** the owner, shares and the bypass permission only.
- **internal:** any member of the tenant, read-only. This is what the
  portal calls "public", so its existing collections migrate as `internal`.
- **public:** anonymous read through `tenancy.bind_public`. Not visible
  gives 404.

**Shares** go through the framework's `sharing` module, resource types
`images.collection` with `OwnedResourcePolicy` and `share_exists_for`.
`sharing` offers `view` and `edit`, so the portal's four roles collapse:

| Portal role | Here |
|---|---|
| view | `view` share |
| contribute | `edit` share: upload, import, run prompts, review results, manage groups |
| manage | `edit` share. Deleting images, re-running the pipeline for a whole collection and editing the pipeline config are **owner or `images.manage`** |
| own | owner (`owner_id`). Delete collection, visibility, shares |

The collapse is a deliberate loss. If a portal user needs "manage" as a
share, the fix is a roles extension in the framework's `sharing` module, not
a bespoke share table here.

**Permissions:**
- `images.view` (the console);
- `images.create`;
- `images.publish` (internal or public visibility);
- `images.manage` (bypass across the tenant);
- `images.originals.view` (see below);
- `images.settings`.

**Originals.** When an image has a `display_key`, meaning a step produced a
derivative such as a blurred copy:
- every viewer, gallery, rendition and public route serves the display copy;
- the original is served only to the owner and holders of
  `images.originals.view`, through `GET …/images/{id}/original`;
- the policy check is in SQL, like everything else.

**Tenancy** follows the repo rule exactly, with its own `sm_images.tenancy`
like `sm_records.tenancy`. Celery tasks run under `tenant_context` for the
job's tenant.

## 3. Pipeline

**Step registry.** A step is a class registered with the module's step
registry. Built-in steps register themselves; a plugin module registers
its own as described in §8:

```python
class Step(Protocol):
    id: str                      # "exif", "anonymize", "prompt:<id>" …
    version: int                 # bump to make completed runs stale
    requires: tuple[str, ...]    # ids that must be completed or skipped first
    mutates_display: bool        # writes display_key (at most one such step runs per image)
    queue: str                   # "images" | "images_heavy" | "images_gpu"
    def params_schema(self) -> type[BaseModel]: ...
    def applies(self, image, params) -> bool: ...
    async def run(self, ctx: StepContext) -> StepOutcome: ...   # three-phase: load / work / store
```

**Built-in steps:**

| Step | Extra | Does |
|---|---|---|
| `exif` | core | Pillow (with `pillow-heif` for HEIC) reads GPS, altitude, heading, DateTimeOriginal, make/model and orientation. Writes location only when the image's `location_source` is lower precedence than `exif` |
| `renditions` | core | Applies EXIF orientation and writes the `thumbnail_sizes` JPEGs from the display copy. Re-runs automatically after a step that changed `display_key` |
| `quality` | `[quality]` (opencv-headless) | Resolution, Laplacian blur and histogram exposure, with thresholds as step params. Informational; output goes to `step_run.output` |
| `anonymize` | `[anonymize]` (torch, ultralytics; YOLO for faces and plates, since facenet-pytorch would downgrade Pillow) | Detects faces and plates (toggled per collection), blurs padded regions, writes `display.jpg` and the regions and counts in `output`. **Never touches `storage_key`.** The weights file is a setting path or downloaded on first use; it is not bundled in the wheel |
| `classify` | `[ai]` (needs the `ai` module) | Structured vision call through `sm_ai.contracts.resolve_model()` and a pydantic-ai `Agent` with `output_type`, on a 1024 px copy. Its vocabulary and prompt are step params with neutral defaults; the portal's land-use prompt moves to its preset |
| `prompt:<id>` | `[ai]` | One `images_prompt` with image scope, run per image |

**Order and status.** The executor orders steps by `requires`. Defaults:
`exif → quality → anonymize → renditions ∥ classify ∥ prompts`.
- The portal's runner semantics are kept: the `SELECT … FOR UPDATE` claim
  on the image's step rows, a 30-minute "running" lease, short DB sessions,
  and a failed step not stopping its independents.
- **Status rules,** which fix the portal's SKIPPED re-run bug:
  - `skipped` is final for that `step_version`;
  - a retry re-runs `failed` and `pending` only;
  - "reprocess" with `force` re-runs everything;
  - bumping a step's `version` makes its completed runs stale, so the
    collection screen shows "N images on an older version" with a re-run
    action.

**Group runs.** `prompt:<id>` with group scope:
- makes sure each member has its image-scope result, reusing stored ones
  with at most 4 concurrent;
- then makes one consolidation call at temperature 0;
- then calls the preset's cross-check if one is registered.

**Presets** are registered by a host plugin. A preset bundles:
- a pipeline config;
- prompts (instructions plus schemas);
- group roles;
- import filename patterns;
- an optional `cross_check(group, results) -> dict`.

The module ships no presets. The portal ships a `lucas` plugin containing
`_LUCAS`, its cross-check, the role order and the
`^(?P<group>.+?)LCLU_(?P<role>Point|North|…)` pattern.

**Queues and the worker.**
- Queues: `images` (light steps, downloads, map build), `images_imports`
  (the import and restart orchestrators, concurrency 1), `images_heavy`
  (quality, classify, prompts) and `images_gpu` (anonymize).
- The module's docs carry the portal's tuned worker settings: `acks_late`,
  prefetch 1, max tasks per child, memory cap, thread pinning, disposing
  the pool after fork, 12 h visibility timeout.
- Interrupted imports are resumed from a `worker_ready` handler.
- Long steps call `background_tasks.heartbeat()`.

**AI metering.** AI steps run in Celery, not in a request, so they need the
`ai.requests` meter outside `RequiresAiRequest`. If `sm_ai.metering` has no
callable for that, the first PR adds one to `ai`'s contracts. It must
finish with `finalize_session`, per the billing invariants.

## 4. Import

**Direct upload.** `POST …/collections/{id}/images` takes one or a batch of
up to `batch_max` files, with an optional `metadata` JSON keyed by filename
(lat, lng, captured_at, external_id, group key and role). Manual
coordinates get `location_source=manual`.
- Above `direct_upload_threshold` bytes, the client uses
  `file_storage.DirectUploadBackend` presigned parts instead, with the same
  flow as `geodata`.
- `max_image_bytes` defaults to 50 MB.
- Files are sniffed by magic bytes, not by extension.
- The decompression-bomb guard (`Image.MAX_IMAGE_PIXELS`) matches
  pagebuilder's #221 behaviour, with a translated 413.

**Base64.** `POST …/images/base64`, deduped on the external id.

**ZIP.** Presigned PUT, then `…/import-zip/{job}/extract`, ported with its
zip-slip guard. New limits: `zip_max_bytes`, `zip_max_entries`, a
per-entry uncompressed size cap and a total uncompressed cap. An optional
`metadata.json` inside the ZIP applies as in the portal. Group keys come
from the filename pattern, as in GeoJSON imports; the portal had no
grouping for ZIPs.

**GeoJSON** (URL or base64 mode). Ported from `geojson_stream.py`,
`tasks_import_batch.py` and `tasks_download.py`:
- ijson validation and count;
- staged to storage, then streamed;
- a checkpoint every 1k features;
- a backpressure ceiling;
- a per-domain semaphore;
- 429/5xx backoff that honours `Retry-After`;
- the three-layer dedupe;
- `external_id` defaulting to `sha256(url)[:32]`.

**The SSRF guard** resolves DNS. It rejects private, loopback, link-local
and metadata addresses at resolution time and again on each redirect. It
can be ported from `smpy_gis`'s `url_safety.py`, or shared with `geodata`
if that lands first; a shared one would go into a small internal helper
both modules vendor, not a cross-module import.

**Auto-run.** Prompts marked `auto_run`, and the collection's pipeline,
run for **every** import path, not only direct upload as in the portal.

**Job controls:** progress, resume, restart, retry-failed and delete, with
set-based restarts in chunks of 1000 ids, all as in the portal.

**Downloaded images** are kept as delivered. The portal re-encoded them at
4000 px and quality 85; here that is the optional setting
`normalize_downloads` (off), and renditions cover display sizes. This
follows the never-destroy-the-original rule.

## 5. Serving and the map

**Image route.**
`GET /api/images/images/{id}/r/{size}`, `…/display` and `…/original`:
- streams from `file_storage`;
- checks access on every request;
- sends ETags;
- for public images: `public, max-age=31536000, immutable`, with the URL
  versioned by `?v=<updated_at>`;
- otherwise: `private, max-age=3600`.

The browser caches thumbnails across a gallery, and no URL expires. A
`public_asset_base_url` setting offloads public renditions to a bucket or
CDN, as in the `geodata` design.

**Points.** `GET /api/images/collections/{id}/points?bbox=&limit=` returns
GeoJSON, filtered by the policy. It serves small collections and mobile
clients.

**PMTiles.** The `[map]` extra; the system binary `tippecanoe` is a setting
path, and the health check reports when it is missing.
- It ports the portal's NDJSON → tippecanoe clustering (`-r1
  --cluster-distance=10 …`, z0–14, layer `images`).
- It rebuilds when the image count changes by 5% or 100 images, and on a
  visibility change.
- It is served through the image route's range-capable twin
  `…/collections/{id}/map.pmtiles`.
- The tiles hold only id, captured_at and group, never filenames or
  properties of images the caller couldn't see. A collection's tiles are
  all one visibility, which is why they are built per collection.

**`geodata`/`maps` link.** When the `geodata` and `maps` modules (separate
design) are installed, a `maps` layer source type `images_collection` can
draw a collection's points. That is an optional extra on the `maps` side;
`images` has no dependency on `geodata`.

## 6. Screens

The console, under `/images`:
- **Collections** with filters for owned, shared, internal, public and all,
  plus create, settings, pipeline config with a step toggle and
  JSON-Schema-driven params form, and sharing through the framework's share
  UI.
- **Collection:** gallery (cursor pagination; filters for has-location,
  step status, review status, group), map tab, import-jobs panel, pipeline
  summary with retry/restart, groups.
- **The import wizard:** GeoJSON client-side preview and property
  auto-mapping, ported from `geojsonPreview.ts`, plus ZIP upload and batch
  upload.
- **Image viewer:** display copy, an original toggle for those allowed,
  metadata, step results, prompt results.
- **Review:** a queue of `unreviewed` prompt results with
  accept/correct/reject. The correction form is generated from the prompt's
  `output_schema`. There is a keyboard path through the queue.
- **Prompt manager:** a port of `CustomPipelineManager` and
  `SchemaFieldBuilder`.

Public:
- `/images/c/{slug}`: a public collection's gallery and map.
- A pagebuilder `ImageGallery` block, as an optional `pagebuilder` extra
  with a floor comment.

The gallery, viewer and import wizard are split to fit the 300-line cap.
The portal's zustand store becomes per-page hooks. Catalogues are en and
de, with keys derived from `en.json` as in news.

## 7. Settings, events, contracts, billing

**Settings** are DB-backed at SYSTEM scope with no env sources:
- `max_image_bytes`, `batch_max`, `direct_upload_threshold`;
- `zip_max_*`, `geojson_max_features`, `geojson_max_bytes`;
- `download_concurrency_per_domain` and `…_total`, `download_timeout`;
- `thumbnail_sizes`, `dedupe_by_hash`, `normalize_downloads`;
- `tippecanoe_path`, `anonymize_weights_path`;
- `map_rebuild_threshold`, `public_asset_base_url`;
- `janitor_grace_days`.

Boot-time values are read in `on_startup` and marked `_RESTART`.

**Events**, published after commit: `ImageAdded`, `ImageProcessed` (all
steps final), `PromptResultReviewed`, `CollectionVisibilityChanged`,
`CollectionDeleted`.

**Contracts** (`sm_images.contracts`, each call names the tenant):
- `get_collection`, `list_collections` (policy-filtered);
- `points(collection, bbox)`;
- `rendition_url(image, rendition, *, collection=None)` (a `Rendition` row of the image; with its public `collection`, behind `public_asset_base_url` when set);
- `register_step`, `register_preset`.

**Billing** is an optional extra. The counter `images.storage_bytes` is
checked on upload and import start, consumed per stored object and released
on hard delete. AI steps are metered by `ai`'s `ai.requests` counter.

**Purge.** Fixes the portal's leak:
- deleting a collection or image soft-deletes it;
- the janitor (beat) hard-deletes past the grace period: rows locked,
  storage prefix removed, then rows;
- the janitor also removes abandoned import staging and orphaned prefixes,
  with dry-run and a cap.

## 8. Extending the module

**A plugin is an ordinary framework module.** It declares
`depends_on=["images"]` and registers its extensions at startup. That gives
it the framework's own permissions, settings, translations, migrations and
events for whatever else it needs. There is no entry-point group and no
second plugin mechanism.

### 8.1 What can be extended

| Point | Registered with | Stored / runs where |
|---|---|---|
| **Step** | `register_step(step)` | Runs in the executor with the claim, lease, retry and restart semantics of §3; status and output in `images_step_run` (no migration) |
| **Preset** | `register_preset(preset)` | Chosen per collection (`images_collection.preset_id`); its values seed the collection's `pipeline_config`, `group_roles` and prompts, which stay editable afterwards |
| **Cross-check** | a preset's `cross_check` | Called after a group-scope prompt run; its return value goes into `images_prompt_result.cross_check` |
| **Result view** (frontend) | `images-steps.ts` in the plugin (§8.4) | Renders a step's output, a prompt result or a cross-check in the image viewer, group view and review queue |
| **Events** | the framework event bus | `ImageAdded`, `ImageProcessed`, `PromptResultReviewed`, `CollectionVisibilityChanged`, `CollectionDeleted`, published after commit |
| **Contracts** | `sm_images.contracts` | Policy-filtered reads (`get_collection`, `list_collections`, `points`, `rendition_url`); every call names its tenant |

**No-code customisation** is prompts. An owner writes an instruction and a
JSON Schema on the prompt manager screen, and the correction form in the
review queue is generated from that schema.

**Per-project data** goes in `images_image.properties` (JSON), filled from
GeoJSON properties or upload metadata. There is no schema extension of the
module's tables. A plugin needing relational data owns its own tables
keyed by `image_id` or `collection_id`, as any module would.

### 8.2 Registration rules

- **When.** `register_*` is called in the plugin's `on_startup`. The module
  orders after its dependants' startup, through `depends_on`, and then
  **freezes the registry**. A later call raises `RegistryFrozenError`, so a
  late registration fails at boot instead of on the first job. Celery
  workers build the same app, so a worker sees exactly the registry the web
  process sees.
- **Ids.**
  - Step and preset ids are namespaced by the plugin's module name
    (`lucas.livestock_count`, `lucas`), and a duplicate id fails at
    registration.
  - Built-in ids (`exif`, `renditions`, `quality`, `anonymize`, `classify`,
    `prompt:*`) are reserved.
  - Prompt-based steps keep the form `prompt:<id>`.
- **Missing plugins.** A collection whose preset or enabled step is no
  longer registered still loads; the plugin may have been uninstalled. Its
  stored results stay readable. The collection screen shows "step
  `lucas.livestock_count` is not installed", and the step is never
  scheduled; its runs stay as they are. Re-installing the plugin resumes
  it.
- **Versions.** A step's `version` is the plugin's to bump. Bumping it marks
  completed runs stale, per §3.
- **Dependencies.**
  - A step's `requires` may name built-in or other plugins' steps.
    Unresolvable or cyclic `requires` fail at freeze time.
  - At most one registered step per collection may set `mutates_display`.
    Enabling a second is refused by the pipeline config validation.
- **Settings.** A step's `params_schema()` is the per-collection settings
  form; the pipeline config UI renders it, and the executor validates
  against it before each run. Deployment-wide settings belong to the
  plugin's own `register_module_settings`.
- **Heavy dependencies.** A plugin that needs torch or similar declares
  them in its own package. The module never imports a plugin's
  dependencies, and a step's `queue` routes it to a worker that has them.

### 8.3 Contract surface

```python
# sm_images.contracts
class Step(Protocol): ...          # §3
class StepContext:                 # passed to Step.run
    image: ImageRead               # metadata only; no ORM object
    params: BaseModel              # validated params_schema() instance
    tenant_id: str
    async def read_display(self) -> bytes: ...
    async def read_original(self) -> bytes: ...
    async def write_display(self, data: bytes, content_type: str) -> None:  # mutates_display only
    def progress(self, pct: int) -> None: ...   # also calls background_tasks.heartbeat()
class StepOutcome:                 # completed(output) | skipped(reason) | failed(code, message)

class Preset(BaseModel):
    id: str
    label_key: str                 # i18n key in the plugin's own catalogue
    pipeline: dict[str, dict]      # step id -> params
    group_roles: list[str] = []
    filename_patterns: list[str] = []   # named groups `group`, optional `role`
    prompts: list[PromptSpec] = []      # instruction, output_schema, scope, auto_run
    cross_check: Callable[[GroupRead, list[PromptResultRead]], dict] | None = None

def register_step(step: Step) -> None: ...
def register_preset(preset: Preset) -> None: ...
```

- **Steps never touch storage or sessions directly.** `StepContext` reads
  and writes through the module, which enforces the
  never-overwrite-the-original rule (`write_display` writes `display_key`,
  never `storage_key`). The module also owns the three-phase session
  handling.
- **Output** must be JSON-serialisable, and is capped by a setting
  (`step_output_max_bytes`, 64 KiB by default).
- **A cross-check** is a pure function over read models. It runs in the
  group-run task and gets no session.

### 8.4 Result views (frontend)

A plugin may ship `images-steps.ts` at its package root. The module globs
these in, the same way pagebuilder globs `pagebuilder-blocks.ts` from
records (#142):

```ts
// portal: modules/lucas/lucas/images-steps.ts
import { registerResultView } from "@simple-module-py/images";   // re-exported by sm_images
import { LivestockCountView } from "./components/LivestockCountView";
import { LucasCrossCheckView } from "./components/LucasCrossCheckView";

registerResultView({ kind: "step", id: "lucas.livestock_count", component: LivestockCountView });
registerResultView({ kind: "cross_check", id: "lucas", component: LucasCrossCheckView });
```

- `kind` is `step`, `prompt_result` (keyed by preset id, for preset
  prompts) or `cross_check` (keyed by preset id).
- A component receives `{ output, image | group, t }` and renders read-only.
- Correction stays the module's schema-generated form, so review behaves the
  same everywhere.
- Anything without a registered view falls back to a generic key/value
  view. Uninstalling a plugin's frontend never breaks the viewer.
- The view files live outside `pages/` (CLAUDE.md's page rule), and their
  strings come from the plugin's own `locales/`.

### 8.5 Worked example: the portal's `lucas` plugin

```python
# portal: modules/lucas/lucas/module.py
from sm_images.contracts import Preset, PromptSpec, register_preset, register_step

class LucasModule(ModuleBase):
    meta = ModuleMeta(name="lucas", depends_on=["images"])

    def on_startup(self, app):
        register_preset(Preset(
            id="lucas",
            label_key="lucas.preset.label",
            pipeline={
                "anonymize": {"faces": True, "plates": True},
                "classify": {"vocabulary": LAND_USE_VOCABULARY, "instruction": LAND_USE_PROMPT},
            },
            group_roles=["point", "north", "east", "south", "west"],
            filename_patterns=[r"^(?P<group>.+?)LCLU_(?P<role>Point|North|South|East|West)"],
            prompts=[
                PromptSpec(id="lucas.photo", scope="image", instruction=PHOTO_PROMPT,
                           output_schema=LUCAS_PHOTO_SCHEMA, auto_run=True),
                PromptSpec(id="lucas.summary", scope="group", inputs="results",
                           instruction=SUMMARY_PROMPT, output_schema=LUCAS_SUMMARY_SCHEMA),
            ],
            cross_check=lucas_cross_check,
        ))
```

This moves `pipeline_presets.py`, `constants_bag.py`,
`cross_check._lucas_cross_check`, the role order in `crud_bag.py:62`, the
filename pattern in `GeoJsonImportDialog.tsx` and the land-use prompt in
`classification_schema.py` out of the generic code, and none of it needs a
custom step. A custom step (`register_step`) is only for work a prompt
can't express, such as a deterministic per-image computation.

## 9. Repo-wide consequences

These are shared with the GIS design; whichever lands first does them:
- `background_tasks`, `file_storage` and `sharing` join the host.
- A `make worker` target, using the `dev-services` Redis.
- Celery `task_always_eager` in unit and e2e tests.
- `tippecanoe` in the CI image.
- CLAUDE.md's "no Redis or Celery" line is updated.

Specific to `images`:
- **CI installs the `[quality]` extra, but not `[anonymize]`.** Torch is too
  heavy for every run. The anonymize step's tests use a fake detector
  through the step interface, and one nightly or opt-in job runs the real
  models with a small fixture set.
- **Floor:** framework `>=0.0.41,<0.1`, after the roadmap's framework bump.
  `ai` is an optional extra at the lockstep floor, with a floor comment.
- **Migrations:** host revisions with `branch_labels = ("images",)`, one
  head, and `alembic check` on SQLite and Postgres.
- **Docs:** `modules/images/docs/`, covering pipeline and steps, writing a
  step or preset plugin, import limits, access and originals, the worker
  guide, and migrating from the portal.

## 10. Phasing

1. **Framework bump to 0.0.41.** Roadmap step 1.
2. **Core:** models, settings, tenancy, policy, sharing, visibility,
   collection and image CRUD, direct and batch upload, `exif` and
   `renditions` (run eagerly), image route, gallery and viewer.
3. **Pipeline framework:** step registry (§8.2 rules: freeze, namespacing,
   missing-plugin handling), `register_step`, `StepContext`,
   `images_step_run`, executor with claim, lease and retry/restart, Celery
   queues, pipeline config UI, the `quality` step, janitor, and the
   `images-steps.ts` glob with the generic fallback view. A test plugin
   module in `modules/images/tests/` exercises registration end to end.
4. **Imports:** GeoJSON URL and base64 streaming with checkpoint, resume
   and dedupe, downloads with the DNS-resolving SSRF guard and rate limits,
   ZIP with limits, import wizard and jobs panel.
5. **Anonymization:** the `anonymize` step writing `display_key`,
   `images.originals.view`, the original toggle, the opt-in real-model CI
   job.
6. **AI:** `classify`, prompts (image and group scope), `register_preset`
   and the cross-check hook, the review queue, the `ai` metering callable if
   needed.
7. **Map:** points endpoint, PMTiles extra, map tab, public collection
   page, pagebuilder `ImageGallery` block.

**Portal adoption**, outside this repo:
- a `lucas` plugin (preset, cross-check, roles, filename pattern, land-use
  classify params);
- a data migration from the portal's tables:
  - `ImagePipelineStatus_DB` columns become `images_step_run` rows;
  - bags become groups;
  - `is_public` becomes `internal`;
  - shares are mapped as in §2;
  - anonymized images keep their key as `storage_key`, flagged as "original
    not retained";
- removing `features/images`.

## 11. Calls made without the maintainer

The maintainer asked for a generic module drawn from gis-data-portal only.
Every choice below is mine:

- One module, with heavy processors as extras (`[quality]`, `[anonymize]`,
  `[ai]`, `[map]`), not separate modules.
- Framework `sharing` with view/edit, collapsing the portal's four roles,
  and owner or `images.manage` for the destructive actions.
- A new `internal` visibility for the portal's "public = any logged-in
  user", and a real anonymous `public` beside it.
- Originals are kept, with a separate display copy and permission.
  Downloads are no longer re-encoded by default.
- A step registry with a per-step status table instead of fixed columns.
  Step versions mark results stale.
- "Bags" are renamed "groups", with per-collection role order. Presets and
  cross-checks are plugin extension points, and LUCAS moves to the portal.
- Extension details (the maintainer chose the module approach over entry
  points):
  - the registry freezes after startup;
  - ids are namespaced by the plugin module;
  - a missing plugin leaves its results readable and its steps unscheduled;
  - steps get storage only through `StepContext`;
  - result views are globbed from `images-steps.ts`, with a generic
    fallback.
- AI goes through the `ai` module, never the portal's own providers.
- A review/correction model for AI results, which the portal lacks.
- An access-checked image route with long cache headers, instead of
  one-hour presigns.
- External connectors are dropped. No dependency on `geodata`.
