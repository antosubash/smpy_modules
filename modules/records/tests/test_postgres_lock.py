"""The per-type lock, on the database whose branch of it has never been run.

:func:`sm_records.services._claims.lock_type` has two implementations — a
no-op ``UPDATE records_type SET version = version`` that takes SQLite's
``RESERVED`` lock, and ``SELECT … FOR UPDATE`` everywhere else. Until this
file, only the first was ever executed: ``tests/test_unique_concurrency.py``
races eight writers against a SQLite *file*, and
``test_lock_type_is_a_write_on_sqlite_and_a_row_lock_elsewhere`` pins the
Postgres branch by compiling it, which proves the statement is emitted and
nothing about whether it holds.

This file runs the same claims against Postgres, and only against Postgres:
every test here skips unless ``RECORDS_TEST_URL`` names one (see
:mod:`tests.pg_support`). Twenty writers rather than the other file's eight,
because ``FOR UPDATE`` queues every waiter on one row and twenty is enough for
a lock that does not actually block to show up as several winners rather than
as an unlucky two.

**Through the service layer, on a session per writer.** The lock serialises
transactions, so each writer needs its own connection — an ``AsyncClient``
would give them that too, but through a request pipeline whose own commit
ordering is a second thing that could explain a pass.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import pytest
import pytest_asyncio
from sm_records.models import Record, RecordType
from sm_records.schema.types import FieldType
from sm_records.services._type_update import update_type
from sm_records.services.errors import Conflict, RecordsError
from sm_records.services.records import create_record
from sm_records.settings import RecordsSettings
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.pg_support import USING_POSTGRES, make_db_state

pytestmark = pytest.mark.skipif(
    not USING_POSTGRES,
    reason="the FOR UPDATE branch of lock_type only exists on Postgres; "
    "set RECORDS_TEST_URL=postgresql+asyncpg://…",
)

WRITERS = 20
"""Wide enough that a lock which does not hold loses visibly. Eight — the
number ``test_unique_concurrency`` uses — was chosen for SQLite's write queue;
nothing here waits on one."""

SETTINGS = RecordsSettings()


def _field(key: str, **overrides: Any) -> dict[str, Any]:
    definition = {"key": key, "type": "text", "label": key.title(), "indexed": True}
    definition.update(overrides)
    return definition


@pytest_asyncio.fixture
async def pg_state() -> Any:
    """A truncated Postgres database on the pooled engine.

    Not ``StaticPool`` and not a shared session: ``make_db_state`` hands back
    the ordinary pooled engine, so ``session_factory()`` inside a task gets a
    connection of its own and twenty of them are twenty transactions.
    """
    state = await make_db_state()
    yield state
    await state.engine.dispose()


async def _seed_type(state: Any, key: str, fields: list[dict], **cols: Any) -> int:
    async with state.session_factory() as session:
        rtype = RecordType(
            key=key,
            label=key.title(),
            label_plural=f"{key.title()}s",
            fields=fields,
            **cols,
        )
        session.add(rtype)
        await session.commit()
        return int(rtype.id)


async def _one_create(state: Any, type_id: int, data: dict[str, Any]) -> str:
    """One writer: its own session, its own transaction, its own outcome.

    The outcome is a short string rather than an exception so ``gather`` need
    not run with ``return_exceptions`` and hide an unexpected failure among
    the expected ones. ``IntegrityError`` is caught separately because "the
    database refused it and nothing turned that into a 409" is the exact
    regression :func:`sm_records.services._claims.flush_write` prevents, and a
    test lumping it in with ``Conflict`` could not see it.
    """
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        try:
            await create_record(session, rtype, data=dict(data), settings=SETTINGS)
            await session.commit()
        except Conflict:
            await session.rollback()
            return "conflict"
        except IntegrityError:
            await session.rollback()
            return "integrity-error"
        except RecordsError as exc:
            await session.rollback()
            return f"records-error:{type(exc).__name__}"
        return "created"


async def _race(state: Any, type_id: int, data: dict[str, Any]) -> Counter:
    outcomes = await asyncio.wait_for(
        asyncio.gather(*(_one_create(state, type_id, data) for _ in range(WRITERS))),
        timeout=60,
    )
    return Counter(outcomes)


async def _stored(state: Any, type_id: int) -> int:
    async with state.session_factory() as session:
        total = await session.execute(
            select(func.count(Record.id))
            .where(Record.type_id == type_id)
            .execution_options(include_deleted=True)
        )
        return int(total.scalar_one())


async def test_twenty_concurrent_creates_of_one_unique_value_store_exactly_one(pg_state):
    """``FOR UPDATE`` closes the check-then-act window of design §7.8.

    ``email`` is ``unique`` and is *not* the ``slug_field``, so no database
    constraint covers it — the index tables are shared across every field of a
    kind, which is the reason §7.8 gives for the rule being application-level.
    Twenty writers pass ``ensure_unique`` only if the row lock did not hold.
    """
    type_id = await _seed_type(
        pg_state,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )

    outcomes = await _race(pg_state, type_id, {"name": "Ada", "email": "ada@example.com"})

    assert outcomes["integrity-error"] == 0, f"an IntegrityError escaped: {dict(outcomes)}"
    assert outcomes["created"] == 1, f"expected one winner, got {dict(outcomes)}"
    assert outcomes["conflict"] == WRITERS - 1, dict(outcomes)
    assert await _stored(pg_state, type_id) == 1


async def test_twenty_concurrent_slug_claims_leave_one_winner(pg_state):
    """§5's slug claim, where a real constraint *does* back the check.

    ``ix_records_record_type_slug`` is a partial unique index, so the losers
    can be refused by either half — ``ensure_slug_free`` before the flush or
    the index during it. Both must arrive as ``Conflict``: an ``IntegrityError``
    reaching the caller is the 500 :func:`flush_write` was written to stop, and
    on Postgres it would additionally poison the transaction.
    """
    type_id = await _seed_type(
        pg_state,
        "product",
        [_field("name"), _field("sku")],
        display_field="name",
        slug_field="sku",
    )

    outcomes = await _race(pg_state, type_id, {"name": "Widget", "sku": "W-1"})

    assert outcomes["integrity-error"] == 0, f"an IntegrityError escaped: {dict(outcomes)}"
    assert outcomes["created"] == 1, dict(outcomes)
    assert set(outcomes) <= {"created", "conflict"}, dict(outcomes)
    assert await _stored(pg_state, type_id) == 1


async def test_twenty_distinct_values_all_succeed(pg_state):
    """The lock must cost throughput, not correctness — and it must not
    deadlock. Twenty writers take the same row lock in an order nobody
    controls; every one of them commits."""
    type_id = await _seed_type(
        pg_state,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )

    outcomes = Counter(
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    _one_create(
                        pg_state,
                        type_id,
                        {"name": f"n{i}", "email": f"n{i}@example.com"},
                    )
                    for i in range(WRITERS)
                )
            ),
            timeout=60,
        )
    )

    assert outcomes == Counter({"created": WRITERS}), dict(outcomes)
    assert await _stored(pg_state, type_id) == WRITERS


async def _edit_schema(state: Any, type_id: int) -> str:
    """Add a field to the type while records are landing against it."""
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        try:
            await update_type(
                session,
                rtype,
                expected_version=rtype.version,
                settings=SETTINGS,
                fields_raw=[
                    _field("name"),
                    _field("email", unique=True),
                    _field("nickname", type=FieldType.TEXT.value),
                ],
            )
            await session.commit()
        except (Conflict, IntegrityError):
            await session.rollback()
            return "conflict"
        except RecordsError as exc:
            await session.rollback()
            return f"records-error:{type(exc).__name__}"
        return "edited"


async def test_a_schema_edit_racing_creates_leaves_every_record_consistent(pg_state):
    """A schema write while records land must not corrupt either side.

    ``update_type`` takes the same per-type lock (through
    :func:`sm_records.services.schema_change.apply`), so the edit and the
    creates serialise against each other. What is asserted is the property that
    survives whichever order they land in, not an order: every stored record
    carries a ``schema_version`` the type has actually had — the one before the
    edit or the one after it, never a third — and the record's payload holds
    the fields that version declares.

    Deliberately *not* asserted: how many of the creates land, or whether the
    edit wins. Both are races, and pinning either would make this a test of the
    scheduler.
    """
    type_id = await _seed_type(
        pg_state,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )
    async with pg_state.session_factory() as session:
        before = int((await session.get(RecordType, type_id)).schema_version)

    creates = [
        _one_create(pg_state, type_id, {"name": f"n{i}", "email": f"n{i}@example.com"})
        for i in range(WRITERS)
    ]
    results = await asyncio.wait_for(
        asyncio.gather(_edit_schema(pg_state, type_id), *creates), timeout=90
    )
    edit_outcome, create_outcomes = results[0], Counter(results[1:])

    assert edit_outcome in {"edited", "conflict"}, edit_outcome
    assert create_outcomes["integrity-error"] == 0, dict(create_outcomes)

    async with pg_state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        after = int(rtype.schema_version)
        rows = (
            (
                await session.execute(
                    select(Record).where(Record.type_id == type_id).order_by(Record.id)
                )
            )
            .scalars()
            .all()
        )

    assert after in {before, before + 1}, f"{before} -> {after}"
    for row in rows:
        assert row.schema_version in {before, after}, (
            f"record {row.uuid} stamped {row.schema_version}, "
            f"type has only ever been {before} or {after}"
        )
        # Every version of this type declares both of these; a payload missing
        # one would mean a record validated against a schema that never
        # existed.
        assert set(row.data) >= {"name", "email"}, row.data
