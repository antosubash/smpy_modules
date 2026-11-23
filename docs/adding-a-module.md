# Adding a module

Every step below is required unless it says otherwise. Most are enforced by
`make lint` or CI and fail loudly; the ones that do not (the menu entry, the
public-route exemption, PyPI Trusted Publishing) are called out.

The examples add a module called `orders` with the Python package `sm_orders`.
Newer modules use an `sm_` package name (`sm_images`, `sm_records`); the
directory under `modules/` is the module's name, and it is also its locale
namespace and its npm name (`@simple-module-py/orders`).

## 1. Scaffold it

```bash
make new-module name=orders
```

This runs `smpy create-module orders --dest modules/orders`. It deliberately
omits `--standalone`: GitHub only runs workflows from the repository-root
`.github/workflows/`, so a nested per-module workflow would never fire, and a
nested `publish.yml` is a publish footgun.

The scaffold names the Python package after the module (`orders`). This guide,
like every module here, uses an `sm_` prefix (`sm_orders`) so the import name
cannot collide with another distribution: rename the package directory and its
imports right after scaffolding, or keep `orders` and read the examples with
that name.

The scaffold is flat. Organise the package and its tests from the start as
[module layout](module-layout.md) describes, with `modules/images` as the
reference: `core/`, `web/`, one folder per domain, `ui/` for frontend code that
is not a page, tests mirroring those areas under `tests/`, and nothing at the
package root that is not looked up by name.

## 2. Complete its metadata

`scripts/check_metadata.py` (in `make lint` and CI) requires all of these in
`modules/orders/pyproject.toml`:

```toml
[project]
name = "simple_module_orders"     # must start with simple_module_
version = "0.0.15"                # the repo's current version
description = "..."               # not empty, not the scaffold placeholder
requires-python = ">=3.12"
readme = "README.md"
license = "MIT"
keywords = ["simple-module", ...] # must include "simple-module"

[project.urls]
Repository = "https://github.com/antosubash/smpy_modules"
```

**Version.** Releases are lockstep, so `version` is the root
`pyproject.toml`'s (and so is `package.json`'s). `scripts/bump_version.py
--check-current` fails when a manifest drifts; from then on, only
`bump_version.py` (run by the release) edits it.

**Framework dependencies are ranges, never `==`** — `scripts/check_rules.py`
refuses an exact pin, because it makes the module uninstallable in any host
running a newer framework build:

```toml
dependencies = [
    "simple_module_core>=0.0.44,<0.1",
    "simple_module_db>=0.0.44,<0.1",
    "simple_module_hosting>=0.0.44,<0.1",
    "simple_module_inertia>=0.0.44,<0.1",
    "simple_module_settings>=0.0.44,<0.1",
    "pydantic-settings>=2.0",
]
```

Since framework 0.0.44 most framework modules follow the module layout (the old
flat paths are gone since 0.0.46); import the new paths, and set the floor to the release that first shipped the path
you import. `host/tests/test_host_boots.py` fails on an import the installed
framework marks deprecated.

**Sibling modules.** A requirement on another module of this repo (usually an
optional extra) needs a `>=` floor and a `# floor: <reason>` comment (and, by
convention, a `<0.1` ceiling; the check enforces only the floor and comment), on its line or directly above it, naming what that release first
shipped (`check_rules.py`):

```toml
[project.optional-dependencies]
# floor: 0.0.16 - pagebuilder.contracts.site first shipped in 0.0.16.
pagebuilder = ["simple_module_pagebuilder>=0.0.16,<0.1"]
```

`check_sibling_contracts.py` then reads every `<sibling>.contracts` import in
the module and checks it exists at tag `v<floor>` (or in the working tree, for
a floor that is the release being prepared). It needs the tags:
`git fetch --tags`. Raise the floor and its comment together when the module
starts using something newer.

**Entry point and build.** The entry point is how a host discovers the module.
If the module has a frontend, `package.json` is copied into the package so a
host can find its JS dependencies after a `pip install`. Frontend tests and
their helpers sit beside the source, so the wheel excludes them; a stray
`vitest` import in an installed module breaks a host's Vite pre-bundling. A
module that builds its own bundle into the gitignored `<package>/static/dist/`
pulls it back with `artifacts` (a force-include would fail on a clean checkout
where the path is absent). As in `modules/images/pyproject.toml`:

