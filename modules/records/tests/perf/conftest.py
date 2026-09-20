"""Fixtures for the perf suite: one seeded, file-backed SQLite database.

File-backed and not ``:memory:`` on purpose — the numbers are supposed to
include the I/O a real install pays, and an in-memory database makes every
page read look like a hash lookup.

The database is seeded once per size and then *reused across runs*: seeding
goes through the real services (``sm_records.seed``), which is the slowest
thing in this directory by an order of magnitude. ``RECORDS_PERF_DB`` points
the suite at a database seeded elsewhere — that is how the 100k study is run
without waiting half an hour inside pytest.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.models import Base, Record, RecordType
from sm_records.settings import RecordsSettings
from sqlalchemy import func, inspect, select

from tests.app_harness import build_app
from tests.perf._bench import Results

DATABASE_URL = os.environ.get("RECORDS_PERF_URL", "")
"""Run the suite against this database instead of a SQLite file.

The whole study has been SQLite until now, and every previous round said so in
its own "On Postgres" section — the statement counts are a property of the code
and travel, but two of F5's findings are SQLite planner choices and were
explicitly left unverified. Point this at a Postgres URL
(``postgresql+asyncpg://…``) and the same measurements run there, with
:func:`tests.perf._bench.explain` switching to Postgres's ``EXPLAIN``.

What does **not** work there is :func:`perf_db_copy`, which copies a file. The
schema-operation and per-feature files that mutate their database therefore
skip on a non-SQLite backend; the read path, the pagination and the aggregate
— which is where the unverified findings are — run unchanged."""

DATASET_SIZE = int(os.environ.get("RECORDS_PERF_N", "2000"))
"""Total records across the five demo types. Small by default so a developer
can run the suite in a minute; the study runs at 100000."""

REPS = int(os.environ.get("RECORDS_PERF_REPS", "20"))
"""Timed repetitions after the warm-up, per measurement."""

TYPE_KEYS = ("company", "contact", "product", "store", "order")


def _db_path() -> Path:
    override = os.environ.get("RECORDS_PERF_DB")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / f"records_perf_{DATASET_SIZE}.db"


_seeded: set[str] = set()


def _create_missing_indexes(conn: Any) -> None:
    """Add any index the model declares that the database does not have yet.

    ``create_all`` is ``checkfirst`` per *table*: a database seeded before a
    revision added an index to an existing table is skipped whole, so the
    suite would keep measuring the old schema against the new code and report
    the new indexes as doing nothing. The seeded file is reused across runs on
    purpose (it is the slowest thing here), which is exactly the case this
    covers — and creating an index that is already there is a no-op, so it is
    also safe on a fresh one.

    **Backend-independent since S2.** It used to read ``sqlite_master`` and
    return early on anything else, on the grounds that a Postgres run is always
    against a database seeded by the same revision. That was true until a
    revision added an index and the before/after pair had to be taken on one
    Postgres database — which is precisely what this function exists for.
    ``inspect`` answers the same question on both backends.

    **And it ``ANALYZE``s what it touched**, which is not tidiness. A new index
    with no ``sqlite_stat1`` row is not "unknown" to SQLite's planner, it is
    *assumed to be very selective* — so on a database whose other indexes were
    analysed by the seeder it wins every lookup it is eligible for, and a list
    page that took 1.1 ms takes 26.5 ms driving from the wrong one. That is a
    property of a half-analysed database, not of the index, and a suite that
    left the file in that state would be measuring a deployment nobody has:
    the revision that creates these indexes runs ``ANALYZE`` too
    (``c4a17b9de0f2``), for the same reason.
    """
    inspector = inspect(conn)
    created: set[str] = set()
    for table in Base.metadata.tables.values():
        if not inspector.has_table(table.name):
            continue
        have = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have:
                index.create(conn)
                created.add(table.name)
    if created and conn.dialect.name == "sqlite":
        for name in sorted(created):
            conn.exec_driver_sql(f"ANALYZE {name}")


def _create_missing_columns(conn: Any) -> None:
    """Add any **column** the model declares that a reused database lacks.

    The sibling of :func:`_create_missing_indexes`, and for the same reason:
    ``create_all`` is ``checkfirst`` per *table*, so a file seeded before an
    additive migration is skipped whole and every later query selects a column
    the file does not have — which is a ``no such column`` on the first read,
    not a wrong measurement. Phase 5 §6.2's nullable ``records_type.collection``
    is what made this concrete.

    Only additive, nullable columns can be recovered this way, which is exactly
    the class of change a reusable perf fixture can absorb: anything else means
    the cached database is the wrong dataset and should be deleted.
    """
    if conn.dialect.name != "sqlite":
        return
    for table in Base.metadata.tables.values():
        rows = conn.exec_driver_sql(f"PRAGMA table_info('{table.name}')").fetchall()
        if not rows:
            continue
        have = {row[1] for row in rows}
        for column in table.columns:
            if column.name in have or not column.nullable:
                continue
            ddl = column.type.compile(dialect=conn.dialect)
            conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}')


async def _record_total(db_state: Any) -> int:
    async with db_state.session_factory() as session:
        return int((await session.execute(select(func.count(Record.id)))).scalar_one())


@pytest_asyncio.fixture
async def perf_db() -> AsyncIterator[Any]:
    """A seeded ``DatabaseState`` over a file-backed SQLite database.

    A fresh engine per test rather than a session-scoped one: the database is
    a file, so reconnecting costs microseconds, and a session-scoped async
    engine would be bound to an event loop the function-scoped tests do not
    run on.
    """
    path = _db_path()
    if DATABASE_URL:
        state = init_db(DATABASE_URL)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        state = init_db(f"sqlite+aiosqlite:///{path}")
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_create_missing_columns)
        await conn.run_sync(_create_missing_indexes)

    marker = DATABASE_URL or str(path)
    if marker not in _seeded:
        have = await _record_total(state)
        if have < DATASET_SIZE:
            from sm_records.seed import seed_database

            await seed_database(
                state, RecordsSettings(), records=DATASET_SIZE - have, seed=42, reset=False
            )
        _seeded.add(marker)
    try:
        yield state
    finally:
        await state.engine.dispose()


@pytest_asyncio.fixture
async def perf_db_copy(perf_db, tmp_path) -> AsyncIterator[Any]:
    """A throwaway copy of the seeded database.

    The schema-operation measurements mutate the type they run against —
    applying a change, toggling ``indexed``, discarding orphaned values — and
    a suite that leaves the seeded file in a different shape than it found it
    is not repeatable. Copying the file is seconds even at 100k records, and
    far cheaper than reseeding.
    """
    import shutil

    if DATABASE_URL:
        pytest.skip("perf_db_copy copies a SQLite file; RECORDS_PERF_URL has no equivalent")
    source = _db_path()
    target = tmp_path / "records_perf_copy.db"
    await perf_db.engine.dispose()
    shutil.copyfile(source, target)
    state = init_db(f"sqlite+aiosqlite:///{target}")
    register_listeners(state)
    try:
        yield state
    finally:
        await state.engine.dispose()


@pytest_asyncio.fixture
async def perf_session(perf_db) -> AsyncIterator[Any]:
    async with perf_db.session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def perf_client(perf_db, tmp_path) -> AsyncIterator[AsyncClient]:
    """The real endpoints, wired to the seeded database."""
    app, _ = await build_app(tmp_path, perf_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        http_client.app = app  # type: ignore[attr-defined]
        yield http_client


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


async def load_type(session: Any, key: str) -> RecordType:
    return (
        (await session.execute(select(RecordType).where(RecordType.key == key))).scalars().first()
    )


async def indexed_fields(session: Any, key: str) -> dict[str, str]:
    """``{field key: field type}`` for the indexed fields of one type.

    The perf cases name fields of the demo dataset, and a demo type whose
    shape changes should make a measurement *skip with a note* rather than
    fail — the suite is an instrument, not a schema test.
    """
    rtype = await load_type(session, key)
    if rtype is None:
        return {}
    return {
        str(raw.get("key")): str(raw.get("type"))
        for raw in (rtype.fields or [])
        if raw.get("indexed")
    }


async def type_counts(session: Any) -> dict[str, int]:
    rows = (
        await session.execute(
            select(RecordType.key, func.count(Record.id))
            .join(Record, Record.type_id == RecordType.id)
            .group_by(RecordType.key)
        )
    ).all()
    return {key: int(count) for key, count in rows}


@pytest.fixture(autouse=True)
def _empty_preview_jobs():
    """No preview job survives into the next measurement.

    ``services.preview_jobs`` is a process-global registry keyed by type key,
    type version and proposed fields — which is exactly right for a host
    serving one database and exactly wrong for a suite that runs several
    measurements against *copies* of one. Without this, the preview measured
    in ``test_preview_job`` is still "completed" when
    ``test_apply_restrictive_with_force`` applies the same change to a fresh
    copy of the same database, the apply reuses its report (as it is designed
    to) and the number recorded is not the one the row claims.
    """
    from sm_records.services import preview_jobs

    preview_jobs._jobs.clear()
    yield
    preview_jobs._jobs.clear()


@pytest.fixture(scope="session", autouse=True)
def _print_results() -> AsyncIterator[None]:
    yield
    print(f"\n\n=== records perf results (N={DATASET_SIZE}, reps={REPS}) ===")
    print(Results.render())
