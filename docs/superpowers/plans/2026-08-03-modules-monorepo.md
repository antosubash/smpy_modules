# simple_module_python_modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the empty `simple_module_python_modules` repo into a uv + npm workspace that publishes distributable SimpleModule add-ons to PyPI, with a runnable demo host, and `pagebuilder` ported out of `smpy_pagebuilder` as the first module.

**Architecture:** A dual workspace (uv members `host` + `modules/*`; npm workspaces `host/client_app` + `modules/*`), the layout `smpy new` produces. `host/` is an unpublished demo app that mounts every module and owns all alembic migrations. Each `modules/<name>/` is an independently importable Python package published to PyPI, discovered at runtime through the `simple_module` entry point. Releases are lockstep — one version, one tag, all modules.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLModel, alembic, Inertia.js + React 19, Vite, Puck (`@measured/puck`), Pillow, pytest + pytest-asyncio, Playwright, ruff, biome, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-03-modules-monorepo-design.md`

## Global Constraints

- **Python:** `requires-python = ">=3.12"` everywhere. `.python-version` is `3.12`.
- **Published modules pin the framework with ranges:** `simple_module_core>=<FW>,<0.1` (same for `_db`, `_hosting`). Never `==`.
- **The host pins exactly:** `simple_module_hosting==<FW>` (same for `_auth`, `_users`, `_dashboard`, `_permissions`).
- `<FW>` is the **latest published** framework version on PyPI, resolved in Task 1 Step 2. The framework repo says `0.0.24`; confirm against PyPI rather than assuming.
- **`ModuleMeta.requires_framework=">=1.0,<2.0"` is correct and stays.** `FRAMEWORK_API_VERSION` is `"1.0.0"` and is decoupled from the package version.
- **Migrations live in `host/migrations/versions/` only.** No module ships migrations.
- **No new files under any `modules/*/<pkg>/pages/` directory.** Inertia page names are derived from that path by `import.meta.glob` — a new file there silently registers a new page. Extractions go to `components/`, `hooks/`, or `utils/`.
- **Max 300 lines** per `.py` / `.ts` / `.tsx` file, enforced by `scripts/check_file_size.py` from Task 5 onward.
- **Module `package.json` stays `private: true`.** Nothing publishes to npm from this repo.
- **Never commit a real secret.** `.env.example` carries placeholders only.
- **Source repos are read-only.** `/Volumes/ext1/GitHub/smpy_pagebuilder` and `/Volumes/ext1/GitHub/simple_module_python` are copy sources. Never modify them.

**Path shorthand used below:**
- `$SRC` = `/Volumes/ext1/GitHub/smpy_pagebuilder`
- `$FW` = `/Volumes/ext1/GitHub/simple_module_python`

---

### Task 1: Workspace root + demo host

Produces a bootable app with `users` + `dashboard` + `permissions` and no custom modules. Everything later builds on this.

**Files:**
- Create: `pyproject.toml`, `package.json`, `.python-version`, `biome.json`, `LICENSE`, `.env.example`, `Makefile`
- Create: `host/main.py`, `host/pyproject.toml`, `host/alembic.ini`, `host/migrations/env.py`, `host/migrations/script.py.mako`, `host/migrations/versions/.gitkeep`
- Create: `host/client_app/{main.tsx,app.tsx,pages.ts,styles.css,package.json,tsconfig.json,vite.config.ts}`, `host/client_app/pages/Error.tsx`, `host/templates/index.html`
- Create: `host/tests/test_host_boots.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: a uv workspace whose members are `host` and `modules/*`; an npm workspace over `host/client_app` and `modules/*`. Later tasks add `modules/pagebuilder` and rely on `make install`, `make dev`, `make migrate`, `make gen-pages`, `make sync-module-deps` existing.

- [ ] **Step 1: Copy the host scaffold and root config from the source app**

```bash
cd /Volumes/ext1/emdash/worktrees/simple_module_python_modules/features/init-i8ghw
SRC=/Volumes/ext1/GitHub/smpy_pagebuilder

mkdir -p host/migrations/versions host/client_app/pages host/templates host/tests

cp "$SRC"/host/main.py host/
cp "$SRC"/host/alembic.ini host/
cp "$SRC"/host/migrations/env.py host/migrations/
cp "$SRC"/host/migrations/script.py.mako host/migrations/
touch host/migrations/versions/.gitkeep
cp "$SRC"/host/client_app/*.ts "$SRC"/host/client_app/*.tsx \
   "$SRC"/host/client_app/*.css "$SRC"/host/client_app/*.json host/client_app/
cp "$SRC"/host/client_app/pages/Error.tsx host/client_app/pages/
cp "$SRC"/host/templates/index.html host/templates/
cp "$SRC"/.python-version . 2>/dev/null || echo "3.12" > .python-version
cp "$FW"/biome.json . 2>/dev/null || true
cp "$SRC"/LICENSE .
```

If `$SRC/.python-version` does not exist, the fallback already wrote `3.12`. If `$FW/biome.json` was not copied, create it in Step 5.

- [ ] **Step 2: Resolve the framework version**

```bash
uv pip index versions simple_module_core 2>/dev/null | head -3
```

Take the highest released version. Export it for the rest of the task and record it in the plan's Global Constraints if it differs from `0.0.24`:

```bash
FWVER=0.0.24   # replace with the version printed above
echo "$FWVER"
```

- [ ] **Step 3: Write the root `pyproject.toml`**

Substitute `<FW>` with `$FWVER` from Step 2.

```toml
[project]
name = "simple-module-python-modules"
version = "0.1.0"
description = "Distributable modules for simple_module_python applications"
requires-python = ">=3.12"
dependencies = []

# Workspace root: not built or installed itself.
[tool.uv]
package = false

[tool.uv.workspace]
members = ["host", "modules/*"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.8",
    "tomlkit>=0.13",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP", "B", "SIM", "C4", "RET", "PTH", "PIE", "RUF"]
ignore = [
    "B008",   # Depends() in default args is idiomatic FastAPI
    "B027",   # Empty methods in ABC without @abstractmethod — optional hooks
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["host/tests"]
addopts = "--durations=20"
```

`testpaths` gains `modules/pagebuilder/tests` in Task 2.

- [ ] **Step 4: Write the root `package.json`**

```json
{
  "name": "simple-module-python-modules",
  "private": true,
  "type": "module",
  "workspaces": [
    "host/client_app",
    "modules/*"
  ],
  "scripts": {
    "dev": "npm run --workspace host/client_app dev",
    "build": "npm run --workspace host/client_app build",
    "lint": "biome check .",
    "format": "biome format --write .",
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui",
    "test:e2e:headed": "playwright test --headed"
  },
  "devDependencies": {
    "@biomejs/biome": "^2.4.11",
    "@playwright/test": "^1.60.0",
    "@types/node": "^22.0.0"
  }
}
```

- [ ] **Step 5: Write `biome.json` if Step 1 did not copy one**

```json
{
  "$schema": "https://biomejs.dev/schemas/2.4.11/schema.json",
  "files": {
    "includes": ["**", "!**/node_modules/**", "!**/dist/**", "!**/.venv/**"]
  },
  "formatter": { "enabled": true, "indentStyle": "space", "indentWidth": 2, "lineWidth": 100 },
  "linter": { "enabled": true, "rules": { "recommended": true } },
  "javascript": { "formatter": { "quoteStyle": "single" } }
}
```

- [ ] **Step 6: Write `host/pyproject.toml`**

Substitute `<FW>`.

```toml
[project]
name = "smpy-modules-host"
version = "0.1.0"
description = "Demo host mounting every module in this repo"
requires-python = ">=3.12"
dependencies = [
    "simple_module_hosting==<FW>",
    "simple_module_auth==<FW>",
    "simple_module_users==<FW>",
    "simple_module_dashboard==<FW>",
    "simple_module_permissions==<FW>",
]

# Host is an application, not a distributable package.
[tool.uv]
package = false

[dependency-groups]
dev = [
    "simple_module_test==<FW>",
    "simple-module-cli==<FW>",
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "aiosqlite>=0.20",
    "alembic>=1.13",
    "psycopg2-binary>=2.9",
]
```

- [ ] **Step 7: Write `.env.example` with placeholders only**

```bash
# Environment: development | production
SM_ENVIRONMENT=development

# Secret key for session middleware. Generate your own:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
SM_SECRET_KEY=replace-me-with-a-generated-secret

# Database — SQLite by default. For the shared dev-services Postgres use:
#   postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules
SM_DATABASE_URL=sqlite+aiosqlite:///./host/app.db

SM_MULTI_TENANT=false

# Vite dev server URL (development only).
SM_VITE_DEV_URL=http://localhost:5050

# Optional: JSON array restricting which installed modules load at boot.
# SM_MODULES_ENABLED=["Auth","Users","PageBuilder"]

# First-boot admin seed. Only applied when the users table is empty.
# SM_USERS_BOOTSTRAP_EMAIL=admin@example.com
# SM_USERS_BOOTSTRAP_PASSWORD=changeme
```

Do **not** copy `$SRC/.env.example` verbatim — it contains a committed `SM_SECRET_KEY`.

- [ ] **Step 8: Write the `Makefile`**

```makefile
.PHONY: install install-py install-js dev dev-api dev-ui build gen-pages sync-module-deps \
        migrate migration downgrade test test-py test-js e2e lint kill \
        link-framework unlink-framework new-module env

install: install-py install-js sync-module-deps

install-py:
	uv sync --all-packages --all-extras

install-js:
	npm install

dev: gen-pages
	@echo "Starting API and UI dev servers..."
	$(MAKE) -j2 dev-api dev-ui

dev-api:
	cd host && uv run uvicorn main:app --reload --port 8000

dev-ui:
	npm run dev

build:
	npm run build

# Regenerate host/client_app/modules.{manifest.json,generated.ts,generated.css}
# from installed modules (workspace + wheel-installed).
gen-pages:
	cd host && uv run python -m simple_module_hosting gen-pages --host-dir=client_app

# Pull JS deps shipped by wheel-installed modules into host/client_app/node_modules.
# Workspace modules under modules/* don't need this — npm hoists them automatically.
sync-module-deps:
	cd host && uv run python -m simple_module_hosting sync-js-deps --host-client-app=client_app

migrate:
	cd host && uv run alembic upgrade heads

migration:
	@test -n "$(msg)" || (echo 'Usage: make migration msg="describe the change"' && exit 1)
	cd host && uv run alembic revision --autogenerate -m "$(msg)"

downgrade:
	cd host && uv run alembic downgrade -1

test: test-py test-js

test-py:
	uv run pytest host/tests
	@for d in modules/*/; do \
	  if [ -d "$$d/tests" ]; then echo "--- pytest $$d"; (cd "$$d" && uv run pytest) || exit 1; fi \
	done

