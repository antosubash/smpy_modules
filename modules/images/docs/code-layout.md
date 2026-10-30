# Code layout

`sm_images` is grouped by feature. Find the feature, then the file. The
300-line cap keeps files small, so a feature is a package, never one big module.

## Top level

Only what the framework or every feature needs stays at the top of the package:

| Module | What it is |
| --- | --- |
| `module.py` | The `ModuleBase` the host loads (the `simple_module` entry point) |
| `tasks.py`, `task_config.py` | The Celery tasks, and their queues and beat schedule. **Both must stay here**: `background_tasks` imports `<package>.tasks` and `<package>.task_config` and looks nowhere else (`tests/core/test_task_discovery.py`) |
| `constants.py`, `errors.py`, `events.py`, `menu.py` | Names, error types, published events, the console menu |
| `settings.py`, `settings_boot.py` | The DB-backed settings class and what is read at boot |
| `clock.py`, `db_time.py`, `intents.py` | Wall clock, database clock, write-ahead object intents, used everywhere |

## Feature packages

| Package | Holds |
| --- | --- |
| `access/` | The collection policy (`access/__init__.py`), write rules, the redaction state, the sharing resource type, a background run's starter right |
| `tenancy/` | Binding the tenant per request (`tenancy/__init__.py`), the tenancy mode, the request context |
| `billing/` | The storage-gauge facade billing sees (`billing/__init__.py`), the hold swap ops, settle, install, repair, metering keys |
| `storage/` | The object store (`storage/__init__.py`) and the object-key layout (`storage/keys.py`) |
| `serving/` | Serving image bytes (`serving/respond.py`): cache headers, `Range`, URLs |
| `jobs/` | The platform beats: janitor, reconcile, purge and their phases |
| `ingest/` | Uploads: multipart, base64, direct-to-storage, admission, dedupe |
| `imports/` | GeoJSON and ZIP import jobs, safe fetching |
| `pipeline/` | The step registry, plugins, planning, claiming and running steps |
| `steps/`, `processing/` | Built-in steps (quality, classify, anonymize) and image helpers (EXIF, renditions, HEIF) |
| `ai/` | Prompts, group prompts, cross-checks and metering through `sm_ai` |
| `regroup/` | Grouping by filename pattern, in place or as a job |
| `map/` | Points, PMTiles builds, the basemap style |
| `models/`, `schemas/` | Tables and request/response shapes |
| `services/` | Reads and writes the endpoints share |
| `endpoints/` | Routers: `api/` (JSON), console and public views, request dependencies, CSRF |
| `contracts/` | What other modules may import. Anything outside it can move |

`access`, `tenancy`, `billing` and `storage` keep their public face in the
package's `__init__.py`, so `from sm_images import billing` and
`billing.check(...)` read as before the package existed. That only works for a
light module: an `__init__.py` runs whenever any sibling is imported, so
`serving`'s heavy byte-serving code lives in `serving/respond.py` and its
`__init__.py` is empty. Every module imports on its own in a fresh interpreter;
keep it that way when adding imports to an `__init__.py`.

## Frontend

`pages/` holds only real Inertia pages (the page name comes from the path). The
rest is in `components/<feature>/`, `hooks/` and `utils/`, and page tests are in
`page-tests/`.

## Tests

`tests/` mirrors the packages: `tests/<feature>/test_*.py`, with shared helpers
in `tests/support/` and files in `tests/fixtures/` and `tests/plugin_fixture/`.
A new test goes in the folder of the feature it exercises.

`tests/pg_support.py` stays at the root: it is the Postgres opt-in every module
copies, and `scripts/tests/test_helper_parity.py` holds the copies identical,
path depth included. The tenancy helpers (`tenancy/__init__.py`,
`tenancy/_mode.py`) are copies of records' in the same way.
