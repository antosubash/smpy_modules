"""test_postgres_lock cases."""

from __future__ import annotations
import asyncio
from collections import Counter
from typing import Any
import pytest
from sm_records.models import Record, RecordType
from sm_records.schema.types import FieldType
from sm_records.records.services._type_update import update_type
from sm_records.records.services.errors import Conflict, RecordsError
from sm_records.records.services.records import create_record
from sm_records.core.settings import RecordsSettings
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from tests.pg_support import USING_POSTGRES
from tests.support.postgres_lock_cases import _field, _seed_type, _one_create, _race, _stored, _edit_schema, WRITERS, SETTINGS

pytestmark = pytest.mark.skipif(
    not USING_POSTGRES,
    reason="the FOR UPDATE branch of lock_type only exists on Postgres; "
    "set RECORDS_TEST_URL=postgresql+asyncpg://…",
)


async def test_twenty_distinct_values_all_succeed(db_state):
    """The lock must cost throughput, not correctness — and it must not
    deadlock. Twenty writers take the same row lock in an order nobody
    controls; every one of them commits."""
    type_id = await _seed_type(
        db_state,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )

    outcomes = Counter(
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    _one_create(
                        db_state,
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
    assert await _stored(db_state, type_id) == WRITERS


async def test_a_schema_edit_racing_creates_leaves_every_record_consistent(db_state):
    """A schema write while records land must not corrupt either side.

    ``update_type`` takes the same per-type lock (through
    :func:`sm_records.records.services.schema_change.apply`), so the edit and the
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
        db_state,
        "contact",
        [_field("name"), _field("email", unique=True)],
        display_field="name",
    )
    async with db_state.session_factory() as session:
        before = int((await session.get(RecordType, type_id)).schema_version)

    creates = [
        _one_create(db_state, type_id, {"name": f"n{i}", "email": f"n{i}@example.com"})
        for i in range(WRITERS)
    ]
    results = await asyncio.wait_for(
        asyncio.gather(_edit_schema(db_state, type_id), *creates), timeout=90
    )
    edit_outcome, create_outcomes = results[0], Counter(results[1:])

    assert edit_outcome in {"edited", "conflict"}, edit_outcome
    assert create_outcomes["integrity-error"] == 0, dict(create_outcomes)

    async with db_state.session_factory() as session:
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
