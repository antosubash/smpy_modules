.PHONY: install install-py install-js dev dev-api dev-ui build gen-pages sync-module-deps typecheck \
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

# Every Python entry point runs from the repo root so the root .env is the
# single source of truth for settings. `--app-dir host` puts host/main.py on
# sys.path without changing cwd.
# Overridable so a second checkout (e.g. a worktree running e2e) can boot
# beside a dev stack that already holds the default ports.
# e2e runs name their overrides E2E_* (see playwright.config.ts); honor them
# too so `make kill` after an aborted e2e run targets the right orphans —
# provided E2E_* (or API_PORT/UI_PORT) is still set when `make kill` runs; an
# inline env on the aborted command line is gone with its shell.
# Every source — including a direct API_PORT/UI_PORT from the environment,
# which `?=` alone would let straight through — passes the same guard
# playwright.config.ts and vite.config.ts apply (`^[1-9][0-9]*$`, else the
# default): a raw bad value would make lsof abort the whole sweep (freeing
# neither port) and would be interpolated unescaped into the pkill regex
# below. `override` re-assigns even env/command-line values, so the guarded
# result always wins. E2E_* wins over SM_UI_PORT because an e2e run
# overrides SM_UI_PORT only inside its own subprocess env — after an aborted
# run the orphan sits on the E2E_* port, not the shell's SM_UI_PORT.
_API_PORT_RAW = $(or $(API_PORT),$(E2E_API_PORT))
override API_PORT := $(if $(shell echo '$(_API_PORT_RAW)' | grep -E '^[1-9][0-9]*$$'),$(_API_PORT_RAW),8000)
_UI_PORT_RAW = $(or $(UI_PORT),$(E2E_UI_PORT),$(SM_UI_PORT))
override UI_PORT := $(if $(shell echo '$(_UI_PORT_RAW)' | grep -E '^[1-9][0-9]*$$'),$(_UI_PORT_RAW),5050)

dev-api:
	uv run --project host uvicorn main:app --app-dir host --reload --port $(API_PORT)

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

# Scoped to this checkout's ports so it never kills the neighboring dev
# stack the port overrides exist to coexist with.
kill:
	@-pkill -f "uvicorn main:app.*--port $(API_PORT)( |$$)" 2>/dev/null
	@-lsof -ti:$(API_PORT),$(UI_PORT) | xargs kill -9 2>/dev/null
	@echo "Ports $(API_PORT), $(UI_PORT) freed."
