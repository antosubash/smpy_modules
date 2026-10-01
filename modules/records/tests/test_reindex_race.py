"""A reindex batch must not write over a record edited while it was in flight.

Design doc §7.7's whole argument is that an index bug produces *wrong query
results rather than slow ones*, and the rebuild is where that is easiest to
cause: :func:`sm_records.services.reindex_runner.run_pending` commits per
batch, so the ``SELECT`` that reads a batch and the ``DELETE``/``INSERT`` that
rewrite its index rows are one transaction but not one instant. An ordinary
edit committed in between used to have its index rows deleted and replaced by
a projection of the payload the rebuild had read — permanently, until somebody
reindexed again.

**Two sessions, and therefore Postgres only.** Not because SQLite is exempt in
principle but because it is untestable here: ``tests.pg_support`` builds the
SQLite database on a ``StaticPool`` over ``:memory:``, so two
``session_factory()`` calls are two sessions on *one connection* and there is
no interleaving to arrange. The second test additionally needs real row locks,
which SQLite does not have at all — there, only the version comparison in
:func:`sm_records.index._batch.current_batch` applies, and
``run_pending``'s ``database is locked`` retry covers the rest.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import pytest_asyncio
from sm_records.index.reindex import reindex_batch
from sm_records.models import RecordType, tables_for
from sm_records.schema.types import IndexKind
from sm_records.services._common import mark_written, type_resolver
from sm_records.services.records import create_record, update_record
from sm_records.settings import RecordsSettings
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.skipif(
    not USING_POSTGRES,
    reason="the interleaving needs two connections (SQLite here is one StaticPool "
    "connection) and the second test needs FOR UPDATE; "
    "set RECORDS_TEST_URL=postgresql+asyncpg://…",
)

SETTINGS = RecordsSettings()


@pytest_asyncio.fixture
async def seeded(db_state) -> Any:
    """A type with one indexed text field and one record holding ``old``."""
    async with db_state.session_factory() as session:
        rtype = RecordType(
            key="gadget",
            label="Gadget",
            label_plural="Gadgets",
            fields=[{"key": "name", "type": "text", "label": "Name", "indexed": True}],
            display_field="name",
        )
        session.add(rtype)
        await session.flush()
        record = await create_record(session, rtype, data={"name": "old"}, settings=SETTINGS)
        await session.commit()
        return db_state, int(rtype.id), str(record.uuid)


async def _indexed(state: Any, type_id: int) -> list[tuple[str, str]]:
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        table = tables_for(rtype).index[IndexKind.TEXT]
        rows = await session.execute(select(table.field_key, table.value).order_by(table.field_key))
        return [(key, value) for key, value in rows.all()]


async def _edit(state: Any, type_id: int, uuid: str, data: dict[str, Any]) -> None:
    """One ordinary edit, on a session of its own, committed."""
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        record_cls = tables_for(rtype).record
        record = (
            (await session.execute(select(record_cls).where(record_cls.uuid == uuid)))
            .scalars()
            .first()
        )
        await update_record(
            session,
            rtype,
            record,
            expected_version=record.version,
            data=dict(data),
            settings=SETTINGS,
        )
        await session.commit()


async def test_a_batch_does_not_write_over_an_edit_committed_since_it_was_read(seeded):
    """The reviewer's reproduction, with no artificial sleeps.

    Session A reads the batch. Session B edits the record and commits — which
    rewrites the record's index rows from the payload it stored. Session A
    then rebuilds the batch it read. Before the fix, A's ``DELETE … WHERE
    record_id IN (…)`` removed B's rows and A's ``INSERT`` put back a
    projection of ``old``; the index disagreed with ``data`` for good.
    """
    state, type_id, uuid = seeded
    async with state.session_factory() as session_a:
        rtype = await session_a.get(RecordType, type_id)
        record_cls = tables_for(rtype).record
        batch = (
            (await session_a.execute(select(record_cls).where(record_cls.type_id == type_id)))
            .scalars()
            .all()
        )
        assert [dict(row.data)["name"] for row in batch] == ["old"]

        await _edit(state, type_id, uuid, {"name": "new"})

        await reindex_batch(session_a, batch, rtype, resolve_type_id=await type_resolver(session_a))
        mark_written(session_a)
        await session_a.commit()

    assert await _indexed(state, type_id) == [("name", "new")]


async def test_an_edit_that_starts_mid_batch_waits_and_wins(seeded):
    """The other half of the interleaving, and the half that needs the lock.

    Here session A gets there first: ``current_batch``'s ``SELECT … FOR
    UPDATE`` holds the record row, so B's ``guarded_bump`` — an ``UPDATE`` of
    that same row — blocks until A commits. B's index write therefore lands
    *after* A's rebuild rather than under it, and the last word belongs to the
    payload that was actually stored. Without the lock A's insert would be
    last and the index would read ``old`` against ``data`` of ``new``.
    """
    state, type_id, uuid = seeded
    async with state.session_factory() as session_a:
        rtype = await session_a.get(RecordType, type_id)
        record_cls = tables_for(rtype).record
        batch = (
            (await session_a.execute(select(record_cls).where(record_cls.type_id == type_id)))
            .scalars()
            .all()
        )
        # Takes the row lock and rewrites the rows, all inside A's still-open
        # transaction.
        await reindex_batch(session_a, batch, rtype, resolve_type_id=await type_resolver(session_a))

        editor = asyncio.create_task(_edit(state, type_id, uuid, {"name": "new"}))
        # Long enough for the editor to reach its UPDATE and block there;
        # if it does not block, it finishes here and the assertion below is
        # the one that fails, which is the failure we want to see.
        await asyncio.sleep(0.3)
        assert not editor.done(), "the editor did not block: the batch took no row lock"

        mark_written(session_a)
        await session_a.commit()
        await asyncio.wait_for(editor, timeout=30)

    assert await _indexed(state, type_id) == [("name", "new")]


async def test_the_title_pass_does_not_write_over_an_edit_committed_since_it_was_read(
    db_state,
):
    """``services._titles.recompute_titles`` has the same read-then-write
    shape and the same commit-per-batch, so it had the same hole.

    The setup is the one that puts the pass to work in the first place: the
    type's ``display_field`` moved, which is what marks a whole-type rebuild
    pending, so every stored ``display_title`` is stale and the walk really
    does assign a new value. Session A reads the batch; session B then edits
    the record, computing the title from the *new* schema and the *new*
    payload; A's walk then commits the title it derived from the payload it
    read, leaving ``display_title`` disagreeing with ``data`` on the one
    column the list view and every ``REF`` label read.
    """
    from sm_records.services._titles import recompute_titles

    async with db_state.session_factory() as session:
        rtype = RecordType(
            key="part",
            label="Part",
            label_plural="Parts",
            fields=[
                {"key": "name", "type": "text", "label": "Name", "indexed": True},
                {"key": "code", "type": "text", "label": "Code", "indexed": True},
            ],
            display_field="name",
        )
        session.add(rtype)
        await session.flush()
        record = await create_record(
            session, rtype, data={"name": "old", "code": "X"}, settings=SETTINGS
        )
        type_id, uuid = int(rtype.id), str(record.uuid)
        await session.commit()

    # The schema change that makes every stored title stale, committed by
    # somebody else — this is the state ``REINDEX_ALL`` marks.
    async with db_state.session_factory() as session:
        moved = await session.get(RecordType, type_id)
        moved.display_field = "code"
        await session.commit()

    async with db_state.session_factory() as session_a:
        rtype = await session_a.get(RecordType, type_id)
        record_cls = tables_for(rtype).record
        # The walk's batch read, taken before the edit: exactly what a
        # multi-batch pass does to every batch after its first commit. Read
        # into the identity map (``.all()``) rather than merely executed, for
        # the same reason — the walk holds instances, not rows.
        stale = (
            (await session_a.execute(select(record_cls).where(record_cls.type_id == type_id)))
            .scalars()
            .all()
        )
        assert [dict(row.data)["code"] for row in stale] == ["X"]

        await _edit(db_state, type_id, uuid, {"name": "new", "code": "Y"})

        await recompute_titles(session_a, rtype, 10)

    async with db_state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        record_cls = tables_for(rtype).record
        row = (
            (await session.execute(select(record_cls).where(record_cls.uuid == uuid)))
            .scalars()
            .first()
        )
        assert (row.display_title, dict(row.data)["code"]) == ("Y", "Y")
