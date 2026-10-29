"""The e2e seeding script writes straight to a database, so it refuses by default."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tests" / "e2e" / "seed_images_review.py"
PG = "postgresql+asyncpg://u:p@localhost/smpy_modules_e2e"


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
    "SM_DATABASE_URL": f"sqlite+aiosqlite:///{ROOT / 'host' / 'test.db'}",
}


def test_the_e2e_sqlite_file_with_the_opt_in_is_allowed(guard):
    assert guard(OK) is None
    assert guard({**OK, "SM_ENVIRONMENT": "testing"}) is None


def test_a_postgres_run_needs_the_database_the_spec_names(guard):
    pg = {**OK, "SM_DATABASE_URL": PG}
    assert guard(pg)  # nothing names it
    assert guard({**pg, "SM_E2E_DATABASE": PG}) is None
    assert guard({**pg, "SM_E2E_DATABASE": PG.replace("_e2e", "_prod")})


@pytest.mark.parametrize(
    "change",
    [
        {"SM_E2E_SEED": ""},
        {"SM_ENVIRONMENT": "production"},
        {"SM_ENVIRONMENT": "prod"},
        {"SM_ENVIRONMENT": "staging"},
        {"SM_ENVIRONMENT": ""},
        {"SM_DATABASE_URL": ""},
        {"SM_DATABASE_URL": "sqlite+aiosqlite:////repo/host/app.db"},
        {"SM_DATABASE_URL": "sqlite+aiosqlite:////elsewhere/host/test.db"},  # look-alike
        {"SM_DATABASE_URL": "sqlite+aiosqlite:////elsewhere/other_test.db"},
    ],
)
def test_anything_else_is_refused(guard, change):
    assert guard({**OK, **change})


def test_a_lookalike_postgres_name_is_not_enough(guard):
    prod_like = "postgresql+asyncpg://u:p@db.prod/smpy_modules_test"
    assert guard({**OK, "SM_DATABASE_URL": prod_like})
    assert guard({**OK, "SM_DATABASE_URL": prod_like, "SM_E2E_DATABASE": PG})


@pytest.mark.parametrize(
    "url",
    [
        "mysql+aiomysql://u:p@localhost/smpy_modules_e2e",
        "mssql+aioodbc://u:p@localhost/smpy_modules_e2e",
        "oracle+oracledb://u:p@localhost/smpy_modules_e2e",
    ],
)
def test_another_dialect_is_refused_even_when_the_spec_names_it(guard, url):
    assert guard({**OK, "SM_DATABASE_URL": url, "SM_E2E_DATABASE": url})


def test_plain_postgresql_driver_is_allowed(guard):
    url = "postgresql://u:p@localhost/smpy_modules_e2e"
    assert guard({**OK, "SM_DATABASE_URL": url, "SM_E2E_DATABASE": url}) is None
