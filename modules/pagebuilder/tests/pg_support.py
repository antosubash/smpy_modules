"""This suite's window onto the repo-level Postgres opt-in.

The decision — in-memory SQLite, or the Postgres database an environment
variable names — belongs to ``tests/pg_support.py`` at the repo root, which
``records`` and ``news`` reach the same way. Everything about *why* it works
the way it does is documented there: one engine per test, why the reset is
``TRUNCATE … RESTART IDENTITY CASCADE`` and why it is armed once per test
rather than run once per database.

What is local to pagebuilder is only which tables a database needs, so that is
all this file holds. Five fixtures across ``conftest.py``, ``db_fixture.py``,
``snapshot_fixture.py`` and ``test_scheduled_publish.py`` used to spell the
in-memory URL out themselves; they all call :func:`make_db_state` now, which
is what makes ``SM_TEST_DATABASE_URL`` reach the whole suite rather than the
part of it that goes through an HTTP client.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _shared() -> Any:
    """Load ``<repo>/tests/pg_support.py`` under a name of its own.

    By path rather than by import: this directory is on ``sys.path`` while the
    suite runs and the repo root is not, so there is no import to make. The
    repo root is three directories up.
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

arm_reset = _pg.arm_reset


async def make_db_state() -> Any:
    """A ``DatabaseState`` with an empty pagebuilder schema, on either backend."""
    from pagebuilder.models import Base

    return await _pg.make_db_state(Base.metadata)
