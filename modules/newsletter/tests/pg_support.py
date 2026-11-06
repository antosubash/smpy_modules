"""This suite's window onto the repo-level Postgres opt-in.

The decision - in-memory SQLite, or the Postgres database an environment
variable names - belongs to ``tests/pg_support.py`` at the repo root, which
every module reaches the same way. Everything about *why* it works the way it
does is documented there.

What is local to newsletter is only which tables a database needs, so that is
all this file holds. ``SM_TEST_DATABASE_URL`` selects the backend.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _shared() -> Any:
    """Load ``<repo>/tests/pg_support.py`` under a name of its own.

    By path rather than by import: ``modules/newsletter/tests`` is itself a
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
    """Table sets that are not ``sm_newsletter``'s but that the harness needs.

    Records always (subscribers are its tables); ``permissions`` only when it is
    installed.
    """
    from sm_records.models import Base as RecordsBase

    try:
        from permissions.models import Base as PermissionsBase
    except ImportError:  # pragma: no cover - exercised only without `permissions`
        return [RecordsBase.metadata]
    return [RecordsBase.metadata, PermissionsBase.metadata]


async def make_db_state(*, file: Path | None = None) -> Any:
    """A ``DatabaseState`` with an empty newsletter schema, on either backend.

    ``file`` gives SQLite one connection per session (see the shared helper),
    for a test about two sessions' transactions. ``sm_newsletter.models`` exists
    from the models task; imported lazily so the skeleton's tests do not need it.
    """
    from sm_newsletter.models import Base

    return await _pg.make_db_state(Base.metadata, *_extra_metadata(), file=file)