```toml
[project.entry-points.simple_module]
orders = "sm_orders.module:OrdersModule"

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "simple_module_test>=0.0.44,<0.1"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["sm_orders"]
exclude = [
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/__tests__/**",
    "**/test-dom.tsx",
    "**/*-test-support.ts",
    "**/page-tests/**",
]
artifacts = ["sm_orders/static/dist/**"]   # only with a built bundle

[tool.hatch.build.targets.wheel.force-include]
"package.json" = "sm_orders/package.json"

[tool.hatch.build.targets.sdist]
artifacts = ["sm_orders/static/dist/**"]   # only with a built bundle

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

## 3. Register its tests

Add `modules/orders/tests` to `testpaths` in the root `pyproject.toml`.
`check_metadata.py` fails until the list matches `modules/*/` exactly. Nothing
else needs editing: `make test-py`, `scripts/pytest_modules.sh` (CI's Python
3.12 and 3.14 legs) and `scripts/pytest_modules_pg.sh` (CI's Postgres job, one
database per module) all loop over `modules/*/`. Tests run from inside the
module directory, under pytest-xdist, so a test must not write under the
working directory or share state with another worker.

## 4. Wire it into the host

In `host/pyproject.toml`, add the dependency and a workspace source:

```toml
dependencies = [
    ...
    "simple_module_orders",
]

