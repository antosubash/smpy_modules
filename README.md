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
| `modules/news` | [`simple_module_news`](https://pypi.org/project/simple_module_news/) | News articles backed by page-builder pages — listing API, category/date metadata, translations, and a live feed block |

### Publishing in more than one language

Pages and articles can exist in several languages, each with its own slug,
draft and approval state. Off by default; turn it on in `.env`:

```bash
SM_PAGEBUILDER_CONTENT_LOCALES='["en","de"]'
SM_PAGEBUILDER_DEFAULT_CONTENT_LOCALE=en
```

The default language keeps its existing addresses (`/p/about`, `/news/x`) and
every other one is prefixed (`/de/p/about`, `/de/news/x`), so switching this on
strands no link that already exists. See
[`modules/pagebuilder/README.md`](modules/pagebuilder/README.md#multilingual-content)
for the model and the editor flow.

## Layout

```
├── host/               # demo host — never published
│   ├── main.py
│   ├── client_app/     # Inertia + React + Vite
│   ├── alembic.ini
│   └── migrations/     # every module's migrations live here
├── modules/            # published packages, one per directory
│   └── pagebuilder/
├── tests/e2e/          # Playwright specs against the demo host
├── scripts/            # release + repo-quality tooling
└── .github/workflows/  # ci.yml, release.yml
```

The repo is both a **uv workspace** (members: `host`, `modules/*`) and an
**npm workspace** (`host/client_app`, `modules/*`), so module frontends share
one hoisted `node_modules` and Vite resolves React, Inertia, and
`@simple-module-py/ui` without per-module aliasing.

## Quick start

```bash
make install     # uv sync + npm install
make env         # create .env with a generated SM_SECRET_KEY
make migrate     # apply migrations
make dev         # API on :8000, Vite on :5050
```

Local dev defaults to SQLite at `host/app.db`. See `CLAUDE.md` for using the
shared `dev-services` Postgres instead.

## Testing

```bash
make test-py     # module suites + host smoke tests + release-script tests
make e2e         # Playwright against a real browser
make lint        # ruff, biome, and the repo checks
```

The e2e suite needs a browser once: `npx playwright install chromium --with-deps`.
It resets `host/test.db` on every run and never touches `host/app.db`.

Three layers cover the code:

1. **Module tests** run from inside each `modules/<name>/` so they pick up
   that module's own pytest config. They use `simple_module_test` fixtures
   and need no host.
2. **Host smoke tests** boot the real app and assert each module's routes and
   menu entries registered — catching wiring breaks isolated tests can't see.
3. **Playwright** drives a browser through login, editing, and publishing.

## Adding a module

See [docs/adding-a-module.md](docs/adding-a-module.md). In short:

```bash
make new-module name=orders
```

then wire it into `host/pyproject.toml`, add it to the release matrix, and
generate its migration.

## Releasing

Releases are **lockstep**: one version across the repo, one tag, every module
published together. Run the `release` workflow from the Actions tab and pick a
bump level. See [docs/releasing.md](docs/releasing.md).

## Working against an unreleased framework

```bash
make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python
make unlink-framework
```

`link-framework` editable-installs the framework's `core`, `db`, and `hosting`
packages into the workspace venv; `unlink-framework` restores the PyPI
versions. Neither touches a tracked file, so a local override cannot leak into
a release.

## Conventions

- **Published modules pin the framework with ranges**
  (`simple_module_core>=0.0.25,<0.1`); the host pins exactly. An `==` pin in a
  module makes it uninstallable in any host running a newer framework.
- **Migrations live in `host/migrations/versions/`**, never in a module.
- **Every `.py`/`.ts`/`.tsx` file stays under 300 lines**, enforced by
  `scripts/check_file_size.py` with no exemptions under `modules/`.
- **Nothing publishes to npm.** Module `package.json` files stay
  `private: true` and ship inside the wheel.

## Licence

MIT
