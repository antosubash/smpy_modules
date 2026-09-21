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

import itertools
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
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.app_harness import build_app
from tests.perf._bench import Results
from tests.perf._schema import create_missing_columns, create_missing_indexes

DATABASE_URL = os.environ.get("RECORDS_PERF_URL", "")
"""Run the suite against this database instead of a SQLite file.

The whole study has been SQLite until now, and every previous round said so in
its own "On Postgres" section — the statement counts are a property of the code
and travel, but two of F5's findings are SQLite planner choices and were
explicitly left unverified. Point this at a Postgres URL
(``postgresql+asyncpg://…``) and the same measurements run there, with
:func:`tests.perf._bench.explain` switching to Postgres's ``EXPLAIN``.

All 49 measurements run on both backends. :func:`perf_db_copy`, which the
schema-operation and per-feature files need because they mutate the database
they measure, used to copy a SQLite file and so skipped 19 of them on
Postgres; it uses ``CREATE DATABASE … TEMPLATE`` there now (see the fixture),
which is the same operation by the server's own means."""

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
        await conn.run_sync(create_missing_columns)
        await conn.run_sync(create_missing_indexes)

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


_copies = itertools.count()


async def _postgres_copy(source_url: str) -> tuple[str, str]:
    """``CREATE DATABASE … TEMPLATE`` — Postgres's answer to ``cp``.

    The server copies the template's files itself, so this is the same
    operation as the SQLite branch's ``shutil.copyfile`` and costs about as
    much. It is the reason the schema-operation, import/export, reindex and
    i18n measurements can run on Postgres at all: until this existed they
    skipped, and the previous Postgres round could say nothing about the
    write-heavy half of the suite.

    Two constraints shape it. ``CREATE DATABASE`` cannot run inside a
    transaction, hence ``AUTOCOMMIT``; and it refuses while **any** session is
    connected to the template, which is why the caller disposes ``perf_db``'s
    engine first. The name carries the process id as well as a counter because
    a second pytest process against the same cluster would otherwise collide
    on ``…_copy_0``.
    """
    admin_url = source_url.rsplit("/", 1)[0] + "/postgres"
    source_name = source_url.rsplit("/", 1)[1].split("?")[0]
    # Postgres truncates identifiers at 63 bytes; the prefix keeps it short
    # enough that the suffix is never what gets cut.
    target_name = f"{source_name[:40]}_c{os.getpid()}_{next(_copies)}"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{target_name}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{target_name}" TEMPLATE "{source_name}"'))
    finally:
        await engine.dispose()
    return admin_url, f"{source_url.rsplit('/', 1)[0]}/{target_name}"


async def _drop_postgres_copy(admin_url: str, target_url: str) -> None:
    name = target_url.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def perf_db_copy(perf_db, tmp_path) -> AsyncIterator[Any]:
    """A throwaway copy of the seeded database.

    The schema-operation measurements mutate the type they run against —
    applying a change, toggling ``indexed``, discarding orphaned values — and
    a suite that leaves the seeded database in a different shape than it found
    it is not repeatable. Copying is seconds even at 100k records, and far
    cheaper than reseeding.

    Both backends copy, by their own means: a file on SQLite, ``CREATE
    DATABASE … TEMPLATE`` on Postgres. Either way ``perf_db``'s engine is
    disposed first — SQLite so the file is not copied mid-write, Postgres
    because the server refuses to use a template that has a connection open.
    """
    import shutil

    await perf_db.engine.dispose()
    if DATABASE_URL:
        admin_url, target_url = await _postgres_copy(DATABASE_URL)
        state = init_db(target_url)
        register_listeners(state)
        try:
            yield state
        finally:
            await state.engine.dispose()
            await _drop_postgres_copy(admin_url, target_url)
        return

    source = _db_path()
    target = tmp_path / "records_perf_copy.db"
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
