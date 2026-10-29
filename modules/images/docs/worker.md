# Running images with real workers

Tests and the e2e server run images in eager mode
(`SM_BG_TASKS_TASK_ALWAYS_EAGER=true`), so every task runs inline in the web
process. This page covers the other mode, with a broker and separate Celery
processes, as a deployment runs it. It also records the last end-to-end check
against real workers.

## Processes

| Make target | Queues | Concurrency | Runs |
|---|---|---|---|
| `make worker` | `images`, `celery` | 4 | light steps (`exif`, `renditions`, plugin steps on `images`), `images.download_items`, `images.reconcile`, `images.janitor`, `images.build_map`, the framework's own tasks |
| `make worker-imports` | `images_imports` | 1 | `images.import_geojson`, `images.reset_import`, `images.restart_collection`, `images.run_regroup`, `images.run_prompt` |
| `make worker-heavy` | `images_heavy` | 2 | `classify`, `prompt:*`, `images.run_group_prompt` |
| `make worker-gpu` | `images_gpu` | 1 | steps that declare `queue = "images_gpu"` (anonymize) |
| `make beat` | - | - | the schedule: `images.reconcile` every 5 minutes, `images.janitor` daily, plus the framework's beats |

Run `worker-imports` with concurrency 1, as the target does. All targets run
`host/worker.py` (`build_runner_celery`) from the repo root, so the workers
read the same `.env` and the same database-stored settings as the web process.
The web process and every worker need:

- the same `SM_DATABASE_URL`;
- the same broker, set by `SM_REDIS_URL`. That one URL seeds both the broker
  and the result backend. `SM_BG_TASKS_BROKER_URL` and
  `SM_BG_TASKS_RESULT_BACKEND` still work but print a deprecation warning;
- `SM_BG_TASKS_TASK_ALWAYS_EAGER` unset or `false`;
- the same file storage (`file_storage` settings). The local backend only
  works when every process shares one filesystem;
