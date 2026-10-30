# Code layout

`sm_images` follows the repo's [module layout](../../../docs/module-layout.md),
and is its reference. This page maps that layout onto images: find the
area, then the feature, then the file.

```
sm_images/
  __init__.py  module.py  tasks.py  task_config.py  index.ts  pagebuilder-blocks.ts
  models/  pages/  locales/  contracts/
  core/      what every feature builds on
  web/       the HTTP side
  ingest/    how images come in
  pipeline/  what happens to them
  jobs/      platform beats and regroup jobs
  map/       points, PMTiles, the basemap
  ui/        the frontend that is not a page
```

## Top level

| Path | What it is |
| --- | --- |
| `module.py` | The `ModuleBase` the host loads (the `simple_module` entry point) |
| `tasks.py`, `task_config.py` | The Celery tasks, and their queues and beat schedule. **Both must stay here**: `background_tasks` imports `<package>.tasks` and `<package>.task_config` and looks nowhere else (`tests/core/test_task_discovery.py`) |
| `models/` | Tables; `simple_module_db` imports `sm_images.models` for migrations |
| `pages/`, `locales/` | Inertia pages and the i18n catalogues, found by the host's globs |
| `contracts/` | What other modules may import. Anything outside it can move |
| `index.ts` | The TS surface a plugin imports (`@simple-module-py/images`) |
| `pagebuilder-blocks.ts` | The ImageGallery block; pagebuilder globs this name |

## Areas

| Path | Holds |
| --- | --- |
| `core/` | Names and limits (`constants.py`), error types (`errors.py`), published events (`events.py`), and the foundations under them: `clock/` (wall and database clock), `settings/` (the DB-backed class and what is read at boot), `tenancy/` (binding the tenant per request, the mode, the request context), `access/` (the collection policy, write rules, redaction state, sharing type, a run's starter right), `storage/` (the object store, key layout, write-ahead intents) and `billing/` (the storage gauge: hold swap ops, settle, install, repair, metering keys) |
| `web/` | `endpoints/` (routers: `api/` for JSON, console and public views, request deps, CSRF, the menu), `schemas/` (request and response shapes), `services/` (reads and writes the endpoints share) and `serving/` (image bytes in `serving/respond.py`: cache headers, `Range`, URLs) |
| `ingest/` | Uploads (multipart, base64, direct-to-storage, admission, dedupe) at its top, and `imports/`: GeoJSON and ZIP import jobs, safe fetching |
| `pipeline/` | The engine at its top (step registry, plugins, planning, claiming, running), `steps/` (built-in quality, classify, anonymize), `processing/` (EXIF, renditions, HEIF) and `ai/` (prompts, group prompts, cross-checks, metering through `sm_ai`) |
| `jobs/` | The platform beats (janitor, reconcile, purge and their phases) and `regroup/`, grouping by filename pattern in place or as a job |
| `map/` | Points, PMTiles builds, the basemap style |
| `ui/` | `components/<feature>/`, `hooks/`, `utils/`, and `page-tests/` (page tests, `test-dom.tsx`, shared test support). `ui/components/results/plugins.ts` globs in the plugins' `images-steps.ts` |

`core/__init__.py`, `web/__init__.py` and `serving/__init__.py` hold only a
docstring: importing one sibling must never run the others. Every module
imports on its own in a fresh interpreter. Keep it that way when adding
imports to an `__init__.py`.

## Tests

`tests/` mirrors the areas: `tests/core/` (boot, contracts, settings, task
discovery, plus `access/`, `billing/`, `storage/`), `tests/web/` (`serving/`,
`collections/`, `groups/`), `tests/ingest/` (with `imports/`),
`tests/pipeline/` (with `ai/`, `steps/`), `tests/jobs/` and `tests/map/`.
Shared helpers are in `tests/support/`; files the tests read are in
`tests/fixtures/` and `tests/plugin_fixture/`.

`tests/pg_support.py` stays at the root, and the tenancy helpers
(`core/tenancy/__init__.py`, `core/tenancy/_mode.py`) are copies of records'.
The repo's parity checks hold both identical across modules; see
[module layout](../../../docs/module-layout.md#tests).
