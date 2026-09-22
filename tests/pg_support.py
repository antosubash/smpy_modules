"""Point a module's test suite at Postgres instead of in-memory SQLite.

Every suite in this repo builds its own database: ``sqlite+aiosqlite:///:memory:``
on a ``StaticPool``, created with ``metadata.create_all`` and thrown away when
the test ends. That is still the default, so ``pytest`` with no environment set
behaves exactly as it always has and CI's SQLite jobs are untouched by this
module's existence. Setting

.. code-block:: console

   SM_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5433/smpy_test

runs the *same* tests against a real Postgres database. One variable for every
module — ``records``, ``pagebuilder`` and ``news`` each reach this file through
a small shim in their own ``tests/`` directory, because only one of the three
is an importable package and none of them shares a ``sys.path`` root with the
others. ``RECORDS_TEST_URL`` is still read, as an alias, so the Postgres CI job
that predates the rename keeps working.

**A fresh engine per test, not a session-scoped one.** ``asyncio_mode = "auto"``
with the default function loop scope gives every test its own event loop, and
an asyncpg pool is bound to the loop that created it — a session-scoped engine
would be reused from a loop it does not belong to and fail on the second test.

**The reset is ``TRUNCATE … RESTART IDENTITY CASCADE``, not ``drop_all`` +
``create_all``.** Two reasons, and only the second is about speed. The first is
that a suite whose primary keys keep climbing is a different suite: records
caches a compiled validator per ``type_id`` and clears that cache per test on
the assumption that every test's first type is id 1, which is what a
``:memory:`` database gives for free and what ``RESTART IDENTITY`` reproduces
on a database that persists. The second is that dropping and recreating ~40
tables per test costs more than the tests do.

``alembic_version`` is left alone: a database this may run against could have
been migrated rather than ``create_all``-ed, and truncating the version table
would make it look unmigrated to anything that checks.

**A test database is built with ``create_all(checkfirst=True)``, which creates
missing tables and never alters an existing one** — so after a model change
(a new column, a new index) an existing Postgres test database has to be
dropped and recreated, or the whole suite errors on the column that is not
there.
"""

from __future__ import annotations

import os
from typing import Any

from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy import MetaData, text
from sqlalchemy.pool import StaticPool

ENV_VAR = "SM_TEST_DATABASE_URL"
"""The name every module in this repo agrees on."""

LEGACY_ENV_VARS = ("RECORDS_TEST_URL",)
"""Read after :data:`ENV_VAR` and kept working on purpose: the Postgres CI job
and ``modules/records/docs/postgres-2026-09-21.md`` both name it."""

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


def _resolve_url() -> str:
    for name in (ENV_VAR, *LEGACY_ENV_VARS):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


TEST_URL = _resolve_url()
"""Empty — the default — means in-memory SQLite, exactly as before."""

USING_POSTGRES = TEST_URL.startswith("postgresql")
"""Read once at import. A test that needs to skip on one backend imports this
rather than sniffing the environment itself, so there is one spelling of the
question in the repo."""

#: Metadata sets already created in this process, by ``id()``. ``create_all``
#: is ``checkfirst=True`` and therefore idempotent, but it still costs a
#: catalogue round trip per table per test, and the answer cannot change
#: mid-session.
_schema_ready: set[int] = set()

#: Whether the *next* :func:`make_db_state` in this test should empty the
#: database. Armed once per test by :func:`arm_reset`.
_reset_pending = True


def arm_reset() -> None:
    """Say that a new test has started, so the next database is a clean one.

    **A test may build more than one database**, and on SQLite those are
    independent ``:memory:`` instances that know nothing of each other — a
    bare ``db_state`` fixture and the one inside an HTTP client's app, say.
    Against one Postgres database they are two engines over the *same* tables,
    so a :func:`make_db_state` that truncated unconditionally would have the
    second fixture empty what the first one seeded.

    Arming per test instead makes the first database of a test the clean one
    and every later database in that same test a second window onto it, which
    is the closest thing to the SQLite behaviour that one database can offer.
    """
    global _reset_pending
    _reset_pending = True


async def _truncate_all(conn: Any) -> None:
    """Empty every table in the search path and reset its identity sequences.

    Read out of ``pg_tables`` rather than walking the metadata, because the
    database may also hold tables this process never declared — another
    module's, or whatever a previously migrated database left behind — and a
    row surviving in one of those is exactly the leakage this prevents.

    ``CASCADE`` because these schemas are full of foreign keys; truncating in
    dependency order would be the same thing spelled less clearly.
    """
    rows = await conn.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = current_schema() AND tablename <> 'alembic_version'"
        )
    )
    names = [f'"{row[0]}"' for row in rows]
    if not names:
        return
    await conn.execute(text(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE"))


async def make_db_state(*metadatas: MetaData) -> Any:
    """A ``DatabaseState`` holding ``metadatas``' tables and no rows.

    The one call every database fixture in the repo makes. On SQLite it is
    byte-for-byte what those fixtures did inline before: ``StaticPool``, so
    every session in a test talks to the same ``:memory:`` database.
    """
    if not USING_POSTGRES:
        state = init_db(SQLITE_URL, poolclass=StaticPool)
        register_listeners(state)
        async with state.engine.begin() as conn:
            for metadata in metadatas:
                await conn.run_sync(metadata.create_all)
        return state

    global _reset_pending
    state = init_db(TEST_URL)
    register_listeners(state)
    async with state.engine.begin() as conn:
        for metadata in metadatas:
            if id(metadata) not in _schema_ready:
                await conn.run_sync(metadata.create_all)
                _schema_ready.add(id(metadata))
        if _reset_pending:
            await _truncate_all(conn)
            _reset_pending = False
    return state