- **the same installed plugins, registered the same way.** A worker never builds
  the app, so a plugin cannot register from `on_startup`. Each process builds the
  registry from the installed `simple_module` entry points and imports every
  package's `images_extensions.py`
  (`sm_images.pipeline.extensions.load_extensions`; see
  [writing-a-plugin.md](writing-a-plugin.md#registration)). A worker that lacks a
  plugin the web process has settles that plugin's step runs as `not_installed`;
  install it identically in the web image and in every worker image.

The real environment takes precedence over `.env` in the workers too
(`load_dotenv_into_environ` uses `setdefault`), so a one-off override on the
command line reaches both sides.

Beat writes `celerybeat-schedule.db` in the repo root, which git ignores.

## Production settings

### Database timeouts

The framework's default for both is `0`, which is off. A worker holding a lock
on a stuck database connection holds a worker slot, and images sets no Celery
time limit on its import tasks, so **set both on Postgres**:

- `SM_DB_STATEMENT_TIMEOUT_MS` (`statement_timeout`) and
  `SM_DB_IDLE_IN_TX_TIMEOUT_MS` (`idle_in_transaction_session_timeout`) for the
  host. Workers inherit them.
- `SM_BG_TASKS_DB_STATEMENT_TIMEOUT_MS` overrides the statement timeout for the
  workers alone, where a longer value than the web process's may belong. Restart
  workers after changing any of them. PgBouncer in transaction mode rejects these startup
  parameters; see the framework's database tuning guide.

### Why imports have no Celery time limit

A 1M-feature GeoJSON import legitimately runs for hours, so a hard or soft task
time limit would kill healthy work. Instead an import is **liveness-guarded**:

- the runner writes a **heartbeat** while it works (also during slow downloads);
- `images.reconcile` reclaims a job whose heartbeat is older than 5 minutes, under
  a new generation, and resumes it from the checkpoint;
- a job that is reclaimed again and again with no progress is failed as
  `stalled` after five relaunches (the **stalled breaker**).

CPU work is bounded by size caps instead of time: `max_image_bytes`, the pixel
guard, the ZIP limits, `geojson_max_feature_bytes`, `step_output_max_bytes`. The
task decorators declare `stuck_after` (12 hours for imports, 2 hours for the
rest), which is what the framework's sweep reads. If you do want a time limit for
image steps, set `task_soft_time_limit`/`task_time_limit`; a step that hits the
soft limit then fails with `time_limit`.

### Celery tuning

The framework fixes `acks_late` and a prefetch multiplier of 1, which suit long
tasks. The rest are `background_tasks` settings, read once when a worker starts
(Settings screen, or the environment as `SM_BG_TASKS_<FIELD>`):

| Setting | Why for images |
| --- | --- |
| `visibility_timeout_seconds` | On a Redis broker a message not acknowledged within it (Celery's default is 1 hour) is redelivered, so a longer task runs twice. Set it above your longest import, for instance 12 hours (43 200) to match the import tasks' `stuck_after` |
| `worker_max_tasks_per_child`, `worker_max_memory_per_child_kb` | Recycle prefork children; torch and OpenCV hold memory. Worth setting on `worker-heavy` and `worker-gpu` |
| `task_reject_on_worker_lost` | Redeliver a task whose child was killed (for instance by the memory cap) |
| `worker_concurrency` | The make targets pass `-c` on the command line |

As general advice, give the heavy workers a thread budget (`OMP_NUM_THREADS=1`, and the same for
OpenCV/MKL if they are used) so a child does not oversubscribe the cores. The
database engine is rebuilt in every forked child, so no connection crosses a fork.

`worker-imports` runs with concurrency 1, and `worker-gpu` with one child.

### The anonymize step

The `anonymize` step is registered only when `torch` and `ultralytics` import.
**Both are AGPL-3.0, and so are the default weights** (see
[index.md](index.md#licence-warning-anonymize)); the module itself is MIT.

- **Weights.** With `anonymize_weights_path` empty, the pinned YOLO weights
  (a face model and a plate model, commit-pinned from Hugging Face) are downloaded
  once, on first use, into `~/.cache/simple_module_images/models` of the user the
  worker runs as. Each load verifies size and SHA-256 and reads from a private
  snapshot, so a swapped cache file is never loaded. **On a read-only home,
  or to keep weights off the network, set `anonymize_weights_path`** to a
  directory holding `face.pt` and `plate.pt`; those are used as they are, with no
  checksum, and a missing file fails the run (`weights_unavailable`). The setting
  needs a restart; workers read it from the same database setting.
- **Recall.** The plate model's recall has not been verified. It is a best-effort
  blur.
- **Re-runs.** A re-run starts from the original. If it detects nothing it
  completes without a new display copy, so the **previously blurred copy
  stays**.
- CI installs the extra only in the weekly `images-models` workflow, with CPU
  torch.

### Map tiles

`tippecanoe` must be on `PATH` of the workers that run `images.build_map` (queue
`images`), or at `tippecanoe_path`. Without it the map falls back to GeoJSON
points and the `images.tippecanoe` health check reports degraded. The map worker
in the browser (MapLibre) is inlined as a `blob:` URL, so no Content-Security-Policy
source has to be added.

## A local run

With dev-services' Postgres and Redis up, on a scratch database and a free
Redis db index:

```bash
export SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/images_t28
export SM_REDIS_URL=redis://localhost:6379/11
export SM_BG_TASKS_TASK_ALWAYS_EAGER=false
uv run --project host alembic -c host/alembic.ini upgrade heads
# each in its own terminal (or in the background, logged to a file)
uv run --project host uvicorn main:app --app-dir host --port 8028
make worker
make worker-imports
make worker-heavy
make beat
```

Each worker logs `<name>@<host> ready.` and sends one `images.reconcile` when
it comes up. Stop the processes with Ctrl-C (or `kill`). Then drop the scratch
database and run `FLUSHDB` on the Redis index you used.

To check a plugin the way a deployment would install it, without installing a
package into the venv, put a `.dist-info` directory with an `entry_points.txt`
on `PYTHONPATH`, next to the plugin package. Do this for the web process and
for every worker. For the workers, pass
`CELERY="PYTHONPATH=host:<extra> uv run --project host celery -A worker:celery"`
to make. The check below did this with the test fixture
`tests/plugin_fixture/images_testplugin`. Its entry point was
`testplugin = images_testplugin.module:TestPluginModule`.

## Verified on 2026-10-29

Times below are UTC.


The setup was framework 0.0.41, Postgres and Redis from dev-services, and the
host with every module, billing included. It ran single-tenant (`default`),
not eager. Four Celery processes ran from the make targets above (worker,
worker-imports, worker-heavy, beat), and uvicorn ran without `--reload`. The
`images_testplugin` fixture was on the path of all of them. The collection's
pipeline was `exif`, `renditions` and `testplugin.count_pixels`.

- **Uploads.** Three JPEGs went through `POST /api/images/collections/{id}/images`.
  All 9 step runs were `completed` within about 2 seconds, and every
  `images.run_step` ran in `make worker`. Each image's `processed_generation`
  reached its `processing_generation`.
- **Registry parity.** `GET .../pipeline` in the web process listed
  `exif, renditions, quality, classify, testplugin.count_pixels`. A worker
  started with the same path registers the same five (checked with
  `load_extensions()`), and the same command without the fixture on the path
  registers only the four built-ins. The plugin step completed in the worker
  with `{"pixels": 307200}`, so the worker found it through its own
  entry-point scan. Nothing reached it from the web process.
- **GeoJSON import (base64, 3 features).** The job completed in about 4
  seconds on `worker-imports`: 3 items `done`, 3 images, and each image's
  steps `completed` on `worker`.
- **Kill mid-import.** The next job had 3 features of about 7 MB of noise
  JPEG each (28 MB of GeoJSON). After its first item was `done`, the imports
  worker (main process and child) got `SIGKILL`. That left the job `running`
  at generation 0, with item 0 `done` and items 1 and 2 `pending`. The worker
  was restarted at once. Its `worker_ready` reconcile found nothing to do,
  because the heartbeat was not yet older than the 5-minute cutoff. The next
  beat `images.reconcile` after the cutoff (about 8 minutes after the kill)
  reclaimed the job (`import_jobs: 1`, generation 1, `relaunches` 1). The new
  runner resumed at the first item without an image. The job completed:
  `done_count` 3, `duplicate_count` 0, `failed_count` 0. Item 0 kept its
  image, and the collection held 3 new images with 3 distinct `sha256`. The
  image row of the attempt the kill interrupted was never committed.
- **Storage billing.** With `billing` installed, every image went through an
  `ingest` op (the hold for the original) and then a `swap` op (original plus
  renditions). All of them settled right after their commit, with no retry
  (`attempts` 0). The old holds were `released`, each image's hold was
  `committed` at exactly its `storage_bytes`, and the
  `images.storage_bytes` gauge equalled the sum of `storage_bytes` over all
  images.

### The kill's leftovers

The interrupted ingest of item 1 left two things behind. Both are documented
recovery paths, not bugs:

- **An `ingest` op still claimed.** Billing had committed its hold
  (7,042,337 bytes) under the op's key. The process died before the insert
  marked the op done or handed it to the settler. Until the op's 30-minute
  ingest claim expired, the gauge counted that hold on top of what the images
  store, so the tenant was over-counted by one original. The claim expired at
  12:31:52. The beat reconcile at 12:34:46 took the op over: the settler
  recorded billing's hold on the op, released it (`released`, settled
  12:34:47) and finished the op. That left no op pending, and the gauge
  (22,066,483) equalled the sum of `storage_bytes` again, 33 minutes after
  the kill.
- **An object intent** (`images_object_intent`) for the original that was
  written but never referenced. The daily janitor reaps it once it is older
  than `janitor_grace_days` (7 days by default). Until then the object stays
  in storage, but billing does not count it.

## Caveats

- **Recovery time.** Recovery after a dead import worker takes between the
  5-minute cutoff (`reconcile.CUTOFF`) and that plus one beat interval, so
  5 to 10 minutes. The reconcile sent on `worker_ready` covers only work that
  is stale already. It does not shorten that window.
- A step run killed mid-run is reclaimed once its lease expires
  (`step_lease_seconds`, 30 minutes by default). It is not reclaimed after
  5 minutes.
- An ingest killed after billing committed its hold over-counts the tenant
  by that original until the op's ingest claim (30 minutes) expires and the
  next reconcile tick settles it, so for 30 to 35 minutes. Near a plan limit,
  that window can refuse an upload that would otherwise fit.
- Plugins must be installed identically in the web image and every worker
  image (see "Processes").
- Image download limits (`download_concurrency_*`) are per download task, not
  fleet-wide ([imports.md](imports.md#downloads-and-the-ssrf-guard)).
- A change to an images setting reaches workers within about 30 seconds (their
  settings cache); the three restart settings need a restart.
