"""The reindex runner takes the type lock first, like every writer (#82).

Every transaction of a rebuild — each map batch, the titles pass, the reduce
rebuild, the clear — opens with the type lock, so its order is type, records,
index and reduce rows, the order a type delete and a record write already
use. Before, a batch locked records and then deleted index rows while a type
delete deleted index rows and then records: a deadlock waiting to happen. And
the reduce-only pass, which carries no pending marker for a move to refuse
on, read whatever table set its (possibly stale) type row named — after a move,
an empty one — and replaced the aggregates with that.

The Postgres tests hold the other operation open, start the runner, and read
from ``pg_stat_activity`` that it is waiting on the **type row** — not on a
record — before letting the other side commit.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sm_records.index.reduce import ReduceSpec, register_reduce_provider
from sm_records.models import IndexReduce, RecordType, tables_for
from sm_records.schema.types import IndexKind
from sm_records.services import types as type_service
from sm_records.services.errors import Conflict
from sm_records.services.records import get_record, update_record
from sm_records.services.reindex_runner import _rebuild, run_pending
from sqlalchemy import select, text

from tests.collections_harness import EVENTS  # noqa: F401 - declares the collections
from tests.move_race_support import SETTINGS, move, seed
from tests.pg_support import USING_POSTGRES

on_postgres = pytest.mark.skipif(
    not USING_POSTGRES, reason="observing a blocked backend needs Postgres"
)


def _count_by_name() -> None:
    register_reduce_provider(
        ReduceSpec(key="by_name", group_by=lambda record, rtype: (record.data or {}).get("name"))
    )


async def _aggregates(state: Any, type_id: int) -> dict[str, int]:
    async with state.session_factory() as session:
        rows = (
            await session.execute(
                select(IndexReduce.group_value, IndexReduce.count).where(
                    IndexReduce.type_id == type_id
                )
            )
        ).all()
    return {str(group): int(count) for group, count in rows}


async def _mark_pending(state: Any, type_id: int) -> None:
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        rtype.reindex_pending = {"name": "2026-10-22T00:00:00+00:00"}
        await session.commit()


async def _waiting_query(state: Any) -> str:
    """The statement of the one other backend waiting on a lock; fail after 10 s."""
    for _ in range(400):
        async with state.engine.connect() as conn:
            query = await conn.scalar(
                text(
                    "SELECT query FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                    "AND datname = current_database() AND pid <> pg_backend_pid() LIMIT 1"
                )
            )
        if query:
            return str(query)
        await asyncio.sleep(0.025)
    raise AssertionError("the runner never waited on a lock")


async def _runner_waits_for(state: Any, type_id: int, hold) -> Any:
    """Run ``hold`` uncommitted, start the runner, see it wait on the type
    row, commit ``hold``; return what the runner returned or raised."""
    async with state.session_factory() as holder:
        await hold(holder)

        async def runner() -> Any:
            try:
                return await run_pending(state, type_id, settings=SETTINGS)
            except Conflict as exc:
                return exc

        task = asyncio.create_task(runner())
        query = await _waiting_query(state)
        assert "records_type" in query and "FOR UPDATE" in query, query
        assert not task.done()
        await holder.commit()
        return await asyncio.wait_for(task, timeout=30)


@on_postgres
async def test_a_reindex_waits_for_a_type_delete_and_ends_quietly(db_state):
    type_id, _ = await seed(db_state)
    await _mark_pending(db_state, type_id)

    async def delete(session):
        rtype = await session.get(RecordType, type_id)
        await type_service.delete_type(session, rtype, confirm_record_count=3)

    assert await _runner_waits_for(db_state, type_id, delete) == 0


@on_postgres
async def test_a_reindex_waits_for_a_record_edit_and_indexes_the_edit(db_state):
    type_id, uuids = await seed(db_state)
    await _mark_pending(db_state, type_id)

    async def edit(session):
        rtype = await session.get(RecordType, type_id)
        record = await get_record(session, rtype, uuids["live-0"])
        await update_record(
            session,
            rtype,
            record,
            expected_version=record.version,
            data={"name": "edited"},
            settings=SETTINGS,
        )

    assert await _runner_waits_for(db_state, type_id, edit) == 3
    async with db_state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        index = tables_for(rtype).index[IndexKind.TEXT]
        values = set((await session.execute(select(index.value))).scalars().all())
        assert "edited" in values and "live-0" not in values
        assert not rtype.reindex_pending


@on_postgres
async def test_a_reduce_rebuild_waits_for_a_move_and_refuses_after_it(db_state):
    _count_by_name()
    type_id, _ = await seed(db_state)
    before = await _aggregates(db_state, type_id)
    assert before == {"live-0": 1, "live-1": 1}
    outcome = await _runner_waits_for(db_state, type_id, lambda s: move(s, type_id))
    assert isinstance(outcome, Conflict)
    assert await _aggregates(db_state, type_id) == before


async def test_a_reduce_rebuild_holding_the_pre_move_type_does_not_empty_the_totals(db_state):
    """The interleaving Codex named, on any backend: the runner's type row
    predates a move that has committed. It used to fold the emptied source
    set and replace the totals with nothing."""
    _count_by_name()
    type_id, _ = await seed(db_state)
    before = await _aggregates(db_state, type_id)
    async with db_state.session_factory() as runner:
        stale = await runner.get(RecordType, type_id)
        async with db_state.session_factory() as mover:
            await move(mover, type_id)
            await mover.commit()
        with pytest.raises(Conflict, match="moved to another collection"):
            await _rebuild(runner, stale, settings=SETTINGS)
    assert await _aggregates(db_state, type_id) == before
