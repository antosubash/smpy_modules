#!/usr/bin/env bash
# Entry point used by playwright.config.ts → webServer.command.
# Resets the test SQLite database, runs migrations, then hands off to the
# server: `make dev` by default, or — with E2E_BUNDLE=1, which CI sets — a
# plain uvicorn (no --reload) serving the production bundle. Keeping this in a
# script (instead of chaining inside the Playwright config) lets us share the
# same logic across CI and local runs and gives Playwright a single PID to wait
# on / kill.
set -euo pipefail

if [[ -z "${SM_DATABASE_URL:-}" ]]; then
  echo "SM_DATABASE_URL must be set by playwright.config.ts" >&2
  exit 1
fi

# Start from an empty database. How that is done depends on the backend, and
# the parameter expansion below is only meaningful for one of them: on a
# Postgres URL `${SM_DATABASE_URL#sqlite+aiosqlite:///}` matches nothing, so
# the prefix is left in place and what used to be `rm -f`-ed was the *whole
# URL* read as a relative path — a file that never existed, removed
# successfully, leaving last run's tables in place. The `case` makes the
# distinction explicit rather than leaving it to a no-op substitution.
case "${SM_DATABASE_URL}" in
  sqlite*)
    # Extract the SQLite file path from a URL like
    # sqlite+aiosqlite:////abs/path/to/test.db so we can `rm` it.
    db_path="${SM_DATABASE_URL#sqlite+aiosqlite:///}"
    if [[ "${db_path}" != /* ]]; then
      db_path="$(pwd)/${db_path}"
    fi
    rm -f "${db_path}" "${db_path}-wal" "${db_path}-shm"
    ;;
  *)
    # Anything else is a server the suite does not own the file of. Drop the
    # schema and let the migrations rebuild it, which is the closest
    # equivalent of deleting the file and is what keeps a rerun independent of
    # the last one.
    #
    # `DROP SCHEMA` rather than `alembic downgrade base`: a downgrade replays
    # every revision's `downgrade()` and so depends on all of them being
    # correct in a database the run is about to throw away regardless, and it
    # leaves behind anything a revision forgot to drop — Postgres enum types,
    # most of the time. Dropping the schema cannot leave anything.
    uv run python - <<'PY'
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main() -> None:
    engine = create_async_engine(os.environ["SM_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()

asyncio.run(main())
PY
    ;;
esac

# Migrations run from the repo root (alembic.ini resolves its script_location
# relative to itself). `make migrate` runs `upgrade heads`, which tolerates a
# split history; the history itself is kept to one head by CI's
# scripts/check_migration_heads.py (#107), so `head` and `heads` agree.
make migrate

# Two content locales, so the multilingual surface is exercised end to end
# rather than only in the module test suites. English stays the default, which
# is what keeps every other spec's URLs unchanged: /p/{slug} and /news/{slug}
# are still where an English page serves.
#
# Written into the settings table rather than exported: the modules read their
# configuration from the database now, and an SM_PAGEBUILDER_* variable would
# be ignored. This runs after `make migrate` because the table it writes to is
# one the migrations create.
uv run python scripts/set_setting.py pagebuilder \
  content_locales '["en","de"]' \
  default_content_locale en

# Same two locales for the records module's own content i18n (Phase 5 §4.2)
# — deliberately its own setting, not pagebuilder's (records must not depend
# on pagebuilder), registered under its package name (`constants.PACKAGE`).
uv run python scripts/set_setting.py sm_records \
  content_locales '["en","de"]' \
  default_content_locale en

# Two Phase 5 ceilings, lowered so a browser test can reach them at all. Both
# default far above anything an e2e run can seed (10,000 records for the
# capped total, 5,000 for a synchronous schema preview), and both are only
# visible in the UI on the far side of the ceiling: the list footer renders a
# capped total as "N+", and "Preview changes" becomes a polled job with a
# progress label. The values sit *above* every other spec's fixtures —
# `records-list-ux.spec.ts` pages through 30 records and asserts an exact total,
# `records-schema-change.spec.ts` previews a type holding two — and low enough
# that `records-paging.spec.ts` / `records-preview.spec.ts` can seed past them
# over the API in seconds.
uv run python scripts/set_setting.py sm_records \
  max_count 32 \
  preview_sync_limit 3

# Usage for the admin Usage tab to show (`billing-usage.spec.ts`): three
# consumes of the demo host's `demo.exports` counter and three holds on its
# `demo.jobs` gauge (`host/demo_meters.py`), for the single-tenant host's
# `default` tenant. Through billing's service API, not SQL, and keyed, so a
# rerun counts nothing twice. A multi-tenant run gets the same rows; its spec
# meters an organisation of its own.
uv run python scripts/seed_usage.py

# The host limits anonymous traffic to public routes per client IP
# (`rate_limit_public`, 120/minute). Every test signs in from scratch — an
# anonymous GET /users/login and POST /api/users/auth/login — and all of them
# come from 127.0.0.1, so a fast shard spends that budget on logins alone and
# the next sign-in page is a 429 (#245). Raised rather than switched off, so
# the limiter stays in the request path; a rule with its own `rate=` (records'
# public forms) is unaffected.
#
# Exported rather than written with set_setting.py: a `host.rate_limit_public`
# row is read at boot too since #260, but the environment wins over it, so an
# export cannot be shadowed by a row a developer's own database already holds.
# Set here, before both `exec`s below, it reaches the bundle server,
# `make dev` and the multi-tenant run alike.
export SM_RATE_LIMIT_PUBLIC=100000/minute

# Multi-tenant runs only (E2E_MULTI_TENANT=1 → SM_MULTI_TENANT=true): resolve
# the tenant from the host, so `<slug>.localhost` addresses an organisation's
# public site the way an anonymous visitor would reach it. A spec names the
# subdomain in the Host header; plain `localhost` matches no tenant, so every
# other request resolves exactly as it did before.
if [[ "${SM_MULTI_TENANT:-}" == "true" ]]; then
  uv run python scripts/set_setting.py tenants subdomain_base localhost
fi

# E2E_BUNDLE=1: the build users get (#119). No Vite dev server and no
# --reload — playwright.config.ts sets SM_ENVIRONMENT=production for this
# mode, which is what makes the host read host/static/dist's manifest instead
# of pointing the page at a dev server. The bundle is built beforehand (CI's
# e2e-setup action, or `make e2e-bundle`) rather than here, so a build failure
# reports as a build failure and not as a webServer timeout. A missing
# manifest would boot fine and render every page without its scripts, which
# reads as 250 unrelated test failures, so refuse up front instead.
if [[ "${E2E_BUNDLE:-}" == "1" ]]; then
  manifest="host/static/dist/.vite/manifest.json"
  if [[ ! -f "${manifest}" ]]; then
    echo "E2E_BUNDLE=1 needs the production bundle (${manifest}); run \`npm run build\` first" >&2
    exit 1
  fi
  exec uv run --project host uvicorn main:app --app-dir host --port "${API_PORT:?}"
fi

exec make dev
