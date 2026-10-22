---
name: running-the-stack
description: Use when launching, restarting, or smoke-testing smpy_modules locally — the demo host (FastAPI/uvicorn API + Vite UI) that mounts pagebuilder, news, records, billing and ai — or when a local run fails to start, a port is taken, or login fails.
---

# Running smpy_modules

Every Python entry point runs from the **repo root** (or a worktree root): the
root `.env` is the single source of truth (see CLAUDE.md).

## Prerequisites (once per checkout / worktree)
- `uv`, Node + npm. A worktree needs its own installs — nothing is shared.
- `make env` — creates `.env` from `.env.example` with a generated `SM_SECRET_KEY`
  (SQLite at `host/app.db`; no Postgres needed).
- `uv sync --all-packages --all-extras` (= `make install-py`), `npm ci`,
  `make sync-module-deps`, `make gen-pages`.
- Postgres is optional: the shared `dev-services` stack when available (never a
  second container beside it), else the one-line `docker run` in CLAUDE.md
  "Local database".

## Launch
| Scenario | Command |
|---|---|
| Migrations | `make migrate` (alembic `upgrade heads`; history has one head, enforced by `scripts/check_migration_heads.py`) |
| Full stack | `SM_USERS_BOOTSTRAP_EMAIL=<email> SM_USERS_BOOTSTRAP_PASSWORD=<pw> make dev` |
| Second stack beside another (worktree) | prefix with `API_PORT=8010 UI_PORT=5070 SM_UI_PORT=5070 SM_VITE_DEV_URL=http://localhost:5070` |
| API only / UI only | `make dev-api` / `make dev-ui` |

`make dev` runs `gen-pages`, then uvicorn on `API_PORT` (default 8000, `--reload`)
and Vite on `UI_PORT` (default 5050). Run it in the background and log to a file.

## Ready check
- Health: `curl -fsS http://localhost:$API_PORT/health` →
  `{"status":"healthy","migration":{...,"is_current":true}}` (~10 s after start).
- The app is served from the **API port**. Vite's own root returns 404 — expected.
  `/` on the API is also 404 (no home page); admin screens such as `/pagebuilder`
  302 to `/users/login`.
- Login: the bootstrap admin from `SM_USERS_BOOTSTRAP_EMAIL`/`_PASSWORD`, created
  on first start against an empty users table. Pick your own values; none are committed.

## Docker (`compose.yaml`)
The host alone in a container: API + pre-built UI, `SM_ENVIRONMENT=production`,
migrations on every start. No Postgres service — never add one.
- Needs `.env` (`make env`) with `SM_SECRET_KEY`, `SM_USERS_RESET_PASSWORD_TOKEN_SECRET`
  and `SM_USERS_VERIFICATION_TOKEN_SECRET` (production refuses to boot on the
  users module's placeholders — the error names them), plus
  `SM_USERS_BOOTSTRAP_EMAIL`/`_PASSWORD` for the first admin.
- `SMPY_PORT=8091 docker compose up -d --build` (default port 8090; container
  listens on 8000). First build ~2 min, start to healthy ~15 s:
  `docker inspect -f '{{.State.Health.Status}}' smpy-modules-host-1`, then
  `curl -fsS http://localhost:8091/health`.
- DB: SQLite in volume `smpy-data` (`/app/var/app.db`, plus pagebuilder media);
  uploads in `smpy-uploads`. Shared Postgres: add `-f compose.yaml -f compose.devnet.yaml`
  (joins external `devnet`, needs dev-services up) and
  `SMPY_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/smpy_modules`
  (the database must exist there).
- `SMPY_*`, not `SM_*`: compose overrides `.env`'s `SM_DATABASE_URL`/`SM_ENVIRONMENT`.
- One-off: `docker compose run --rm host python scripts/set_setting.py …`.
- Stop: `docker compose down` (`-v` drops data); remove the image with
  `docker image rm smpy-modules-host:dev`.

## Stop / reset
- `make kill` (honours `API_PORT`/`UI_PORT` — pass the same values you started with).
- Reset data: stop, delete `host/app.db`, `make migrate`.

## Gotchas
- Never put the UI on 5060/5061: Chromium refuses them (`ERR_UNSAFE_PORT`) and the
  app renders blank in Playwright. 5070 works.
- Boot prints SM003/SM024 warnings for news/ai/records; they predate current work and
  are not failures.
- Multi-tenancy is off in the demo host by default; everything runs as tenant
  `"default"`. Billing tenant screens need `SM_MULTI_TENANT=true` (all modules can
  stay enabled). Multi-tenant e2e: `E2E_MULTI_TENANT=1 npx playwright test
  billing-tenant news-tenant`.

## Tests
- Python: `make test-py`, or `cd modules/<name> && uv run pytest -q`.
- Lint/all checks: `make lint` (ruff, biome, tsc, metadata, readmes, 300-line cap).
- JS: `make test-js`. E2E: `make e2e` — Playwright starts its own server via
  `tests/e2e/start-test-server.sh` on a throwaway DB.
