.PHONY: install install-py install-js dev dev-api dev-ui build gen-pages sync-module-deps typecheck \
        migrate migration downgrade test test-py test-js e2e lint kill \
        link-framework unlink-framework new-module env

# Ports are overridable so a second checkout (worktree, parallel review) can
# run its own pair of dev servers without colliding with the primary one.
SM_API_PORT ?= 8000
SM_VITE_PORT ?= 5050
export SM_VITE_PORT

install: install-py install-js sync-module-deps

install-py:
	uv sync --all-packages --all-extras

install-js:
	npm install

dev: gen-pages
	@echo "Starting API and UI dev servers..."
	$(MAKE) -j2 dev-api dev-ui

# Every Python entry point runs from the repo root so the root .env is the
# single source of truth for settings. `--app-dir host` puts host/main.py on
# sys.path without changing cwd.
dev-api:
	uv run --project host uvicorn main:app --app-dir host --reload --port $(SM_API_PORT)

dev-ui:
	npm run dev

build:
	npm run build

# Regenerate host/client_app/modules.{manifest.json,generated.ts,generated.css}
# from installed modules (workspace + wheel-installed).
gen-pages:
	uv run --project host python -m simple_module_hosting gen-pages --host-dir=host/client_app

# Pull JS deps shipped by wheel-installed modules into host/client_app/node_modules.
# Workspace modules under modules/* don't need this — npm hoists them automatically.
sync-module-deps:
	uv run --project host python -m simple_module_hosting sync-js-deps --host-client-app=host/client_app

migrate:
	uv run --project host alembic -c host/alembic.ini upgrade heads

migration:
	@test -n "$(msg)" || (echo 'Usage: make migration msg="describe the change"' && exit 1)
	uv run --project host alembic -c host/alembic.ini revision --autogenerate -m "$(msg)"

downgrade:
	uv run --project host alembic -c host/alembic.ini downgrade -1

test: test-py test-js

test-py:
	uv run pytest host/tests scripts/tests
	@for d in modules/*/; do \
	  if [ -d "$$d/tests" ]; then echo "--- pytest $$d"; (cd "$$d" && uv run pytest) || exit 1; fi \
	done

# Unit tests for module frontend code, from the repo root — vitest.config.ts
# includes modules/**/*.test.ts(x). The e2e suite covers browser behaviour;
# this covers logic a browser test can only reach indirectly.
test-js:
	npx vitest run
	npm run --workspace host/client_app test --if-present

e2e:
	npm run test:e2e

# Typecheck module TSX. `npm run build` only runs tsc over host/client_app, so
# without this a module-level type error (a missing import, a dropped props
# annotation) reaches the browser with every suite green.
# The `find` guard skips a module that has a tsconfig but no sources yet —
# tsc treats an empty program as TS18003 and fails the build.
typecheck:
	@for d in modules/*/; do \
	  if [ -f "$$d/tsconfig.json" ] && [ -n "$$(find "$$d" -name '*.ts' -o -name '*.tsx' | head -1)" ]; then \
	    echo "--- tsc $$d"; npx tsc --noEmit -p "$$d/tsconfig.json" || exit 1; \
	  fi \
	done

lint:
	uvx ruff check .
	npx biome check .
	$(MAKE) typecheck
	uv run python scripts/check_metadata.py
	uv run python scripts/check_readmes.py
	uv run python scripts/check_hardcoded_strings.py
	uv run python scripts/check_file_size.py
	uv run python scripts/bump_version.py --check-current

env:
	@test -f .env || (cp .env.example .env && \
	  python3 -c "import pathlib, secrets; p=pathlib.Path('.env'); \
	  p.write_text(p.read_text().replace('replace-me-with-a-generated-secret', secrets.token_urlsafe(32)))" && \
	  echo ".env created with a generated SM_SECRET_KEY")

# First-party modules the host installs from PyPI that also live in the
# framework repo. Linking core/db/hosting alone is not enough when the work
# spans one of these — the host would keep running the released build and the
# change would look like it had no effect.
FRAMEWORK_MODULES ?= branding

# Develop against an unreleased framework checkout.
#   make link-framework FRAMEWORK=/Volumes/ext1/GitHub/simple_module_python
# Override the module list with e.g. FRAMEWORK_MODULES="branding users".
link-framework:
	@test -n "$(FRAMEWORK)" || (echo 'Usage: make link-framework FRAMEWORK=/path/to/simple_module_python' && exit 1)
	uv pip install -e $(FRAMEWORK)/framework/core \
	               -e $(FRAMEWORK)/framework/db \
	               -e $(FRAMEWORK)/framework/hosting \
	               $(foreach m,$(FRAMEWORK_MODULES),-e $(FRAMEWORK)/modules/$(m))
	@echo "Framework linked ($(FRAMEWORK_MODULES)). Run 'make unlink-framework' to restore PyPI versions."

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