[tool.uv.sources.simple_module_orders]
workspace = true
```

Then `make install`. Optionally add the module's display name (the `name` its module class declares,
as in `"PageBuilder"`) to `REPO_MODULES` in
`host/tests/test_host_boots.py` and assert its routes there, the way the other
modules do.

## 5. Keep magic strings in constants

`scripts/check_hardcoded_strings.py` refuses, outside tests and
`constants.py`, a literal permission in `RequiresPermission(...)` or
`registry.add_group(...)`, a role name in `registry.map_role(...)`, a page
name in `inertia.render(...)` and a module name in `depends_on=[...]`. Put
them in `sm_orders/core/constants.py` as `PERM_*`, `ROLE_*`, `_PAGE_*` and
`_MODULE_*` (see `modules/analytics/sm_analytics/core/constants.py`).

## 6. Settings come from the database

Settings are DB-backed through the framework's settings module, never the
environment. Subclass `DbBackedSettings` (`simple_module_core.settings_base`),
which drops pydantic-settings' env, `.env` and secrets sources, and register it
in the module's `register_settings` with `register_module_settings`. A field is
added to the class, never to `.env.example`. A value the module reads while
booting (a route prefix, a mount) must be read from `app.state` in
`on_startup`, because hydration happens at lifespan start, and its field is
marked `json_schema_extra={"requires_restart": True}`. A stored secret is never
a plain `str`: copy the stored-secret crypto (`core/crypto.py`, see section 11)
or records' `SealedSecret`.

## 7. Tenancy

If the module's tables carry `MultiTenantMixin`, every entry point binds a
tenant, because the framework filters those tables only while one is bound
(and on a single-tenant host nothing is bound, so a read is unfiltered).
Copy images' `sm_images/core/tenancy/` rather than writing a new one: routers
get `bind_admin` / `bind_public` (single-tenant host → `"default"`;
multi-tenant → the tenant the framework resolved; none → 403
`tenant_required` for admin, 404 for public), background work runs under
`tenant_scope`, and `install_guard` installs the fail-closed guard that raises
on ORM work with no tenant bound. A deliberate cross-tenant read is tagged with
`all_tenants(...)`. Add the copy to the tenancy parity families (section 11).

## 8. Read other modules only through their contracts

In Python, a module imports a sibling only as `<package>.contracts`
(`from sm_records.contracts import ...`, or an `import_module` string);
`check_sibling_contracts.py` fails on any other path into a sibling. If the
module offers something to others, put it in its own `contracts/` package and
add that package to `[tool.pyright] include` in the root `pyproject.toml`, with
any caller in another module, so `basedpyright` checks the signatures at both
ends.

In TypeScript a module is public only through its package root,
`@simple-module-py/orders`, which `package.json` names with `exports`:

```json
{
  "name": "@simple-module-py/orders",
  "version": "0.0.15",
  "private": true,
  "exports": { ".": "./sm_orders/index.ts" },
  "peerDependencies": { "@simple-module-py/ui": ">=0.0.38", "react": "^19.3.1" },
  "devDependencies": { "@simple-module-py/tsconfig": "*" }
}
```

`scripts/check_ts_imports.py` refuses `@simple-module-py/<module>/<file>`, a
module root with neither `exports` nor `main`, and a relative path into
another module's directory. `private: true` stays: nothing publishes to npm,
and an exact `@simple-module-py/*` pin is refused like a Python one.

## 9. Frontend

- **`pages/` holds only real Inertia pages.** The page name comes from the
  path (`import.meta.glob`), so `check_rules.py` fails on any file there that
  is not a `.tsx` with `export default`. Helpers go in `components/`,
  `hooks/` or `utils/` (under `ui/` in the module layout).
- **`tsconfig.json`** at the module root, so `make typecheck` (part of
  `make lint`, and CI's frontend build) runs `tsc` over the module:

  ```json
  {
    "extends": "@simple-module-py/tsconfig/base.json",
    "compilerOptions": { "resolveJsonModule": true },
    "include": ["sm_orders/**/*.ts", "sm_orders/**/*.tsx"]
  }
  ```

- **Biome** checks `pages/`, `components/`, `hooks/`, `utils/` and `ui/`.
- **Pagebuilder blocks**, if any, register from `pagebuilder-blocks.ts` at the
  package root, which pagebuilder globs from every installed module; declare
  `@simple-module-py/pagebuilder` an optional peer dependency.

## 10. Locales

Ship `sm_orders/locales/en.json` and `de.json` and route every UI string
through `t()`. `scripts/check_locales.py` fails when `de.json`'s key tree or
placeholders differ from `en.json`, when a translation is blank, or when any
string carries a Markdown code span (the console shows the backticks). Add a
key to both catalogues at once.

The npm `@simple-module-py/i18n` package does not know the module's keys, so
derive them from the module's own `en.json` at compile time: copy
`modules/news/news/ui/utils/i18n.ts`, the reference implementation. Puck block
labels hold the key and are resolved at render (each module's
`localizeConfig.ts`).

## 11. Copied helpers stay in step

When the module copies a helper another module already has (tenancy, the
stored-secret crypto, public cache headers, …), add the copy to its family in
`scripts/tests/parity_families.py`, `parity_tenancy.py` or `parity_crypto.py`.
`scripts/tests/test_helper_parity.py` (in `make test-py` and CI's repo checks)
then fails when the copies drift. A stored-secret field also goes in
`reencrypt_support.TARGETS`, so `scripts/reencrypt_secrets.py` rotates it.

## 12. Wire it into the UI and the auth layer

Two hooks are easy to forget because nothing fails loudly without them:

**`register_menu_items`** — without it the module boots and its routes work,
but nothing links to them. Menu role filtering is a plain intersection with no
admin bypass: listing roles hides the entry from an `admin` user unless
`"admin"` is among them. Leave `roles` empty when the views are auth-gated
rather than permission-gated.

**`register_public_routes`** — `AuthMiddleware` gates *every* request. Any
route meant for anonymous visitors (a public viewer, sitemap, robots, a
webhook) must be exempted here or it 302s to the login page. Two traps:

- Rules match with `startswith`, so terminate directory prefixes with `/`.
  A bare `/p` also matches `/pagebuilder/` — that hands your whole admin UI
  to anonymous visitors.
- Pin the methods (`{"GET", "HEAD"}`) so the exemption can't widen later.

Playwright specs run authenticated and will not catch a missing exemption.
Assert on the registry directly — see
`modules/pagebuilder/tests/web/test_public_routes.py`.

## 13. Write its README

`scripts/check_readmes.py` requires `modules/orders/README.md` with an H1, at
least 500 bytes, and the words "Install" and "Usage". Cover what the module
does, installation, its settings and permissions, and its routes; put longer
guides in `modules/orders/docs/`.

## 14. Generate its migration

Migrations live in the host, never in the module:

```bash
make migration msg="add orders"
```

Open the generated revision in `host/migrations/versions/` and add the branch
label under the identifiers:

```python
branch_labels = ("orders",)
```

The label only names the revision; `alembic downgrade orders@base` walks every
revision beneath it, not just this module's. Read the rest of the file —
confirm it creates your tables and drops nothing — and apply it with
`make migrate`. The history must end in one head: if another branch added a
revision off the same parent, `scripts/check_migration_heads.py` fails until an
empty `alembic merge heads` revision joins them. CI's Postgres job runs the
upgrade, a downgrade to base and `alembic check`.

## 15. CI, Docker and the release pick it up

Nothing to edit. CI's pytest steps loop over `modules/*/`, the Dockerfile
copies every `modules/*/pyproject.toml` and `package.json`, and the release's
`resolve` job builds the `publish-pypi` matrix from every
`modules/*/pyproject.toml`'s `project.name`.

The one manual step: before the module's first release, add a Trusted Publisher
on <https://pypi.org/manage/account/publishing/> with the values in the header
comment of `.github/workflows/release.yml` (project `simple_module_orders`,
owner `antosubash`, repository `smpy_modules`, workflow `release.yml`,
environment `pypi`). Publishing uses OIDC, so no API
token is needed, but without this the first release fails at that module's
publish.

## 16. Verify

```bash
make lint
make test
make build
```

`make lint` runs ruff, basedpyright, biome, `make typecheck` and every
`scripts/check_*.py` named above, plus `moved_paths.py --check` and
`bump_version.py --check-current`.
