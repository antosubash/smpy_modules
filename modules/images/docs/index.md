# Images documentation

`simple_module_images` keeps **collections of photos** in a SimpleModule host:
each image has an immutable original, optional location, capture time and camera
metadata, and everything derived from it (EXIF, renditions, quality metrics, an
anonymised display copy, AI labels, map tiles) is produced by **pipeline steps**
that run as background tasks. Collections are private, shared with chosen users,
internal to the organisation, or public on the web.

The design is `docs/superpowers/specs/2026-10-28-images-module-design.md` in the
source repository. These pages describe what the code does now, and where it
differs from the design the page says so.

## Who should read what

| You are | Read |
| --- | --- |
| Installing the module, or deciding who may see what | this page, then [access.md](access.md) |
| Running it in production: workers, beat, queues, timeouts | [worker.md](worker.md) |
| Importing GeoJSON, ZIPs or many files, or setting limits | [imports.md](imports.md) |
| Configuring steps, AI prompts, groups, presets or storage billing | [pipeline.md](pipeline.md) |
| Adding a step, a preset or a result view from another module | [writing-a-plugin.md](writing-a-plugin.md) |
| Moving the gis-data-portal `images` feature onto this module | [migrating-from-portal.md](migrating-from-portal.md) |
| Changing the module's code: where each feature lives | [code-layout.md](code-layout.md) |

## Concepts

- **Collection.** The unit of access. It has an owner, a `visibility`
  (`private`, `internal` or `public`), a pipeline configuration, an optional
  preset and an ordered list of group roles.
- **Image.** Belongs to one collection. `storage_key` is the original and is
  never written after insert. A step that changes what people see writes a
  separate **display copy** (`display_key`); everyone is served that copy, and
  the original only to the owner and holders of `images.originals.view`.
- **Step.** One unit of pipeline work on one image, with a status
  (`pending`, `running`, `completed`, `skipped`, `failed`), a version and a JSON
  output. Built-in: `exif`, `renditions`, `quality`, `anonymize`, `classify`,
  and one `prompt:<id>` per AI prompt. A plugin adds its own without a
  migration.
- **Group.** A set of images of one site, each with a role (the portal called
  them bags). Roles are per collection; a filename pattern can fill groups at
  import time.
- **Prompt.** An instruction plus an optional JSON Schema, run for each image
  or for each group. Results can be reviewed (accepted, corrected, rejected).
- **Preset.** What a plugin bundles for a collection: pipeline, prompts, group
  roles, filename patterns and an optional cross-check. The module ships none.

## Screens

The console is at `/admin/images`.

- **Collections** lists owned, shared, internal and public collections and
  creates new ones. A new collection starts with `exif` and `renditions`.
- **Collection** has tabs: the gallery with filters and uploads, the map, groups
  and prompts, plus the pipeline and the import jobs for anyone who may edit.
  Sharing is a dialog on the collection.
- **Image** is the viewer: display copy, metadata, step results, prompt results,
  an original toggle for those allowed, and the group assignment.