test-js:
	npm run --workspace host/client_app test --if-present

e2e:
	npm run test:e2e

lint:
	uvx ruff check .
	npx biome check .
	uv run python scripts/check_metadata.py
	uv run python scripts/check_readmes.py
	uv run python scripts/check_hardcoded_strings.py
	uv run python scripts/check_file_size.py
	uv run python scripts/bump_version.py --check-current

env:
	@test -f .env || (cp .env.example .env && \
	  python3 -c "import re,pathlib,secrets; p=pathlib.Path('.env'); \
	  p.write_text(p.read_text().replace('replace-me-with-a-generated-secret', secrets.token_urlsafe(32)))" && \
	  echo ".env created with a generated SM_SECRET_KEY")

# Develop against an unreleased framework checkout.
#   make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python
link-framework:
	@test -n "$(FRAMEWORK)" || (echo 'Usage: make link-framework FRAMEWORK=/path/to/simple_module_python' && exit 1)
	uv pip install -e $(FRAMEWORK)/framework/core \
	               -e $(FRAMEWORK)/framework/db \
	               -e $(FRAMEWORK)/framework/hosting
	@echo "Framework linked. Run 'make unlink-framework' to restore PyPI versions."

unlink-framework:
	uv sync --all-packages --all-extras --reinstall
	@echo "Restored PyPI framework versions."

new-module:
	@test -n "$(name)" || (echo 'Usage: make new-module name=orders' && exit 1)
	uv run smpy create-module $(name) --dest modules/$(name)
	@echo "Now add simple_module_$(name) to host/pyproject.toml dependencies and"
	@echo "[tool.uv.sources] simple_module_$(name) = { workspace = true }"

kill:
	@-pkill -f "uvicorn main:app" 2>/dev/null
	@-pkill -f vite 2>/dev/null
	@-lsof -ti:8000,5050 | xargs kill -9 2>/dev/null
	@echo "Ports 8000, 5050 freed."
```

`scripts/check_*.py` and `bump_version.py` arrive in Tasks 5 and 7 — `make lint` is not expected to pass until then. `make install`, `make dev`, `make migrate` must work at the end of this task.

- [ ] **Step 9: Extend `.gitignore`**

Append to the existing file:

```gitignore
# Python
.venv/
__pycache__/
*.pyc

# Node
node_modules/
dist/

# Built module frontend bundles (force-included into wheels at build time)
modules/*/*/static/dist/

