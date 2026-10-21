#!/bin/sh
# Container entry point for the demo host image (see the Dockerfile).
#
# Applies the migrations, then hands the process over to uvicorn serving the
# pre-built UI. Runs from /app, the image's copy of the repo root, for the same
# reason every entry point does locally: alembic.ini resolves its
# script_location relative to itself and the app is loaded with
# `--app-dir host` (see CLAUDE.md, "Run Python entry points from the repo
# root").
#
# Arguments, when given, replace the server: `docker compose run --rm host
# python scripts/set_setting.py ...` runs that command after the migrations.
set -eu

cd /app
alembic -c host/alembic.ini upgrade heads

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn main:app --app-dir host --host 0.0.0.0 --port "${PORT:-8000}"
