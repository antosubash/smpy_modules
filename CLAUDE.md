# CLAUDE.md

Guidance for Claude Code in this repository. See `README.md` for general
project documentation.

## What this repo is

A monorepo of **distributable** SimpleModule add-ons plus a demo host. Each
`modules/<name>/` is published to PyPI as `simple_module_<name>`. `host/` is a
development app that mounts them; it is never published.

## Rules that are easy to get wrong

**Pin policy differs by role.** Published modules depend on the framework with
*ranges* (`simple_module_core>=0.0.25,<0.1`). The host pins *exactly*
(`simple_module_hosting==0.0.25`). Never give a published module an `==` pin —
it becomes uninstallable in any host running a newer framework build.

**Migrations live in `host/migrations/versions/`, never in a module.** Modules
ship SQLModel tables; each consuming host autogenerates its own revisions
against them. A module's first revision carries
`branch_labels = ("<module>",)` so it can be removed on its own with
`alembic downgrade <module>@base`.

**Never add a file under `modules/*/*/pages/` unless it is a real Inertia
page.** The page name is derived from that path by `import.meta.glob`, so a
stray `.tsx` there silently registers a new page. Extractions go to
`components/`, `hooks/`, or `utils/`.

**Releases are lockstep.** One version across the repo. `scripts/bump_version.py`
is the only thing that edits versions, and it must never rewrite framework
dependency specifiers — the framework's own copy of that script does, which
would pin the framework to a version that doesn't exist. `scripts/tests/`
guards this and CI runs `--check-current`.

**Run Python entry points from the repo root.** `alembic.ini` resolves its
`script_location` relative to itself and `dev-api` uses `--app-dir host`, so
the root `.env` is the single source of truth for settings regardless of the
command.

**300-line cap** on every `.py` / `.ts` / `.tsx`, enforced by
`scripts/check_file_size.py`. Nothing under `modules/` is exempt.

## Local database (shared dev-services stack)

**Do NOT spin up a new Postgres container for local dev.** All repos under
`/Volumes/ext1/GitHub` share one stack defined in
`/Volumes/ext1/GitHub/dev-services` (PostGIS + Redis + MinIO + Adminer on the
`devnet` Docker network). Start it once with `make up` there.

Local dev defaults to **SQLite** (`host/app.db`), so Postgres is optional. To
use it, set:

```
SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules
```

Add the database to `dev-services/init/01-databases.sql` if it doesn't exist.
If 5432 is taken by an old per-project container, stop that container rather
than remapping ports. This repo does not use Redis or Celery.

## Working against an unreleased framework

```bash
make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python
make unlink-framework
```

Editable-installs the framework's `core`/`db`/`hosting` into the workspace
venv and back. Neither touches a tracked file.

## Known deferred work

- **UI i18n.** Pagebuilder's TSX copy is hardcoded English; there is no
  `locales/en.json`. Other first-party modules have one.
- **`smpy_pagebuilder`** still holds the pre-port copy of this module. This
  repo is canonical; that one is frozen.
