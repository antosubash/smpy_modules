"""The e2e seeding script writes straight to a database, so it refuses by default."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "tests" / "e2e" / "seed_images_review.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("seed_images_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.guard


OK = {
    "SM_E2E_SEED": "1",
    "SM_ENVIRONMENT": "development",
    "SM_DATABASE_URL": "sqlite+aiosqlite:////repo/host/test.db",
}


def test_the_e2e_database_with_the_opt_in_is_allowed(guard):
    assert guard(OK) is None
    pg = {**OK, "SM_DATABASE_URL": "postgresql+asyncpg://u:p@localhost/smpy_modules_e2e"}
    assert guard(pg) is None


@pytest.mark.parametrize(
    "change",
    [
        {"SM_E2E_SEED": ""},
        {"SM_ENVIRONMENT": "production"},
        {"SM_DATABASE_URL": ""},
        {"SM_DATABASE_URL": "sqlite+aiosqlite:////repo/host/app.db"},
        {"SM_DATABASE_URL": "postgresql+asyncpg://u:p@db.prod/smpy_modules"},
        {"SM_DATABASE_URL": "postgresql+asyncpg://u:p@db/latest"},
    ],
)
def test_anything_else_is_refused(guard, change):
    assert guard({**OK, **change})
