"""Writes and lifecycle operations racing a collection move (#82), on SQLite.

Every test here runs on a **file** database on the default pool (``file_db``),
one connection per session, so the two sides are two real transactions. The
in-memory harness shares one connection between every session, and there a
"stale" session simply reads the other's uncommitted move.

Two shapes. *Interleaved*: a session loads what it will act on, a move commits
from another connection, then the first session acts — and must be refused
with a ``409``, having written nothing, instead of writing into (or purging
from) the tables the type just left. *Blocked*: the move holds its transaction
open while the other operation starts; that operation must still be waiting
when the window closes, and refused once the move commits. The Postgres
versions, which prove the wait from ``pg_stat_activity``, are in
``test_collections_move_race_pg.py``.
"""

from __future__ import annotations

import asyncio

import pytest
from sm_records.models import RecordType
from sm_records.services import _lifecycle
from sm_records.services._delete_locks import DeleteGraph, check_delete_plan
from sm_records.services._empty_trash import _purge_ids, empty_trash
from sm_records.services.errors import Conflict, NotFound
from sm_records.services.records import create_record, get_deleted_record, get_record

from tests.collections_harness import EVENTS  # noqa: F401 - declares the collections
from tests.move_race_support import SETTINGS, count, move, seed

MOVED = "moved to another collection"

WINDOW = 0.3
"""How long a blocked operation must stay blocked. Not an ordering sleep: a
lock that holds can never let the operation finish inside it, so this cannot
flake; a lock that does not hold finishes in milliseconds and fails it."""


async def test_a_write_holding_the_pre_move_type_row_is_refused(file_db):
    type_id, _ = await seed(file_db)
    async with file_db.session_factory() as writer:
        stale = await writer.get(RecordType, type_id)
        assert stale.collection is None
        async with file_db.session_factory() as mover:
            await move(mover, type_id)
            await mover.commit()
        with pytest.raises(Conflict, match=MOVED):
            await create_record(writer, stale, data={"name": "late"}, settings=SETTINGS)
        await writer.rollback()
    assert await count(file_db, None, type_id) == 0
    assert await count(file_db, "events", type_id) == 3


async def test_a_write_waits_for_an_uncommitted_move_and_is_then_refused(file_db):
    type_id, _ = await seed(file_db)
    async with file_db.session_factory() as writer, file_db.session_factory() as mover:
        stale = await writer.get(RecordType, type_id)
        await move(mover, type_id)  # holds SQLite's write lock, uncommitted
        task = asyncio.create_task(
            create_record(writer, stale, data={"name": "late"}, settings=SETTINGS)
        )
        done, _ = await asyncio.wait({task}, timeout=WINDOW)
        assert not done, "the write went ahead while the move held the type lock"
        await mover.commit()
        with pytest.raises(Conflict, match=MOVED):
            await task
        await writer.rollback()
    assert await count(file_db, None, type_id) == 0
    assert await count(file_db, "events", type_id) == 3


async def _stale_then_move(file_db, type_id: int, uuids: dict[str, str], act) -> None:
    """Load the type and its records in one session, commit a move from
    another, then ``act`` in the first — which must be refused."""
    async with file_db.session_factory() as actor:
        stale = await actor.get(RecordType, type_id)
        live = await get_record(actor, stale, uuids["live-0"])
        binned = await get_deleted_record(actor, stale, uuids["binned"])
        async with file_db.session_factory() as mover:
            await move(mover, type_id)
            await mover.commit()
        with pytest.raises(Conflict, match=MOVED):
            await act(actor, stale, live, binned)
        await actor.rollback()


@pytest.mark.parametrize("operation", ["trash", "restore", "purge", "empty_trash"])
async def test_a_lifecycle_operation_holding_the_pre_move_type_is_refused(file_db, operation):
    """Purge and empty-trash used to delete nothing from the old tables, report
    success and publish ``RecordPurged`` while the record survived the move."""
    type_id, uuids = await seed(file_db)

    async def act(db, rtype, live, binned):
        if operation == "trash":
            await _lifecycle.soft_delete_record(db, rtype, live, settings=SETTINGS)
        elif operation == "restore":
            await _lifecycle.restore_record(db, rtype, binned, settings=SETTINGS)
        elif operation == "purge":
            await _lifecycle.hard_delete_record(db, rtype, binned)
        else:
            await empty_trash(db, rtype)

    await _stale_then_move(file_db, type_id, uuids, act)
    assert await count(file_db, None, type_id) == 0
    assert await count(file_db, "events", type_id) == 3
    assert await count(file_db, "events", type_id, trashed=True) == 1


async def test_a_second_purge_of_one_record_is_a_404_not_a_second_purge(file_db):
    type_id, uuids = await seed(file_db)
    async with file_db.session_factory() as first, file_db.session_factory() as second:
        rtype_a = await first.get(RecordType, type_id)
        rtype_b = await second.get(RecordType, type_id)
        record_a = await get_deleted_record(first, rtype_a, uuids["binned"])
        record_b = await get_deleted_record(second, rtype_b, uuids["binned"])
        await _lifecycle.hard_delete_record(first, rtype_a, record_a)
        await first.commit()
        with pytest.raises(NotFound):
            await _lifecycle.hard_delete_record(second, rtype_b, record_b)
        await second.rollback()
    assert await count(file_db, None, type_id, trashed=True) == 0


async def test_a_restore_of_a_record_restored_meanwhile_is_a_409(file_db):
    type_id, uuids = await seed(file_db)
    async with file_db.session_factory() as first, file_db.session_factory() as second:
        rtype_a = await first.get(RecordType, type_id)
        rtype_b = await second.get(RecordType, type_id)
        record_a = await get_deleted_record(first, rtype_a, uuids["binned"])
        record_b = await get_deleted_record(second, rtype_b, uuids["binned"])
        await _lifecycle.restore_record(first, rtype_a, record_a, settings=SETTINGS)
        await first.commit()
        with pytest.raises(Conflict, match="not in the trash"):
            await _lifecycle.restore_record(second, rtype_b, record_b, settings=SETTINGS)
        await second.rollback()


async def test_a_purge_that_deletes_fewer_rows_than_it_selected_is_refused(file_db):
    """The affected-row check: ids nobody can delete any more are a 409 (and
    the caller's rollback), never ``RecordPurged`` for a row that is gone."""
    type_id, uuids = await seed(file_db)
    async with file_db.session_factory() as db:
        rtype = await db.get(RecordType, type_id)
        binned = await get_deleted_record(db, rtype, uuids["binned"])
        with pytest.raises(Conflict, match="changed while they were being purged"):
            await _purge_ids(db, rtype, [binned.id, 10_000_000])
        await db.rollback()
    assert await count(file_db, None, type_id, trashed=True) == 1


async def test_a_delete_plan_reaching_an_unlocked_type_is_refused(file_db):
    type_id, _ = await seed(file_db)
    async with file_db.session_factory() as db:
        rtype = await db.get(RecordType, type_id)
        unlocked = DeleteGraph(frozenset(), {type_id: None})
        with pytest.raises(Conflict, match="relations into this record changed"):
            await check_delete_plan(db, unlocked, [rtype])
        moved_meanwhile = DeleteGraph(frozenset({type_id}), {type_id: "events"})
        with pytest.raises(Conflict):
            await check_delete_plan(db, moved_meanwhile, [rtype])
        read_only_moved = DeleteGraph(frozenset(), {type_id: "events"})
        with pytest.raises(Conflict, match="this delete reads moved"):
            await check_delete_plan(db, read_only_moved, [])
