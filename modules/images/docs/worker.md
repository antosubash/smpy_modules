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
- **the same installed plugins.** The registry is built from the installed
  `simple_module` entry points in each process
  (`sm_images.pipeline.extensions.load_extensions`). If a worker lacks a
  plugin the web process has, that worker's runs of the plugin's steps settle
  as `not_installed`.

The real environment takes precedence over `.env` in the workers too
(`load_dotenv_into_environ` uses `setdefault`), so a one-off override on the
command line reaches both sides.

Beat writes `celerybeat-schedule.db` in the repo root, which git ignores.

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
