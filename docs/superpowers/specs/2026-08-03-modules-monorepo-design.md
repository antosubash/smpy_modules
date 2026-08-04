# simple_module_python_modules — repo setup design

**Date:** 2026-08-03
**Status:** Approved

## Purpose

`simple_module_python_modules` is the home for distributable SimpleModule add-on
modules that are too domain-specific to live in the framework core. Each module
publishes to PyPI as `simple_module_<name>`. The repo also ships a runnable demo
host that mounts every module for local development, manual QA, and end-to-end
tests.

The first module is **pagebuilder**, ported out of the `smpy_pagebuilder`
application. After the port this repo is canonical; `smpy_pagebuilder` is frozen.

## Context

Three repos in the ecosystem:

- **`simple_module_python`** — the framework. Publishes `simple_module_*`
  (package version `0.0.24`) to PyPI and `@simple-module-py/*` to npm. Modules
  are discovered at boot through the `[project.entry-points.simple_module]`
  entry point. `FRAMEWORK_API_VERSION` is `"1.0.0"` and is deliberately
  decoupled from the package version — a module's
  `ModuleMeta.requires_framework=">=1.0,<2.0"` is correct even against a
  `0.0.24` package.
- **`smpy_pagebuilder`** — an app scaffolded by `smpy new`, holding
  `modules/pagebuilder` (~8.2k LOC Python + TSX, 18 pytest files, 7 Playwright
  specs, a Puck-based editor) and 10 alembic migrations in its host.
- **`simple_module_python_modules`** — this repo. Currently empty apart from
  `README.md` and `.gitattributes`.

Framework convention: **migrations always live in the host, never in a module
package.** A published module ships models; each consuming host autogenerates
its own alembic revisions against them.

## Approach

A scaffold-shaped workspace (the layout `smpy new` produces, which
`smpy_pagebuilder` and `smpy_gis` already use) combined with the release
apparatus from the framework repo. Rejected alternatives:

- **Scaffold shape alone.** `smpy new` produces an *application*; it has nothing
  for publishing modules. Under a lockstep release model, retrofitting the
  version-bump machinery later is the painful part, so it goes in from day one.
- **Full framework-shaped monorepo.** Mirroring `simple_module_python` wholesale
  would mean maintaining a `packages/*` shared-JS tree and a docs site for a
  repo with one module in it. Both are cheap to add when a second module needs
  them.

## Repository layout

```
simple_module_python_modules/
├── pyproject.toml              # uv workspace root (package = false)
├── package.json                # npm workspace root
├── uv.lock  package-lock.json
├── .python-version             # 3.12
├── Makefile
├── .env.example
├── biome.json
├── LICENSE                     # MIT
├── host/                       # demo host — never published
│   ├── main.py
│   ├── pyproject.toml          # package = false
│   ├── alembic.ini
│   ├── migrations/versions/
│   ├── client_app/             # Inertia + React + Vite
│   └── tests/                  # host smoke tests
├── modules/
│   └── pagebuilder/            # simple_module_pagebuilder — published
├── playwright.config.ts
├── tests/e2e/                  # Playwright specs + start-test-server.sh
├── scripts/
│   ├── bump_version.py
│   ├── check_file_size.py
│   ├── check_hardcoded_strings.py
│   ├── check_metadata.py
│   └── check_readmes.py
├── docs/
│   ├── adding-a-module.md
│   └── releasing.md
├── README.md
├── CLAUDE.md
└── .github/workflows/{ci.yml,release.yml}
```

### Workspace wiring

Dual workspace, matching `smpy_pagebuilder`:

- **uv** — root `pyproject.toml` declares `[tool.uv] package = false` and
  `[tool.uv.workspace] members = ["host", "modules/*"]`.
- **npm** — root `package.json` declares `workspaces = ["host/client_app",
  "modules/*"]`, so module frontends share one hoisted `node_modules` and Vite
  resolves React / Inertia / `@simple-module-py/ui` without per-module aliasing.

Adding a module means creating `modules/<name>/` and adding two lines to
`host/pyproject.toml`: the dependency, and a
`[tool.uv.sources] simple_module_<name> = { workspace = true }` entry.

No `hello` sample module. It is a scaffold artifact; pagebuilder is this repo's
reference implementation.

The root `pyproject.toml` additionally carries shared ruff configuration and
pytest `testpaths`; `biome.json` covers JS. Both are copied from the framework
repo so lint rules stay consistent across repos.

### Dependency pin policy

Pin style differs by role, and the difference is load-bearing:

| Role | Style | Example |
|---|---|---|
| Published module | Range | `simple_module_core>=0.0.24,<0.1` |
| Demo host (an app) | Exact | `simple_module_hosting==0.0.24` |

A published module pinned `==0.0.24` would be uninstallable in any host running
framework `0.0.25`. The host is not published, so exact pins there buy
reproducibility at no cost.

### Local framework override

Developing a module against unreleased framework changes uses:

```bash
make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python
make unlink-framework
```

`link-framework` runs `uv pip install -e` for the framework's `core`, `db`, and
`hosting` packages into the workspace venv. `unlink-framework` re-syncs back to
the PyPI versions. Neither touches a tracked file, so a local override cannot
leak into a release.

## The pagebuilder module

### Ported unchanged

The full `pagebuilder/` package: `models.py`, `service.py`, `services.py`,
`media_service.py`, `layout_service.py`, `diff.py`, `security.py`,
`permissions.py`, `settings.py`, `deps.py`, `endpoints/{api,views,seo}.py`, the
6 Puck block components, 6 TSX pages, and `utils/`. All 18 pytest files move
with it. The 7 Playwright specs move to `tests/e2e/`.

`ModuleMeta.requires_framework=">=1.0,<2.0"` stays as-is — see the
`FRAMEWORK_API_VERSION` note in Context.

### Modernized during the port

| Change | Rationale |
|---|---|
| Framework deps `==0.0.12` → `>=0.0.24,<0.1` | Installable against any current framework build |
| Add `readme`, `license = "MIT"`, `authors`, `keywords`, `project.urls.Repository` | Required by `check_metadata` |
| `schemas.py` → `contracts/schemas.py` | Current convention: `contracts/` is the declared public surface |
| Add `py.typed` | Ships type information to consumers, as every current first-party module does |
| Add `constants.py` with `PERM_*` / `_PAGE_*` / `_MODULE_*` | Required by `check_hardcoded_strings` |
| `ModuleMeta.version` reads `importlib.metadata.version("simple_module_pagebuilder")` | Removes drift — meta currently says `0.2.0` while pyproject says `0.1.0` |

### File splits

`check_file_size` (300-line cap) is enforced from day one, so six files are
split as part of the port:

| File | Lines |
|---|---|
| `pages/PageEditor.tsx` | 922 |
| `pages/MediaLibrary.tsx` | 599 |
| `endpoints/api.py` | 406 |
| `media_service.py` | 395 |
| `service.py` | 380 |
| `tests/conftest.py` | 301 |

Splits are behaviour-preserving extractions, made after the ported test suite is
green so the existing tests and e2e specs act as the safety net. Splitting
before the suite passes would make it impossible to tell a move from a rewrite.

### JS packaging

The module's `package.json` stays `private: true` and is force-included into the
wheel at `pagebuilder/package.json`. Hosts discover its JS dependencies (notably
`@measured/puck`) via `smpy host sync-js-deps`. Nothing is published to npm from
this repo.

## Demo host

Installs `simple_module_auth`, `_users`, `_dashboard`, `_permissions` from PyPI
at exact pins, and `simple_module_pagebuilder` from the workspace. Pagebuilder
does its own uploads via Pillow, so `file_storage` is not required.

SQLite (`host/app.db`) by default; `SM_DATABASE_URL` points at the shared
`dev-services` Postgres stack when wanted.

### Migrations

`host/migrations/versions/` gets **two squashed baseline revisions**, mirroring
how `smpy_pagebuilder`'s history starts:

1. `initial` — the framework module tables (auth, users, permissions,
   dashboard).
2. `add_pagebuilder` — every pagebuilder table in one revision, carrying
   `branch_labels = ("pagebuilder",)` per framework convention so the module can
   later be downgraded independently with `alembic downgrade pagebuilder@base`.

The 10 incremental migrations in `smpy_pagebuilder` are not replayed. They exist
only to walk that host's database forward; it is being frozen, and consumers
autogenerate their own revisions against the module's models. Replaying its
history here would be noise with no upgrade path attached to it.

## Testing

Three layers:

1. **Module pytest** — run from inside `modules/pagebuilder/` so it picks up its
   own `[tool.pytest.ini_options]` (notably `asyncio_mode = "auto"`). Uses
   `simple_module_test` fixtures (`build_test_app`, `fake_event_bus`); no host
   required. The 18 ported test files live here, and they are the safety net for
   the file splits.
2. **Host smoke test** — boots the app and asserts pagebuilder's routes and menu
   entries registered. Catches wiring breaks that isolated module tests cannot
   see.