# Local databases
host/*.db

# Env
.env

# Playwright
playwright-report/
test-results/
```

- [ ] **Step 10: Write the host smoke test (it will fail — nothing is installed yet)**

Create `host/tests/test_host_boots.py`:

```python
"""Smoke tests: the demo host boots and mounts its modules.

These catch wiring breaks (missing dependency, entry point typo, route
prefix collision) that module-level tests can't see because they build a
minimal app instead of the real host.
"""

from __future__ import annotations

import pytest
from simple_module_hosting import Settings, create_app


@pytest.fixture
def app():
    return create_app(Settings())


def test_app_boots(app):
    assert app is not None


def test_core_modules_registered(app):
    names = {m.meta.name for m in app.state.modules}
    assert {"Auth", "Users", "Dashboard", "Permissions"} <= names


def test_openapi_schema_generates(app):
    schema = app.openapi()
    assert schema["openapi"].startswith("3.")
```

`app.state.modules` is the framework's registry of booted modules. If the attribute name differs in the installed framework version, read `simple_module_hosting/app_builder.py` in the synced `.venv` and use the real one — do not guess.

- [ ] **Step 11: Install and run the smoke test**

```bash
make install
make env
uv run pytest host/tests -v
```

Expected: PASS. If `test_core_modules_registered` fails on the `app.state` attribute, fix the test against the installed framework as noted in Step 10.

- [ ] **Step 12: Generate the baseline migration for the framework tables**

```bash
make migration msg="initial"
```

Open the generated file under `host/migrations/versions/` and read it before committing — confirm it creates the auth/users/permissions tables and drops nothing. Then:

```bash
make migrate
```

Expected: `alembic upgrade heads` completes and `host/app.db` exists.

- [ ] **Step 13: Verify the app actually runs**

```bash
make gen-pages
npm run build
```

Expected: `gen-pages` writes `host/client_app/modules.generated.ts` and `modules.manifest.json`; `npm run build` completes typecheck + vite build with no errors.

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "Add workspace root and demo host

uv workspace (host + modules/*) and npm workspace (host/client_app +
modules/*), demo host mounting auth/users/dashboard/permissions, baseline
migration, and the Makefile driving install/dev/migrate/lint."
```

---

### Task 2: Port pagebuilder verbatim

A behaviour-preserving move. No renames, no restructuring, no cleanup — those are Tasks 3 and 5. Keeping this task a pure copy is what makes the next two reviewable.

**Files:**
- Create: `modules/pagebuilder/` (whole tree copied from `$SRC/modules/pagebuilder/`)
- Modify: `host/pyproject.toml` (add dependency + `[tool.uv.sources]`)
- Modify: `pyproject.toml` (add `modules/pagebuilder/tests` to `testpaths`)

**Interfaces:**
- Consumes: the workspace and host from Task 1.
- Produces: `modules/pagebuilder/pagebuilder/` importable as `pagebuilder`, exposing `PagebuilderModule` via the `simple_module` entry point; 18 pytest files under `modules/pagebuilder/tests/`.

- [ ] **Step 1: Copy the module tree**

```bash
SRC=/Volumes/ext1/GitHub/smpy_pagebuilder
mkdir -p modules
cp -R "$SRC"/modules/pagebuilder modules/pagebuilder
find modules/pagebuilder -name '__pycache__' -type d -prune -exec rm -rf {} +
find modules/pagebuilder -name '.DS_Store' -delete
mkdir -p modules/pagebuilder/pagebuilder/static/dist
```

`static/dist` is gitignored but must exist for the editable install — `[tool.hatch.build.targets.wheel.force-include]` references it.

- [ ] **Step 2: Repin the framework dependencies**

In `modules/pagebuilder/pyproject.toml`, replace the three `==0.0.12` pins with ranges (`<FW>` from Task 1 Step 2) and the dev pin with the exact framework version:

```toml
dependencies = [
    "simple_module_core>=<FW>,<0.1",
    "simple_module_db>=<FW>,<0.1",
    "simple_module_hosting>=<FW>,<0.1",
    "pydantic-settings>=2.0",
    "sqlalchemy>=2.0",
    "sqlmodel>=0.0.21",
    "Pillow>=10.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "simple_module_test>=<FW>,<0.1"]
```

- [ ] **Step 3: Wire the module into the host**

In `host/pyproject.toml`, add `"simple_module_pagebuilder"` to `dependencies` and append:

```toml
[tool.uv.sources.simple_module_pagebuilder]
workspace = true
```

In the root `pyproject.toml`, change `testpaths` to:

```toml
testpaths = ["host/tests", "modules/pagebuilder/tests"]
```

- [ ] **Step 4: Install and run the ported tests**

```bash
make install
cd modules/pagebuilder && uv run pytest -v; cd ../..
```

Expected: all 18 test files pass. Failures here are import-path or framework-API drift between `0.0.12` and `<FW>` — fix them in the module, and note each fix in the commit message so the behaviour delta is visible.

- [ ] **Step 5: Verify the module boots inside the host**

Add to `host/tests/test_host_boots.py`:

```python
def test_pagebuilder_registered(app):
    names = {m.meta.name for m in app.state.modules}
    assert "PageBuilder" in names


def test_pagebuilder_routes_mounted(app):
    paths = {r.path for r in app.routes}
    assert "/api/pagebuilder/pages" in paths
```

Run:

```bash
uv run pytest host/tests -v
```

Expected: PASS.

- [ ] **Step 6: Generate the pagebuilder migration**

```bash
make migration msg="add pagebuilder"
```

Open the generated file. Add the branch label under the revision identifiers so the module can be downgraded independently:

```python
branch_labels = ("pagebuilder",)
```

Read the rest of the file — it must create the pagebuilder tables and drop nothing. Then:

```bash
make migrate
```

- [ ] **Step 7: Verify the frontend builds**

```bash
make gen-pages
npm install
npm run build
```

Expected: `modules.generated.ts` now includes a `PageBuilder` entry; the vite build resolves `@measured/puck` through the npm workspace and completes.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Port pagebuilder module from smpy_pagebuilder

Verbatim move of modules/pagebuilder with framework pins widened to
ranges. Migrations regenerated as a single squashed baseline with the
pagebuilder branch label rather than replaying the source app's 10
incremental revisions."
```

---

### Task 3: Modernize pagebuilder packaging and conventions

**Files:**
- Modify: `modules/pagebuilder/pyproject.toml`
- Create: `modules/pagebuilder/pagebuilder/py.typed`
- Create: `modules/pagebuilder/pagebuilder/constants.py`
- Create: `modules/pagebuilder/pagebuilder/contracts/__init__.py`
- Move: `modules/pagebuilder/pagebuilder/schemas.py` → `modules/pagebuilder/pagebuilder/contracts/schemas.py`
- Modify: `modules/pagebuilder/pagebuilder/module.py`, `endpoints/*.py`, `service.py`, `media_service.py`, `layout_service.py`, `permissions.py`, `deps.py` (import updates + constant usage)
- Modify: `modules/pagebuilder/README.md`

**Interfaces:**
- Consumes: the ported module from Task 2.
- Produces: `pagebuilder.contracts.schemas` as the public DTO surface; `pagebuilder.constants` exporting `PACKAGE`, `PERM_*`, `_PAGE_*`, `_MODULE_*`; `ModuleMeta.version` sourced from installed package metadata.

- [ ] **Step 1: Complete the package metadata**

In `modules/pagebuilder/pyproject.toml`, the `[project]` table must carry all of these — `scripts/check_metadata.py` (Task 5) enforces every one:

```toml
[project]
name = "simple_module_pagebuilder"
version = "0.1.0"
description = "Drag-and-drop visual page builder for simple_module apps"
readme = "README.md"
license = "MIT"
authors = [{ name = "Anto Subash", email = "antosubash@live.com" }]
keywords = ["simple-module", "pagebuilder", "cms", "puck"]
requires-python = ">=3.12"

[project.urls]
Repository = "https://github.com/antosubash/simple_module_python_modules"
```

- [ ] **Step 2: Add `py.typed`**

```bash
touch modules/pagebuilder/pagebuilder/py.typed
```

Hatchling includes package data under `packages = ["pagebuilder"]` automatically, so no `pyproject.toml` change is needed.

- [ ] **Step 3: Move schemas into `contracts/`**

```bash
mkdir -p modules/pagebuilder/pagebuilder/contracts
git mv modules/pagebuilder/pagebuilder/schemas.py \
       modules/pagebuilder/pagebuilder/contracts/schemas.py
```

Create `modules/pagebuilder/pagebuilder/contracts/__init__.py`:

```python
"""Public contract surface for the PageBuilder module.

Consumers import DTOs from here. Everything else in the package is
internal and may change without a major version bump.
"""

from pagebuilder.contracts.schemas import *  # noqa: F401,F403
```

If `schemas.py` has no `__all__`, add one listing every DTO it defines rather than relying on the star import to pick the right names.

Update every importer:

```bash
grep -rln "from pagebuilder.schemas\|from pagebuilder import schemas" modules/pagebuilder \
  | xargs sed -i '' 's/from pagebuilder\.schemas/from pagebuilder.contracts.schemas/g'
grep -rn "pagebuilder\.schemas" modules/pagebuilder
```

The final `grep` must print nothing.

- [ ] **Step 4: Run the tests — they must still pass**

```bash
cd modules/pagebuilder && uv run pytest -v; cd ../..
```

Expected: PASS. A failure here is an import that the `sed` missed.

- [ ] **Step 5: Extract magic strings into `constants.py`**

Create `modules/pagebuilder/pagebuilder/constants.py`. Fill in the real values by reading `permissions.py`, `module.py`, and `endpoints/views.py` — the names below are the required shape, the values must match what the code uses today:

```python
"""Named constants for strings the framework's lint rules require to be declared.

`scripts/check_hardcoded_strings.py` rejects inline literals in
`RequiresPermission(...)`, `registry.map_role(...)`, `registry.add_group(...)`,
`inertia.render(...)`, and `ModuleMeta.depends_on`.
"""

from __future__ import annotations

PACKAGE = "pagebuilder"

# Permissions — must match the strings registered in register_permissions().
PERM_PAGE_VIEW = "pagebuilder.page_view"
PERM_PAGE_EDIT = "pagebuilder.page_edit"
PERM_PAGE_PUBLISH = "pagebuilder.page_publish"
PERM_PAGE_APPROVE = "pagebuilder.page_approve"
PERM_MEDIA_MANAGE = "pagebuilder.media_manage"
PERM_LAYOUT_EDIT = "pagebuilder.layout_edit"

# Inertia page names — "<ModuleName>/<PageFileStem>".
_PAGE_LIST = "PageBuilder/PageList"
_PAGE_EDITOR = "PageBuilder/PageEditor"
_PAGE_MEDIA_LIBRARY = "PageBuilder/MediaLibrary"
_PAGE_LAYOUT_EDITOR = "PageBuilder/LayoutEditor"
_PAGE_PENDING_REVIEW = "PageBuilder/PendingReview"
_PAGE_PUBLIC = "PageBuilder/PublicPage"
```

Replace the corresponding literals in `permissions.py`, `module.py`, and `endpoints/views.py` with these constants.

- [ ] **Step 6: Source `ModuleMeta.version` from package metadata**

In `modules/pagebuilder/pagebuilder/module.py`, replace the hardcoded `version="0.2.0"`:

```python
from importlib.metadata import version as _dist_version

_VERSION = _dist_version("simple_module_pagebuilder")


class PagebuilderModule(ModuleBase):
    meta = ModuleMeta(
        name="PageBuilder",
        route_prefix="/api/pagebuilder",
        view_prefix="/pagebuilder",
        depends_on=[],
        version=_VERSION,
        requires_framework=">=1.0,<2.0",
    )
```

This makes `pyproject.toml` the single source of truth, so the lockstep bump in Task 7 cannot leave `meta.version` behind.

- [ ] **Step 7: Rewrite the module README**

`modules/pagebuilder/README.md` must open with an `# simple_module_pagebuilder` heading and cover: what the module does, installation (`uv add simple_module_pagebuilder`), the host wiring it needs, its settings (from `settings.py`), its permissions, and the note that migrations are autogenerated in the consuming host. `scripts/check_readmes.py` (Task 5) checks the heading and non-emptiness.

- [ ] **Step 8: Verify everything still passes**

```bash
cd modules/pagebuilder && uv run pytest -v; cd ../..
uv run pytest host/tests -v
uvx ruff check .
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Modernize pagebuilder to current module conventions

Complete PyPI metadata, py.typed, schemas moved to contracts/, magic
strings extracted to constants.py, and ModuleMeta.version read from
installed package metadata instead of a hardcoded string."
```

---

### Task 4: Port the end-to-end suite

**Files:**
- Create: `playwright.config.ts`
- Create: `tests/e2e/{helpers.ts,start-test-server.sh,login.spec.ts,pagebuilder.spec.ts,image-block.spec.ts,csrf.spec.ts,revisions-diff.spec.ts,public-viewer-headers.spec.ts}`
- Create: `tests/e2e/fixtures/hero-1024x768.png`

**Interfaces:**
- Consumes: the host and module from Tasks 1–3.
- Produces: `npm run test:e2e` as the browser-level regression gate that Task 5's refactor depends on.

- [ ] **Step 1: Copy the suite**

```bash
SRC=/Volumes/ext1/GitHub/smpy_pagebuilder
mkdir -p tests/e2e/fixtures
cp -R "$SRC"/tests/e2e/. tests/e2e/
cp "$SRC"/playwright.config.ts .
chmod +x tests/e2e/start-test-server.sh
```

- [ ] **Step 2: Fix the paths the wrapper assumes**

Read `tests/e2e/start-test-server.sh` and `playwright.config.ts`. Both were written for the source repo — check every path and command they reference against this repo (`host/test.db` reset, `alembic upgrade`, `make dev`, ports 8000/5050) and correct any that differ. The `SM_USERS_BOOTSTRAP_*` env vars baked into `playwright.config.ts` must stay, since the specs log in with them.

- [ ] **Step 3: Install the browser**

```bash
npx playwright install chromium --with-deps
```

- [ ] **Step 4: Run the suite**

```bash
npm run test:e2e
```

Expected: all 7 specs pass. If a spec fails on a selector, fix the spec — not the application — unless the failure reveals a real port regression, in which case fix the module and say so in the commit message.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Port the Playwright end-to-end suite

7 specs covering login, page editing, image blocks, CSRF, revision diffs,
and public-viewer headers. Wrapper isolates runs against host/test.db."
```

---

### Task 5: Quality scripts and file splits

`check_file_size` is adopted with no exemptions, so the six oversized files are split here. The suites from Tasks 2–4 are the safety net; they must be green before starting and stay green after every split.

**Files:**
- Create: `scripts/{check_file_size.py,check_hardcoded_strings.py,check_metadata.py,check_readmes.py}`
- Create: `modules/pagebuilder/pagebuilder/endpoints/api/{__init__.py,pages.py,workflow.py,revisions.py,layout.py,uploads.py}`
- Delete: `modules/pagebuilder/pagebuilder/endpoints/api.py`
- Create: `modules/pagebuilder/pagebuilder/service/{__init__.py,_workflow.py,_revisions.py}`
- Delete: `modules/pagebuilder/pagebuilder/service.py`
- Create: `modules/pagebuilder/pagebuilder/media_images.py`
- Modify: `modules/pagebuilder/pagebuilder/media_service.py`
- Create: `modules/pagebuilder/pagebuilder/utils/datetime.ts`, `utils/editorSnapshot.ts`
- Create: `modules/pagebuilder/pagebuilder/components/{PageEditorToolbar.tsx,PageSettingsPanel.tsx,RevisionHistoryPanel.tsx}`
- Create: `modules/pagebuilder/pagebuilder/hooks/useAutosave.ts`
- Modify: `modules/pagebuilder/pagebuilder/pages/PageEditor.tsx`
- Create: `modules/pagebuilder/pagebuilder/components/media/{MediaFilters.tsx,MediaUploadQueue.tsx,MediaGrid.tsx,FolderItem.tsx}`
- Modify: `modules/pagebuilder/pagebuilder/pages/MediaLibrary.tsx`
- Create: `modules/pagebuilder/tests/fixtures/{__init__.py,app.py,clients.py}`
- Modify: `modules/pagebuilder/tests/conftest.py`

**Interfaces:**
- Consumes: everything from Tasks 2–4.
- Produces: no public API change. `from pagebuilder.endpoints.api import router`, `from pagebuilder.service import PagesService`, and `from pagebuilder.media_service import MediaService` all keep working — the packages re-export them.

- [ ] **Step 1: Copy the quality scripts**

```bash
FW=/Volumes/ext1/GitHub/simple_module_python
mkdir -p scripts
cp "$FW"/scripts/check_file_size.py "$FW"/scripts/check_hardcoded_strings.py \
   "$FW"/scripts/check_metadata.py "$FW"/scripts/check_readmes.py scripts/
touch scripts/__init__.py
```

- [ ] **Step 2: Adapt the scripts to this repo**

Read each one. They hardcode the framework repo's assumptions and all three need edits:

- `check_metadata.py` — says "all 17 published packages", walks `framework/*` and `modules/*`, and asserts the canonical `project.urls.Repository`. Drop the `framework/*` walk, drop the `packages/*` npm rules, and change the expected repository URL to `https://github.com/antosubash/simple_module_python_modules`.
- `check_file_size.py` — its `DEFAULT_EXEMPT_GLOBS` references `packages/ui/src/components/ui/**`, which does not exist here. Replace the tuple with `()` so nothing is exempt.
- `check_readmes.py` / `check_hardcoded_strings.py` — check their root-walking assumptions and correct any `framework/`-specific paths.

- [ ] **Step 3: Run them to see the real violation list**

```bash
uv run python scripts/check_metadata.py
uv run python scripts/check_readmes.py
uv run python scripts/check_hardcoded_strings.py
uv run python scripts/check_file_size.py
```

Expected: the first three PASS (Task 3 did that work); `check_file_size.py` FAILS listing six files. Record the exact list — it is the work for the rest of this task.

- [ ] **Step 4: Split `endpoints/api.py` (406 lines) by resource**

```bash
cd modules/pagebuilder/pagebuilder/endpoints
mkdir api_pkg
git mv api.py api_pkg/_original.py
git mv api_pkg api
```

Create `api/__init__.py`, which must preserve `from pagebuilder.endpoints.api import router`:

```python
"""PageBuilder admin API, split by resource.

The aggregate ``router`` is what ``module.py`` mounts; sub-routers carry no
prefix of their own so every path is unchanged from the single-file version.
"""

from fastapi import APIRouter

from pagebuilder.endpoints.api import layout, pages, revisions, uploads, workflow

router = APIRouter()
router.include_router(pages.router)
router.include_router(workflow.router)
router.include_router(revisions.router)
router.include_router(layout.router)
router.include_router(uploads.router)

__all__ = ["router"]
```

Move the endpoints out of `_original.py` into these files, each declaring its own `router = APIRouter()` and carrying the imports it needs:

| File | Endpoints (source line numbers) |
|---|---|
| `pages.py` | `list_pages` 55, `create_page` 78, `get_page` 86, `update_page` 96, `delete_page` 110 |
| `workflow.py` | `list_pending` 66, `_note` 114, `publish_page` 123, `unpublish_page` 139, `submit_page` 153, `approve_page` 168, `schedule_page` 183, `reject_page` 212 |
| `revisions.py` | `list_revisions` 223, `get_revision` 239, `diff_revisions` 253, `restore_revision` 275 |
| `layout.py` | `get_layout` 285, `update_layout` 296, `list_layout_revisions` 309, `get_layout_revision` 322, `restore_layout_revision` 335 |
| `uploads.py` | `list_uploads` 344, `create_upload` 388, `delete_upload` 402 |

Registration order in `__init__.py` matters: FastAPI matches routes in order, so `pages.py`'s `/pages/{page_id}` must not shadow `workflow.py`'s `/pages/pending`. Check the original file's ordering and preserve it — if `list_pending` was declared before `get_page`, `workflow.router` must be included before `pages.router`.

Then delete the leftover:

```bash
git rm modules/pagebuilder/pagebuilder/endpoints/api/_original.py
```

- [ ] **Step 5: Run the tests**

```bash
cd modules/pagebuilder && uv run pytest -v; cd ../..
```

Expected: PASS. A 404 in a test points at route ordering — revisit the include order.

- [ ] **Step 6: Split `service.py` (380 lines) using mixins**

`PagesService` is one class, so split it by composing mixins rather than by carving out functions. Note the name collision: `services.py` (plural, the `PagebuilderServices` state container) already exists and is untouched — the new package is `service/` (singular).

```bash
cd modules/pagebuilder/pagebuilder
mkdir service_pkg && git mv service.py service_pkg/_original.py && git mv service_pkg service
```

- `service/_workflow.py` — `WorkflowMixin` with `publish` 159, `unpublish` 174, `schedule` 186, `process_due` 232, `submit_for_review` 276, `approve` 298, `reject` 320.
- `service/_revisions.py` — `RevisionsMixin` with `_record_revision` 133, `list_revisions` 341, `get_revision` 349, `diff_revisions` 355, `restore_revision` 369.
- `service/__init__.py` — module-level helpers `_Unset` 23 and `_normalize_to_utc` 30, plus:

```python
class PagesService(WorkflowMixin, RevisionsMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
    # list_pages, list_pending, get_page, get_by_slug_published,
    # list_indexable_published, create, update, delete stay here.
```

Mixins reference `self.db` and call each other's methods; that works unchanged under composition. Export `PagesService` from `__init__.py` so `from pagebuilder.service import PagesService` is unaffected. Delete `_original.py` when the move is complete.

- [ ] **Step 7: Run the tests**

```bash
cd modules/pagebuilder && uv run pytest -v; cd ../..
```

Expected: PASS.

- [ ] **Step 8: Split `media_service.py` (395 lines)**

Extract the image-processing and filename helpers into `pagebuilder/media_images.py` as module-level functions: `normalize_folder` 42, `_sniff_content_type` 90, `_safe_extension` 99, `_is_animated` 104, plus `_process_image` 325 and `_generate_thumbnails` 355 — the last two are currently methods, so give them explicit parameters for whatever `self` state they read (they use `self.settings`; pass `settings: PagebuilderSettings`). Rename them without the leading underscore since they now cross a module boundary: `process_image`, `generate_thumbnails`.

`media_service.py` keeps the `MediaService` class and imports what it needs. Re-export `normalize_folder` from `media_service` if anything outside imports it from there:

```bash
grep -rn "normalize_folder" modules/pagebuilder --include=*.py
```

- [ ] **Step 9: Run the tests**

```bash
cd modules/pagebuilder && uv run pytest -v; cd ../..
```

Expected: PASS, including `tests/test_image_processing.py`.

- [ ] **Step 10: Split `tests/conftest.py` (301 lines)**

```bash
mkdir -p modules/pagebuilder/tests/fixtures
touch modules/pagebuilder/tests/fixtures/__init__.py
```

- `fixtures/app.py` — `_stub_user` 54, `_StubAuthMiddleware` 63, `_build_app` 83.
- `fixtures/clients.py` — `_client_for` 188, `_client_fixture` 194, and `create_draft` 282.
- `conftest.py` keeps only the `@pytest.fixture` declarations (`client`, `authed_client`, `csrf_client`, `open_client`, `editor_client`, `approver_client`), importing the helpers from `tests.fixtures`.

pytest only collects fixtures from `conftest.py` itself, so the decorated fixtures must stay there — only the undecorated helpers move.

- [ ] **Step 11: Split `pages/PageEditor.tsx` (922 lines)**

**Do not create any file under `pages/`** — every `.tsx` there becomes an Inertia page name. Extract to sibling directories:

- `utils/datetime.ts` — `toLocalInput` 58, `fromLocalInput` 71.
- `utils/editorSnapshot.ts` — `SaveState` 77, `EditorSnapshot` 79, `snapshotKey` 90, `formatSaveLabel` 94, `AUTOSAVE_DEBOUNCE_MS` 51.
- `hooks/useAutosave.ts` — the debounced autosave effect at 488 and its `saveState` / `lastSavedAt` / `autosaveError` state, returned as an object.
- `components/PageEditorToolbar.tsx` — the toolbar JSX at 531–662, taking title/slug/status/save-label as props.
- `components/PageSettingsPanel.tsx` — the settings drawer (SEO fields, JSON-LD, schedule) gated by `showSettings`.
- `components/RevisionHistoryPanel.tsx` — the history drawer gated by `showHistory`, plus `EVENT_LABELS` 37 and `RESTORABLE_EVENTS` 46.

`PageEditor.tsx` keeps its state, handlers, and composition. Line numbers are from the pre-split file; read the current file before cutting, and adjust boundaries if a clean prop interface falls elsewhere. The hard requirements are: every file ≤300 lines, no new files under `pages/`, and no behaviour change.

- [ ] **Step 12: Split `pages/MediaLibrary.tsx` (599 lines)**

Same constraint. Extract to `components/media/`:

- `MediaFilters.tsx` — `ListFilters` 24, `CONTENT_TYPE_OPTIONS` 45, `parseKB` 59, and the filter bar JSX.
- `MediaUploadQueue.tsx` — `UploadStatus` 32, `UploadItem` 34, `uploadKey` 67, and the upload queue UI.
- `MediaGrid.tsx` — the asset grid and `formatBytes` 53.
- `FolderItem.tsx` — `FolderItem` 574.

- [ ] **Step 13: Verify the splits**

```bash
uv run python scripts/check_file_size.py
cd modules/pagebuilder && uv run pytest -v; cd ../..
uv run pytest host/tests -v
uvx ruff check .
npx biome check .
make gen-pages && npm run build
npm run test:e2e
```

Expected: all PASS. `check_file_size.py` must exit 0 with no exemptions. `make gen-pages` must still list exactly the six original PageBuilder pages — if it lists more, a `.tsx` file landed under `pages/`.

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "Adopt the quality checks and split oversized files

check_file_size (300 lines) now passes with no exemptions: api.py split
by resource, PagesService composed from workflow/revisions mixins, image
helpers extracted from media_service, and the two large editor pages
split into components. No public API or behaviour change."
```

---

### Task 6: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `make` targets and `scripts/check_*.py` from Tasks 1 and 5.
- Produces: the PR gate. `bump_version.py --check` is added to it in Task 7.

- [ ] **Step 1: Copy the source app's CI as the base**

```bash
mkdir -p .github/workflows
cp /Volumes/ext1/GitHub/smpy_pagebuilder/.github/workflows/ci.yml .github/workflows/ci.yml
```

- [ ] **Step 2: Adapt it**

Read the file and make these changes:

- The `Stub force-include dirs` steps say `mkdir -p modules/hello/hello/static/dist modules/pagebuilder/pagebuilder/static/dist`. There is no `hello` module here — change every occurrence to `mkdir -p modules/pagebuilder/pagebuilder/static/dist`.
- The `Run pytest (hello)` step must be deleted.
- Add `uv run pytest host/tests` as a step in the `python-tests` job, after the module pytest step.
- Bump `NODE_VERSION` from `"20"` to `"24"` to match the framework repo.

- [ ] **Step 3: Add the `checks` job**

Append to `.github/workflows/ci.yml`:

```yaml
  checks:
    name: Repo checks (metadata, readmes, strings, file size)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: latest
          enable-cache: true

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Stub force-include dirs
        run: mkdir -p modules/pagebuilder/pagebuilder/static/dist

      - name: Sync workspace
        run: uv sync --all-packages --all-extras

      - name: Package metadata
        run: uv run python scripts/check_metadata.py

      - name: READMEs
        run: uv run python scripts/check_readmes.py

      - name: Hardcoded strings
        run: uv run python scripts/check_hardcoded_strings.py

      - name: File size
        run: uv run python scripts/check_file_size.py
```

- [ ] **Step 4: Add a biome job**

```yaml
  lint-js:
    name: Lint (biome)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: npm
      - run: npm ci
      - run: npx biome check .
```

- [ ] **Step 5: Validate the workflow parses**

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid')"
```

Expected: `valid`. Then reproduce each job locally:

```bash
uvx ruff check . && npx biome check . && uv run python scripts/check_file_size.py
cd modules/pagebuilder && uv run pytest; cd ../..
uv run pytest host/tests
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "Add CI workflow

ruff, biome, per-module pytest, host tests, frontend build, Playwright
e2e, and the repo checks job (metadata, readmes, hardcoded strings,
file size)."
```

---

### Task 7: Lockstep release

**Files:**
- Create: `scripts/bump_version.py`
- Create: `.github/workflows/release.yml`
- Create: `scripts/tests/test_bump_version.py`
- Modify: `.github/workflows/ci.yml` (add the `--check` step)
- Modify: `pyproject.toml` (add `scripts/tests` to `testpaths`)

**Interfaces:**
- Consumes: the module layout from Tasks 2–3.
- Produces: `scripts/bump_version.py <version>` rewriting every publishable package's version, and `--check <version>` / `--check-current` verifying sync. `release.yml` calls both.

- [ ] **Step 1: Write the failing test first**

Create `scripts/tests/test_bump_version.py`:

```python
"""The repo-local bump script must never rewrite framework dependency pins.

The framework's version of this script rewrites every ``simple_module_*``
requirement to ``==<version>``. Run here, that would turn
``simple_module_core>=0.0.24,<0.1`` into ``==<this repo's version>`` —
pinning the framework to a version that does not exist.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tomlkit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "bump_version.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_dry_run_reports_module_and_root(tmp_path):
    result = _run("9.9.9", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "modules/pagebuilder/pyproject.toml" in result.stdout
    assert "pyproject.toml" in result.stdout


def test_framework_pins_are_never_rewritten():
    """A dry run must not claim it would touch a simple_module_core spec."""
    result = _run("9.9.9", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "simple_module_core" not in result.stdout
    assert "simple_module_db" not in result.stdout
    assert "simple_module_hosting" not in result.stdout


def test_check_current_passes_on_a_synced_tree():
    result = _run("--check-current")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fails_on_a_version_the_tree_does_not_have():
    result = _run("--check", "9.9.9")
    assert result.returncode != 0


def test_module_version_matches_root_version():
    root = tomlkit.parse((REPO / "pyproject.toml").read_text())["project"]["version"]
    mod = tomlkit.parse(
        (REPO / "modules" / "pagebuilder" / "pyproject.toml").read_text()
    )["project"]["version"]
    assert str(root) == str(mod)
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
mkdir -p scripts/tests && touch scripts/tests/__init__.py
uv run pytest scripts/tests -v
```

Expected: FAIL — `scripts/bump_version.py` does not exist.

- [ ] **Step 3: Write `scripts/bump_version.py`**

```python
"""Bump the version of every publishable package in this repo, in lockstep.

Rewrites ``project.version`` in the root ``pyproject.toml`` and in every
``modules/*/pyproject.toml``, plus ``version`` in every
``modules/*/package.json``.

Deliberately does NOT touch dependency specifiers. The framework repo's
script rewrites every ``simple_module_*`` requirement to ``==<version>``;
here those requirements point at the *framework's* versions, which move
independently of this repo's. Rewriting them would pin the framework to a
version that does not exist.

Usage:
  python scripts/bump_version.py 0.2.0
  python scripts/bump_version.py 0.2.0 --dry-run
  python scripts/bump_version.py --check 0.2.0
  python scripts/bump_version.py --check-current
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import tomlkit

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-.]?(a|b|rc|alpha|beta)\d*)?$")


def _module_pyprojects() -> list[Path]:
    return sorted((REPO_ROOT / "modules").glob("*/pyproject.toml"))


