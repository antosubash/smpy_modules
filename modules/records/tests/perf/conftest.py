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
from sqlalchemy import func, select

from tests.app_harness import build_app
from tests.perf._bench import Results

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
    """
    have = {
        row[0]
        for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            if index.name not in have:
                index.create(conn)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    state = init_db(f"sqlite+aiosqlite:///{path}")
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_create_missing_indexes)

    if str(path) not in _seeded:
        have = await _record_total(state)
        if have < DATASET_SIZE:
            from sm_records.seed import seed_database

            await seed_database(
                state, RecordsSettings(), records=DATASET_SIZE - have, seed=42, reset=False
            )
        _seeded.add(str(path))
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
