"""Point the unit suite at Postgres instead of in-memory SQLite.

Everything in this directory has always run on ``sqlite+aiosqlite:///:memory:``
— see :mod:`tests.conftest` — and that is still the default, so CI and a
developer's ``pytest`` are unchanged by this module's existence. Setting

.. code-block:: console

   RECORDS_TEST_URL=postgresql+asyncpg://postgres@127.0.0.1:5433/records_unit

runs the *same* tests against a real Postgres database instead. The variable is
opt-in and read once, here; no test knows about it, and the two fixtures that
build a database (:func:`tests.conftest.db_state` and
:func:`tests.app_harness.build_app`) ask this module for one rather than
constructing it themselves.

**A fresh engine per test, not a session-scoped one.** ``asyncio_mode = "auto"``
with the default function loop scope gives every test its own event loop, and
an asyncpg pool is bound to the loop that created it — a session-scoped engine
would be reused from a loop it does not belong to and fail on the second test.
This is the same reasoning :mod:`tests.perf.conftest` records for ``perf_db``.

**The reset is ``TRUNCATE … RESTART IDENTITY CASCADE``, not ``drop_all`` +
``create_all``.** Two reasons, and only the second is about speed. The first is
that :func:`tests.conftest._clear_model_cache` exists because each test's
``:memory:`` database hands out ``type_id`` 1 afresh — a compiled validator is
cached per type id, so a suite where ids keep climbing would have tests sharing
a cache entry under ids that mean different things. ``RESTART IDENTITY`` is
what reproduces that on a database that persists between tests; a plain
``TRUNCATE`` would leave the sequences where they were and quietly break the
assumption that cache-clearing fixture is written against. The second is that
dropping and recreating ~40 tables per test costs more than the tests do.

``alembic_version`` is left alone: a database this suite runs against may have
been migrated rather than ``create_all``-ed, and truncating the version table
would make it look unmigrated to anything that checks.
"""

from __future__ import annotations

import os
from typing import Any

from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

TEST_URL = os.environ.get("RECORDS_TEST_URL", "").strip()
"""Empty — the default — means in-memory SQLite, exactly as before."""

USING_POSTGRES = TEST_URL.startswith("postgresql")
"""Read once at import. A test that needs to skip on one backend imports this
rather than sniffing the environment itself, so there is one spelling of the
question in the suite."""

SQLITE_URL = "sqlite+aiosqlite:///:memory:"

#: Set once the schema has been created in this process. ``create_all`` is
#: ``checkfirst=True`` and therefore idempotent, but it still costs a catalogue
#: round trip per table per test, and the answer cannot change mid-session:
#: collections are declared at *import* (``tests/collections_harness.py``), so
#: ``Base.metadata`` is complete before the first test runs.
_schema_ready = False

#: Whether the *next* ``make_db_state`` in this test should empty the database.
#: Armed once per test by :func:`arm_reset`; see it for why it is not simply
#: "truncate on every call".
_reset_pending = True


def arm_reset() -> None:
    """Say that a new test has started, so the next database is a clean one.

    **A test may build more than one ``DatabaseState``**, and on SQLite those
    are independent ``:memory:`` databases: ``tests/conftest.py``'s ``db_state``
    fixture and ``app_harness.build_app``'s default are two different databases
    that know nothing of each other, and a handful of tests take both. Against
    one Postgres database they are two engines over the *same* tables, so a
    ``make_db_state`` that truncated unconditionally would have the second
    fixture empty what the first one seeded — which is exactly how
    ``test_a_trashed_collection_record_is_hidden_from_a_plain_select`` failed,
    with its type deleted out from under a request that had already been made.

    Arming per test instead makes the first database of a test the clean one
    and every later database in that same test a second window onto it, which
    is the closest thing to the SQLite behaviour that one database can offer.
    """
    global _reset_pending
    _reset_pending = True


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


async def _truncate_all(conn: Any) -> None:
    """Empty every table in the search path and reset its identity sequences.

    Read out of ``pg_tables`` rather than walking ``Base.metadata``, because
    the database may also hold tables this process never declared — the
    ``permissions`` table above, and whatever a previously migrated database
    left behind — and a row surviving in one of those is exactly the kind of
    leakage between tests this is here to prevent.

    ``CASCADE`` because the index tables reference ``records_record`` and the
    revisions reference it too; truncating them one at a time in dependency
    order would be the same thing spelled less clearly.
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


async def make_db_state() -> Any:
    """A ``DatabaseState`` with an empty schema, on whichever backend is
    selected — the one call both database fixtures make.

    On SQLite this is byte-for-byte what :mod:`tests.conftest` did before:
    ``StaticPool`` so every session in a test talks to the same ``:memory:``
    database.
    """
    from sm_records.models import Base

    if not USING_POSTGRES:
        state = init_db(SQLITE_URL, poolclass=StaticPool)
        register_listeners(state)
        async with state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for metadata in _extra_metadata():
                await conn.run_sync(metadata.create_all)
        return state

    global _schema_ready, _reset_pending
    state = init_db(TEST_URL)
    register_listeners(state)
    async with state.engine.begin() as conn:
        if not _schema_ready:
            await conn.run_sync(Base.metadata.create_all)
            for metadata in _extra_metadata():
                await conn.run_sync(metadata.create_all)
            _schema_ready = True
        if _reset_pending:
            await _truncate_all(conn)
            _reset_pending = False
    return state
