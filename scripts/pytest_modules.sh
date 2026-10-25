#!/usr/bin/env bash
# Run pytest in each module directory, every one even after a failure.
#
#   scripts/pytest_modules.sh                    # every modules/*/
#   scripts/pytest_modules.sh pagebuilder news   # just these
#
# From within each module, so each picks up its own
# `[tool.pytest.ini_options]` (e.g. `asyncio_mode = "auto"`). The default list
# is `modules/*/`, as in `make test-py`, so a new module is tested without
# editing a workflow (#118). Each module gets its own log group and, on
# failure, an annotation naming it; the script exits non-zero at the end, so
# one run shows every broken module rather than only the first.
#
# Extra pytest arguments go through PYTEST_ADDOPTS, and the environment
# (SM_TEST_DATABASE_URL, say) reaches every module unchanged. Each suite runs
# on PYTEST_WORKERS pytest-xdist workers (default `auto`, one per core; `0`
# runs serially); under xdist, simple_module_test gives every worker its own
# `<SM_TEST_DATABASE_URL's database>_gwN` Postgres database.
#
# Run from the repo root (CI does).
set -uo pipefail

if [ $# -gt 0 ]; then
  dirs=()
  for name in "$@"; do dirs+=("modules/$name/"); done
else
  dirs=(modules/*/)
fi

failed=()
for d in "${dirs[@]}"; do
  name=$(basename "$d")
  if [ ! -d "$d/tests" ]; then
    failed+=("$name")
    echo "::error title=pytest $name::modules/$name has no tests/ directory"
    continue
  fi
  echo "::group::pytest $name"
  if ! (cd "$d" && uv run pytest -n "${PYTEST_WORKERS:-auto}"); then
    failed+=("$name")
    echo "::error title=pytest $name::pytest failed in modules/$name"
  fi
  echo "::endgroup::"
done

if [ ${#failed[@]} -gt 0 ]; then
  echo "::error::pytest failed in: ${failed[*]}"
  exit 1
fi
