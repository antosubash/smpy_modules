#!/bin/sh
# Container entry point for the demo host image (see the Dockerfile).
#
# Applies the migrations (unless SMPY_MIGRATE_ON_START=0), then hands the process over to uvicorn serving the
# pre-built UI. Runs from /app, the image's copy of the repo root, for the same
# reason every entry point does locally: alembic.ini resolves its
# script_location relative to itself and the app is loaded with
# `--app-dir host` (see CLAUDE.md, "Run Python entry points from the repo
# root").
#
# Arguments, when given, replace the server: `docker compose run --rm host
# python scripts/set_setting.py ...` runs that command after the migrations.
#
# Migrating on start suits the one container compose.yaml runs. Nothing locks
# the upgrade across processes, so several replicas starting together would run
# the same DDL concurrently: run more than one with SMPY_MIGRATE_ON_START=0 and
# apply the migrations once, beforehand, as a one-off job
# (`docker compose run --rm -e SMPY_MIGRATE_ON_START=1 host true`).
set -eu

cd /app
case "${SMPY_MIGRATE_ON_START:-1}" in
  1 | true | yes) alembic -c host/alembic.ini upgrade heads ;;
  0 | false | no) echo "smpy-entrypoint: SMPY_MIGRATE_ON_START=0, skipping migrations" >&2 ;;
  *) echo "smpy-entrypoint: SMPY_MIGRATE_ON_START must be 1 or 0, got '${SMPY_MIGRATE_ON_START}'" >&2; exit 64 ;;
esac

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn main:app --app-dir host --host 0.0.0.0 --port "${PORT:-8000}"
