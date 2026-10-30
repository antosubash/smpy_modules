# Code layout

`sm_images` follows the repo's [module layout](../../../docs/module-layout.md),
and is its reference. This page maps that layout onto images: find the
feature, then the file.

## Top level

| Path | What it is |
| --- | --- |
| `module.py` | The `ModuleBase` the host loads (the `simple_module` entry point) |
| `tasks.py`, `task_config.py` | The Celery tasks, and their queues and beat schedule. **Both must stay here**: `background_tasks` imports `<package>.tasks` and `<package>.task_config` and looks nowhere else (`tests/core/test_task_discovery.py`) |
| `constants.py`, `errors.py`, `events.py` | Names, error types, published events |
| `index.ts` | The TS surface a plugin imports (`@simple-module-py/images`) |
| `pagebuilder-blocks.ts` | The ImageGallery block; pagebuilder globs this name |

## Feature packages

| Package | Holds |
| --- | --- |
| `access/` | The collection policy (`access/__init__.py`), write rules, the redaction state, the sharing resource type, a background run's starter right |
| `tenancy/` | Binding the tenant per request (`tenancy/__init__.py`), the tenancy mode, the request context |
| `settings/` | The DB-backed settings class (`settings/__init__.py`) and what is read at boot (`settings/boot.py`) |
| `clock/` | The wall clock (`clock/__init__.py`) and the database clock (`clock/db.py`) |
| `billing/` | The storage-gauge facade billing sees (`billing/__init__.py`), the hold swap ops, settle, install, repair, metering keys |
| `storage/` | The object store (`storage/__init__.py`), the object-key layout (`storage/keys.py`) and write-ahead object intents (`storage/intents.py`) |
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
| `endpoints/` | Routers: `api/` (JSON), console and public views, request dependencies, CSRF, the console menu |
| `contracts/` | What other modules may import. Anything outside it can move |

`serving/__init__.py` holds only a docstring: its byte-serving code is heavy
and imports half the package, so it lives in `serving/respond.py`. Every module
imports on its own in a fresh interpreter. Keep it that way when adding
imports to an `__init__.py`.

## Frontend

- `pages/`: the Inertia pages.
- `components/<feature>/`: everything else, grouped by feature.
  `components/results/plugins.ts` globs in the plugins' `images-steps.ts`.
- `hooks/`, `utils/`: hooks and plain TS.
- `page-tests/`: the page tests, `test-dom.tsx` and shared test support.

## Tests

`tests/<feature>/test_*.py` mirrors the packages; `tests/core/` covers boot,
contracts, settings and task discovery. Shared helpers are in `tests/support/`;
files the tests read are in `tests/fixtures/` and `tests/plugin_fixture/`.

`tests/pg_support.py` stays at the root, and the tenancy helpers
(`tenancy/__init__.py`, `tenancy/_mode.py`) are copies of records'. The repo's
parity checks hold both identical across modules; see
[module layout](../../../docs/module-layout.md#tests).
