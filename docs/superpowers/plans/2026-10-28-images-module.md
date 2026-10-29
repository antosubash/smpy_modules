# Images module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This file is also the run's state.** Tick a task's box in the same commit
> that finishes it. A resumed session starts at the first unticked task.

**Goal:** Ship `modules/images` (`sm_images`, PyPI `simple_module_images`): photo collections with location, a registered-step pipeline, imports at portal scale, review of AI results, a map and plugin extension points, on framework 0.0.41.

**Architecture:** One framework module modelled on `modules/records` (layout, tenancy copy, settings, harness, i18n). It stores bytes through the framework `file_storage` backend under its own key layout, shares through `sharing`, and runs work as Celery tasks through `background_tasks`. Celery workers never build the app, so everything a task needs (extension registry, settings, storage, the DB engine) has a worker-safe bootstrap of its own. Heavy processors are extras (`[quality]`, `[anonymize]`, `[ai]`, `[map]`, `[pagebuilder]`, `[billing]`) imported only inside the step that needs them.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy async, Alembic (host), Celery via `background_tasks`, Pillow + pillow-heif, ijson, httpx, opencv-python-headless, torch/facenet-pytorch/ultralytics (extra only), pydantic-ai through `sm_ai.contracts`, tippecanoe (system binary), React + Inertia + `@simple-module-py/ui`, MapLibre + pmtiles, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-images-module-design.md` (approved). Read it alongside this plan.
**Porting map:** `docs/superpowers/plans/2026-10-28-images-module-porting-map.md`. It is Codex's read of the portal: files to port, invariants and tests worth porting. The portal source is `~/Repos/gis-data-portal/backend/app/features/images/` and `frontend/src/features/images/`. Use it as reference only; never import from it.
**Framework reference:** the 0.0.41 sources are in `~/Repos/simple_module_python` (local HEAD equals 0.0.41 for all Python). Read `docs/modules/{sharing,file_storage,background_tasks}.md` there before touching those APIs.

## Global Constraints

- Framework floor in `modules/images/pyproject.toml`: `simple_module_*>=0.0.41,<0.1`. Never `==`. The host pins exactly `==0.0.41`.
- Sibling extras: `ai = ["simple_module_ai>=…,<0.1"]`, `billing = [...]` and `pagebuilder = [...]`, each with a `# floor: <reason>` comment naming the change it needs. The `ai` floor is the next lockstep version, because Task 22 adds `consume_requests`.
- `pip install simple_module_images` pulls no torch, ultralytics or cv2.
- Package `sm_images`; `ModuleMeta.name = "Images"`; locale namespace `images`; table prefix `images_`; `create_module_base("images")`.
- Routes: API `/api/images`, console `/admin/images`, public `/images/c/{slug}`. Constants live in `sm_images/constants.py`.
- Settings subclass `DbBackedSettings` (no env), SYSTEM scope. Boot-time fields are `_RESTART` and are read in `on_startup`. Workers read settings with `background_tasks.settings_for(ImagesSettings, "sm_images")`.
- Every router binds a tenant (`sm_images.tenancy`, a copy of `sm_records.tenancy`, added to the parity families). A public response for a resolved tenant is never shareable-cached (CLAUDE.md, records #196).
- Beat and recovery tasks never run unscoped. They enumerate tenants in a narrow `all_tenants()` query, then do each tenant's work under `tenant_context(t)`.
- Files: at most 300 lines (split by responsibility at 280). Nothing but real Inertia pages under `sm_images/pages/`. en and de catalogues in step. Frontend keys derived from `en.json` as in `modules/news/news/utils/i18n.ts`.
- **Originals are immutable.** Nothing writes `storage_key` after insert. Only `StepContext.write_display` produces a display copy, and only under a valid lease (Task 10).
- Migrations: host revisions only. The first images revision carries `branch_labels=("images",)`. The history has one head. Run `alembic check` on SQLite and Postgres after every migration change.
- Outside a request, commit with `simple_module_db.finalize_session` wherever events or billing are queued.
- Tests: targeted only (the touched module's test files, or one e2e spec). No full suites and no CI waits until `/ship`. `PYTEST_WORKERS=8`. Run `~/.claude/bin/wait-for-headroom` before any suite, dev server, worker or browser. Stop servers and workers when done.
- Commits: `feat(images): <task>`, ending with `Claude-Session: https://claude.ai/code/session_017uTbtobjCKQYnAxF5tgK8t`.

## Decisions made during planning (deviations from the design text)

1. **Extension registration (§8.2).** Celery workers never build the app or run module hooks. In the web process, a dependant's `on_startup` also runs *after* images' own. So a plugin registers through a file, the Python twin of `images-steps.ts`:
   - The plugin's package ships `images_extensions.py` with `def register(registry) -> None`.
   - `sm_images.pipeline.extensions.load_extensions()` iterates the installed `simple_module` entry points. For each module package that has an `images_extensions` submodule (`find_spec`), it imports it and calls `register`, then freezes the registry.
   - The web app calls it in images' `on_startup`. A worker calls it on first registry read. Both run one code path, so the registries match.
   - A plugin is still an ordinary framework module, with no new entry-point group. `register_step`/`register_preset` outside `load_extensions` raises `RegistryFrozenError` once frozen.

   The docs' worked example changes accordingly.
2. **`internal` visibility needs our own policy.** `OwnedResourcePolicy` knows only `public`. `ImagesCollectionPolicy` wraps it and adds `visibility='internal'` for view to any authenticated principal in the bound tenant. Binding already requires active membership (multi-tenant), and on single-tenant every user is a member. The same policy object is used by lists, `RequiresResource` and the `ResourceType` registration.
3. **No share UI in the framework.** Images builds a share dialog against `/api/sharing/shares`, plus its own gated user picker `GET /api/images/collections/{id}/share-candidates?q=`. That picker is owner or `images.manage`, uses `UserDirectory.search`, and is filtered to `tenant_member_ids`.
4. **No delete-by-prefix in `file_storage`.** The janitor deletes known keys. An intent table `images_object_intent(key, created_at)` is written in an independent session before every object write and cleared when the referencing row commits. The janitor reaps intents older than the grace period that no row references (dry-run, cap). This catches crash and rollback orphans.
5. **Bytes go through the backend directly.** They use `app.state.file_storage.backend` in the web process, and `build_backend(settings_for(FileStorageSettings,"file_storage"))` in workers, under our key layout. `StoredFile` rows and the `file_storage` quota are not used.
6. **Delivery is at-most-once (`enqueue_after_commit`).** A beat task `images.reconcile` (every 5 min) re-dispatches, per tenant:
   - step runs that are `pending` or have an expired lease, older than 5 minutes;
   - import items that are pending;
   - import jobs whose heartbeat is stale.

   `worker_ready` (a Celery signal connected in `sm_images/tasks.py`) triggers one reconcile.
7. **Console at `/admin/images`** (the repo convention), not the design's bare `/images`.
8. **`normalize_downloads` is dropped.** Re-encoding would replace the delivered original, and renditions already cover display sizes.
9. **Direct upload threshold is per image.** The default `direct_upload_threshold = 20 MiB` sits below `max_image_bytes = 50 MiB`. The multipart batch route registers a body limit of `upload_body_max_bytes = 100 MiB`.
10. **Storage billing uses a gauge.** The meter is `images.storage_bytes`, kind `gauge`. Each image holds one committed hold sized to the sum of its objects (`images_image.storage_hold_id`, `storage_bytes`). When the display copy or renditions change, the image takes a new hold for the new total and then releases the old one. The janitor releases the hold on hard delete.

## Review Focus

1. **A caller sees an image or count they cannot open.** This covers lists, counts, points, tiles, renditions, groups, the review queue and the contracts. Task 6 adds `test_every_read_route_hides_private_collection`, parametrised over `tests/read_routes.py`, which each later task appends to.
2. **A slow worker overwrites a newer result** (lease expired and reclaimed). Task 10 adds `test_stale_lease_cannot_complete_or_publish_display`.
3. **A huge or hostile input.** This covers a pixel bomb, a zip bomb, zip-slip, a replaced presigned object, HEIC, a wrong extension, and an SSRF via redirect or a GeoJSON source URL. Tasks 7, 16, 17 and 18 own the tests.
4. **An interrupted import replays.** Task 17 adds `test_resume_after_kill_no_duplicates_base64_without_ids`.
5. **A tenant leak in a worker or beat task.** Task 10 adds `test_task_runs_in_enqueuer_tenant` and `test_reconcile_scopes_each_tenant`.

---

## Phase 1 — Framework bump

### Task 1: Framework 0.0.41, worker topology, CI extras

**Files:**
- Modify: `host/pyproject.toml` (pins `==0.0.41`; add `simple_module_file_storage`, `simple_module_sharing` and `simple_module_background_tasks` at `==0.0.41`), `host/client_app/package.json`, `uv.lock` and `package-lock.json`.
- Create: host revisions porting each framework revision this host lacks, in upstream order. The candidates, from the framework's `host/migrations/versions/`, are `f733c7938fd1` (sharing), `d7b3a9e5c1f2` (check whether `30033455948e` already is it), `bb906e1a1089`, `1f5985daa10b`, `a625f0b7c912` and `a626b1c8d023`. Also add any `background_tasks`/`file_storage` tables that the host never ported (diff the table sets). Each docstring ends `(framework 0.0.4x)` and names its upstream id, like `b65e04cf65d7`. Linear, one head.
- Create: `host/worker.py` (`celery = build_runner_celery(<repo>/.env)`).
- Modify: `Makefile`, adding these targets (dev-services Redis):

  | Target | Command |
  |---|---|
  | `worker` | `-Q images,celery -c 4` |
  | `worker-imports` | `-Q images_imports -c 1` |
  | `worker-heavy` | `-Q images_heavy -c 2` |
  | `worker-gpu` | `-Q images_gpu -c 1` |
  | `beat` | `celery beat` |

  They are not started by `dev`.
- Modify: `.env.example` (`SM_REDIS_URL` commented; `SM_BG_TASKS_TASK_ALWAYS_EAGER=true` for runs without a worker), `tests/e2e/start-test-server.sh` (export `SM_BG_TASKS_TASK_ALWAYS_EAGER=true` and `SM_BG_TASKS_TASK_EAGER_PROPAGATES=true`).
- Modify: `.github/workflows/ci.yml` at lines 86 and 528: `--all-extras` becomes `--all-extras --no-extra anonymize`. Install `tippecanoe` with apt in the Python test job and the Postgres job.
- Modify: `CLAUDE.md` (Redis/Celery is now used, by images; the ported revisions; the 0.0.40 bearer-token hashing note) and any code broken by 0.0.39–0.0.41 (grep for `@simple-module-py/ui/components/ui/form`).

**Done-check:**
- `make lint`;
- `alembic upgrade heads && alembic check` on SQLite and on Postgres (`smpy_modules_images` in dev-services);
- `scripts/check_migration_heads.py`;
- `uv run pytest -n 8 host/tests`;
- each module's `test_framework_pins.py`.

- [x] Commit `deps: framework 0.0.41`

---

## Phase 2 — Core

### Task 2: Module skeleton

**Files:**
- Create:
  - `modules/images/{pyproject.toml,package.json,tsconfig.json,README.md}`. Copy records' shapes. Extras: `quality`, `anonymize`, `ai`, `billing`, `map` and `pagebuilder`. Pytest `addopts = "-m 'not perf and not real_models'"`.
  - Under `sm_images/`: `__init__.py`, `constants.py`, `module.py`, `settings.py`, `settings_boot.py`, `tenancy.py`, `_tenancy_mode.py`, `_tenant_guard.py`, `deps.py`, `menu.py`, `locales/{en,de}.json` and `utils/i18n.ts`.
  - Under `tests/`: `__init__.py`, `conftest.py`, `pg_support.py`, `app_harness.py`, `stub_auth.py` and `isolation_support.py`.
- Modify:
  - root `pyproject.toml` `testpaths`;
  - `host/pyproject.toml` (dependency plus workspace source);
  - `host/tests/test_host_boots.py` (`REPO_MODULES` gets `"Images"`);
  - `host/tests/test_menu_labels.py`;
  - `scripts/tests/parity_tenancy.py` and `parity_families.py`;
  - `.github/workflows/ci.yml` (`ci_images` in the Postgres DB loop, plus a "Run pytest (images, Postgres)" step);
  - the `README.md` module table.

**Interfaces — Produces:**
- Constants:
  - `PACKAGE="sm_images"`, `MODULE_NAME="Images"`, `DISTRIBUTION="simple_module_images"`;
  - `ROUTE_PREFIX_API="/api/images"`, `VIEW_PREFIX="/admin/images"`, `PUBLIC_PREFIX="/images"`;
  - `PERM_VIEW/CREATE/PUBLISH/MANAGE/ORIGINALS/SETTINGS` = `images.view`, `images.create`, `images.publish`, `images.manage`, `images.originals.view`, `images.settings`.
- `ImagesSettings(DbBackedSettings)`:
  - `max_image_bytes=50*2**20`, `batch_max=50`, `upload_body_max_bytes=100*2**20`, `direct_upload_threshold=20*2**20`;
  - `zip_max_bytes=2*2**30`, `zip_max_entries=10_000`, `zip_max_entry_bytes=200*2**20`, `zip_max_total_bytes=8*2**30`, `zip_max_ratio=200`;
  - `geojson_max_features=1_000_000`, `geojson_max_bytes=2*2**30`;
  - `download_concurrency_per_domain=4`, `download_concurrency_total=32`, `download_timeout=60`;
  - `thumbnail_sizes={"marker":64,"small":160,"medium":400,"large":1024}`, `dedupe_by_hash=False`;
  - `tippecanoe_path="tippecanoe"`, `anonymize_weights_path=""`;
  - `map_rebuild_threshold_pct=5`, `map_rebuild_threshold_abs=100`;
  - `public_asset_base_url=""`, `janitor_grace_days=7`, `step_output_max_bytes=65536`, `step_lease_seconds=1800`.
- `ImagesServices` at `app.state.sm_images`.
- `register_body_limits` (upload routes: `upload_body_max_bytes`; base64: the same).
- `register_public_routes` (GET-only for `/images/c/` and the public serving/points/map prefixes).
- Harness: `images_app`, `client`, `as_user(user_id, perms)`, `two_tenants`, plus a `storage` fixture (filesystem backend on `tmp_path`, installed as `app.state.file_storage.backend`).

**Tests** (`tests/test_module_boot.py`):
- `test_module_registers_permissions`;
- `test_settings_ignore_env`: with env `SM_IMAGES_MAX_IMAGE_BYTES=1` set, the default stays.
- `test_public_routes_get_only`.

**Done-check:**
- `cd modules/images && uv run pytest -n 8 tests/test_module_boot.py`;
- `make lint`;
- `uv run pytest host/tests/test_host_boots.py host/tests/test_menu_labels.py`.

- [x] Commit `feat(images): module skeleton`

### Task 3: Models and first migration

**Files:** Create `sm_images/models/{__init__.py,_base.py,enums.py,collection.py,image.py,rendition.py,step_run.py,group.py,prompt.py,import_job.py,import_item.py,object_intent.py}`, plus `host/migrations/versions/<rev>_add_images.py` (autogenerate; add `branch_labels=("images",)` and a Postgres `_drop_enums()`, as in `e23090832709`).

**Interfaces — Produces** (columns as spec §1, plus the following):
- Collection stats: `image_count`, `located_count`, `bbox_minx/miny/maxx/maxy`, `map_built_at`, `map_image_count`.
- `Image`: adds `storage_hold_id`, `storage_bytes` and `display_generation:int`.
- `StepRun`: adds `lease_token: uuid|None`, `lease_expires_at`, `step_version`, `prompt_revision: int|None`.
- `Prompt`: adds `revision:int`, bumped when the instruction or schema is edited.
- `ImportJob`: adds `generation:int`, `heartbeat_at` and `staged_keys: list[str]`.
- `ImportItem` replaces the spec's `images_download` and covers both modes. It is unique on `(job_id, feature_index)`, with `url|None`, `external_id`, `status`, `attempts`, `last_error`, `lat`, `lng`, `captured_at`, `group_key`, `group_role`, `properties`, `image_id`.
- `ObjectIntent(key pk, created_at)`, not tenant-scoped (platform janitor).
- Enums:
  - `Visibility{private,internal,public}`;
  - `LocationSource`, int precedence `exif=1, import_=2, manual=3`;
  - `StepStatus{pending,running,completed,skipped,failed}`;
  - `ReviewStatus{unreviewed,accepted,corrected,rejected}`;
  - `ImportKind{geojson_url,geojson_base64,zip}`;
  - `JobStatus{pending,staging,running,paused,completed,failed,cancelled}`;
  - `ItemStatus{pending,done,duplicate,failed}`.
- Partial unique index `uq_images_image_external` on `(collection_id, external_source, external_id) WHERE external_id IS NOT NULL` (both dialects).
- `sm_images/storage_keys.py`: `original_key`, `display_key(t,c,i,generation)` (→ `…/display.<gen>.jpg`), `rendition_key(t,c,i,size,generation)`, `map_key` and `import_key`.

**Tests:**
- `tests/test_models.py`: `test_external_id_dedupe_index`, `test_import_item_unique_per_feature`, `test_soft_delete_hides_collection`.
- `tests/test_storage_keys.py`: the exact key strings.

**Done-check:** the tests pass; `alembic check` on SQLite and Postgres; one head.

- [x] Commit `feat(images): data model and migration`

### Task 4: Storage adapter and object intents

**Files:** Create `sm_images/storage.py`, `sm_images/intents.py`.

**Interfaces — Produces:**
- `ImageStore` methods: `put(key, data|aiter, *, content_type, size)`, `read(key)->bytes`, `stream(key)`, `stream_range(key,start,end)`, `head(key)->(size,etag)|None`, `delete_keys(keys)->int` and `exists(key)`.
- `store_for(app)` and `worker_store()`.
- `async with object_intent(keys):`. It records the intents in an independent session before the write. The caller clears them in the same transaction that commits the referencing row, via `clear_intents(db, keys)`.

**Tests:**
- a round trip;
- a range read;
- `delete_keys` ignores missing keys;
- an intent survives a rolled-back caller transaction and is cleared on commit.

- [x] Commit `feat(images): storage adapter`

### Task 5: Access policy and sharing

**Files:** Create `sm_images/access.py`, `sm_images/resource_types.py`. Modify `module.py`: `register_resource_types`, and `depends_on` gets the real `ModuleMeta` names of sharing, file_storage and background_tasks.

**Interfaces — Produces:**
- `COLLECTION_RESOURCE="images.collection"`.
- `POLICY = ImagesCollectionPolicy(...)`: wraps `OwnedResourcePolicy(owner_id, bypass_perm=PERM_MANAGE, visibility_col=Collection.visibility, share_exists=share_exists_for(...))`. For `view`, it adds `OR visibility IN ('internal','public')` when `principal.user_id` is set and `OR visibility='public'` otherwise.
- `visible_images(who, action) -> Select`.
- Dependencies `CollectionView`, `CollectionEdit` and `CollectionOwner` (owner or manage), via `RequiresResource(POLICY, …)`.
- `can_view_original(who, image, collection)`.
- `public_collection(slug)`.

**Tests** (`tests/test_access.py`, a matrix of visibility × principal over **both** the list and the detail route):
- the owner sees private;
- a stranger gets 404;
- a member sees internal on list *and* detail;
- anonymous sees only public;
- a view share can't upload and an edit share can;
- an edit share can't delete;
- `images.manage` bypasses.

- [x] Commit `feat(images): access policy`

### Task 6: Collection API, stats, contracts

**Files:** Create `sm_images/endpoints/api/{__init__.py,collections.py,shares.py}`, `sm_images/schemas/collection.py`, `sm_images/services/{collections.py,stats.py}`, `sm_images/events.py`, `sm_images/contracts/{__init__.py,events.py,schemas.py,reads.py}`, `tests/read_routes.py`.

**Interfaces — Produces:**
- Routes:
  - `GET/POST /api/images/collections` (filter `owned|shared|internal|public|all`, cursor);
  - `GET/PATCH/DELETE /api/images/collections/{id}`;
  - `PUT …/{id}/visibility` (internal and public need `images.publish`);
  - `GET …/{id}/share-candidates?q=`.
- Events `CollectionVisibilityChanged` and `CollectionDeleted` (`db.on_commit`).
- `stats.on_image_added(db, coll_id, lat, lng)`, `on_image_removed` and `on_location_changed`. They are incremental SQL `UPDATE`s in the caller's transaction (counts plus bbox extension). `recompute(db, coll_id)` serves deletes and shrinks, called by reconcile.
- Contracts `get_collection(tenant_id, id, principal)`, `list_collections(tenant_id, principal, …)`, `points(tenant_id, coll_id, bbox, principal)` (wired in Task 26) and `rendition_url(image, size)`. Each pins `tenant_context(tenant_id)`.

**Tests:**
- CRUD;
- slug 409;
- the publish permission;
- an event fires only after commit;
- the share-candidates picker returns only tenant members and gives 403 for an edit share;
- the contracts filter by tenant and policy;
- `test_unbound_tenant_admin_403`;
- `test_every_read_route_hides_private_collection`.

- [x] Commit `feat(images): collection API and contracts`

### Task 7: Ingest, direct and batch upload

**Files:** Create `sm_images/ingest/{__init__.py,sniff.py,guards.py,service.py,direct.py}`, `sm_images/endpoints/api/{images.py,uploads.py}`, `sm_images/schemas/image.py`.

**Interfaces — Produces:**
- `sniff(data)->str|None` (jpeg, png, webp, heic/heif, tiff).
- `guard_pixels(data)->(w,h)` raises `ImageTooLarge`, which maps to a translated 413 (pagebuilder #221's pattern).
- `IngestService.add_image(collection, *, data|staged_key, filename, meta: IngestMeta, source) -> Image | Duplicate`:
  1. hash;
  2. three-layer external dedupe (pre-check, in-batch set, IntegrityError re-check), plus hash dedupe when on;
  3. write the original under an intent (or adopt the staged key);
  4. insert;
  5. create pending `StepRun`s for the enabled steps;
  6. update stats;
  7. clear the intents;
  8. on commit, `ImageAdded` and `pipeline.dispatch(image_id)`. This is a no-op hook until Task 10.
- `IngestMeta(lat,lng,captured_at,external_source,external_id,group_key,group_role,properties)`. Manual coordinates set `location_source=manual`.
- Routes:
  - `POST /api/images/collections/{id}/images` (multipart, 1..`batch_max` files, optional `metadata` JSON keyed by filename; a file over `direct_upload_threshold` gives 413 `use_direct_upload`);
  - `POST …/images/base64`;
  - `POST …/collections/{id}/uploads`, then `{upload_id, part_size, part_urls}` through `DirectUploadBackend`, then `POST /api/images/uploads/{id}/complete {parts, filename, metadata}`. On complete it calls `head`, verifies size ≤ `max_image_bytes`, sniffs, guards and ingests (`DELETE` aborts);
  - `GET …/collections/{id}/images` (cursor; `has_location`, `step`, `step_status`, `review_status`, `group`);
  - `GET/PATCH/DELETE /api/images/images/{id}`. PATCH sets a manual location through a conditional update and updates stats. DELETE is owner or manage, and soft.

**Tests:**
- `test_magic_bytes_not_extension`;
- `test_unknown_type_415`;
- `test_bomb_pixels_413_translated`;
- `test_batch_over_max_422`;
- `test_over_threshold_requires_direct`;
- `test_direct_upload_complete_checks_size`;
- `test_base64_dedupes_external_id`;
- `test_hash_dedupe_off_by_default`;
- `test_heic_upload_processes` (`pillow-heif` is a core dependency);
- `test_original_never_rewritten`, which later tasks extend;
- `test_body_limit_via_host_middleware` (through the full app).

- [x] Commit `feat(images): upload and ingest`

### Task 8: `exif` and `renditions` processors

**Files:** Create `sm_images/processing/{exif.py,renditions.py}`, plus fixtures in `tests/fixtures/` (a geotagged jpeg, a rotated jpeg, a heic, a png without exif).

**Interfaces — Produces:**
- `read_exif(data)->ExifData(lat,lng,altitude,heading,captured_at,make,model,orientation)`, ported from the portal's `pipeline/geolocation.py`.
- `make_renditions(display_bytes, sizes)->dict[str,(bytes,w,h)]`. It applies `exif_transpose`, encodes JPEG at q85, never enlarges, and strips metadata.

**Tests:** exact values for each fixture.

- [x] Commit `feat(images): exif and rendition processors`

---

## Phase 3 — Pipeline framework

### Task 9: Step registry and extension loading

**Files:** Create `sm_images/pipeline/{registry.py,step.py,presets.py,extensions.py}`. Export them from `sm_images/contracts/__init__.py`.

**Interfaces — Produces** (spec §8.3):
- `Step` Protocol.
- `StepContext`: `image`, `params`, `tenant_id`, `read_display()`, `read_original()`, `write_display(data, content_type)` (only for `mutates_display`; writes to `display_key(…, generation+1)`), and `progress(pct)` (renews the lease and calls `heartbeat`).
- `StepOutcome.completed/skipped/failed`.
- `Preset` and `PromptSpec`.
- `register_step`, `register_preset`, `get_step(id)->Step|None`, `get_preset`, `all_steps()`, `freeze()`, `is_frozen()`.
- `load_extensions()`, idempotent (Decision 1).
- Errors `RegistryFrozenError`, `DuplicateStepError`, `ReservedStepIdError`, `UnresolvedRequiresError`, `CyclicRequiresError`.
- Reserved ids: `exif`, `renditions`, `quality`, `anonymize`, `classify`, and the prefix `prompt:`. Plugin ids match `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`.
- `topo_order(ids)`.
- The registry freezes implementations only; `prompt:<id>` steps are resolved per execution from the DB (Task 22).

**Tests:**
- duplicate, reserved and namespace errors;
- unresolved and cyclic `requires` fail at freeze;
- a late registration raises;
- `load_extensions` finds a fixture package's `images_extensions.py`;
- `test_registry_parity_fresh_process`: run `python -c` in a subprocess with no app built, call `load_extensions()`, and get the same ids as the web app;
- `test_mutates_display_at_most_one`.

- [x] Commit `feat(images): step registry and extension loading`

### Task 10: Executor, leases, orchestration, reconcile (hard)

Before implementing, a Codex root-cause/design pass over this task's interfaces settles the async-DB-in-Celery approach. Check how `background_tasks.sync_db` and `simple_module_db` build engines; one option is an `asyncio.run` wrapper over a per-process async engine with the host's tenant policy.

**Files:** Create `sm_images/pipeline/{executor.py,claim.py,config.py,orchestrate.py,builtin_steps.py,worker_runtime.py}`, `sm_images/tasks.py`, `sm_images/task_config.py`, `sm_images/reconcile.py`.

**Interfaces:**
- Consumes: Tasks 4, 8 and 9.
- Produces:
  - `validate_pipeline_config(cfg)->PipelineConfig` (params validated by each step's `params_schema()`; unknown ids are kept as `not_installed`).
  - Built-in `ExifStep` and `RenditionsStep`, registered internally.
  - `claim_ready(db, image_id, now, lease_s) -> list[Claim(step, token)]`. It is one conditional `UPDATE … SET status='running', lease_token=:new, lease_expires_at=… WHERE image_id=:i AND step IN (:ready) AND (status='pending' OR (status='running' AND lease_expires_at < now)) RETURNING step`. That is atomic on both dialects (SQLite ≥ 3.35 `RETURNING`).
  - `ready` means every `requires` is `completed`/`skipped` at the current version.
  - `complete(db, image_id, step, token, outcome)` is a conditional update `WHERE lease_token=:token`; a rowcount of 0 means a lost lease, so the result is discarded.
  - Display publication is fenced the same way: `UPDATE image SET display_key=:k, display_generation=:g WHERE id=:i AND display_generation=:g-1` inside the `complete` transaction, and the loser's object is deleted.
  - `ExifStep`'s location write is a conditional update `WHERE location_source IS NULL OR location_source=1`.
  - `dispatch(image_id)`: claim ready steps; for each, `enqueue_after_commit(images.run_step, image_id, step, token)` on the step's queue.
  - `images.run_step`: work, `complete`, then `dispatch(image_id)` again, which continues to newly eligible dependants. The same path serves eager and async.
  - When every enabled step is final, `ImageProcessed` fires once.
  - Status rules (spec §3):
    - `skipped` is final per version;
    - a retry re-runs `failed` and `pending`;
    - `force` re-runs all;
    - a stale `step_version`/`prompt_revision` is shown as stale and re-runs only via `force` or "re-run stale";
    - a failed step never blocks independent steps.
  - `images.restart_collection(collection_id, scope)` runs in chunks of 1000 on `images_imports`.
  - `images.reconcile` (beat, 5 min): `all_tenants()` distinct tenant ids, then per tenant `tenant_context` re-dispatches stale pending or expired steps, pending import items and stale jobs (Decision 6), and recomputes the stats of collections touched by deletes.
  - `worker_ready` triggers one reconcile.
  - `worker_runtime.py` provides the worker-side settings, store, engine and `load_extensions()` bootstrap.
  - Output over `step_output_max_bytes` fails the step with `output_too_large`.

**Tests** (eager unless noted):
- `test_skipped_is_final_for_version`;
- `test_exif_never_overrides_manual_location`;
- `test_manual_edit_between_load_and_store_wins`;
- `test_failed_step_does_not_block_independent`;
- `test_dependants_dispatch_after_completion` (renditions run after a display-mutating fake step);
- `test_lease_expiry_reclaims`;
- `test_stale_lease_cannot_complete_or_publish_display`;
- `test_concurrent_claim_runs_once` (Postgres; two real connections);
- `test_force_reruns_all`;
- `test_version_bump_marks_stale`;
- `test_task_runs_in_enqueuer_tenant`;
- `test_reconcile_scopes_each_tenant` (two tenants, no header);
- `test_reconcile_redispatches_lost_message`;
- `test_output_cap`.

- [x] Commit `feat(images): pipeline executor`

### Task 11: `quality` step and pipeline API

**Files:** Create `sm_images/steps/quality.py` (cv2 imported inside; registered only if `find_spec("cv2")`) and `sm_images/endpoints/api/pipeline.py`.

**Interfaces — Produces:**
- `QualityParams(min_width=640,min_height=480,blur_threshold=100.0,dark_threshold=0.05,bright_threshold=0.95)`.
- Routes:
  - `GET /api/images/collections/{id}/pipeline` (config; the registered steps with their JSON schemas; status, stale and not-installed counts);
  - `PUT …/pipeline` (owner or manage; validates);
  - `POST …/pipeline/restart {scope: failed|stale|all}`;
  - `POST /api/images/images/{id}/reprocess {force}`.

**Tests:** `test_quality_metrics_known_fixture`, `test_quality_absent_without_cv2`, `test_not_installed_step_reported_never_scheduled`, and the permission tests.

- [x] Commit `feat(images): quality step and pipeline API`

### Task 12: Image serving route

**Files:** Create `sm_images/endpoints/api/serve.py`, `sm_images/endpoints/public.py`, `sm_images/urls.py`, `sm_images/cache.py`.

**Interfaces — Produces:**
- `GET /api/images/images/{id}/r/{size}`, `…/display` and `…/original` stream from the store. The ETag is the object's generation-specific key plus its size. `If-None-Match` gives 304.
- `cache_headers(request, collection, route)`:
  - `public, max-age=31536000, immutable` only when **all** of these hold: the collection is public, the route is `r/` or `display`, it is served through the public twin, and no tenant was resolved from a request-specific source (CLAUDE.md #196 rule);
  - otherwise `private, max-age=3600`;
  - `…/original` of an image with a display copy is always `private, no-store`.
- Headers are computed before the 304 decision.
- `…/original` needs `can_view_original` when a display copy exists.
- `rendition_url(image,size)` gives `…?v=<display_generation>`, behind `public_asset_base_url` for public collections.

**Tests:** headers per case; a 304; a stranger and anonymous get 404 on private; the protected original returns 403 to an edit share and is `no-store` for the owner; an unknown size gives 404.

- [x] Commit `feat(images): access-checked image route`

### Task 13: Console screens — collections, gallery, viewer, sharing

**Files:** Create `sm_images/endpoints/views.py`, `sm_images/pages/{Collections,Collection,Image}.tsx`, `sm_images/components/{collections,gallery,viewer,share}/*`, `sm_images/hooks/{useCollections,useImages,useShares}.ts`, `sm_images/utils/api.ts`, and the locale keys.

**Interfaces — Produces:**
- Inertia pages `Images/Collections`, `Images/Collection` and `Images/Image`.
- The gallery is a cursor grid of `small` renditions with filter chips.
- The viewer shows the display copy, an original toggle (when the `can_view_original` prop is set), metadata and results. Results use the generic view until Task 14.
- The share dialog lists, grants (view/edit) and revokes through `/api/sharing/shares`, with the share-candidates picker.
- Collection tabs appear as their tasks land.

**Tests:**
- vitest page tests (`page-tests/`).
- e2e `tests/e2e/images-core.spec.ts`: create a collection, upload two jpegs, see thumbnails (eager pipeline), open the viewer, share with a second user who then sees it. Standalone.

- [x] Commit `feat(images): console collections, gallery and viewer`

### Task 14: Pipeline UI and result-view registry

**Files:** Create `sm_images/components/pipeline/*`, `sm_images/components/results/{registry.ts,GenericResultView.tsx,ResultView.tsx}`, `sm_images/images-steps.ts` (`import.meta.glob('../../*/*/images-steps.ts', { eager: true })`, mirroring pagebuilder's `puck-blocks.ts`) and `sm_images/index.ts`. Modify `package.json` `exports`.

**Interfaces — Produces:**
- `registerResultView({kind:'step'|'prompt_result'|'cross_check', id, component})`, which throws on a duplicate.
- `<ResultView …/>`, with a generic fallback.
- The pipeline tab: toggles, a JSON-schema params form, a stale banner and restart actions.

**Tests:** vitest `registry.test.ts` and `PipelineTab.test.tsx`.

- [x] Commit `feat(images): pipeline UI and result views`

### Task 15: Test plugin and janitor

**Files:** Create `modules/images/tests/plugin_fixture/images_testplugin/{__init__.py,module.py,images_extensions.py}` (step `testplugin.count_pixels` and a preset `testplugin`), `tests/test_plugin_e2e.py`, `sm_images/janitor.py`.

**Interfaces — Produces:**
- `images.janitor` (beat, daily; per tenant).
- `purge_expired(db, store, *, now, grace_days, dry_run=False, cap=1000) -> PurgeReport`. It row-locks, collects every key (original, all display generations, renditions, map, job staging), deletes them, hard-deletes the rows, and calls the billing release hook (Task 25).
- `reap_intents(...)`: intents older than the grace period that no row references.

**Tests:**
- the plugin's step runs and its output is stored;
- registering outside `load_extensions` after the freeze raises;
- a removed plugin leaves its results readable and its step `not_installed`;
- `test_purge_removes_storage_and_rows`;
- `test_purge_dry_run`;
- `test_purge_respects_grace`;
- `test_orphan_intent_reaped`.

- [x] Commit `feat(images): plugin end-to-end test and janitor`

---

## Phase 4 — Imports

### Task 16: Safe fetch — SSRF guard, limiter, downloader (hard)

**Files:** Create `sm_images/imports/{url_safety.py,fetch.py,rate_limit.py}`.

**Interfaces — Produces:**
- `resolve_public(url)->(host, ips)` resolves with `getaddrinfo`. It rejects private, loopback, link-local, multicast, reserved, CGNAT and metadata addresses (169.254.169.254, fd00:ec2::254) and non-http(s) schemes.
- `safe_stream(url, *, max_bytes, timeout) -> AsyncIterator[bytes]`. It pins the IP (SNI and Host intact), re-validates each redirect (at most 5) and enforces `max_bytes` while streaming.
- `DomainLimiter(per_domain,total)`.
- `backoff(response, attempt)` honours `Retry-After` (capped at 300 s).

**Tests:**
- `test_rejects_private_ip_after_dns`;
- `test_redirect_to_private_rejected`;
- `test_ipv6_mapped_v4_rejected`;
- `test_oversize_stream_aborted`;
- `test_retry_after_honoured`;
- `test_per_domain_concurrency`.

- [x] Commit `feat(images): safe fetch`

### Task 17: GeoJSON import (URL and base64) (hard)

**Files:** Create `sm_images/imports/{geojson_stream.py,mapping.py,jobs.py,filename_pattern.py,tasks.py}` and `sm_images/endpoints/api/imports.py`.

**Interfaces — Produces:**
- `Mapping(url_prop,image_prop,lat_prop,lng_prop,datetime_prop,external_id_prop,group_key_prop,group_role_prop,filename_pattern)`.
- The source is staged to storage. A source URL goes through `safe_stream` with `geojson_max_bytes`.
- `validate_and_count` (ijson, `geojson_max_features`).
- `images.import_geojson(job_id, generation)`:
  - it aborts if the job's generation moved on;
  - it streams from `checkpoint_index`;
  - per chunk of 1000 features, it upserts `ImportItem`s (`ON CONFLICT (job_id, feature_index) DO NOTHING`) and advances the checkpoint **in one transaction**;
  - base64 items ingest inline, and an item that already has an `image_id` is skipped;
  - URL items are dispatched to `images.download_items(job_id, ids)` with a backpressure ceiling;
  - it upserts groups from properties or the pattern;
  - it heartbeats `job.heartbeat_at`.
- `external_id` defaults to `sha256(url)[:32]` (URL mode), or to `sha256(job_id:feature_index)` for base64 items without one.
- `images.download_items` uses `safe_stream`, `DomainLimiter` and `backoff`, then calls `IngestService.add_image(source="import")`.
- Job controls:
  - `POST /api/images/collections/{id}/imports`;
  - `GET …/imports`;
  - `GET /api/images/imports/{job}`;
  - `POST …/{job}/{resume|restart|retry-failed|pause}`, where `restart` bumps the generation and chunked set-based resets happen in 1000s;
  - `DELETE`.

**Tests** (port from the porting map):
- `test_resume_after_kill_no_duplicates_base64_without_ids`;
- `test_checkpoint_atomic_with_items`;
- `test_restart_bumps_generation_old_task_aborts`;
- `test_three_layer_dedupe`;
- `test_feature_limit`;
- `test_source_url_ssrf_rejected`;
- `test_filename_pattern_groups`;
- `test_download_idempotent`.

- [x] Commit `feat(images): GeoJSON import`

### Task 18: ZIP import

**Files:** Create `sm_images/imports/{zip_import.py,zip_safety.py}` (port the portal's `zip_safety.py`).

**Interfaces — Produces:**
- `POST /api/images/collections/{id}/imports/zip` returns `{job_id, upload}` (direct upload when supported, else relay).
- `POST /api/images/imports/{job}/extract`:
  - it calls `head` to verify the size ≤ `zip_max_bytes` and records the etag;
  - it seals the job: status becomes `running`, and further part or complete calls return 409;
  - extraction re-checks the etag and enforces `zip_max_entries`, `zip_max_entry_bytes`, `zip_max_total_bytes` and `zip_max_ratio` on the bytes **actually decompressed**;
  - it applies a zip-slip guard, an optional `metadata.json` and pattern grouping.
- Each entry becomes an `ImportItem` (so it resumes and dedupes like GeoJSON).

**Tests:**
- `test_zip_slip_rejected`;
- `test_zip_total_uncompressed_cap` (a lying header);
- `test_zip_entry_cap`;
- `test_replaced_object_after_seal_rejected`;
- `test_zip_metadata_json_applied`;
- `test_zip_groups_by_pattern`.

- [x] Commit `feat(images): ZIP import`

### Task 19: Import wizard, jobs panel, auto-run

**Files:** Create `sm_images/components/imports/*` (port `geojsonPreview.ts`, preview and auto-mapping) and `sm_images/hooks/useImportJobs.ts`. Modify ingest so that every path queues the `auto_run` prompts (a no-op until Task 22).

**Tests:**
- vitest `geojsonPreview.test.ts`.
- e2e `tests/e2e/images-import.spec.ts`: a base64 GeoJSON of 3 features gives a completed job and 3 located images. Standalone.

- [ ] Commit `feat(images): import wizard and jobs panel`

---

## Phase 5 — Anonymization

### Task 20: `anonymize` step and the real-model CI job

**Files:** Create `sm_images/steps/anonymize/{__init__.py,step.py,detectors.py,blur.py}` (lazy torch, facenet-pytorch and ultralytics; registered only when importable; weights from the setting or downloaded once to a cache dir) and `.github/workflows/images-models.yml` (`workflow_dispatch` plus a weekly schedule; `uv sync --extra anonymize`; `pytest -m real_models`). Modify the viewer's original toggle.

**Interfaces — Produces:**
- `AnonymizeParams(faces=True, plates=True, padding=0.15, min_confidence=0.5)`.
- A `Detector` protocol (injectable fake).
- Output `{regions, faces, plates}`.
- `mutates_display=True`, queue `images_gpu`.

**Tests:** `test_display_written_original_untouched`, `test_renditions_rerun_from_display`, `test_original_route_permission`, and `@pytest.mark.real_models test_real_face_blur`.

- [ ] Commit `feat(images): anonymization writes a display copy`

---

## Phase 6 — Groups and AI

### Task 21: Groups

**Files:** Create `sm_images/endpoints/api/groups.py`, `sm_images/services/groups.py` (port `regroup.py` and `crud_bag.py`, with roles from `collection.group_roles`) and `sm_images/components/groups/*`.

**Interfaces — Produces:**
- `GET/POST /api/images/collections/{id}/groups`, `GET/PATCH/DELETE /api/images/groups/{id}`.
- `POST …/collections/{id}/regroup {pattern}`.
- Members are ordered by `group_roles`.

**Tests:** role order; regroup; an edit share manages groups and a view share can't.

- [ ] Commit `feat(images): groups`

### Task 22: `ai` metering callable, `classify`, image prompts (hard)

**Files:**
- `modules/ai/sm_ai/{metering.py,contracts/__init__.py}`: add `async def consume_requests(tenant_id, qty=1, *, idempotency_key, source) -> bool`. It must work in a worker (no app): when `sm_billing` is importable it uses billing's usage service in its own session with `finalize_session`, and otherwise it returns True. Check billing's worker-side entry point in `modules/billing/docs/`. Tests go in `modules/ai/tests/test_metering_outside_request.py`. Bump the images `ai` extra floor.
- Create: `sm_images/steps/classify.py`, `sm_images/ai/{runner.py,schema_safety.py,prompt_steps.py}`, `sm_images/endpoints/api/prompts.py`.

**Interfaces — Produces:**
- `ClassifyParams(vocabulary=[], instruction=<neutral default>, max_side=1024)`.
- `run_structured(instruction, output_schema|None, images) -> (data|text, model_name)`. It uses `resolve_model()` and an `Agent` whose output type is built from the schema after `schema_safety.check`.
- `prompt_steps.resolve(db, collection) -> list[Step]` (per execution; version = `prompt.revision`).
- The `PromptResult` upsert resets the review to `unreviewed` and keeps the last 5 reviewed values in `history`.
- Prompts CRUD and `POST /api/images/prompts/{id}/run {scope}`.
- An exceeded quota fails the step with `quota_exceeded`, without retrying.

**Tests** (pydantic-ai `TestModel`/`FunctionModel`):
- `test_classify_uses_resolve_model`;
- `test_rerun_resets_review_keeps_history`;
- `test_prompt_edit_marks_results_stale`;
- `test_schema_safety_rejects_deep_schema`;
- `test_metered_per_call`;
- `test_quota_exceeded_fails_step`;
- `test_absent_without_ai_module`.

- [ ] Commit `feat(images,ai): classify, prompts and metering outside requests`

### Task 23: Group prompts, presets, cross-check, prompt manager UI

**Files:** Create `sm_images/ai/group_run.py`, `sm_images/services/presets.py` and `sm_images/components/prompts/*` (port `CustomPipelineManager` and `SchemaFieldBuilder`).

**Interfaces — Produces:**
- `run_group(prompt, group)`: member results with at most 4 concurrent, reusing stored ones; one consolidation call at temperature 0; then `preset.cross_check`, whose exceptions are stored as `{error}`.
- `apply_preset(collection, preset_id)` is idempotent by `PromptSpec.id`.
- `GET /api/images/presets`.

**Tests:** one consolidation per group; members reused; the cross-check stored or its error captured; applying a preset is idempotent; the test plugin's preset is listed.

- [ ] Commit `feat(images): group prompts, presets and cross-check`

### Task 24: Review queue

**Files:** Create `sm_images/endpoints/api/review.py`, `sm_images/pages/Review.tsx` and `sm_images/components/review/*` (a schema-generated correction form; keys j/k, a, r, e).

**Interfaces — Produces:**
- `GET /api/images/collections/{id}/review?status=&prompt=` (cursor).
- `POST /api/images/prompt-results/{id}/review {action, data?}`. `correct` validates `data` against the schema (422 otherwise).
- `PromptResultReviewed` on commit.

**Tests:**
- API permissions and validation, and the event after commit.
- vitest: the keyboard flow.
- e2e `images-review.spec.ts`: seed results with a test-only script (no AI call), accept one and correct one.

- [ ] Commit `feat(images): review queue`

### Task 25: Storage billing gauge

**Files:** Create `sm_images/billing.py`.

**Interfaces — Produces:**
- Meter `images.storage_bytes` (gauge, unit bytes), defined in `on_startup` when `billing_meters` exists.
- `check` on upload and import start (402 or `quota_exceeded`).
- Per image, `reserve` then `commit` a hold for the total bytes, stored as `storage_hold_id`. On a display or rendition change it reserves and commits the new total and releases the old hold. If the hold fails, the new objects are deleted and the step fails with `quota_exceeded`.
- The janitor releases the hold.
- Worker-side access goes through the same seam as Task 22.
- `None` billing means unlimited.

**Tests:** over quota gives 402; a regenerated display moves the hold; a purge releases it; no billing means no-op.

- [ ] Commit `feat(images): storage metering`

---

## Phase 7 — Map and public

### Task 26: Points and PMTiles

**Files:** Create `sm_images/map/{points.py,pmtiles_build.py,tasks.py}` and `sm_images/endpoints/api/map.py`.

**Interfaces — Produces:**
- `GET /api/images/collections/{id}/points?bbox=&limit=` returns GeoJSON with only id, captured_at and group_id, filtered by the policy. It is also the `points` contract.
- `build_map(collection_id)` writes NDJSON and runs tippecanoe with the portal's exact arguments (`-l images -Z0 -z14 -r1 --cluster-distance=10 …`), then stores the result under `map_key`.
- Rebuilds trigger on the thresholds after `ImageProcessed` and on `CollectionVisibilityChanged`.
- `GET …/collections/{id}/map.pmtiles` serves Range requests (206, `Accept-Ranges`) with Task 12's cache rules.
- A health check reports when tippecanoe is missing.

**Tests:** the bbox filter; points hide a private collection; `test_range_request_206`; `test_tiles_have_no_filenames` (skipped if tippecanoe is absent); the rebuild threshold.

- [ ] Commit `feat(images): points and PMTiles`

### Task 27: Map tab, public page, pagebuilder block

**Files:** Create `sm_images/components/map/*` (`maplibre-gl` and `pmtiles` npm deps), `sm_images/pages/PublicCollection.tsx` (`/images/c/{slug}`, `bind_public`) and `sm_images/pagebuilder-blocks.ts` (an `ImageGallery` block; labels as keys via `localizeConfig.ts`; pagebuilder as an optional peer).

**Tests:**
- vitest: the block config.
- e2e `images-public.spec.ts`: publish, then view anonymously with thumbnails; the map tab renders a canvas.

- [ ] Commit `feat(images): map tab, public page and gallery block`

---

## Phase 8 — Verification and docs

### Task 28: Real-worker integration check

Not eager. Start dev-services Redis, `make worker worker-imports worker-heavy beat` (after the headroom check) and the dev server. Then:
- upload 3 images and see all steps complete;
- run a 3-feature base64 GeoJSON import;
- kill `worker-imports` mid-import, restart it, and see it resume without duplicates;
- confirm that a plugin step runs in the worker (registry parity).

Record the results in `modules/images/docs/worker.md` and stop everything afterwards. Fix whatever breaks.

- [ ] Commit `test(images): real-worker integration notes`

### Task 29: Module docs and repo notes

**Files:** `modules/images/docs/{index,pipeline,writing-a-plugin,imports,access,worker,migrating-from-portal}.md` (worker settings from spec §3; the plugin example uses `images_extensions.py`), `modules/images/README.md` and `CLAUDE.md` (images in the tenancy, no-env and i18n lists; Celery; the CI extras rule; the `images_extensions.py` registration rule).

**Done-check:** `make lint`.

- [ ] Commit `docs(images): module documentation`

Then `/ship`, which updates PR #272.
