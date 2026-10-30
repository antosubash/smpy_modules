"""This suite's window onto the repo-level Postgres opt-in.

The decision — in-memory SQLite, or the Postgres database an environment
variable names — belongs to ``tests/support/pg.py`` at the repo root, which
``pagebuilder`` and ``news`` reach the same way. Everything about *why* it
works the way it does is documented there: one engine per test, why the reset
is ``TRUNCATE … RESTART IDENTITY CASCADE`` and why it is armed per test rather
than run per database.

What is local to images is only which tables a database needs, so that is all
this file holds.

``SM_TEST_DATABASE_URL`` selects the backend; every module in the repo reads it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _shared() -> Any:
    """Load ``<repo>/tests/support/pg.py`` under a name of its own.

    By path rather than by import: ``modules/images/tests`` is itself a
    package called ``tests`` and is what ``import tests.support.pg`` would
    find while this suite runs. The repo root is three directories up.
    """
    name = "smpy_tests_pg_support"
    module = sys.modules.get(name)
    if module is None:
        path = Path(__file__).resolve().parents[4] / "tests" / "pg_support.py"
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
    """Table sets that are not ``sm_images``'s but that the harness needs.

    ``sharing`` always: the access policy's ``EXISTS`` names its table.
    ``permissions`` only when it is installed — see the import guard in
    :mod:`tests.support.app_harness` for why its table has to exist even though this
    module's ``Base`` never declares it.
    """
    from sharing.models import Base as SharingBase

    try:
        from permissions.models import Base as PermissionsBase
    except ImportError:  # pragma: no cover - exercised only without `permissions`
        return [SharingBase.metadata]
    return [SharingBase.metadata, PermissionsBase.metadata]


async def make_db_state(*, file: Path | None = None) -> Any:
    """A ``DatabaseState`` with an empty images schema, on either backend.

    ``file`` gives SQLite one connection per session (see the shared helper),
    for a test about two sessions' transactions.
    """
    from sm_images.models import Base

    return await _pg.make_db_state(Base.metadata, *_extra_metadata(), file=file)
