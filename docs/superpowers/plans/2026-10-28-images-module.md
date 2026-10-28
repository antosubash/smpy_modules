# Images module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This file is also the run's state.** Tick a task's box in the same commit
> that finishes it. A resumed session starts at the first unticked task.

**Goal:** Ship `modules/images` (`sm_images`, PyPI `simple_module_images`): photo collections with location, a registered-step pipeline, imports at portal scale, review of AI results, a map and plugin extension points, on framework 0.0.41.

**Architecture:** One framework module modelled on `modules/records` (layout, tenancy copy, settings, harness, i18n). It stores bytes through the framework's `file_storage` backend, shares through `sharing`, and runs work as Celery tasks through `background_tasks` (eager in tests and e2e). Heavy processors are extras (`[quality]`, `[anonymize]`, `[ai]`, `[map]`, `[pagebuilder]`) imported only inside the step that needs them.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic (host), Celery via `background_tasks`, Pillow + pillow-heif, ijson, httpx, opencv-python-headless, torch/facenet-pytorch/ultralytics (extra only), pydantic-ai through `sm_ai.contracts`, tippecanoe (system binary), React + Inertia + `@simple-module-py/ui`, MapLibre + pmtiles (frontend), vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-images-module-design.md` (approved). Read it alongside this plan.
**Porting map:** `docs/superpowers/plans/2026-10-28-images-module-porting-map.md` (Codex's read of the portal: files to port, invariants, tests worth porting). The portal source is `~/Repos/gis-data-portal/backend/app/features/images/` and `frontend/src/features/images/`. Read it as reference only; never import from it.

## Global Constraints

- Framework floor in `modules/images/pyproject.toml`: `simple_module_*>=0.0.41,<0.1`. Never `==`. The host pins exactly `==0.0.41`.
- Sibling extras: `ai = ["simple_module_ai>=0.0.13,<0.1"]`, `billing = ["simple_module_billing>=0.0.13,<0.1"]` and `pagebuilder = ["simple_module_pagebuilder>=0.0.13,<0.1"]`, each with a `# floor: <reason>` comment. If the `ai` metering callable (Task 22) is new, the `ai` floor is the next lockstep version and the comment says so.
- Plain `pip install simple_module_images` pulls no torch, ultralytics or cv2. Import them only inside the step module, behind the extra.
- Package `sm_images`. `ModuleMeta.name = "Images"`. Locale namespace `images`. Table prefix `images_`. `create_module_base("images")`.
- Routes: API `/api/images`, console views `/admin/images`, public views `/images/c/{slug}`. Constants live in `sm_images/constants.py` (`check_hardcoded_strings`).
- The settings class subclasses `DbBackedSettings` (no env), SYSTEM scope. Boot-time fields are `json_schema_extra=_RESTART` and read in `on_startup`.
- Every router binds a tenant via `sm_images.tenancy.bind_admin` / `bind_public`. It is a copy of `sm_records.tenancy` and is added to the parity family in `scripts/tests/parity_tenancy.py`.
- Every `.py`, `.ts` and `.tsx` file is at most 300 lines; split by responsibility at 280.
- Nothing goes under `sm_images/pages/` except real Inertia pages.
- en and de catalogues are kept in step (`check_locales`). Frontend keys are derived from `locales/en.json` as in `modules/news/news/utils/i18n.ts`.
- **Originals are immutable.** No code path writes `storage_key` after insert. Only `StepContext.write_display` writes `display_key`.
- Migrations: host revisions only. The first images revision carries `branch_labels = ("images",)`. The history ends in one head. Run `alembic check` on SQLite and Postgres after each migration task.
- Outside a request, commit with `simple_module_db.finalize_session` wherever events or billing are involved.
- Tests: targeted only (the module's touched test files, or one e2e spec). No full suites and no CI waits until `/ship`. `PYTEST_WORKERS=8`. Run `~/.claude/bin/wait-for-headroom` before any suite, dev server or browser.
- Commit messages: `feat(images): <task>`, ending with `Claude-Session: https://claude.ai/code/session_017uTbtobjCKQYnAxF5tgK8t`.

## Decisions made during planning (deviations from the design text)

1. **Registry freeze timing (§8.2).** In the framework, a dependant's `on_startup` runs *after* its dependency's, and the framework has no "after all modules started" hook (verified against 0.0.41). So:
   - plugins call `register_step` / `register_preset` from a `register_*` hook. The documented choice is `register_settings(app)`, which every module's runs before any `on_startup`;
   - images freezes the registry in its own `on_startup`, and lazily on first read in a Celery worker;
   - a registration after the freeze raises `RegistryFrozenError`.

   The worked example in the module docs uses `register_settings`. The intent of the design (a late registration fails at boot) holds.
2. **No share UI ships in the framework.** Images builds its own share dialog against `GET/POST/DELETE /api/sharing/shares`.
3. **`file_storage` has no delete-by-prefix.** The janitor deletes known keys. Each image's keys come from its row, its renditions, its display copy and the map. Import staging keys are recorded on the job.
4. **Bytes go through `app.state.file_storage.backend` directly.** They go through the backend (or `build_backend(settings_for(...))` in a worker) under our own key layout, not as `StoredFile` rows. The `file_storage` quota therefore doesn't apply; images' own limits and billing do.
5. **No framework `worker_ready` hook.** `sm_images/tasks.py` connects `celery.signals.worker_ready` itself to resume interrupted imports.
6. Console URL `/admin/images` (repo convention, as records and news use) instead of the design's bare `/images`.

## Review Focus

1. **A caller sees an image or count they cannot open.** Lists, counts, points, tiles, renditions, group views and the review queue must all apply the same SQL policy. Task 6 adds `test_every_read_route_hides_private_collection` and parametrises it over every GET route.
2. **A re-run after a skipped step, or EXIF after a manual location, changes data it must not.** Task 13 adds `test_skipped_is_final_for_version` and `test_exif_never_overrides_manual_location`.
3. **A huge or hostile upload.** This covers a decompression bomb, a zip bomb, zip-slip, HEIC, and a wrong extension versus the magic bytes. Tasks 8 and 17 add `test_bomb_pixels_413_translated`, `test_zip_total_uncompressed_cap` and `test_heic_upload_processes`.
4. **An import interrupted mid-stream** (worker restart). It must resume from the checkpoint without duplicates. Task 16 adds `test_resume_after_kill_no_duplicates`.
5. **A tenant leak on a single-tenant host or in a worker task.** Task 6 adds `test_unbound_tenant_admin_403`. Task 12 adds `test_task_runs_in_enqueuer_tenant`.

---

## Phase 1 — Framework bump

### Task 1: Framework 0.0.41

**Files:**
- Modify: `host/pyproject.toml` (every `==0.0.38` becomes `==0.0.41`; add `simple_module_file_storage`, `simple_module_sharing`, `simple_module_background_tasks` at `==0.0.41` if they are not already present; check the exact PyPI names), `host/client_app/package.json` (`@simple-module-py/*` to 0.0.41), `uv.lock`, `package-lock.json`.
- Create: host revisions porting the framework's revisions this host lacks, in order. They are listed in the framework repo at `host/migrations/versions/`: `f733c7938fd1` (sharing_resource_share), `d7b3a9e5c1f2` (mail keys; check whether `30033455948e` already ported it), `bb906e1a1089`, `1f5985daa10b`, `a625f0b7c912`, `a626b1c8d023`, plus any `background_tasks` / `file_storage` tables that 0.0.38's port skipped. Each docstring ends `(framework 0.0.4x)` and states the upstream id, as `b65e04cf65d7` does. Linear, one head.
- Modify: `CLAUDE.md`. Update the "no Redis or Celery" line, list the 0.0.39–0.0.41 ported revisions, and add the 0.0.40 note that bearer tokens are hashed (everyone re-logs in once).
- Modify: any test or code that 0.0.39–0.0.41 broke (`TenantDeleted`/`UserDeleted` moved but are re-exported; `@simple-module-py/ui/components/ui/form` was removed, so grep the modules for it).
- Create: `Makefile` target `worker` (`uv run celery -A host.worker:celery worker -l info -Q images,images_imports,images_heavy,images_gpu,celery`) and `host/worker.py` (`celery = build_runner_celery(<repo>/.env)`, modelled on the framework's `scripts/run_worker.py`).
- Modify: `.env.example` (`SM_REDIS_URL` commented, pointing at dev-services; `SM_BG_TASKS_TASK_ALWAYS_EAGER=true` for local runs without a worker).

**Done-check:**
- `make lint` passes.
- `uv run alembic upgrade heads && uv run alembic check` passes on SQLite and on Postgres (`SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules_images`, created in dev-services).
- `scripts/check_migration_heads.py` passes.
- `uv run pytest host/tests -n 8` passes.
- The framework-pins tests in each module (`test_framework_pins.py`) pass.

- [ ] Commit `deps: framework 0.0.41`

---

## Phase 2 — Core

### Task 2: Module skeleton

**Files:**
- Create:
  - `modules/images/{pyproject.toml,package.json,tsconfig.json,README.md}` (copy records' shapes; extras `quality`, `anonymize`, `ai`, `billing`, `map`, `pagebuilder`, `dev`).
  - `sm_images/{__init__.py,constants.py,module.py,settings.py,settings_boot.py,tenancy.py,_tenancy_mode.py,_tenant_guard.py,deps.py,locales/en.json,locales/de.json,utils/i18n.ts}`.
  - `tests/{__init__.py,conftest.py,pg_support.py,app_harness.py,stub_auth.py,isolation_support.py}`.
- Modify:
  - root `pyproject.toml` `testpaths` (add `"modules/images/tests"`);
  - `host/pyproject.toml` (dependency plus workspace source);
  - `host/tests/test_host_boots.py` `REPO_MODULES` (add `"Images"`);
  - `host/tests/test_menu_labels.py` (`sm_images`, `images.`);
  - `scripts/tests/parity_tenancy.py` and `parity_families.py` (add images' copies);
  - `.github/workflows/ci.yml` (add `ci_images` to the Postgres DB loop and a "Run pytest (images, Postgres)" step);
  - `README.md` module table.

**Interfaces — Produces:**
- `constants.PACKAGE="sm_images"`, `MODULE_NAME="Images"`, `DISTRIBUTION="simple_module_images"`, `ROUTE_PREFIX_API="/api/images"`, `VIEW_PREFIX="/admin/images"`, `PUBLIC_PREFIX="/images"`.
- Permissions `PERM_VIEW="images.view"`, `PERM_CREATE="images.create"`, `PERM_PUBLISH="images.publish"`, `PERM_MANAGE="images.manage"`, `PERM_ORIGINALS="images.originals.view"`, `PERM_SETTINGS="images.settings"`.
- `ImagesSettings(DbBackedSettings)` fields, with defaults from the spec:
  - `max_image_bytes=50*2**20`, `batch_max=50`, `direct_upload_threshold=64*2**20`;
  - `zip_max_bytes=2*2**30`, `zip_max_entries=10_000`, `zip_max_entry_bytes=200*2**20`, `zip_max_total_bytes=8*2**30`;
  - `geojson_max_features=1_000_000`, `geojson_max_bytes=2*2**30`;
  - `download_concurrency_per_domain=4`, `download_concurrency_total=32`, `download_timeout=60`;
  - `thumbnail_sizes={"marker":64,"small":160,"medium":400,"large":1024}`;
  - `dedupe_by_hash=False`, `normalize_downloads=False`;
  - `tippecanoe_path="tippecanoe"`, `anonymize_weights_path=""`;
  - `map_rebuild_threshold_pct=5`, `map_rebuild_threshold_abs=100`;
  - `public_asset_base_url=""`, `janitor_grace_days=7`, `step_output_max_bytes=65536`.
- `ImagesServices` at `app.state.sm_images` with `.settings`.
- Tenancy exports identical to records' (`bind_admin`, `bind_public`, `tenant_scope`, `TenantRequired`).
- Harness: `images_app`, `client`, `as_user(user_id, perms)`, `two_tenants`, plus a `storage` fixture giving the module an in-memory or `tmp_path` filesystem backend.

**Tests** (`tests/test_module_boot.py`):
- `test_module_registers_permissions` asserts the six permissions are in the registry.
- `test_settings_ignore_env` with `SM_IMAGES_MAX_IMAGE_BYTES=1` set in the env still sees `ImagesSettings().max_image_bytes == 50*2**20`.
- `test_unbound_tenant_admin_403` (multi-tenant harness, no tenant): `GET /api/images/collections` gives 403 `tenant_required`.

**Done-check:** `cd modules/images && uv run pytest -n 8 tests/test_module_boot.py`, `make lint`, `uv run pytest host/tests/test_host_boots.py host/tests/test_menu_labels.py`.

- [ ] Commit `feat(images): module skeleton`

### Task 3: Models and first migration

**Files:**
- Create: `sm_images/models/{__init__.py,_base.py,collection.py,image.py,rendition.py,step_run.py,group.py,prompt.py,import_job.py,download.py,enums.py}`; `host/migrations/versions/<rev>_add_images.py` (autogenerate with `make migration msg="add images"`, then add `branch_labels=("images",)` and a Postgres `_drop_enums()` helper as in `e23090832709`).

**Interfaces — Produces** (columns exactly as spec §1):
- Models `Collection`, `Image`, `Rendition`, `StepRun`, `Group`, `Prompt`, `PromptResult`, `ImportJob`, `Download`.
- Enums `Visibility{private,internal,public}`, `LocationSource{exif=1,import_=2,manual=3}` (an int precedence column), `StepStatus{pending,running,completed,skipped,failed}`, `ReviewStatus{unreviewed,accepted,corrected,rejected}`, `ImportKind{geojson_url,geojson_base64,zip}`, `JobStatus`, `DownloadStatus`.
- The partial unique index `uq_images_image_external` on `(collection_id, external_source, external_id) WHERE external_id IS NOT NULL` (both dialects).
- Unique constraints: `(tenant_id, slug)` on collection, `(image_id, size)` on rendition, `(image_id, step)` on step_run, `(collection_id, key)` on group, and on prompt_result `(prompt_id, image_id)` plus `(prompt_id, group_id)`.
- `sm_images/storage_keys.py`: `original_key(t,c,i,ext)`, `display_key(t,c,i)`, `rendition_key(t,c,i,size)`, `map_key(t,c)` and `import_key(t,job,name)`, matching spec §1's layout.

**Tests:**
- `tests/test_models.py`:
  - `test_external_id_dedupe_index`: a second insert with the same external triple raises `IntegrityError`, and a null external_id never conflicts.
  - `test_soft_delete_hides_collection`.
- `tests/test_storage_keys.py`: the exact strings.

**Done-check:** both test files pass; `alembic upgrade heads && alembic check` pass on SQLite and Postgres; one head.

- [ ] Commit `feat(images): data model and migration`

### Task 4: Storage adapter

**Files:** Create `sm_images/storage.py`.

**Interfaces — Produces:**
- `class ImageStore`:
  - `async put(key, data: bytes | AsyncIterator[bytes], *, content_type, size)`;
  - `async read(key) -> bytes`;
  - `async stream(key) -> AsyncIterator[bytes]`;
  - `async stream_range(key, start, end)`;
  - `async delete_keys(keys: Iterable[str]) -> int`;
  - `async exists(key)`.
- `def store_for(app) -> ImageStore` (uses `app.state.file_storage.backend`).
- `def worker_store() -> ImageStore` (`build_backend(settings_for(FileStorageSettings, "file_storage"))`, cached).

**Tests** (`tests/test_storage.py`, filesystem backend on `tmp_path`): round trip; a range read; `delete_keys` ignores missing keys.

- [ ] Commit `feat(images): storage adapter`

### Task 5: Access policy and sharing

**Files:** Create `sm_images/access.py`, `sm_images/resource_types.py`; modify `module.py` (`register_resource_types`, `depends_on` includes `"Sharing"`, `"FileStorage"` and `"BackgroundTasks"` by their real `ModuleMeta` names).

**Interfaces — Produces:**
- `COLLECTION_RESOURCE="images.collection"`.
- `POLICY = OwnedResourcePolicy(Collection.owner_id, bypass_perm=PERM_MANAGE, visibility_col=Collection.visibility, share_exists=share_exists_for(...))`.
- `def visible_collections(who: ResourcePrincipal, action) -> Select` adds `OR visibility='internal'` for view when `who` is a tenant member.
- `def visible_images(who, action) -> Select` joins collection under the same predicate and excludes soft-deleted collections.
- Dependencies `CollectionView`, `CollectionEdit` and `CollectionOwner` (owner or `images.manage`, for destructive actions) via `RequiresResource`.
- `def can_view_original(who, image, collection) -> bool` (owner or `PERM_ORIGINALS`).
- `public_collection(slug)` for anonymous access: `visibility='public'`, otherwise 404.

**Tests** (`tests/test_access.py`, parametrised over visibility × principal):
- an owner sees private;
- a stranger is 404 on private;
- a member sees internal;
- anonymous sees only public;
- a `view` share can't upload (403) and an `edit` share can;
- an `edit` share can't delete the collection;
- `images.manage` bypasses.

- [ ] Commit `feat(images): access policy and sharing`

### Task 6: Collection CRUD API

**Files:** Create `sm_images/endpoints/api/{__init__.py,collections.py}`, `sm_images/schemas/collection.py`, `sm_images/services/collections.py`, `sm_images/events.py`, `sm_images/contracts/{__init__.py,events.py,schemas.py}`.

**Interfaces — Produces:**
- Routes:
  - `GET/POST /api/images/collections` (filters `owned|shared|internal|public|all`, cursor pagination);
  - `GET/PATCH/DELETE /api/images/collections/{id}`;
  - `PUT …/{id}/visibility` (internal/public need `images.publish`).
- `CollectionService` with `create`, `update`, `set_visibility` and `soft_delete`.
- Events `CollectionVisibilityChanged` and `CollectionDeleted`, published via `db.on_commit`.
- Schemas `CollectionCreate`, `CollectionUpdate`, `CollectionOut` (output models carry no input bounds; see CLAUDE.md billing note) and `CollectionPage`.

**Tests** (`tests/test_collections_api.py`):
- CRUD;
- slug uniqueness per tenant (409);
- publish permission;
- an event fires only after commit;
- `test_every_read_route_hides_private_collection`, parametrised over a list `READ_ROUTES` in `tests/read_routes.py` that later tasks append to (gallery, image detail, renditions, points, map, groups, prompts, review queue, import jobs).

- [ ] Commit `feat(images): collection API`

### Task 7: Image ingest service and direct/batch upload

**Files:** Create `sm_images/ingest/{__init__.py,sniff.py,guards.py,service.py}`, `sm_images/endpoints/api/images.py`, `sm_images/schemas/image.py`.

**Interfaces — Produces:**
- `sniff(data: bytes) -> str | None` returns a content type from magic bytes (jpeg, png, webp, heic/heif, tiff).
- `guard_pixels(data) -> (w,h)` raises `ImageTooLarge` (mapped to a translated 413, as pagebuilder #221 does; reuse its message key pattern).
- `IngestService.add_image(collection, data, filename, meta: IngestMeta, *, source) -> Image | Duplicate`:
  - it sha256-hashes the data;
  - it dedupes by external triple (three layers: pre-check, in-batch set, IntegrityError re-check) and by hash when `dedupe_by_hash` is on;
  - it writes the original under `original_key`, inserts the row and creates the pending `StepRun` rows for the collection's enabled steps;
  - it fires `ImageAdded` on commit and enqueues the pipeline after commit (Task 12 wires the executor; until then a no-op hook `on_image_added`).
- `IngestMeta(lat,lng,captured_at,external_source,external_id,group_key,group_role,properties)`. Manual lat/lng sets `location_source=manual`.
- Routes:
  - `POST /api/images/collections/{id}/images` (multipart, 1..`batch_max` files plus optional `metadata` JSON keyed by filename);
  - `POST …/images/base64`;
  - `GET …/collections/{id}/images` (cursor, filters `has_location`, `step`, `step_status`, `review_status`, `group`);
  - `GET/PATCH/DELETE /api/images/images/{id}` (PATCH: lat/lng manual, group; DELETE needs owner or manage).

**Tests** (`tests/test_upload.py`):
- `test_magic_bytes_not_extension` (a PNG named `.jpg` is stored as `image/png`; a text file is 415);
- `test_bomb_pixels_413_translated`;
- `test_batch_over_max_422`;
- `test_base64_dedupes_external_id`;
- `test_hash_dedupe_off_by_default`;
- `test_heic_upload_processes` (needs `pillow-heif` in the core deps);
- `test_original_never_rewritten`, which asserts the bytes at `storage_key` stay equal across the whole lifecycle; later tasks extend it.

- [ ] Commit `feat(images): upload and ingest`

### Task 8: Built-in `exif` and `renditions` (as plain functions)

**Files:** Create `sm_images/processing/{exif.py,renditions.py}`.

**Interfaces — Produces:**
- `read_exif(data) -> ExifData(lat,lng,altitude,heading,captured_at,make,model,orientation)`, ported from the portal's `pipeline/geolocation.py` (GPS rationals, ref signs, DateTimeOriginal with offset).
- `make_renditions(display_bytes, sizes: dict[str,int]) -> dict[str, (bytes,w,h)]` applies `ImageOps.exif_transpose`, gives JPEG q85, never enlarges, and strips metadata.

**Tests:** fixture images in `tests/fixtures/` (a geotagged jpeg, a rotated jpeg, a heic, a png without exif), with exact expected values.

- [ ] Commit `feat(images): exif and rendition processors`

### Task 9: Image serving route

**Files:** Create `sm_images/endpoints/api/serve.py`, `sm_images/endpoints/public.py`.

**Interfaces — Produces:**
- `GET /api/images/images/{id}/r/{size}`, `…/display` and `…/original`:
  - stream from `ImageStore`;
  - an `ETag` is `sha256` (original) or the rendition's key plus `updated_at`;
  - honour `If-None-Match` with 304;
  - public collection: `Cache-Control: public, max-age=31536000, immutable`; otherwise `private, max-age=3600`;
  - `…/original` needs `can_view_original` when `display_key` is set (the original *is* the display copy when it isn't);
  - unknown size gives 404.
- Public twins under `bind_public` for public collections.
- `rendition_url(image, size) -> str` in `sm_images/urls.py`: `?v=<updated_at epoch>`, prefixed by `public_asset_base_url` for public collections when it's set.

**Tests** (`tests/test_serve.py`): cache headers per visibility; a 304 path; private is 404 to a stranger and to anonymous; the original route is 403 for an `edit` share once `display_key` is set.

- [ ] Commit `feat(images): access-checked image route`

### Task 10: Console screens — collections, gallery, viewer

**Files:** Create `sm_images/endpoints/views.py`, `sm_images/pages/{Collections.tsx,Collection.tsx,Image.tsx}`, `sm_images/components/{collections/*,gallery/*,viewer/*,share/ShareDialog.tsx}`, `sm_images/hooks/{useCollections.ts,useImages.ts,useShares.ts}`, `sm_images/utils/api.ts`, `menu.py`, and locale keys.

**Interfaces — Produces:**
- Inertia pages `Images/Collections`, `Images/Collection` and `Images/Image`.
- The gallery is a cursor-paginated grid of `small` renditions with filter chips.
- The viewer shows the display copy, an original toggle (shown only when the prop `can_view_original`), metadata, step results (generic key/value view for now; Task 14 adds the registry) and prompt results (Task 22).
- The share dialog lists, grants and revokes through `/api/sharing/shares`, with view/edit and a user picker from the framework's user directory endpoint.
- Collection tabs: Gallery, Map (Task 27), Imports (Task 19), Pipeline (Task 14), Groups (Task 21), Prompts (Task 23), Review (Task 24). Placeholders render only for implemented tabs.

**Tests:**
- vitest page tests in `sm_images/page-tests/` for `Collections` and `Image` (render, filter, original toggle hidden without the prop).
- e2e `tests/e2e/images-core.spec.ts`: create a collection, upload two jpegs, see thumbnails, open the viewer, share with a second user who sees it (standalone; it seeds its own data).

- [ ] Commit `feat(images): console collections, gallery and viewer`

---

## Phase 3 — Pipeline framework

### Task 11: Step registry and contracts

**Files:** Create `sm_images/pipeline/{registry.py,step.py,presets.py}`; export them from `sm_images/contracts/__init__.py`.

**Interfaces — Produces** (exactly spec §8.3):
- `Step` Protocol.
- `StepContext` (`image: ImageRead`, `params`, `tenant_id`, `read_display()`, `read_original()`, `write_display(data, content_type)` — raises unless `step.mutates_display` — and `progress(pct)`, which calls `background_tasks.heartbeat`).
- `StepOutcome.completed(output) | .skipped(reason) | .failed(code, message)`.
- `Preset` and `PromptSpec` (pydantic).
- `register_step`, `register_preset`, `get_step(id) -> Step | None`, `get_preset`, `all_steps()`, `freeze()`, `is_frozen()`.
- Errors `RegistryFrozenError`, `DuplicateStepError`, `ReservedStepIdError`, `UnresolvedRequiresError`, `CyclicRequiresError`.
- `RESERVED={"exif","renditions","quality","anonymize","classify"}` plus the prefix `prompt:`.
- Plugin ids must be `<module>.<name>` (regex `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`); built-ins register through an internal path.
- `topo_order(step_ids) -> list[str]` validates and orders.
- Freeze semantics are in "Decisions made" item 1.

**Tests** (`tests/test_registry.py`):
- duplicate id;
- reserved id;
- a bad namespace;
- an unresolved `requires` and a cycle fail at `freeze()`;
- a registration after freeze raises;
- `test_mutates_display_at_most_one` (pipeline config validation refuses two);
- a missing step returns `None` and doesn't raise.

- [ ] Commit `feat(images): step registry`

### Task 12: Executor, claim, lease, Celery tasks (hard)

**Files:** Create `sm_images/pipeline/{executor.py,claim.py,config.py,builtin_steps.py}`, `sm_images/tasks.py`, `sm_images/task_config.py`.

**Interfaces:**
- Consumes: Task 11's registry, Task 8's processors, Task 4's `ImageStore`.
- Produces:
  - `pipeline_config` validation: `validate_pipeline_config(cfg: dict) -> PipelineConfig` (enabled steps plus params validated by each step's `params_schema()`; an unknown step id is kept and reported as `not_installed`).
  - Built-in `ExifStep` (writes location only when `image.location_source` is NULL or `exif`, so it never overrides import or manual) and `RenditionsStep` (re-runs when `display_key` changed after its last completion).
  - `claim_steps(db, image_id, now) -> list[StepRun]`: `SELECT … FOR UPDATE SKIP LOCKED` on Postgres and a plain transaction on SQLite; a `running` row older than 30 minutes is reclaimable.
  - `run_image(image_id, *, force=False)`, three-phase per step with short sessions (load / work outside the session / store).
  - Status rules from spec §3:
    - `skipped` is final for its `step_version`;
    - a retry runs `failed` and `pending`;
    - `force` runs all;
    - a stale `step_version` counts as pending only under `force` or the "re-run stale" action;
    - an independent step still runs after a sibling fails.
  - `ImageProcessed` fires when every enabled step is final.
- Celery: `images.run_image` (queue chosen per step: the task runs light steps inline and enqueues `images.run_step` on `images_heavy` / `images_gpu` for others), `images.restart_collection(collection_id, scope: failed|stale|all)` (set-based in chunks of 1000 ids, on `images_imports`). `TASK_ROUTES`/`QUEUES` live in `task_config.py`.
- Enqueue with `enqueue_after_commit`. Ingest's `on_image_added` now enqueues `images.run_image`.
- Output larger than `step_output_max_bytes` fails the step with `output_too_large`.

**Tests** (`tests/test_executor.py`, eager Celery):
- `test_skipped_is_final_for_version`;
- `test_exif_never_overrides_manual_location`;
- `test_failed_step_does_not_block_independent`;
- `test_lease_reclaims_after_30_min` (freezegun or an injected clock);
- `test_concurrent_claim_runs_once` (Postgres only; skip on SQLite; two real connections, as in `fix/race-tests-real-connections`);
- `test_force_reruns_all`;
- `test_version_bump_marks_stale`;
- `test_task_runs_in_enqueuer_tenant`;
- `test_output_cap`.

- [ ] Commit `feat(images): pipeline executor and tasks`

### Task 13: `quality` step and pipeline API

**Files:** Create `sm_images/steps/quality.py` (imports cv2 inside `run`; registers only when `find_spec("cv2")`), `sm_images/endpoints/api/pipeline.py`.

**Interfaces — Produces:**
- `QualityParams(min_width=640, min_height=480, blur_threshold=100.0, dark_threshold=0.05, bright_threshold=0.95)`. Port the portal's `pipeline/quality.py` metrics.
- Routes:
  - `GET /api/images/collections/{id}/pipeline` (config, the registered steps with their JSON schemas, per-step status counts, stale counts, `not_installed` steps);
  - `PUT …/pipeline` (owner or manage);
  - `POST …/pipeline/restart {scope}`;
  - `POST /api/images/images/{id}/reprocess {force}`.

**Tests:**
- `test_quality_metrics_known_fixture` (blurred versus sharp fixture);
- `test_quality_absent_without_cv2` (monkeypatch `find_spec`);
- pipeline API permission tests;
- `test_not_installed_step_reported_never_scheduled`.

- [ ] Commit `feat(images): quality step and pipeline API`

### Task 14: Pipeline config UI and result-view registry

**Files:**
- Create: `sm_images/components/pipeline/*`, `sm_images/components/results/{registry.ts,GenericResultView.tsx,ResultView.tsx}`, `sm_images/images-steps.ts` (`import.meta.glob('../../*/*/images-steps.ts', { eager: true })` excluding itself; mirror pagebuilder's `puck-blocks.ts`), `sm_images/index.ts`.
- Modify: `package.json` `exports` so `@simple-module-py/images` resolves `registerResultView`.

**Interfaces — Produces:**
- `registerResultView({kind: 'step'|'prompt_result'|'cross_check', id, component})`. It throws on a duplicate.
- `<ResultView kind id output image? group?/>`, which falls back to `GenericResultView`.
- The pipeline tab: step toggles, a params form generated from the JSON schema (use the same JSON-schema form approach records uses, if it has one; otherwise a small field renderer), stale banner and restart buttons.

**Tests:** vitest `registry.test.ts` (fallback, duplicate throws) and `PipelineTab.test.tsx` (toggle sends PUT, not-installed warning shown).

- [ ] Commit `feat(images): pipeline UI and result views`

### Task 15: Test plugin and janitor

**Files:**
- Create: `modules/images/tests/plugin_fixture/` (a tiny module `images_testplugin` with `register_step` of `testplugin.count_pixels` and a preset, registered in `register_settings`), `tests/test_plugin_e2e.py`.
- Create: `sm_images/janitor.py` and its tasks `images.janitor` (beat, daily) and `images.purge_collection`.

**Interfaces — Produces:**
- `purge_expired(db, store, *, now, grace_days, dry_run=False, cap=1000) -> PurgeReport`. It locks rows and deletes every key of each image (original, display, renditions), the map key and job staging keys, then hard-deletes the rows. It also removes abandoned import staging older than the grace period.
- Billing release hook point (Task 25 wires it).

**Tests:**
- the plugin's step runs through the executor and its output is stored;
- a registration in `on_startup` (too late) raises at boot;
- uninstalling (unregister in a fresh app) leaves its results readable and `not_installed`;
- `test_purge_removes_storage_and_rows`;
- `test_purge_dry_run_changes_nothing`;
- `test_purge_respects_grace`.

- [ ] Commit `feat(images): plugin end-to-end test and janitor`

---

## Phase 4 — Imports

### Task 16: GeoJSON streaming import (hard)

**Files:** Create `sm_images/imports/{geojson_stream.py,mapping.py,checkpoint.py,jobs.py,filename_pattern.py}`, `sm_images/imports/tasks.py` (registered through `sm_images/tasks.py`).

**Interfaces — Produces:**
- `Mapping(url_prop, image_prop, lat_prop, lng_prop, datetime_prop, external_id_prop, group_key_prop, group_role_prop, filename_pattern)`.
- `validate_and_count(source) -> int` (ijson; limits `geojson_max_features` and `geojson_max_bytes`).
- `stage_source(job, data|url) -> key`.
- Task `images.import_geojson(job_id)`:
  - it streams features from the staged key and resumes at `checkpoint_index`;
  - it checkpoints every 1000 features;
  - base64 mode ingests inline;
  - URL mode inserts `Download` rows with `external_id = external_id_prop or sha256(url)[:32]`, with a backpressure ceiling on pending downloads;
  - it applies the group key and role from properties or the filename pattern, upserting `Group`.
- Job controls: `POST /api/images/collections/{id}/imports` (kind geojson_url or geojson_base64, mapping), `GET …/imports`, `GET /api/images/imports/{job}`, and `POST …/{job}/{resume|restart|retry-failed}` and `DELETE`.

**Tests** (port from the portal's `test_import_resume.py` and `test_import_dedup.py`; see the porting map):
- `test_resume_after_kill_no_duplicates` (raise mid-stream, rerun the task);
- `test_checkpoint_every_1000`;
- `test_three_layer_dedupe`;
- `test_feature_limit`;
- `test_filename_pattern_groups`.

- [ ] Commit `feat(images): GeoJSON streaming import`

### Task 17: Downloads with the SSRF guard and rate limits (hard)

**Files:** Create `sm_images/imports/{url_safety.py,downloader.py,rate_limit.py}`.

**Interfaces — Produces:**
- `resolve_public(url) -> (host, ips)`. It resolves DNS (`loop.getaddrinfo`) and rejects private, loopback, link-local, multicast, reserved and metadata addresses (169.254.169.254, fd00:ec2::254) and non-http(s) schemes.
- An httpx transport that pins the resolved IP and re-checks each redirect, with at most 5 redirects.
- `DomainLimiter(per_domain, total)` (asyncio semaphores).
- Task `images.download_batch(job_id, ids)`:
  - 429/5xx backoff honours `Retry-After` (capped);
  - `max_image_bytes` is enforced while streaming;
  - sniff, then `IngestService.add_image(source="import")`;
  - per-row status/attempts/last_error.
- `normalize_downloads` (off) re-encodes at 4000 px and quality 85 only when it's on.

**Tests:**
- `test_rejects_private_ip_after_dns` (a hostname resolving to 10.x, via a monkeypatched resolver);
- `test_redirect_to_private_rejected`;
- `test_retry_after_honoured`;
- `test_oversize_stream_aborted`;
- `test_per_domain_concurrency` (counting a fake transport);
- `test_download_idempotent` (port the portal's `test_download_task_idempotency`).

- [ ] Commit `feat(images): safe downloads`

### Task 18: ZIP import with limits

**Files:** Create `sm_images/imports/{zip_import.py,zip_safety.py}` (port the portal's `zip_safety.py`).

**Interfaces — Produces:**
- `POST /api/images/collections/{id}/imports/zip` returns `{job_id, upload}` (a presigned PUT through `DirectUploadBackend` when supported, else the multipart relay).
- `POST /api/images/imports/{job}/extract`.
- Limits: `zip_max_bytes`, `zip_max_entries`, `zip_max_entry_bytes`, `zip_max_total_bytes`, and the compression ratio.
- Zip-slip guard.
- An optional `metadata.json` applies as in the portal.
- Filename-pattern grouping.

**Tests:** `test_zip_slip_rejected`, `test_zip_total_uncompressed_cap`, `test_zip_entry_cap`, `test_zip_metadata_json_applied` and `test_zip_groups_by_pattern`.

- [ ] Commit `feat(images): ZIP import`

### Task 19: Import wizard and jobs panel; auto-run everywhere

**Files:**
- Create: `sm_images/components/imports/*` (port the portal's `geojsonPreview.ts` client-side preview and property auto-mapping, split under 300 lines) and `sm_images/hooks/useImportJobs.ts`.
- Modify: ingest so that every import path enqueues the pipeline and the `auto_run` prompts (prompt enqueue is a no-op hook until Task 22).

**Tests:**
- vitest `geojsonPreview.test.ts` (auto-mapping of common property names).
- e2e `tests/e2e/images-import.spec.ts`: a base64 GeoJSON import of 3 features shows a completed job and 3 located images (standalone; the URL mode is covered by unit tests only, since e2e has no outbound network).

- [ ] Commit `feat(images): import wizard and jobs panel`

---

## Phase 5 — Anonymization

### Task 20: `anonymize` step, originals permission and opt-in CI job

**Files:**
- Create: `sm_images/steps/anonymize/{__init__.py,step.py,detectors.py,blur.py}` (the detectors import torch, facenet_pytorch and ultralytics lazily; register only when they're importable; weights from `anonymize_weights_path` or downloaded once to the cache dir).
- Modify: the viewer's original toggle.
- Create: `.github/workflows/images-models.yml` (`workflow_dispatch` plus a weekly schedule; installs `[anonymize]` and runs `pytest -m real_models`).

**Interfaces — Produces:**
- `AnonymizeParams(faces=True, plates=True, padding=0.15, min_confidence=0.5)`.
- A `Detector` protocol `detect(img) -> list[Region]` with an injectable fake.
- Output `{regions:[…], faces:n, plates:n}`.
- It writes a display copy via `ctx.write_display`. `mutates_display=True`, queue `images_gpu`.

**Tests:**
- with a fake detector: `test_display_written_original_untouched` (extends `test_original_never_rewritten`), `test_renditions_rerun_from_display` and `test_original_route_permission`;
- `@pytest.mark.real_models test_real_face_blur` (deselected by default via `addopts`).

- [ ] Commit `feat(images): anonymization writes a display copy`

---

## Phase 6 — AI

### Task 21: Groups

**Files:** Create `sm_images/endpoints/api/groups.py`, `sm_images/services/groups.py` (port the regroup logic from the portal's `regroup.py` and `crud_bag.py` with `group_roles` from the collection, not hardcoded), and `sm_images/components/groups/*`.

**Interfaces — Produces:**
- `GET/POST /api/images/collections/{id}/groups`, `GET/PATCH/DELETE /api/images/groups/{id}`.
- `POST …/collections/{id}/regroup {pattern}`.
- A group detail lists its members ordered by `collection.group_roles`.

**Tests:** role order from the collection; regroup by pattern; an `edit` share can manage groups.

- [ ] Commit `feat(images): groups`

### Task 22: `ai` metering callable, `classify` and image prompts (hard)

**Files:**
- `modules/ai/sm_ai/contracts/__init__.py` plus `modules/ai/sm_ai/metering.py`: add `async def consume_requests(tenant_id: str, qty: int = 1, *, idempotency_key: str, source: str) -> bool`. With billing installed it goes through billing's `UsageService` in its own session finished with `finalize_session`; without billing it returns True. Add tests in `modules/ai/tests/test_metering_outside_request.py`.
- Create: `sm_images/steps/classify.py`, `sm_images/ai/{runner.py,schema_safety.py}`, `sm_images/endpoints/api/prompts.py`.

**Interfaces — Produces:**
- `ClassifyParams(vocabulary: list[str] = [], instruction: str = <neutral default>, max_side=1024)`.
- `run_structured(instruction, output_schema | None, images: list[bytes]) -> (data|text, model_name)`, using `sm_ai.contracts.resolve_model()` and a pydantic-ai `Agent` (output type built from the JSON Schema after `schema_safety.check(schema)`, which caps depth, size and `$ref`).
- `prompt:<id>` steps synthesised from `images_prompt` rows with image scope.
- A `PromptResult` upsert that preserves the review history (last 5).
- Prompts CRUD: `/api/images/collections/{id}/prompts`, `/api/images/prompts/{id}`, `POST …/prompts/{id}/run {scope: all|unprocessed|ids}`.
- Billing exceeded fails the step with `quota_exceeded`, with no retry storm.

**Tests:**
- pydantic-ai `TestModel`/`FunctionModel` (no network);
- `test_classify_uses_resolve_model`;
- `test_rerun_resets_review_keeps_history`;
- `test_schema_safety_rejects_deep_schema`;
- `test_metered_per_call`;
- `test_quota_exceeded_fails_step`;
- `test_absent_without_ai_module`.

- [ ] Commit `feat(images,ai): classify, prompts and metering outside requests`

### Task 23: Group-scope prompts, presets and cross-check

**Files:** Create `sm_images/ai/group_run.py`, `sm_images/services/presets.py`, `sm_images/components/prompts/*` (port `CustomPipelineManager` and `SchemaFieldBuilder`).

**Interfaces — Produces:**
- `run_group(prompt, group)`:
  - it ensures member image-scope results, reusing stored ones with at most 4 concurrent;
  - it makes one consolidation call at temperature 0;
  - it calls `preset.cross_check(group_read, results)`, whose return value goes into `cross_check`, guarded by try/except as `{error}`.
- `apply_preset(collection, preset_id)` seeds `pipeline_config`, `group_roles`, prompts (by `PromptSpec.id`, idempotent) and `preset_id`.
- `GET /api/images/presets`.
- Group-scope inputs: images, results or both.

**Tests:** consolidation is called once per group; members are reused; the cross-check is stored; a cross-check exception is captured; applying a preset is idempotent; the test plugin's preset is listed.

- [ ] Commit `feat(images): group prompts, presets and cross-check`

### Task 24: Review queue

**Files:** Create `sm_images/endpoints/api/review.py`, `sm_images/pages/Review.tsx`, `sm_images/components/review/*` (a schema-generated correction form, keyboard path: j/k move, a accept, r reject, e edit).

**Interfaces — Produces:**
- `GET /api/images/collections/{id}/review?status=unreviewed&prompt=` (cursor).
- `POST /api/images/prompt-results/{id}/review {action: accept|correct|reject, data?}`; `correct` validates `data` against the prompt's `output_schema` (422 otherwise).
- `PromptResultReviewed` is published on commit.

**Tests:**
- API: an `edit` share can review and a `view` share can't; correction validation; the event after commit.
- vitest: keyboard flow.
- e2e `tests/e2e/images-review.spec.ts`: seed a prompt result through a test-only seeding script (no AI call) and accept one, then correct one.

- [ ] Commit `feat(images): review queue`

### Task 25: Billing storage counter

**Files:** Create `sm_images/billing.py`.

**Interfaces — Produces:**
- Meter `images.storage_bytes` (defined in `on_startup` when `app.state.billing_meters` exists).
- `check` on upload and import start; `consume` per stored object (original, display and renditions) with idempotency key `obj:<key>`; `release` on hard delete in the janitor.
- `None` billing means unlimited.

**Tests:** over quota gives 402/`quota_exceeded` on upload; the janitor releases; no billing means no-op.

- [ ] Commit `feat(images): storage metering`

---

## Phase 7 — Map and public

### Task 26: Points and PMTiles

**Files:** Create `sm_images/map/{points.py,pmtiles_build.py,tasks.py}` and `sm_images/endpoints/api/map.py`.

**Interfaces — Produces:**
- `GET /api/images/collections/{id}/points?bbox=&limit=` returns a GeoJSON FeatureCollection (id, captured_at, group_id only) under the policy.
- `build_map(collection_id)`:
  - it writes NDJSON and runs `tippecanoe -o out.pmtiles -l images -z14 -Z0 -r1 --cluster-distance=10 …` (port the portal's exact args);
  - it stores at `map_key` and sets `map_built_at` and `map_image_count`;
  - it fires on the thresholds (`map_rebuild_threshold_pct` or `_abs`) after `ImageProcessed`, and on `CollectionVisibilityChanged`.
- `GET …/collections/{id}/map.pmtiles` with Range support (206, `Accept-Ranges`).
- The health check reports a missing tippecanoe.

**Tests:**
- points bbox filter;
- points hide a private collection;
- `test_range_request_206`;
- `test_tiles_have_no_filenames` (skip if tippecanoe is absent locally; CI installs it, so add `apt-get install -y tippecanoe` to the pytest jobs in `ci.yml`);
- the rebuild threshold.

- [ ] Commit `feat(images): points and PMTiles map`

### Task 27: Map tab, public collection page, pagebuilder block

**Files:**
- Create: `sm_images/components/map/*` (MapLibre plus the `pmtiles` protocol; add the npm deps to `modules/images/package.json` and the root lock), `sm_images/pages/PublicCollection.tsx` (served at `/images/c/{slug}` via `bind_public`), `sm_images/pagebuilder-blocks.ts` (an `ImageGallery` block: collection picker, size and count; labels are keys resolved by `localizeConfig.ts`), and `pagebuilder` as an optional peer.

**Tests:**
- vitest for the block config.
- e2e `tests/e2e/images-public.spec.ts`: publish a collection, view `/images/c/<slug>` anonymously and see thumbnails; the map tab renders a canvas.

- [ ] Commit `feat(images): map tab, public page and gallery block`

---

## Phase 8 — Docs and finish

### Task 28: Module docs and repo notes

**Files:** `modules/images/docs/{index.md,pipeline.md,writing-a-plugin.md,imports.md,access.md,worker.md,migrating-from-portal.md}` (worker settings from spec §3), `modules/images/README.md`, and `CLAUDE.md` (images in the tenancy, no-env and i18n lists; Celery now used; the CI extras rule from spec §9).

**Done-check:** `make lint` (check_readmes, locales, file size, rules).

- [ ] Commit `docs(images): module documentation`

Then `/ship` updates PR #272.
