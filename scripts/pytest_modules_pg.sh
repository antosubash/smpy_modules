#!/usr/bin/env bash
# Run each module's pytest against Postgres, every one on a database of its own
# and every one even after a failure (#360).
#
#   scripts/pytest_modules_pg.sh                    # every modules/*/
#   scripts/pytest_modules_pg.sh pagebuilder news   # just these
#
# The Postgres twin of scripts/pytest_modules.sh, and the same default list
# (`modules/*/`), so a new module runs on Postgres without editing ci.yml. For
# each module it creates `<PG_DB_PREFIX><module>` (default prefix `ci_`, so
# `ci_records`, `ci_ai`, …) with createdb, then runs scripts/pytest_modules.sh
# for that module with SM_TEST_DATABASE_URL pointing at it. A database that
# already exists is an error: the suites reset their database their own way
# and must not inherit another run's rows.
#
# Connection: libpq's PGHOST, PGPORT, PGUSER and PGPASSWORD (defaults
# localhost, 5432, postgres, postgres), used by createdb and, unescaped, in the
# asyncpg URL. PYTEST_WORKERS and PYTEST_ADDOPTS reach pytest_modules.sh as
# they are; records also gets `-q -p no:cacheprovider`, as its CI step always
# had. The records perf smoke is not run here: it wants a database of its own
# and a different invocation (ci.yml's "records perf smoke" step).
#
# Run from the repo root (CI does).
set -uo pipefail

export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-postgres}" PGPASSWORD="${PGPASSWORD:-postgres}"
prefix="${PG_DB_PREFIX:-ci_}"

if [ $# -gt 0 ]; then
  names=("$@")
else
  names=()
  for d in modules/*/; do names+=("$(basename "$d")"); done
fi

failed=()
for name in "${names[@]}"; do
  db="${prefix}${name}"
  if ! createdb "$db"; then
    failed+=("$name")
    echo "::error title=pytest $name (Postgres)::could not create database $db"
    continue
  fi
  addopts="${PYTEST_ADDOPTS:-}"
  if [ "$name" = records ]; then addopts="$addopts -q -p no:cacheprovider"; fi
  url="postgresql+asyncpg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${db}"
  if ! SM_TEST_DATABASE_URL="$url" PYTEST_ADDOPTS="$addopts" scripts/pytest_modules.sh "$name"; then
    failed+=("$name")
  fi
done

if [ ${#failed[@]} -gt 0 ]; then
  echo "::error::pytest (Postgres) failed in: ${failed[*]}"
  exit 1
fi
