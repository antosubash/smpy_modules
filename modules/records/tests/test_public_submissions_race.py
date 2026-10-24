"""A record write racing a type's conversion to a newsletter list (#101).

A writer validates its payload against the type's schema *before* it takes
the type lock. If the conversion — which appends the required, unique
``sm_email`` — commits in between, the writer must be refused with a ``409``
rather than insert a subscriber with no address. On SQLite the two sides are
two real transactions on a file database (``file_db``); on Postgres the
writer is seen blocked on the lock (``pg_stat_activity``) before the
conversion commits.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sm_records.models import RecordType
from sm_records.services._type_update import update_type
from sm_records.services.errors import Conflict
from sm_records.services.records import create_record
from sqlalchemy import text

from tests.move_race_support import FIELDS, SETTINGS, count
from tests.pg_support import USING_POSTGRES

CHANGED = "schema of record type 'list' changed"


async def _empty_type(state: Any) -> int:
    async with state.session_factory() as session:
        rtype = RecordType(key="list", label="List", label_plural="Lists", fields=FIELDS)
        session.add(rtype)
        await session.commit()
        return int(rtype.id)


async def _convert(session: Any, type_id: int) -> None:
    """Make the type a newsletter list, uncommitted."""
    rtype = await session.get(RecordType, type_id)
    await update_type(
        session,
        rtype,
        expected_version=rtype.version,
        settings=SETTINGS,
        public_submissions={"kind": "subscription"},
    )


async def _addresses_missing(state: Any, type_id: int) -> None:
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        assert any(f["key"] == "sm_email" for f in rtype.fields)
    assert await count(state, None, type_id) == 0


async def test_a_write_validated_before_the_conversion_committed_is_refused(file_db):
    type_id = await _empty_type(file_db)
    async with file_db.session_factory() as writer:
        stale = await writer.get(RecordType, type_id)
        async with file_db.session_factory() as converter:
            await _convert(converter, type_id)
            await converter.commit()
        with pytest.raises(Conflict, match=CHANGED):
            await create_record(writer, stale, data={"name": "late"}, settings=SETTINGS)
        await writer.rollback()
    await _addresses_missing(file_db, type_id)


async def _blocked(state: Any, pid: int) -> None:
    """Return once backend ``pid`` waits on a lock; fail after 10 s."""
    for _ in range(400):
        async with state.engine.connect() as conn:
            wait = await conn.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
        if wait == "Lock":
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"backend {pid} never waited on a lock")


@pytest.mark.skipif(not USING_POSTGRES, reason="a blocking lock needs Postgres; RECORDS_TEST_URL")
async def test_a_write_blocked_behind_the_conversion_is_refused_once_it_commits(db_state):
    type_id = await _empty_type(db_state)
    async with db_state.session_factory() as converter, db_state.session_factory() as writer:
        await _convert(converter, type_id)
        pid = int(await writer.scalar(text("SELECT pg_backend_pid()")))
        # Read while the conversion is uncommitted: the committed, plain type.
        stale = await writer.get(RecordType, type_id)
        assert not any(f["key"] == "sm_email" for f in stale.fields)
        task = asyncio.create_task(
            create_record(writer, stale, data={"name": "late"}, settings=SETTINGS)
        )
        await _blocked(db_state, pid)
        await converter.commit()
        with pytest.raises(Conflict, match=CHANGED):
            await asyncio.wait_for(task, timeout=30)
        await writer.rollback()
    await _addresses_missing(db_state, type_id)