3. **Playwright e2e** — the 7 ported specs in `tests/e2e/`, with
   `start-test-server.sh` isolating the run against `host/test.db` so it never
   touches `host/app.db`. An admin is seeded from `SM_USERS_BOOTSTRAP_*` env
   vars baked into `playwright.config.ts`.

## Makefile

`install`, `dev`, `dev-api`, `dev-ui`, `gen-pages`, `sync-module-deps`,
`migrate`, `migration msg=…`, `test-py`, `test-js`, `e2e`, `lint`, `kill`, plus:

- `link-framework` / `unlink-framework` — see above.
- `new-module name=<x>` — wraps `smpy create-module <x> --dest modules/<x>`.
  Deliberately without `--standalone`: GitHub only runs workflows from the
  repository-root `.github/workflows/`, so a nested per-module workflow would
  never run, and a nested `publish.yml` is a publish footgun.

## CI

`ci.yml`, based on `smpy_pagebuilder`'s existing workflow:

- Concurrency group cancelling in-progress runs except on `main`.
- Stub the gitignored `modules/*/<pkg>/static/dist` force-include directories
  before `uv sync` — editable installs need them to exist.
- `uv sync --all-packages --all-extras`, then pytest run from within each module
  directory, plus host tests.
- `sync-module-deps` → `gen-pages` → `npm run build` (tsc + vite).
- Playwright with browsers cached on the resolved Playwright version,
  `--max-failures=1`, report uploaded as an artifact.

Added on top of that base:

- A **`checks`** job running `check_metadata`, `check_hardcoded_strings`,
  `check_file_size`, `check_readmes`, and `bump_version.py --check`.
- `biome check` alongside the existing ruff job.

## Release

Lockstep: every module in the repo shares one version, and one release publishes
all of them. Modeled on the framework's four-stage `release.yml`:

1. **resolve** — `workflow_dispatch` with a `bump` choice
   (patch/minor/major) or an explicit `version` override; validates the result.
2. **build** — bumps versions in the working tree only (no commit), then
   `uv build --all-packages`; uploads artifacts.
3. **publish-pypi** — a matrix job per module, OIDC trusted publishing,
   `fail-fast: false`.
4. **finalize** — commits the version bump, tags, and creates the GitHub
   release.

The tag reaches origin only after every publish succeeds, so a failed build
never strands an orphan tag.

Two adaptations from the framework's version of this machinery:

- **`scripts/bump_version.py` is a variant, not a copy.** The framework's script
  rewrites every `simple_module_*` dependency to `==<version>`. Run unmodified
  here, it would rewrite `simple_module_core>=0.0.24,<0.1` into
  `==<this repo's version>`, pinning the framework to a version that does not
  exist. This repo's script bumps **only its own packages' versions** and never
  touches framework dependency specifiers. Its `--check` mode runs in CI to stop
  that regressing.
- **Version anchor** is the root `pyproject.toml`'s `version`. `host/` is
  excluded from publishing (`package = false`).

## Documentation

- `README.md` — what the repo is, layout, quick start, adding a module, release
  process.
- `CLAUDE.md` — shared `dev-services` Postgres note (path
  `/Volumes/ext1/GitHub/dev-services`), the pin policy, and the
  migrations-live-in-the-host rule.
- `docs/adding-a-module.md`, `docs/releasing.md`.

No docs site until there is more than one module.

## Deferred

Recorded here so they are not silently dropped:

- **UI i18n / `locales/en.json`** for pagebuilder. Its TSX copy is hardcoded
  English. `branding` has locales; adding them is a feature addition, not a port.
- **Converting or archiving `smpy_pagebuilder`.** This repo becomes canonical;
  what happens to that repo is separate work.
- **`packages/*` shared JS.** Added when a second module needs to share
  frontend code with pagebuilder. Shared UI already comes from the published
  `@simple-module-py/ui`.
- **docker-compose stack.** The host runs on SQLite by default and against the
  shared `dev-services` Postgres when needed.

## Success criteria

- `make install && make migrate && make dev` boots the host with pagebuilder
  mounted and usable.
- `make test-py` passes: all 18 ported pagebuilder tests plus host smoke tests.
- `make e2e` passes all 7 ported Playwright specs.
- `make lint` passes, including `check_file_size` with no exemptions for
  pagebuilder.
- `uv build --all-packages` produces a `simple_module_pagebuilder` wheel
  containing `pagebuilder/package.json` and the built `static/dist`.
- `release.yml` runs green through `build` on a dry run.