def _module_package_jsons() -> list[Path]:
    return sorted((REPO_ROOT / "modules").glob("*/package.json"))


def _root_pyproject() -> Path:
    return REPO_ROOT / "pyproject.toml"


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _read_version(path: Path) -> str:
    if path.suffix == ".toml":
        return str(tomlkit.parse(path.read_text())["project"]["version"])
    return str(json.loads(path.read_text())["version"])


def _write_version(path: Path, version: str) -> None:
    if path.suffix == ".toml":
        doc = tomlkit.parse(path.read_text())
        doc["project"]["version"] = version
        path.write_text(tomlkit.dumps(doc))
        return
    text = path.read_text()
    data = json.loads(text)
    data["version"] = version
    indent = 2
    path.write_text(json.dumps(data, indent=indent) + "\n")


def _targets() -> list[Path]:
    return [_root_pyproject(), *_module_pyprojects(), *_module_package_jsons()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="target version, e.g. 0.2.0")
    parser.add_argument("--check", metavar="VERSION", help="verify the tree is at VERSION")
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="verify every package matches the root version",
    )
    parser.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    args = parser.parse_args(argv)

    if args.check_current:
        expected = _read_version(_root_pyproject())
    elif args.check:
        expected = args.check
    else:
        expected = args.version

    if not expected:
        parser.error("a version, --check VERSION, or --check-current is required")
    if not VERSION_RE.match(expected):
        print(f"error: {expected!r} is not a valid version", file=sys.stderr)
        return 2

    checking = bool(args.check or args.check_current)
    drift: list[str] = []

    for path in _targets():
        current = _read_version(path)
        if current == expected:
            continue
        if checking:
            drift.append(f"{_rel(path)}: {current} (expected {expected})")
        elif args.dry_run:
            print(f"{_rel(path)}: {current} -> {expected}")
        else:
            _write_version(path, expected)
            print(f"{_rel(path)}: {current} -> {expected}")

    if drift:
        print("version drift detected:", file=sys.stderr)
        for line in drift:
            print(f"  {line}", file=sys.stderr)
        return 1

    if checking:
        print(f"all packages at {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest scripts/tests -v
```

Expected: PASS. `test_check_current_passes_on_a_synced_tree` requires the root and module versions to match — both are `0.1.0` from Tasks 1 and 3. If they drifted, run `uv run python scripts/bump_version.py 0.1.0` first.

Add `scripts/tests` to `testpaths` in the root `pyproject.toml`.

- [ ] **Step 5: Write `.github/workflows/release.yml`**

```yaml
# Lockstep release: one version, one tag, every module published.
#
# The tag reaches origin only in `finalize`, after every publish has
# succeeded, so a failed build never strands an orphan tag.
#
# One-time PyPI setup per module, at https://pypi.org/manage/account/publishing/
#   PyPI project name = simple_module_<name>
#   Owner             = antosubash
#   Repository name   = simple_module_python_modules
#   Workflow filename = release.yml
#   Environment       = pypi

name: release

on:
  workflow_dispatch:
    inputs:
      bump:
        description: "Semver bump (ignored if `version` is set)"
        type: choice
        options: [patch, minor, major]
        default: patch
      version:
        description: "Explicit version override (e.g. 0.2.0)"
        required: false
        type: string

permissions:
  contents: write
  id-token: write

env:
  PYTHON_VERSION: "3.12"
  NODE_VERSION: "24"

jobs:
  resolve:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.compute.outputs.version }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - id: compute
        shell: bash
        run: |
          if [ -n "${{ inputs.version }}" ]; then
            ver="${{ inputs.version }}"
          else
            ver=$(BUMP="${{ inputs.bump }}" python3 <<'PY'
          import os, pathlib, re, tomllib
          cur = tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"]
          m = re.match(r"^(\d+)\.(\d+)\.(\d+)", cur)
          if not m:
              raise SystemExit(f"cannot parse current version: {cur!r}")
          major, minor, patch = map(int, m.groups())
          bump = os.environ["BUMP"]
          if bump == "major":
              major, minor, patch = major + 1, 0, 0
          elif bump == "minor":
              minor, patch = minor + 1, 0
          else:
              patch += 1
          print(f"{major}.{minor}.{patch}")
          PY
          )
          fi
          echo "${ver}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([.-]?(a|b|rc|alpha|beta)[0-9]*)?$' \
            || { echo "::error::'${ver}' is not a valid version"; exit 1; }
          echo "version=${ver}" >> "$GITHUB_OUTPUT"

  build:
    needs: resolve
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v3
        with:
          version: latest
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}
      - name: Stub force-include dirs
        run: mkdir -p modules/pagebuilder/pagebuilder/static/dist
      - name: Sync workspace
        run: uv sync --all-packages --all-extras
      - name: Bump versions (working tree only)
        run: uv run python scripts/bump_version.py "${{ needs.resolve.outputs.version }}"
      - name: Install npm workspace
        run: npm ci
      - name: Build module frontends
        run: |
          make gen-pages
          npm run build
      - name: Build wheels + sdists
        run: uv build --all-packages --out-dir dist-py
      - uses: actions/upload-artifact@v4
        with:
          name: dist-py
          path: dist-py/
          retention-days: 14

  publish-pypi:
    needs: [resolve, build]
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    strategy:
      fail-fast: false
      matrix:
        package:
          - simple_module_pagebuilder
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist-py
          path: dist-py
      - name: Select this package's artifacts
        run: |
          mkdir -p upload
          norm=$(echo "${{ matrix.package }}" | tr '_' '-')
          find dist-py -maxdepth 1 -type f \
            \( -iname "${{ matrix.package }}-*" -o -iname "${norm}-*" \) \
            -exec cp {} upload/ \;
          ls -l upload
          test -n "$(ls -A upload)" || { echo "::error::no artifacts for ${{ matrix.package }}"; exit 1; }
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: upload

  finalize:
    needs: [resolve, publish-pypi]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v3
        with:
          version: latest
      - name: Bump versions
        run: uv run python scripts/bump_version.py "${{ needs.resolve.outputs.version }}"
      - name: Commit and tag
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          git commit -m "Release v${{ needs.resolve.outputs.version }}"
          git tag "v${{ needs.resolve.outputs.version }}"
          git push origin HEAD:main --follow-tags
      - name: Create GitHub release
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release create "v${{ needs.resolve.outputs.version }}" --generate-notes
```

**Every new module must be added to the `publish-pypi` matrix.** That is the one manual step when a module lands; note it in `docs/adding-a-module.md` in Task 8.

- [ ] **Step 6: Add the version-sync check to CI**

In `.github/workflows/ci.yml`, append to the `checks` job's steps:

```yaml
      - name: Version sync
        run: uv run python scripts/bump_version.py --check-current
