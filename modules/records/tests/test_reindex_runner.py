"""The out-of-request half of §8.5: the rebuild, the CLI and the alarm.

Everything here is about a rebuild that may not finish. It runs on its own
session and commits (nothing else in the services layer does), it is
idempotent so an interrupted run converges when repeated, and if it never runs
at all the health check of §8.9 says so instead of leaving one field quietly
refusing filters forever.

The setup commits before handing over, because the runner opens a *second*
session: an uncommitted schema change would not be there to find.
"""

from __future__ import annotations

import pytest
from sm_records.constants import REINDEX_ALL
from sm_records.index import reindex as reindex_module
from sm_records.index.query import Filter, FilterOp, build_query
from sm_records.models import IndexNumber, IndexText, Record, RecordType
from sm_records.services import records as record_service
from sm_records.services import schema_change
from sm_records.services import types as type_service
from sm_records.services.reindex_runner import run_pending, schedule
from sm_records.settings import RecordsSettings
from sqlalchemy import select


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


async def fresh_type(db, type_id: int):
    """Re-read the type through the test's own session.

    ``populate_existing`` because the runner committed on a *different*
    session: the row in this one's identity map is the one it wrote before
    handing over, and a plain select would hand that stale copy straight back.
    """
    stmt = (
        select(RecordType).where(RecordType.id == type_id).execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalars().one()


async def values(db, table, field_key: str):
    rows = (await db.execute(select(table).where(table.field_key == field_key))).scalars().all()
    return [row.value for row in rows]


async def test_a_retyped_field_moves_between_index_tables_and_starts_filtering_again(
    db, db_state, settings, field_def
):
    """§8.4 end to end: the payload keeps the string ``"12"`` forever, the
    rebuild writes ``12`` into ``records_index_number``, and ``price > 1`` is
    correct the moment it finishes — with no record rewritten."""
    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("price", "text")],
        settings=settings,
    )
    record = await record_service.create_record(db, rtype, data={"price": "12"}, settings=settings)
    type_id, record_id = rtype.id, record.id
    assert await values(db, IndexText, "price") == ["12"]

    await schema_change.apply(
        db, rtype, fields_raw=[field_def("price", "number")], expected_version=1, settings=settings
    )
    await db.commit()

    assert await run_pending(db_state, type_id, settings=settings) == 1

    fresh = await fresh_type(db, type_id)
    assert fresh.reindex_pending == {}
    assert await values(db, IndexText, "price") == []
    assert [str(v) for v in await values(db, IndexNumber, "price")] == ["12.00000"]
    # The payload never moved.
    payload = (await db.execute(select(Record.data).where(Record.id == record_id))).scalar_one()
    assert payload == {"price": "12"}

    found = (
        (
            await db.execute(
                build_query(fresh, list(fresh.fields), [Filter("price", FilterOp.GT, 1)])
            )
        )
        .scalars()
        .all()
    )
    assert [r.id for r in found] == [record.id]


async def test_a_removed_fields_index_rows_are_deleted_by_the_runner(
    db, db_state, settings, field_def
):
    fields = [field_def("title", "text"), field_def("price", "text")]
    rtype = await type_service.create_type(
        db, key="product", label="Product", fields_raw=fields, settings=settings
    )
    await record_service.create_record(
        db, rtype, data={"title": "One", "price": "12"}, settings=settings
    )
    type_id = rtype.id
    await schema_change.apply(
        db, rtype, fields_raw=[fields[0]], expected_version=1, settings=settings
    )
    await db.commit()

    await run_pending(db_state, type_id, settings=settings)

    assert await values(db, IndexText, "price") == []
    assert await values(db, IndexText, "title") == ["One"]


async def test_a_display_field_change_rebuilds_every_display_title(
    db, db_state, settings, field_def
):
    fields = [field_def("title", "text"), field_def("alt", "text")]
    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=fields,
        display_field="title",
        settings=settings,
    )
    for i in range(3):
        await record_service.create_record(
            db, rtype, data={"title": f"Title {i}", "alt": f"Alt {i}"}, settings=settings
        )

    type_id = rtype.id
    await schema_change.apply(
        db, rtype, expected_version=1, settings=settings, changes={"display_field": "alt"}
    )
    await db.commit()
    assert await run_pending(db_state, type_id, settings=settings) == 3

    titles = (await db.execute(select(Record.display_title).order_by(Record.id))).scalars().all()
    assert titles == ["Alt 0", "Alt 1", "Alt 2"]
    assert REINDEX_ALL not in (await fresh_type(db, type_id)).reindex_pending


async def test_nothing_pending_is_a_no_op_and_a_missing_type_is_not_an_error(
    db, db_state, settings, field_def
):
    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("price", "number")],
        settings=settings,
    )
    type_id = rtype.id
    await db.commit()
    assert await run_pending(db_state, type_id, settings=settings) == 0
    assert await run_pending(db_state, 4242, settings=settings) == 0


async def test_an_interrupted_run_leaves_the_markers_set_and_converges_on_the_next(
    db, db_state, settings, field_def, monkeypatch
):
    """§7.7's guarantee, and the reason a lost background task is recoverable
    rather than corrupting: the markers are cleared *last*, so a crash halfway
    through is finished by running the command again."""
    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("price", "text")],
        settings=settings,
    )
    for i in range(4):
        await record_service.create_record(
            db, rtype, data={"price": str(10 + i)}, settings=settings
        )
    type_id = rtype.id
    await schema_change.apply(
        db, rtype, fields_raw=[field_def("price", "number")], expected_version=1, settings=settings
    )
    await db.commit()

    real = reindex_module.reindex_record
    seen = {"count": 0}

    async def flaky(db_, record, rtype_, **kwargs):
        seen["count"] += 1
        if seen["count"] > 2:
            raise RuntimeError("worker died mid-rebuild")
        await real(db_, record, rtype_, **kwargs)

    monkeypatch.setattr(reindex_module, "reindex_record", flaky)
    small = RecordsSettings(reindex_batch_size=2)
    with pytest.raises(RuntimeError):
        await run_pending(db_state, type_id, settings=small)

    assert set((await fresh_type(db, type_id)).reindex_pending) == {"price"}

    monkeypatch.setattr(reindex_module, "reindex_record", real)
    assert await run_pending(db_state, type_id, settings=settings) == 4

    assert (await fresh_type(db, type_id)).reindex_pending == {}
    assert len(await values(db, IndexNumber, "price")) == 4
    assert await values(db, IndexText, "price") == []


async def test_schedule_swallows_a_failure_so_a_background_task_cannot_escape(
    db, db_state, settings, field_def, monkeypatch
):
    """It runs with the response already sent, where an exception has nobody to
    tell. The markers stay set, which is what the health check reports on."""
    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("price", "text")],
        settings=settings,
    )
    await record_service.create_record(db, rtype, data={"price": "12"}, settings=settings)
    type_id = rtype.id
    await schema_change.apply(
        db, rtype, fields_raw=[field_def("price", "number")], expected_version=1, settings=settings
    )
    await db.commit()

    async def boom(*args, **kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(reindex_module, "reindex_record", boom)
    assert await schedule(db_state, type_id, settings) == 0

    assert set((await fresh_type(db, type_id)).reindex_pending) == {"price"}
