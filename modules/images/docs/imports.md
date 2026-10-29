# Getting images in

Four ways, all of which run the collection's pipeline afterwards and all of which
check the storage gauge first when `billing` is installed (402 `quota_exceeded`;
an import item that does not fit fails with the same code).

| Way | Route | Use |
| --- | --- | --- |
| Multipart batch | `POST /api/images/collections/{id}/images` | Up to `batch_max` files, each at most `direct_upload_threshold` |
| Base64 | `POST /api/images/collections/{id}/images/base64` | One image from a client that cannot send multipart |
| Direct upload | `POST /api/images/collections/{id}/uploads`, then parts, then `complete` | One large file (up to `max_image_bytes`) straight to storage |
| ZIP | `POST /api/images/collections/{id}/imports/zip`, parts, `POST /api/images/imports/{job}/extract` | An archive of images, optionally with `metadata.json` |
| GeoJSON | `POST /api/images/collections/{id}/imports` | Thousands to a million located images, from URLs or inline base64 |

All of them need an `edit` right on the collection (owner, an edit share, or
`images.manage`).

## What every upload is checked for

- **The bytes, not the name.** The type is sniffed from magic bytes. Accepted:
  JPEG, PNG, WebP, HEIC, HEIF and TIFF (415 `unsupported_type` otherwise). The
  original is stored under the extension of the sniffed type, and its
  `content_type` is the sniffed one. A direct upload's declared type must agree
  with the bytes.
- **Size.** Over `max_image_bytes` is 413 `file_too_large`; over
  `direct_upload_threshold` through the multipart route is 413
  `use_direct_upload`. The multipart and base64 routes carry a request-body
  ceiling of `upload_body_max_bytes` plus 1 MiB of multipart framing; other
  routes use the host's global limit. More than `batch_max` files is 422
  `batch_too_large`.
- **Pixels.** A decompression bomb (more pixels than Pillow's
  `Image.MAX_IMAGE_PIXELS` allows) is 413 `image_too_many_pixels`. A host that
  sets `MAX_IMAGE_PIXELS = None` switches the guard off.
- **Originals stay as delivered.** Nothing re-encodes a downloaded or uploaded
  image; the design's `normalize_downloads` option was dropped, because it would
  replace the delivered original. Renditions cover display sizes.

Per-file outcomes are `created`, `duplicate` or `error` (with `code` and
`detail`); a batch of one file raises that file's error instead.

### Metadata and dedupe

The multipart route takes a `metadata` form field: JSON keyed by filename, each
value `lat`, `lng`, `captured_at`, `external_source`, `external_id`, `group_key`,
`group_role` and `properties` (at most 16 KiB). Coordinates typed by a person are
`location_source = manual` and are never overwritten by EXIF or an import.

