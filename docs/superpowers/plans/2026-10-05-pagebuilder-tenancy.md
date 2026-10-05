# pagebuilder tenancy (#38) — implementation plan

Design: `docs/superpowers/specs/2026-10-05-pagebuilder-tenancy-design.md`.
All paths relative to `modules/pagebuilder/` unless noted. Run tests with
`cd modules/pagebuilder && uv run pytest -q`. 300-line cap on every file
(`uv run python scripts/check_file_size.py` from the repo root).

## T1 — Tenancy core, models, migration (HARD, sequential, first)

Files: new `pagebuilder/tenancy.py` (mode + binding), `pagebuilder/models/*`,
every `APIRouter` in `pagebuilder/endpoints/**` and the public routers, `module.py`
(`on_startup` → `tenancy.configure`), `tests/tenant_fixture.py` (registered in
`pyproject.toml` addopts), `host/migrations/versions/<new>_pagebuilder_tenant_id.py`.

- `DEFAULT_TENANT = "default"`; `detect_mode(app)` / `configure(app)` copied in
  spirit from `modules/records/sm_records/_tenancy_mode.py` (refuse `fixed != "default"`).
- `resolve_admin` (SINGLE → default; MULTI → `request.state.tenant_id`, else 403),
  `resolve_public` (SINGLE → default; MULTI → `request.state.tenant_id` or None).
- `bind_admin` / `bind_public` yield deps using `simple_module_db.tenant_context`;
  `bind_public` raises `HTTPException(404, "Page not found")` with no tenant.
  Must be FIRST in each router's dependencies (before `get_db`).
- `MultiTenantMixin` on all nine tables; tenant-prefixed unique indexes per the design.
- Test first: `tests/test_tenancy_core.py` — SM024 clean, mode detection, refusal,
  bind_public 404 with no tenant in MULTI mode, admin 403.
- Autouse sync fixture binding `"default"` for existing tests.
- Migration: add column, backfill `'default'`, NOT NULL, index, swap unique
  indexes (SQLite via `batch_alter_table`, like `4ecb931245dd_records_tenant_id.py`).
- Done: full pagebuilder suite green; `alembic upgrade heads && alembic check` clean.

## T2 — Media per tenant (after T1; parallel with T3, T4)

Files: `media_files.py`, `media_service.py`, `boot.py` (mount), `snapshots/capture.py`,
`snapshots/media_match.py`, `snapshots/apply.py` (media paths only), tests.
- Path `media_root/<tenant>/<filename>`; URL `<prefix>/<tenant>/<filename>`.
- `MediaFiles` 404s a path whose first segment ≠ bound tenant (MULTI mode).
- Startup legacy move of top-level files into `default/` (idempotent).
- Orphan scan under `all_tenants()`, per-row tenant dir.
- Done: tests for path/URL, cross-tenant 404, legacy move, orphan scan.

## T3 — Snapshot blobs per tenant (after T1; parallel)

Files: `snapshots/blobs.py`, `snapshots/service.py` (BlobStore construction),
legacy blob move, tests. GC in tenant A must never delete tenant B's blobs.

## T4 — Scheduler loops tenants (after T1; parallel)

Files: `scheduler.py`, tests. Distinct due tenant ids under `all_tenants()`;
fresh session per tenant under `tenant_context`; one tenant failing doesn't stop others.

## T5 — Isolation tests (after T1–T4)

New `tests/test_tenancy_isolation*.py`: admin read isolation, same slug in two
tenants, redirect scoping, layout per tenant, public viewer/sitemap per tenant
and 404 without tenant.

## T6 — Deps + docs (independent)

`pyproject.toml` floors `simple_module_core`/`simple_module_db >=0.0.35,<0.1`
(refresh `uv.lock`); README tenancy section; CLAUDE.md note.

Final: repo-root `make lint`, `make test-py`, alembic check.