```

- [ ] **Step 7: Verify**

```bash
uv run pytest scripts/tests -v
uv run python scripts/bump_version.py --check-current
uv run python scripts/bump_version.py 0.2.0 --dry-run
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('valid')"
uv build --all-packages --out-dir /tmp/dist-check
python3 -c "
import zipfile, glob
w = glob.glob('/tmp/dist-check/simple_module_pagebuilder-*.whl')[0]
names = zipfile.ZipFile(w).namelist()
assert 'pagebuilder/package.json' in names, 'package.json missing from wheel'
assert 'pagebuilder/py.typed' in names, 'py.typed missing from wheel'
print('wheel contents OK')
"
```

Expected: tests PASS, `--check-current` passes, the dry run lists the root and module files but mentions no `simple_module_core`, both YAML files parse, and the wheel check prints OK.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add lockstep release machinery

bump_version.py rewrites only this repo's own package versions and never
touches framework dependency specifiers — the framework's version of the
script would rewrite them to a nonexistent pin. release.yml resolves,
builds, publishes per-module via trusted publishing, then tags."
```

---

### Task 8: Documentation

**Files:**
- Create: `CLAUDE.md`, `docs/adding-a-module.md`, `docs/releasing.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write `README.md`**

Replace the one-line stub. Cover, in this order: what the repo is (distributable SimpleModule add-ons + a demo host); the layout tree from the spec; quick start (`make install`, `make env`, `make migrate`, `make dev`, noting API on :8000 and Vite on :5050); running tests (`make test-py`, `make e2e`); the module list (a table with `pagebuilder` → `simple_module_pagebuilder` → PyPI link); adding a module (link to `docs/adding-a-module.md`); releasing (link to `docs/releasing.md`).

- [ ] **Step 2: Write `CLAUDE.md`**

Must state:

- **Local database.** All repos under `/Volumes/ext1/GitHub` share one stack in `/Volumes/ext1/GitHub/dev-services` (PostGIS + Redis + MinIO + Adminer on the `devnet` network); start it with `make up` there. Do not spin up a per-project Postgres. Local dev defaults to SQLite (`host/app.db`), so Postgres is optional; to use it set `SM_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/smpy_modules` and add the database to `dev-services/init/01-databases.sql`.
- **Pin policy.** Published modules use ranges (`simple_module_core>=<FW>,<0.1`); the host pins exactly. Never pin a published module with `==` — it makes the module uninstallable in hosts on a newer framework.
- **Migrations live in `host/migrations/versions/`.** Modules never ship migrations. A module's first revision carries `branch_labels = ("<module>",)`.
- **Never add files under `modules/*/*/pages/`** except real Inertia pages — the path determines the page name.
- **Releases are lockstep.** One version across the repo; `scripts/bump_version.py` is the only thing that edits versions, and it must never rewrite framework dependency specifiers.
- **Working against an unreleased framework:** `make link-framework FRAMEWORK=…` / `make unlink-framework`.

- [ ] **Step 3: Write `docs/adding-a-module.md`**

The full checklist: `make new-module name=<x>`; add the dependency and `[tool.uv.sources]` entry to `host/pyproject.toml`; add `modules/<x>/tests` to root `testpaths`; add the module to the `publish-pypi` matrix in `.github/workflows/release.yml`; add the `static/dist` stub path to the CI `Stub force-include dirs` steps; set the version to match the current lockstep version; `make install && make migration msg="add <x>" && make migrate`; add the `branch_labels` marker to the first revision.

- [ ] **Step 4: Write `docs/releasing.md`**

Cover: lockstep meaning; running the `release` workflow with a `bump` choice or explicit `version`; what each of the four jobs does; the one-time PyPI trusted-publishing setup per module (with the exact field values from `release.yml`'s header comment); and what to do if a publish fails mid-matrix (no tag was pushed — fix and re-run).

- [ ] **Step 5: Verify the docs are accurate**

Walk every command in `README.md` and `docs/*.md` and run it. Any command that fails is a doc bug — fix the doc.

```bash
uv run python scripts/check_readmes.py
```

Expected: PASS.

- [ ] **Step 6: Final full verification**

```bash
make install
make lint
make test-py
make build
make e2e
```

Expected: all PASS. This is the spec's success criteria in one run.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add README, CLAUDE.md, and contributor docs

Covers layout, quick start, the pin policy, migrations-live-in-the-host,
adding a module, and the lockstep release process."
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Repository layout | 1 |
| Workspace wiring (uv + npm), no `hello` module | 1, 2 |
| Dependency pin policy (ranges vs exact) | 1, 2, Global Constraints |
| Local framework override (`link-framework`) | 1 (Makefile) |
| Pagebuilder ported unchanged | 2 |
| Modernized during the port (metadata, contracts/, py.typed, constants, meta.version) | 3 |
| File splits (6 files, no exemptions) | 5 |
| JS packaging (`private: true`, wheel force-include) | 2 (copied), 7 (wheel content verified) |
| Demo host composition | 1, 2 |
| Migrations: two squashed baselines + branch label | 1 (initial), 2 (pagebuilder) |
| Testing: module pytest / host smoke / Playwright | 2, 1+2, 4 |
| Makefile targets | 1 |
| CI | 6 |
| Release (lockstep, 4 stages, bump variant) | 7 |
| Documentation | 8 |
| Deferred items | Not implemented, by design |
| Success criteria | 8 Step 6 |

**Type consistency:** `PagesService` keeps its name through the Task 5 mixin split and is re-exported from `service/__init__.py`. `router` is re-exported from `endpoints/api/__init__.py`. `MediaService` stays in `media_service.py`; only the helpers move, and they lose their leading underscore (`process_image`, `generate_thumbnails`) because they now cross a module boundary. `bump_version.py`'s flags (`--check`, `--check-current`, `--dry-run`) are used identically in its tests, the Makefile `lint` target, and the CI `checks` job.

**Known adjustment point:** the split boundaries in Task 5 Steps 11–12 cite line numbers from the pre-split files. The implementer must read the current file before cutting. The invariants that cannot be adjusted are: ≤300 lines per file, no new files under `pages/`, and the full test + e2e suite green after each split.
