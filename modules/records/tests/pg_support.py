"""This suite's window onto the repo-level Postgres opt-in.

The decision — in-memory SQLite, or the Postgres database an environment
variable names — belongs to ``tests/pg_support.py`` at the repo root, which
``pagebuilder`` and ``news`` reach the same way. Everything about *why* it
works the way it does is documented there: one engine per test, why the reset
is ``TRUNCATE … RESTART IDENTITY CASCADE`` and why it is armed per test rather
than run per database.

What is local to records is only which tables a database needs, so that is all
this file holds.

``RECORDS_TEST_URL`` still selects the backend; it is now an alias for
``SM_TEST_DATABASE_URL``, which every module in the repo reads.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy.pool import StaticPool


def _shared() -> Any:
    """Load ``<repo>/tests/pg_support.py`` under a name of its own.

    By path rather than by import: ``modules/records/tests`` is itself a
    package called ``tests`` and is what ``import tests.pg_support`` would
    find while this suite runs. The repo root is three directories up.
    """
    name = "smpy_tests_pg_support"
    module = sys.modules.get(name)
    if module is None:
        path = Path(__file__).resolve().parents[3] / "tests" / "pg_support.py"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


_pg = _shared()

TEST_URL: str = _pg.TEST_URL
USING_POSTGRES: bool = _pg.USING_POSTGRES
SQLITE_URL: str = _pg.SQLITE_URL
arm_reset = _pg.arm_reset


def _extra_metadata() -> list[Any]:
    """Table sets that are not ``sm_records``'s but that the harness needs.

    ``permissions`` only when it is installed — see the import guard in
    :mod:`tests.app_harness` for why its table has to exist even though this
    module's ``Base`` never declares it.
    """
    try:
        from permissions.models import Base as PermissionsBase
    except ImportError:  # pragma: no cover - exercised only without `permissions`
        return []
    return [PermissionsBase.metadata]


async def make_db_state() -> Any:
    """A ``DatabaseState`` with an empty records schema, on either backend."""
    from sm_records.models import Base

    return await _pg.make_db_state(Base.metadata, *_extra_metadata())


async def make_sqlite_db_state() -> Any:
    """In-memory SQLite, whatever ``SM_TEST_DATABASE_URL`` says.

    For the tests that are *about* SQLite rather than merely willing to run on
    it — pysqlite's transaction control is a behaviour of that driver, and a
    test of it that quietly became a Postgres test on the Postgres job would
    stop covering the thing it was written for. Everything else goes through
    :func:`make_db_state` and runs on whichever backend the suite was pointed
    at.

    The body is the SQLite branch of the shared ``make_db_state``:
    ``StaticPool``, so every session in the test talks to the same
    ``:memory:`` database, and ``register_listeners``, because the
    soft-delete filter is an ORM execute hook rather than a column default.
    """
    from sm_records.models import Base

    state = init_db(_pg.SQLITE_URL, poolclass=StaticPool)
    register_listeners(state)
    async with state.engine.begin() as conn:
        for metadata in (Base.metadata, *_extra_metadata()):
            await conn.run_sync(metadata.create_all)
    return state