A duplicate is decided in three layers: a pre-check, an in-batch set, and the
unique index on `(collection, external_source, external_id)` (trashed images
count, so re-uploading a trashed image's id is a duplicate, not an error). With
`dedupe_by_hash` on, a file whose `sha256` already exists in the collection is a
duplicate too; that has no index behind it, so two concurrent uploads of the same
bytes can both land.

## Direct upload

For a file above `direct_upload_threshold`, the console uses
`POST /collections/{id}/uploads` (`filename`, `size`, `content_type`). The answer
carries a signed `upload_id`, a `part_size` (8 MiB), one URL per part and
`direct`:

- On **S3 or MinIO** `direct` is true and the URLs are presigned: the browser
  `PUT`s each part straight to the bucket.
- On a backend that cannot presign (the filesystem) the URLs are this app's relay
  route, `PUT /api/images/uploads/{upload_id}/parts/{n}`.

Then `POST /api/images/uploads/{upload_id}/complete` with the part etags and any
metadata, or `DELETE /api/images/uploads/{upload_id}` to abort. The token is
signed with the host's `secret_key`, valid for 24 hours, and is **not encrypted**:
it shows up in relay URLs and so in access logs, and grants nothing without the
owner's session, an edit right and a bound tenant. A replayed `complete` answers
with the image it created. An abandoned upload is reclaimed by the janitor.

**Admission.** An open upload lets the client write straight to storage, so it is
admitted before the `upload_id` is issued (here and for a ZIP import's upload):

- at most `max_open_uploads_per_tenant` (default 20) uploads may be open in a
  tenant at once; one more is `429 too_many_open_uploads`;
- with billing installed, the storage gauge plus the declared sizes of the
  tenant's open uploads plus this one must fit the plan, or it is
  `402 quota_exceeded`.

An upload is open until it is completed, aborted or expires. The declared size is
binding: every part must be exactly its expected size and `complete` refuses a
missing, short or extra part. Admission is **serialised per tenant**: each open
first writes the tenant's `images_upload_admission` row (a row lock on Postgres,
the write lock on SQLite) and holds it until its session row is committed, so the
next open counts it. The cap is hard. The quota check is soft: the gauge's
headroom is read from billing *before* the lock (so no billing connection is ever
opened while it is held), then compared under the lock with the declared sizes
of every open upload. Only holds that `complete` takes between that read and the
lock go unseen, an overshoot of at most the declared sizes of the uploads
completing in that window; their own holds are still the enforcement. A refused
open releases the lock, then aborts the backend's multipart upload it had
started. While the lock is held, nothing but the admission session's connection
is used: the backend's multipart upload is started and its parts presigned
before it is taken.

> **Bucket CORS (S3 and MinIO).** The browser talks to the bucket directly, so
> the bucket's CORS configuration must allow the **`PUT`** method from the
> console's origin, and must **expose the `ETag` response header**
> (`ExposeHeaders: ["ETag"]`). Without the exposed header the browser cannot read
> the etag of a part, and `complete` fails. The presigned requests carry no
> credentials, so `AllowedHeaders` can be `*`. The filesystem backend relays
> parts through the app and needs none of this.

## ZIP archives

`POST .../imports/zip` (`filename`, `size`, optional `mapping` with only
`filename_pattern`, `auto_run_prompts`) creates a job in `uploading` and returns
`job_id` and an upload ticket like the direct upload's. After the parts are sent,
`POST /api/images/imports/{job_id}/extract` seals it (the etags are checked
against storage) and starts the runner.

The archive is inspected before any image is imported, and one refusal fails the
whole archive with a constant code:

- The end records are read first, ZIP64 included, and the entry count is capped
  before `ZipFile` ever loads the directory (`zip_max_bytes`, `zip_max_entries`).
- Zip-slip names (`..`, absolute paths, drive letters, backslashes, NUL),
  symlinks, encrypted entries, compression other than stored or deflate,
  overlapping entry data and nested archives are refused.
- Every entry is decompressed once while counting what comes out, and the header's
  claimed size is never trusted: `zip_max_entry_bytes`, `zip_max_total_bytes`,
  `zip_max_ratio`.
- Folders, `__MACOSX/` and dot-files are not entries. Duplicate names are allowed
  and each is its own image.

A root `metadata.json` (an object keyed by filename; the portal's spelling
`latitude`/`longitude`/`external_metadata` and this module's `lat`/`lng`/
`properties` are both read) supplies coordinates (stored as `manual`), capture
time, external id and group key. A malformed one fails the job as
`metadata_invalid`, and a second one as `metadata_duplicate`. Groups can also come
from the mapping's `filename_pattern` matched against the entry's name.

## GeoJSON imports

`POST /collections/{id}/imports` is a form: `kind` (`geojson_url` or
`geojson_base64`), `mapping` (JSON), `auto_run_prompts` (default true), and exactly
one of an uploaded `file` or a `source_url`. Everything a client can get wrong is
a 422 with a code before a job exists, including a source that is not a complete
`FeatureCollection`, more than `geojson_max_features` features, and a `source_url`
that fails the SSRF check.

> **Size limits.** An uploaded `file` is part of the request body, which the
> upload routes cap at `upload_body_max_bytes` plus 1 MiB of form framing (about
> 101 MiB by default), so that is the real ceiling for an uploaded GeoJSON.
> `geojson_max_bytes` (2 GiB) bounds what is fetched from a `source_url`; it is
> checked on an upload too, but the body limit refuses first. Host a larger file
> and import it by URL.

The mapping names properties, as a name or a dotted path (`meta.photo.url`):

| Field | Meaning |
| --- | --- |
| `url_prop` | Image URL (required for `geojson_url`) |
| `image_prop` | Base64 image data, a data URI allowed (required for `geojson_base64`) |
| `lat_prop`, `lng_prop` | Coordinates; else the feature's geometry |
| `datetime_prop` | Capture time |
| `external_id_prop` | Dedupe key. Default: `sha256(url)[:32]` for URLs, `sha256("<job>:<index>")` for base64 (stable across a replay of the job) |
| `group_key_prop`, `group_role_prop` | Group membership |
| `filename_pattern` | A regular expression with `(?P<group>...)` and optional `(?P<role>...)`, matched against the filename |

A role is matched case-insensitively against the collection's `group_roles` and
stored in the collection's spelling; one the collection does not list is dropped.
Patterns run on the `regex` engine with a per-match timeout, so a catastrophic
pattern costs one feature its grouping and never a worker.

The source is staged in storage and streamed with `ijson` (the file is never
loaded whole), recorded in chunks of 1 000 features with a checkpoint, and a job
holds back while 5 000 of its items are still pending. One JSON string token is
read whole before the size budget applies (an `ijson` limit), so a single token
can use memory up to `geojson_max_bytes`; `geojson_max_feature_bytes` rejects
larger features as `feature_too_large`. An image from a feature is a normal
upload, so every check above applies.

### Downloads and the SSRF guard

A URL is fetched only when its scheme is http or https, its port is 80 or 443, it
has no userinfo, and **every address its host resolves to is public**. The check
runs again on each redirect, and the resolved addresses are the ones dialled, so
DNS rebinding cannot swap them. Loopback, private, link-local and metadata
addresses are refused.

A presigned source URL's query string is its credential, so it is kept out of the
logs: a filter on the `httpx` logger (installed at boot and in every worker)
logs each request with its scheme, host and path only. Images' own log lines
name the host, never the URL.

A fetch honours `download_timeout` and the size cap. Transport errors, 408, 429
and 5xx are retried with backoff, honouring `Retry-After` (a date or seconds; a
wait over a day fails the item, and a wait too long to sit through leaves the item
pending for `images.reconcile`). Anything else (another 4xx, an unsafe URL, a
body too large) fails the item, and an item is attempted at most 8 times in its
lifetime.

> **The limits are per download task.** `download_concurrency_per_domain` and
> `download_concurrency_total` bound one `images.download_items` task (one event
> loop), not the fleet. With several workers the ceiling on one remote host is
> the limit times the number of download tasks running at once. A Redis-backed
> limiter would be a drop-in, but there is none.

### Controls and recovery

A job is `uploading`, `pending`, `staging`, `running`, `paused`, `resetting`,
`completed`, `failed` or `cancelled`. `GET .../imports` lists a collection's jobs;
`pause`, `resume`, `restart`, `retry-failed` and `DELETE` are each one
compare-and-set on the job row, so a double click or two reviewers lose cleanly.
Restart needs the source (staged, or a URL to fetch again); retry-failed on a
base64 job needs its staged source, which a finished job with failures keeps
until `janitor_grace_days`. A job that finished with no failures deletes its
staging at once.

A killed worker is recovered by `images.reconcile`: a job whose heartbeat is older
than 5 minutes is reclaimed under a new generation and resumed from its checkpoint
(base64: the first item without an image), with no duplicates. A job found stale
again after five relaunches with no progress fails as `stalled` instead of looping. Every
write is fenced on the job's generation, so a runner that lost its job cannot
write. See [worker.md](worker.md) for the times.

A job runs under the starter's edit right and is cancelled (`access_revoked`) if it
is lost ([access.md](access.md#background-work-runs-under-the-starters-right)).
