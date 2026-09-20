#!/usr/bin/env bash
# Entry point used by playwright.config.ts → webServer.command.
# Resets the test SQLite database, runs migrations, then hands off to
# `make dev`. Keeping this in a script (instead of chaining inside the
# Playwright config) lets us share the same logic across CI and local
# runs and gives Playwright a single PID to wait on / kill.
set -euo pipefail

if [[ -z "${SM_DATABASE_URL:-}" ]]; then
  echo "SM_DATABASE_URL must be set by playwright.config.ts" >&2
  exit 1
fi

# Extract the SQLite file path from a URL like
# sqlite+aiosqlite:////abs/path/to/test.db so we can `rm` it.
db_path="${SM_DATABASE_URL#sqlite+aiosqlite:///}"
if [[ "${db_path}" != /* ]]; then
  db_path="$(pwd)/${db_path}"
fi

rm -f "${db_path}" "${db_path}-wal" "${db_path}-shm"

# Migrations run from the repo root (alembic.ini resolves its script_location
# relative to itself), and `heads` rather than `head` because pagebuilder's
# first revision carries a branch label.
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
# `records-list.spec.ts` pages through 30 records and asserts an exact total,
# `records-schema-change.spec.ts` previews a type holding two — and low enough
# that `records-paging.spec.ts` / `records-preview.spec.ts` can seed past them
# over the API in seconds.
uv run python scripts/set_setting.py sm_records \
  max_count 32 \
  preview_sync_limit 3

exec make dev
