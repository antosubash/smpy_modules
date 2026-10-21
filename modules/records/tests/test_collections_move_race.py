"""A record write racing a collection move cannot land in the tables the
type just left (#82).

A writer loads its type row before it takes the type lock, so the row it
holds can say ``collection = None`` while a move to ``events`` commits under
it. ``lock_type`` re-reads ``collection`` once the lock is held and refuses
with a ``409``; without that the writer's record went into the shared tables,
where no read of an ``events`` type would ever look.

The first test interleaves the two deterministically on any backend: the
writer's row is loaded, the move commits, *then* the writer writes. The second
runs them as two real transactions on Postgres, with the writer blocked on the
move's row lock until the move commits.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sm_records.models import RecordType, table_set
from sm_records.services._type_update import update_type
from sm_records.services.errors import Conflict
from sm_records.services.records import create_record
from sm_records.settings import RecordsSettings
from sqlalchemy import func, select

from tests.collections_harness import EVENTS  # noqa: F401 - declares the collections
from tests.pg_support import USING_POSTGRES

SETTINGS = RecordsSettings()
FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]


async def _seed(state: Any, records: int = 2) -> int:
    async with state.session_factory() as session:
        rtype = RecordType(
            key="author",
            label="Author",
            label_plural="Authors",
            fields=FIELDS,
            display_field="name",
        )
        session.add(rtype)
        await session.flush()
        for index in range(records):
            await create_record(session, rtype, data={"name": f"a{index}"}, settings=SETTINGS)
        await session.commit()
        return int(rtype.id)


async def _count(state: Any, collection: str | None, type_id: int) -> int:
    record = table_set(collection).record
    async with state.session_factory() as session:
        stmt = (
            select(func.count())
            .select_from(record)
            .where(record.type_id == type_id)
            .execution_options(include_deleted=True)
        )
        return int(await session.scalar(stmt) or 0)


async def _move(session: Any, type_id: int) -> None:
    rtype = await session.get(RecordType, type_id)
    await update_type(
        session, rtype, expected_version=rtype.version, settings=SETTINGS, collection="events"
    )


async def test_a_write_holding_the_pre_move_type_row_is_refused(db_state):
    type_id = await _seed(db_state)
    async with db_state.session_factory() as writer:
        stale = await writer.get(RecordType, type_id)
        assert stale.collection is None
        await writer.commit()  # the row stays loaded; the read transaction ends

        async with db_state.session_factory() as mover:
            await _move(mover, type_id)
            await mover.commit()

        with pytest.raises(Conflict, match="moved to another collection"):
            await create_record(writer, stale, data={"name": "late"}, settings=SETTINGS)
        await writer.rollback()

    assert await _count(db_state, None, type_id) == 0
    assert await _count(db_state, "events", type_id) == 2


@pytest.mark.skipif(not USING_POSTGRES, reason="two concurrent transactions need Postgres")
async def test_a_write_blocked_behind_a_move_is_refused_once_it_commits(db_state):
    type_id = await _seed(db_state)
    moved_uncommitted = asyncio.Event()

    async def mover() -> None:
        async with db_state.session_factory() as session:
            await _move(session, type_id)
            moved_uncommitted.set()
            await asyncio.sleep(0.5)  # the writer is now queued on the row lock
            await session.commit()

    async def writer() -> str:
        async with db_state.session_factory() as session:
            stale = await session.get(RecordType, type_id)
            await moved_uncommitted.wait()
            try:
                await create_record(session, stale, data={"name": "late"}, settings=SETTINGS)
                await session.commit()
            except Conflict:
                await session.rollback()
                return "conflict"
            return "created"

    _, outcome = await asyncio.wait_for(asyncio.gather(mover(), writer()), timeout=30)
    assert outcome == "conflict"
    assert await _count(db_state, None, type_id) == 0
    assert await _count(db_state, "events", type_id) == 2
