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
- Postgres is optional: the shared `dev-services` stack, never a new container
  (CLAUDE.md "Local database").

## Launch
| Scenario | Command |
|---|---|
| Migrations | `make migrate` (alembic `upgrade heads` — there are several heads) |
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

## Stop / reset
- `make kill` (honours `API_PORT`/`UI_PORT` — pass the same values you started with).
- Reset data: stop, delete `host/app.db`, `make migrate`.

## Gotchas
- Never put the UI on 5060/5061: Chromium refuses them (`ERR_UNSAFE_PORT`) and the
  app renders blank in Playwright. 5070 works.
- Boot prints SM003/SM024 warnings for news/ai/records; they predate current work and
  are not failures.
- Multi-tenancy is off in the demo host (news blocks it); everything runs as
  tenant `"default"`. Billing tenant screens need `SM_MULTI_TENANT=true` without News.

## Tests
- Python: `make test-py`, or `cd modules/<name> && uv run pytest -q`.
- Lint/all checks: `make lint` (ruff, biome, tsc, metadata, readmes, 300-line cap).
- JS: `make test-js`. E2E: `make e2e` — Playwright starts its own server via
  `tests/e2e/start-test-server.sh` on a throwaway DB.
