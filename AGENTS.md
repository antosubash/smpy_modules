# AGENTS.md

Rules for coding agents in this repository; `README.md` is the human
introduction. Where a rule has more detail, the link says where.

## What this repo is

A monorepo of **distributable** SimpleModule add-ons plus a demo host. Each
`modules/<name>/` is published to PyPI as `simple_module_<name>`; `host/` is a
development app that mounts them and is never published. The nine modules,
each with docs in `modules/<name>/docs/`: **ai**, **analytics**, **billing**,
**events**, **images**, **news**, **newsletter**, **pagebuilder**, **records**.

New code must run on **Python 3.12** (the `requires-python` floor) and **3.14**
(the Docker runtime); CI tests both. Run Python entry points (`scripts/*.py`,
`make dev-api`, and alembic as `uv run --project host alembic -c host/alembic.ini
...`, which is what `make migrate`, `migration` and `downgrade` run) from the repo root:
`host/alembic.ini` resolves `script_location` relative to itself and `dev-api`
uses `--app-dir host`, so the root `.env` is the one source of settings.

## Checks

`make lint` runs, in order:

| Step | Enforces |
| --- | --- |
| `ruff check .` | Lint incl. `S` (bandit) except `S101`, because a production `assert` only narrows a type after a real check, never validates input; tests and `scripts/` have per-file ignores, production code a line-level `# noqa: Sxxx - <reason>` |
| `basedpyright` | Basic mode over `[tool.pyright] include` only: every `contracts/` package and its cross-module callers (#338); widen it module by module. There a SQLModel column in a query goes through `sqlmodel.col()`, and a suppression is `# pyright: ignore[rule]` with its reason |
| `npx biome check .` | JS/TS lint and format |
| `make typecheck` | `tsc --noEmit` per module |
| `scripts/check_metadata.py` | Package metadata and the root pytest `testpaths` |
| `scripts/check_rules.py` | No `==` framework pin in a module; sibling requirements carry a `>=` floor and `# floor:` comment; only real pages under `pages/` |
| `scripts/check_sibling_contracts.py` | Each `<sibling>.contracts` import exists at the floor's tag; no import of a sibling's other code (needs `git fetch --tags`) |
| `scripts/moved_paths.py --check` | The 0.0.14 moved-path stubs match their tables; nothing imports an old path |
| `scripts/check_ts_imports.py` | No deep frontend import into another module (#337) |
| `scripts/check_readmes.py` | Each module README exists, is ≥500 bytes, has an H1, Install and Usage |
| `scripts/check_hardcoded_strings.py` | Permissions, roles, Inertia pages and module deps are named constants |
| `scripts/check_file_size.py` | 300-line cap; 280+ warns |
| `scripts/check_locales.py` | Each `locales/<lang>.json` matches `en.json`'s keys and placeholders |
| `scripts/check_migration_heads.py` | One migration head |
| `scripts/bump_version.py --check-current` | Every package carries the lockstep version |

Tests: `make test-py`, `make test-js`, `make e2e-bundle` (serial) or
`make e2e-parallel` (three local shards). CI (`.github/workflows/ci.yml`):
`Lint (ruff)` (ruff + basedpyright), `Lint (biome)`, `Python tests (pytest, 3.12)`
and `(pytest, 3.14)`, `Postgres (migrations + module suites)`,
`Frontend build (tsc + vite)`, `Frontend unit tests (vitest)`,
`Docker image (build + boot)`, `Background tasks (Redis + Celery worker)`,
`Repo checks (metadata, readmes, strings, file size)` (the lint scripts plus
`pytest scripts/tests`), three `E2E shard` jobs merged into `E2E (Playwright)`,
and the opt-in `E2E (multi-tenant)`, `E2E (billing per user)` and
`E2E (newsletter)`. Also: `framework-latest.yml` (nightly, every module against
the newest framework in range; red means the next bump needs work),
`images-models.yml` (weekly or manual, images' anonymize step on the real
models) and `release.yml` (`docs/releasing.md`).

## Detailed rules

Domain-specific rules live in flat `.agents/rules/*.md` files so each instruction
file stays under Antigravity CLI's 24 KB rule limit (`CLAUDE.md` imports
`AGENTS.md`; read the matching rule file when working on those topics):

| File | Scope |
|---|---|
| `.agents/rules/cross-module-rules.md` | Cross-module dependencies, tenancy, storage, auth, transactions, layout, E2E |
| `.agents/rules/per-module-invariants.md` | Per-module invariants (`records`, `events`, `newsletter`, `billing`, `images`, `ai`) |

## Local setup

- **Install**: `make install` syncs `--all-extras --no-extra anonymize`, like the
  CI Python, lint, repo-checks, e2e and release jobs and `framework-latest`;
  the Postgres, frontend and background-tasks jobs sync no extras. CI apt-installs `tippecanoe`.
- **Database**: SQLite (`host/app.db`) by default; Postgres with
  `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules`.
  Prefer the shared `dev-services` stack (PostGIS, Redis, MinIO, Adminer on
  `devnet`; `make up` there; add the database to its `init/01-databases.sql`), no
  per-project Postgres beside it (stop an old one on 5432, don't remap). Without
  it: `docker run -d --name smpy-postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=smpy_modules postgres:16`.
- **Workers**: images, newsletter and events use Redis/Celery. `make worker`
  (the `images`, `newsletter`, `events` and `celery` queues), `worker-imports`,
  `worker-heavy`, `worker-gpu` and `beat` run `host/worker.py`
  (`build_runner_celery`), one queue set each; `make dev` starts none. Without
  one, `SM_BG_TASKS_TASK_ALWAYS_EAGER=true` (e2e adds `..._EAGER_PROPAGATES=true`).
- **Tenancy**: the demo host is single-tenant; `SM_MULTI_TENANT=true` boots every
  module multi-tenant.

## Working against an unreleased framework

`make link-framework FRAMEWORK=/path/to/simple_module_python` editable-installs
its `core`/`db`/`hosting` plus `FRAMEWORK_MODULES` (default `branding`) into the
venv; `make unlink-framework` reverts. Neither touches a tracked file;
`FRAMEWORK` has no default.

## i18n

- Set `ModuleMeta.i18n_audience="admin"` when no anonymous page, form or embedded block reads that module's shared catalogue; public strings must then come from server copy or a bundled catalogue (events' `PageLocale` is the reference).
- **Console UI is English and German in all nine modules**: `locales/en.json` and
  `de.json`, every string through `t(keys.<module>.<section>.<key>)`, no
  `defaultValue`. Add a key to every catalogue at once. A runtime-chosen family
  (`filters.op.<op>`) is a `Record<Union, string>` of `keys.…` leaves. The
  namespace is the `modules/<name>` directory (`sm_billing` is `billing`), as in
  `tests/vitest-i18n.ts`.
- **Host chrome**: the framework ships the `ui` catalogue (German since 0.0.38)
  and `POST /i18n/set-locale` (`locale` cookie). `host/locales/overrides/de.json`
  keeps only labels the host words differently; `host/tests/test_ui_locales.py`
  fails on an untranslated `ui` key or a vanished or redundant override.
- **The trap when adding a module**: npm's `@simple-module-py/i18n` has only the
  framework's namespaces, so `keys.<yourmodule>` does not exist, and
  `smpy host gen-i18n` writes into `node_modules` (wiped by `npm ci`; a consuming
  host lacks the runtime `keys`). Derive `keys` from the module's own `en.json`
  at compile time (`resolveJsonModule` plus a mapped type, leaves typed `string`);
  reference: `modules/news/news/ui/utils/i18n.ts` (about 180 lines).
- **Puck block labels** hold the *key*, resolved at render (each module's
  `localizeConfig.ts`; pagebuilder's recurses into `arrayFields`/`objectFields`).
- **Content i18n** is pagebuilder's `content_locales` (what the site publishes),
  separate from `SM_I18N_SUPPORTED_LOCALES` (what the console speaks).

## Pointers

- `SECURITY.md` (reporting, scope); `CHANGELOG.md` (lockstep, a
  `## <version> (unreleased)` section).
- `docs/module-layout.md`, `docs/adding-a-module.md`, `docs/releasing.md`,
  `docs/secret-key-rotation.md`, `host/migrations/README.md`.
- History, not current rules: `docs/plans/`, `docs/superpowers/` and dated
  `*-20YY-MM-DD.md` reports. Where one disagrees with this file or a module doc,
  this file and the module doc win.
