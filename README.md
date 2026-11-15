# simple_module_python_modules

Distributable add-on modules for [simple_module_python](https://github.com/antosubash/simple_module_python)
applications, plus a demo host that mounts them all.

Modules that are too domain-specific to belong in the framework core live
here. Each publishes to PyPI as `simple_module_<name>` and is discovered at
boot through the `simple_module` entry point — a consuming host installs it
and adds one dependency line, no registration code.

## Modules

| Directory | Package | Purpose |
|---|---|---|
| `modules/pagebuilder` | [`simple_module_pagebuilder`](https://pypi.org/project/simple_module_pagebuilder/) | Drag-and-drop visual page builder with revisions, approvals, media library, scheduling, multilingual content, and SEO |
| `modules/news` | [`simple_module_news`](https://pypi.org/project/simple_module_news/) | A self-contained news archive — articles with categories, tags, revisions, approvals, translations, SEO and a public viewer. Pagebuilder is an optional extra (`[pagebuilder]`): with it, a News feed block, Pages and Media in the admin search, and articles in the content bundle |
| `modules/records` | [`simple_module_records`](https://pypi.org/project/simple_module_records/) | Admin-defined record types stored as JSON documents with typed SQL indexes — schema editor, generic CRUD screens, relations, revisions, import/export, and an anonymous read API |
| `modules/billing` | [`simple_module_billing`](https://pypi.org/project/simple_module_billing/) | Plans, Stripe subscriptions and entitlements for multi-tenant apps — plan editor, Checkout and Customer Portal, webhooks, per-seat sync, dunning suspension, and a manual provider for installs without Stripe ([docs](modules/billing/docs/index.md)) |
| `modules/ai` | [`simple_module_ai`](https://pypi.org/project/simple_module_ai/) | AI base module: provider-configurable Pydantic AI service layer, encrypted key storage, admin settings UI ([README](modules/ai/README.md)) |
| `modules/newsletter` | [`simple_module_newsletter`](https://pypi.org/project/simple_module_newsletter/) | Email campaigns to records' subscription lists — tenant-wide suppressions mirrored from unsubscribes, DB-backed SMTP settings with an encrypted password, Puck campaign editor, email renderer, preview and test send, throttled sending with retries, open and click tracking and reports, segments and audiences, subscriber and suppression screens, and a Mailchimp import. **Needs a Celery worker and beat (Redis) in production** ([operations](modules/newsletter/docs/operations.md)) |
| `modules/images` | [`simple_module_images`](https://pypi.org/project/simple_module_images/) | Image collections with an immutable-original processing pipeline — EXIF and location, renditions, quality checks, optional anonymisation, geo-located imports and map tiles; private, shared, internal or public per collection. **Needs Celery workers (Redis) in production** ([workers](modules/images/docs/worker.md)) |
| `modules/analytics` | [`simple_module_analytics`](https://pypi.org/project/simple_module_analytics/) | Anonymous traffic and application events, with tenant reports and local country/region/city geolocation ([docs](modules/analytics/docs/index.md)) |

### Publishing in more than one language

Pages and articles can exist in several languages, each with its own slug,
draft and approval state. Off by default; turn it on under **Settings →
PageBuilder**, or headlessly:

```bash
python scripts/set_setting.py pagebuilder \
  content_locales '["en","de"]' default_content_locale en
```

Both fields are marked *requires restart* on that screen: the languages decide
which routes get mounted, and that happens once, at boot.

The default language keeps its existing addresses (`/p/about`, `/news/x`) and
every other one is prefixed (`/de/p/about`, `/de/news/x`), so switching this on
strands no link that already exists. See
[`modules/pagebuilder/README.md`](modules/pagebuilder/README.md#multilingual-content)
for the model and the editor flow.

## Layout

```
├── modules/              # published packages, one per directory
│   ├── ai/  analytics/  billing/  images/
│   └── news/  newsletter/  pagebuilder/  records/
├── host/                 # demo host — never published
│   ├── main.py
│   ├── worker.py         # Celery app for `make worker` / `beat`
│   ├── client_app/       # Inertia + React + Vite
│   ├── locales/          # the host's catalogue and its overrides of the chrome's labels
│   ├── templates/        # index.html, the Inertia root
│   ├── alembic.ini
│   ├── migrations/       # every module's migrations live here
│   └── tests/            # host smoke tests
├── tests/e2e/            # Playwright specs against the demo host
├── scripts/              # repo checks, release tooling, e2e harness, settings CLI
├── docs/                 # module layout, adding a module, releasing, key rotation
├── docker/entrypoint.sh  # container start: migrate, then uvicorn
├── Dockerfile            # the demo host as one image
├── compose.yaml          # runs that image; compose.devnet.yaml joins dev-services
├── Makefile
├── .env.example          # copied to .env by `make env`
├── AGENTS.md             # the guide for coding agents (CLAUDE.md imports it)
├── CLAUDE.md
├── CHANGELOG.md
├── SECURITY.md
└── .github/
    ├── workflows/        # ci.yml, release.yml, framework-latest.yml, images-models.yml
    ├── actions/e2e-setup/
    └── dependabot.yml
```

The repo is both a **uv workspace** (members: `host`, `modules/*`) and an
**npm workspace** (`host/client_app`, `modules/*`), so module frontends share
one hoisted `node_modules` and Vite resolves React, Inertia, and
`@simple-module-py/ui` without per-module aliasing.

`scripts/` holds three kinds of tool: the checks `make lint` runs
(`check_*.py`, `moved_paths.py`, `bump_version.py --check-current`), the
release and e2e harness (`bump_version.py`, `release_ci_gate.py`,
`e2e_shards.mjs`, `pytest_modules.sh`, `pytest_modules_pg.sh`,
`bg_tasks_smoke.py`), and operator commands (`set_setting.py`,
`reencrypt_secrets.py`, `seed_usage.py`). Their own tests are in
`scripts/tests/`.

## Quick start

You need [uv](https://docs.astral.sh/uv/), Python 3.12 (`.python-version`; uv
installs it) and Node 26.

```bash
make install     # Python workspace + npm workspace + wheel-shipped JS deps
make env         # .env from .env.example, with three generated secrets
make migrate     # apply migrations
make dev         # API on :8000, Vite on :5050
```

- **`make install`** is `install-py` (`uv sync --all-packages --all-extras
  --no-extra anonymize`: every extra except images' onnxruntime one),
  `install-js` (`npm install`) and `sync-module-deps`, which pulls the JS
  dependencies of wheel-installed modules into `host/client_app`.
- **`make env`** copies `.env.example`, which ships no secret values, and
  appends a generated `SM_SECRET_KEY`, `SM_USERS_RESET_PASSWORD_TOKEN_SECRET`
  and `SM_USERS_VERIFICATION_TOKEN_SECRET`. It does nothing if `.env` exists.
- **First admin.** Uncomment `SM_USERS_BOOTSTRAP_EMAIL` and
  `SM_USERS_BOOTSTRAP_PASSWORD` in `.env` before the first boot; they seed an
  admin while the users table is empty, and only then.
- **`make dev`** runs the API (uvicorn with `--reload`) and Vite together.
  To run a second checkout beside the first, move both and tell each about the
  other: `API_PORT=8001 UI_PORT=5051 SM_UI_PORT=5051
  SM_VITE_DEV_URL=http://localhost:5051 make dev` (Vite reads `SM_UI_PORT`, the
  API `SM_VITE_DEV_URL`); `make kill` frees this checkout's ports.
- **Migrations.** `make migration msg="…"` autogenerates a revision in
  `host/migrations/versions/`, `make migrate` runs `upgrade heads`, and
  `make downgrade` steps back one revision.
- **Background tasks.** images and newsletter run work on Celery. `.env.example`
  sets `SM_BG_TASKS_TASK_ALWAYS_EAGER=true`, so tasks run inline in the web
  process. Recurring work still needs beat: without `make beat` a scheduled
  newsletter campaign is never dispatched
  ([operations](modules/newsletter/docs/operations.md)). To run them the way production does,
  point `SM_REDIS_URL` at a Redis, drop the eager line, and start the workers
  beside `make dev`: `make worker` (the `images`, `newsletter` and `celery`
  queues), `make worker-imports`, `make worker-heavy`, `make worker-gpu`, and
  one `make beat`.

Local dev defaults to SQLite at `host/app.db`. For Postgres, set

```
SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules
```

and use the shared `dev-services` stack where you have it, or
`docker run -d --name smpy-postgres -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=smpy_modules postgres:16`
otherwise.

Run every Python entry point from the repo root: `alembic.ini` resolves its
paths relative to itself and the API loads with `--app-dir host`, so the root
`.env` is the one source of settings whatever the command.

## Running in Docker

`compose.yaml` runs the demo host alone in a container — the API serving the
pre-built UI, no Vite, no database service:

```bash
make env                       # once: .env with generated secrets
echo 'SM_USERS_BOOTSTRAP_EMAIL=admin@example.com' >> .env
echo "SM_USERS_BOOTSTRAP_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')" >> .env  # note it down
docker compose up -d --build   # http://localhost:8090, first build ~2 min
curl -fsS http://localhost:8090/health/live
docker compose down            # -v also drops the data volumes
```

- **Image.** The `Dockerfile` builds the UI in a Node 26 `ui` stage (`npm ci`,
  `sync-js-deps`, `gen-pages`, `npm run build`), then installs the Python
  workspace without dev dependencies into a slim Python 3.14 `runtime` image,
  which runs as the unprivileged uid 10001. Each start runs
  `alembic upgrade heads`, then uvicorn. The container runs
  `SM_ENVIRONMENT=production`, and its `HEALTHCHECK` polls `/health/live`.
  Base images are pinned to an exact tag and digest; Dependabot bumps them.
- **Background tasks run in-process.** The stack has no Redis and no worker,
  so compose sets `SM_BG_TASKS_TASK_ALWAYS_EAGER=true`, the `memory://` broker,
  the `cache+memory://` result backend and
  `SM_BG_TASKS_BROADCAST_INVALIDATIONS=false` (production refuses the default
  localhost broker even when eager). That is enough for a demo. A real images
  or newsletter deployment needs Redis, overrides for all four, and worker and
  beat processes like the `make worker` targets.
- **Migrations** run on every start, which is right for the one container
  compose starts and wrong for several: nothing locks the upgrade, so replicas
  starting together would run the same DDL at once. `SMPY_MIGRATE_ON_START`
  takes `1`/`true`/`yes` (the default) or `0`/`false`/`no`; anything else stops
  the container with exit code 64. Run more than one replica with
  `SMPY_MIGRATE_ON_START=0` and migrate once beforehand:
  `docker compose run --rm -e SMPY_MIGRATE_ON_START=1 host true`.
- **Secrets** come from the env file, never the image: `SM_SECRET_KEY` and the
  two `SM_USERS_*_TOKEN_SECRET` keys, which production refuses to boot without.
  `.env.example` carries no values for them; `make env` generates all three. A
  `.env` written by hand needs them added (or regenerate it with `make env` after
  moving the old one aside). `SMPY_ENV_FILE=path` picks a different file.
  Rotating `SM_SECRET_KEY` without losing the stored credentials it encrypts:
  [docs/secret-key-rotation.md](docs/secret-key-rotation.md).
- **Admin.** `SM_USERS_BOOTSTRAP_EMAIL` / `_PASSWORD` in the env file seed the
  first admin, on first start against an empty users table only.
- **Plain HTTP.** Production marks the session cookie `Secure`, which browsers
  accept on `http://localhost` / `127.0.0.1` (Chrome, Firefox) but drop on any
  other plain-HTTP origin and in Safari — login then appears to succeed and
  never sticks. Put TLS in front, or for a throwaway LAN demo turn the flag off
  (a DB-backed users setting, not an env var):
  `docker compose run --rm host python scripts/set_setting.py users cookie_secure false`.
- **Port.** `SMPY_PORT` (default `8090`) is the host port; the container
  listens on 8000. It is published on `127.0.0.1` only; set
  `SMPY_BIND_ADDRESS=0.0.0.0` to reach it from other machines.
- **Database.** SQLite at `/app/var/app.db` in the `smpy-data` volume by default
  (pagebuilder media and snapshots live there too; file uploads are in
  `smpy-uploads`). For the shared dev-services Postgres, add the overlay that
  joins its `devnet` network and point `SMPY_DATABASE_URL` at it — the
  `smpy_modules` database must exist there:

  ```bash
  SMPY_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/smpy_modules \
    docker compose -f compose.yaml -f compose.devnet.yaml up -d --build
  ```

  The compose variables are `SMPY_*` rather than `SM_*` because `.env`'s own
  `SM_DATABASE_URL` and `SM_ENVIRONMENT` describe a process on your machine;
  compose overrides both inside the container.
- **One-off commands** run after the migrations, in place of the server:
  `docker compose run --rm host python scripts/set_setting.py pagebuilder content_locales '["en","de"]'`.

## Testing

```bash
make test           # test-py + test-js
make test-py        # host smoke tests, scripts/tests, then each module's suite
make test-js        # vitest: module frontend unit tests
make e2e            # Playwright against the dev stack
make e2e-bundle     # Playwright against the production bundle (what CI runs)
make e2e-parallel   # the bundle run in three local shards
make lint           # every static check, listed below
```

The Python suites run on pytest-xdist, one suite after another, each with
`PYTEST_WORKERS` workers (`auto`, one per core, by default;
`PYTEST_WORKERS=8 make test-py` on a shared machine, `0` for a serial run).
With `SM_TEST_DATABASE_URL` set, each worker gets its own Postgres database,
`<name>_gw0`, `<name>_gw1`, …, created on first use — the role needs
`CREATEDB`. A test must therefore not write under the working directory or
share any other state with a test another worker may be running.

The e2e suite needs a browser once: `npx playwright install chromium --with-deps`.
It resets `host/test.db` on every run and never touches `host/app.db`.
CI splits it into three `--shard=i/3` jobs, each booting its own host on its
own database, so every spec file must pass on a fresh database with no other
file run first. `npx playwright test --shard=2/3` reproduces one shard locally.
`make e2e-parallel` runs all three at once on one machine
(`scripts/e2e_shards.mjs`): one SQLite template database copied per shard, a
host per shard, logs in `.e2e-shards/`; `E2E_SHARDS` changes the count. It
runs the default suite only — the opt-in specs (`E2E_MULTI_TENANT=1`,
`E2E_BILLING_USER=1`, `E2E_NEWSLETTER=1`) run through `npx playwright test`
with their variable set.

Three layers cover the code:

1. **Module tests** run from inside each `modules/<name>/` so they pick up
   that module's own pytest config. They use `simple_module_test` fixtures
   and need no host.
2. **Host smoke tests** boot the real app and assert each module's routes and
   menu entries registered — catching wiring breaks isolated tests can't see.
3. **Playwright** drives a browser through login, editing, and publishing.

### `make lint`

In order: `ruff check`, `basedpyright` (scope: `[tool.pyright] include` in
`pyproject.toml` — every `contracts/` package and its callers in other
modules), `biome check`, `make typecheck` (`tsc` over each module's
`tsconfig.json`), then the repo checks in `scripts/`:

| Script | Fails on |
|---|---|
| `check_metadata.py` | a module `pyproject.toml` missing a required field, or root `testpaths` out of step with `modules/*/` |
| `check_rules.py` | an `==` pin in a published module, a non-page file under `pages/`, a sibling requirement without a `>=` floor and `# floor:` comment |
| `check_sibling_contracts.py` | an import of a sibling's anything-but-`contracts`, or of a contract its floor release does not ship (needs `git fetch --tags`) |
| `moved_paths.py --check` | a drifted 0.0.14 moved-path stub, or a repo import of an old path |
| `check_ts_imports.py` | a TS import of another module's internal file instead of its package root |
| `check_readmes.py` | a module README under 500 bytes, without an H1, or without "Install" and "Usage" |
| `check_hardcoded_strings.py` | a permission, role, Inertia page or `depends_on` literal instead of a constant |
| `check_file_size.py` | a `.py`/`.ts`/`.tsx` file over 300 lines (warns from 280) |
| `check_locales.py` | a translation whose keys or placeholders differ from `en.json` |
| `check_migration_heads.py` | more than one Alembic head |
| `bump_version.py --check-current` | a manifest whose version differs from the root's |

### CI

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`:

| Job | What it does |
|---|---|
| Lint (ruff), Lint (biome) | `ruff check` and `basedpyright`; `biome check` |
| Python tests (3.12, 3.14) | every module's suite (`scripts/pytest_modules.sh`) and the host tests, on both interpreters |
| Postgres | migration round trip with `alembic check`, then every module's suite on a database of its own (`scripts/pytest_modules_pg.sh`), and the records perf smoke |
| Frontend build | `sync-module-deps`, `gen-pages`, `make typecheck`, `npm run build` |
| Frontend unit tests | `npx vitest run` |
| Docker image | builds the image and waits for `/health/live` under production settings |
| Background tasks | host, worker and beat against Redis and Postgres; `scripts/bg_tasks_smoke.py` runs an image pipeline and a campaign send |
| E2E shard 1–3, E2E (Playwright) | the bundle suite in three shards; the last job merges their reports and is the one status covering all three |
| E2E (multi-tenant), (billing per user), (newsletter) | the opt-in specs, each in its own job |
| Repo checks | the `scripts/` checks above, and `pytest scripts/tests` |

Two more workflows run on a schedule: `framework-latest.yml` (nightly) runs
every module's tests against the newest framework their ranges allow, and
`images-models.yml` (weekly) installs images' `[anonymize]` extra, downloads
the pinned models and runs the `real_models` tests.

## Adding a module

The full checklist is [docs/adding-a-module.md](docs/adding-a-module.md); the
package's shape is [docs/module-layout.md](docs/module-layout.md). In short:

1. `make new-module name=orders`, then arrange it as `docs/module-layout.md`
   describes.
2. Complete its `pyproject.toml` (the fields `check_metadata.py` wants, the
   repo's version, framework *ranges*) and add `modules/orders/tests` to the
   root `testpaths`.
3. Add it to `host/pyproject.toml` as a dependency with a workspace source.
4. Ship `locales/en.json` and `de.json`, a README with Install and Usage, and
   a `tsconfig.json` if it has a frontend.
5. Read other modules only through their `contracts` (Python) and package root
   (TS).
6. Generate its migration in the host, with `branch_labels = ("orders",)`.
7. Set up PyPI Trusted Publishing before its first release. CI and the release
   matrix pick it up on their own.

## Releasing

Releases are **lockstep**: one version across the repo, one tag, every module
published together. Run the `release` workflow from the Actions tab, on `main`,
with either a `bump` level (`patch`, `minor`, `major`) or an explicit
`version`. It refuses to start unless CI is green on the commit it would ship
(`scripts/release_ci_gate.py`), and waits for CI still running. Then:

1. `resolve` fixes the version and the package list;
2. `build` commits the bump, builds every package, and pushes the commit to a
   `release/v<version>` staging branch;
3. `publish-pypi` uploads each package through Trusted Publishing;
4. `finalize` tags the staged commit, lands the bump on `main`, creates the
   GitHub release and deletes the staging branch.

Changes are recorded as they merge, in `CHANGELOG.md` under the
`## <version> (unreleased)` section at the top. See
[docs/releasing.md](docs/releasing.md) for the failure modes and how to
recover from each.

## Working against an unreleased framework

```bash
make link-framework FRAMEWORK=/path/to/simple_module_python
make unlink-framework
```

`FRAMEWORK` is required and has no default. `link-framework` editable-installs
the framework's `core`, `db`, and `hosting` packages into the workspace venv,
plus the framework modules in `FRAMEWORK_MODULES` (default `branding`;
`FRAMEWORK_MODULES="branding users"` to add more). `unlink-framework` restores
the PyPI versions. Neither touches a tracked file, so a local override cannot
leak into a release.

## Conventions

- **Published modules pin the framework with ranges**
  (`simple_module_core>=0.0.36,<0.1`); the host pins exactly. An `==` pin in a
  module makes it uninstallable in any host running a newer framework.
- **A requirement on another module of this repo has a `>=` floor and a
  `# floor: <reason>` comment** saying what that release first shipped.
- **Modules read each other only through `contracts`.** In Python that is
  `<package>.contracts` (`check_sibling_contracts.py`); in TypeScript it is
  the package root, `@simple-module-py/<module>` (`check_ts_imports.py`).
- **Migrations live in `host/migrations/versions/`**, never in a module, and
  the history ends in exactly one head.
- **`pages/` holds only real Inertia pages** — the page name comes from the
  path. Helpers go in `components/`, `hooks/` or `utils/`.
- **Permissions, roles, page names and module names are constants**, not
  literals (`check_hardcoded_strings.py`).
- **Every `.py`/`.ts`/`.tsx` file stays under 300 lines**, enforced by
  `scripts/check_file_size.py` with no exemptions under `modules/`.
- **Linting.** ruff with `E W F I N UP B SIM C4 RET PTH PIE RUF S`; bandit's
  `S101` (assert) is ignored, and a deliberate case in production code takes
  `# noqa: Sxxx - <reason>`. basedpyright in basic mode over the
  `[tool.pyright] include` list. Biome (lint and format) over the host's
  `client_app`, the modules' frontend folders and `tests/e2e`.
- **Nothing publishes to npm.** Module `package.json` files stay
  `private: true` and ship inside the wheel.

Coding agents: [AGENTS.md](AGENTS.md) has the rules that are easy to get
wrong.

## Security

Report a vulnerability privately through GitHub (the repository's
**Security** tab, *Report a vulnerability*), not in a public issue. See
[SECURITY.md](SECURITY.md).

## Licence

MIT