- **Review** is the queue of AI results; see [pipeline.md](pipeline.md#reviewing-results).
- `/images/c/{slug}` is the anonymous page of a public collection: a gallery
  with a lightbox, and the map. The optional pagebuilder extra adds an
  `ImageGallery` block that shows a public collection on a page.

## Install

```bash
pip install simple_module_images
```

A plain install pulls no onnxruntime or OpenCV. Heavy processors are
extras, imported only inside the step that needs them; with an extra missing
the step is not registered and a collection that enabled it keeps the
configuration, its runs settling as `not_installed`.

| Extra | Adds |
| --- | --- |
| `quality` | OpenCV: resolution, blur and exposure metrics |
| `anonymize` | onnxruntime (MIT): face and number-plate detection, blurred into a display copy. Model licences and attribution below |
| `ai` | `simple_module_ai`: `classify` and prompts |
| `billing` | `simple_module_billing`: storage and AI-request metering |
| `pagebuilder` | `simple_module_pagebuilder`: the `ImageGallery` block |

The map view needs no extra: its PMTiles archive is built by the `tippecanoe`
binary (`tippecanoe_path`), which must be on the worker's machine.

The module depends on the framework's `settings`, `sharing`, `file_storage` and
`background_tasks` modules. Migrations live in the consuming host
(`make migration`), never in the wheel; the first images revision carries
`branch_labels = ("images",)`, which names the revision but does not roll back
only this module (see the repo `CLAUDE.md`).

### `anonymize`: models and licences

The extra installs only **onnxruntime** (MIT; it brings numpy, BSD). No torch,
no ultralytics and nothing AGPL. The step downloads two ONNX models on first
use, each pinned by size and SHA-256:

| Detects | Model | Licence | Source |
| --- | --- | --- | --- |
| Faces | YuNet, `face_detection_yunet_2026may.onnx` (230 KB), by Shiqi Yu, from OpenCV Zoo | [MIT](https://github.com/opencv/opencv_zoo/blob/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4/models/face_detection_yunet/LICENSE) | [opencv/opencv_zoo @ eb9f4f2](https://github.com/opencv/opencv_zoo/tree/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4/models/face_detection_yunet) |
| Number plates | `yolo-v9-s-608-license-plates-end2end.onnx` (28.6 MB), by ankandrew | [MIT](https://github.com/ankandrew/open-image-models/blob/main/LICENSE) | [open-image-models release `assets`](https://github.com/ankandrew/open-image-models/releases/tag/assets) |

Both are MIT, so redistributing them, or a product that downloads them, needs
the copyright notice and licence text kept with them; the repository's
`NOTICE` file carries both. Three more things to know:

- The plate model was trained with the YOLOv9 reference code (WongKinYiu/yolov9,
  GPL-3.0), not ultralytics, and its author publishes the weights under the
  repository's MIT licence. The training data is not documented. If that
  provenance matters to you, point `anonymize_weights_path` at a model of your
  own.
- Recall has not been verified against a labelled set. Treat the blur as best
  effort, not as a guarantee that no plate or face remains. Plates are searched
  in the whole frame and, on a large picture, in four overlapping tiles too;
  faces at full size and at 640 px. A low `min_confidence` blurs more false
  positives (a wheel, say) rather than fewer faces.
- A re-run that finds nothing leaves the **previously blurred display copy** in
  place; it does not revert to the original.

The weights are never in the wheel. Where they come from is in
[worker.md](worker.md#the-anonymize-step).

## Permissions

| Permission | Allows |
| --- | --- |
| `images.view` | Open the console and the API; what the access policy admits |
| `images.create` | Create collections and upload |
| `images.publish` | Make a collection `internal` or `public` |
| `images.manage` | Act on every collection of the tenant as if the owner (it also satisfies `images.publish`) |
| `images.originals.view` | Download the immutable original of a protected image |

[access.md](access.md) has the full table of who may do what.

The module's settings are governed by the framework's `settings.edit`, as every
other module's are; images has no settings permission of its own.

## Settings

Stored in the database and edited on the Settings screen or with
`scripts/set_setting.py`. **There is no `SM_IMAGES_*` environment variable**, and
the class ignores `.env`. The scope is system: one configuration for every
tenant. Workers read the same values (cached for about 30 seconds).

| Setting | Default | Meaning |
| --- | --- | --- |
| `max_image_bytes` | 50 MiB | Largest single image |
| `batch_max` | 50 | Files per multipart request |
| `upload_body_max_bytes` | 100 MiB | Body ceiling of the upload routes (read per request) |
| `direct_upload_threshold` | 20 MiB | Files above this must use a direct (multipart) upload |
| `max_open_uploads_per_tenant` | 20 | Direct and ZIP uploads a tenant may have open at once ([imports](imports.md#direct-upload)) |
| `zip_max_bytes` | 2 GiB | Largest ZIP |
| `zip_max_entries` | 10 000 | Entries per ZIP |
| `zip_max_entry_bytes` | 200 MiB | One decompressed entry |
| `zip_max_total_bytes` | 8 GiB | All decompressed bytes of a ZIP |
| `zip_max_ratio` | 200 | Highest compression ratio of an entry |
| `geojson_max_features` | 1 000 000 | Features per GeoJSON source |
| `geojson_max_bytes` | 2 GiB | Largest GeoJSON source |
| `geojson_max_feature_bytes` | 60 MiB | One feature (fits a 50 MiB image as base64) |
| `download_concurrency_per_domain` | 4 | Simultaneous downloads from one host, per task |
| `download_concurrency_total` | 32 | Simultaneous downloads across hosts, per task |
| `download_timeout` | 60 s (1 to 240) | One image download |
| `thumbnail_sizes` | marker 64, small 160, medium 400, large 1024 | Rendition name to longest edge in pixels |
| `dedupe_by_hash` | off | Skip an upload whose `sha256` exists in the collection |
| `map_rebuild_threshold_pct` | 5 | Rebuild the map when this percentage of points changed ... |
| `map_rebuild_threshold_abs` | 100 | ... or this many, whichever comes first |
| `map_style_url` | `https://tiles.openfreemap.org/styles/positron` | MapLibre style drawn under the points; empty or `https://` only. See [Basemap](#basemap) |
| `janitor_grace_days` | 7 | Days an unreferenced object or a trashed row is kept |
| `step_output_max_bytes` | 65 536 | Largest JSON a step may store |
| `step_lease_seconds` | 1 800 | How long a running step holds its lease |
| `tippecanoe_path` | `tippecanoe` | The binary that builds PMTiles. **Restart** |
| `anonymize_weights_path` | empty | Directory with `face.onnx` and `plate.onnx`; read per run |
| `public_asset_base_url` | empty | Origin that serves public renditions instead of this app; single-tenant hosts only (ignored, with a warning, on a multi-tenant one). **Restart** |

`thumbnail_sizes` and the limits are read per request or per task. The three
fields marked **Restart** are read once while booting.

### Basemap

The map (the collection's Map tab and the public page) draws its points over
the MapLibre style named by `map_style_url`. The default is OpenFreeMap's
Positron: free, no API key, OpenStreetMap data, with its attribution in the
map's (i) button.

**Privacy trade-off.** With a basemap, every viewer's browser, in the console
and on public pages, fetches the style and the tiles for the area it looks at
from that host, which so learns their IP address and roughly where they look.
Set `map_style_url` to empty for a flat background and no third-party request
at all; the points work the same either way.

The style's origin (`https://tiles.openfreemap.org` for the default) is added
to the Content-Security-Policy's `connect-src` and `img-src` through a CSP
provider, evaluated per response, so a change applies at the next page load
without a restart. Only that one origin is allowed: a style whose tiles,
glyphs or sprite live on another host needs them on the same origin. A style
that cannot be fetched (offline, blocked, gone) falls back to the flat
background, and the points are still drawn.

## Events and contracts

Published after commit: `ImageAdded`, `ImageProcessed` (all steps final),
`PromptResultReviewed`, `CollectionVisibilityChanged`, `CollectionDeleted`.

Another module imports only `sm_images.contracts`: the events, the read models
(`CollectionRead`, `ImageRead`, `GroupRead`, `PromptResultRead`), the
policy-filtered reads `get_collection`, `list_collections`, `points` and
`rendition_url` (each call names its tenant and principal), and the extension
points `register_step`, `register_preset`, `Step`, `StepContext`, `StepOutcome`,
`Preset` and `PromptSpec` ([writing-a-plugin.md](writing-a-plugin.md)).

## Behaviours worth knowing

These are deliberate, and each is explained where it belongs.

- A withheld image answers 404, exactly like an absent one, to anyone who may
  not edit the collection ([access.md](access.md#withheld-images)).
- Pipeline progress and step outputs are for editors; viewers see counts of the
  display-safe images only.
- Uninstalling a plugin that provided the display-mutating step withholds the
  affected displays until the owner re-saves the pipeline
  ([access.md](access.md#withheld-images)).
- Lowering a plan limit evicts nothing ([pipeline.md](pipeline.md#storage-metering)).
- Eager mode has no overall deadline ([pipeline.md](pipeline.md#eager-mode)).
- A plugin must be installed identically in the web process and every worker
  ([writing-a-plugin.md](writing-a-plugin.md#registration)).
- Deleting a collection does not remove its rows in the framework's `sharing`
  module ([access.md](access.md#sharing)).
