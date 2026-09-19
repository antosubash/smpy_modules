"""The rebuild: index rows are derived, so they must be reconstructible."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sm_records.index.reindex import clear_pending, reindex_record, reindex_type
from sm_records.index.writer import delete_index, write_index
from sm_records.models import INDEX_TABLES, IndexNumber, IndexText
from sqlalchemy import delete, select

NOTHING = staticmethod(lambda _key: None)


async def snapshot(db, rtype) -> list[tuple]:
    """Every index row of a type, id-free: the ids are autoincrement and a
    rebuild will not reuse them, but nothing else about a row may change."""
    out: list[tuple] = []
    for table in INDEX_TABLES:
        rows = (await db.execute(select(table).where(table.type_id == rtype.id))).scalars().all()
        for row in rows:
            data = row.model_dump()
            data.pop("id", None)
            out.append((table.__tablename__, tuple(sorted(data.items()))))
    return sorted(out)


@pytest.fixture
async def catalogue(db, make_type, make_record, field_def):
    """Six records, so a batch size of two is genuinely several batches."""
    rtype = await make_type(
        "item",
        [field_def("name", "text"), field_def("price", "number"), field_def("tags", "multiselect")],
    )
    records = []
    for n in range(6):
        records.append(
            await make_record(
                rtype, {"name": f"item-{n}", "price": str(n), "tags": [f"t{n}", "all"]}
            )
        )
    return rtype, records


async def test_reindex_reconstructs_what_the_writer_wrote(db, catalogue):
    rtype, records = catalogue
    for record in records:
        await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
    written = await snapshot(db, rtype)
    assert written

    for table in INDEX_TABLES:
        await db.execute(delete(table))
    await db.flush()
    assert await snapshot(db, rtype) == []

    count = await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=10)
    assert count == len(records)
    assert await snapshot(db, rtype) == written


async def test_running_twice_converges(db, catalogue):
    rtype, _records = catalogue
    await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=10)
    once = await snapshot(db, rtype)
    await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=10)
    assert await snapshot(db, rtype) == once


async def test_a_batch_smaller_than_the_type_still_covers_it(db, catalogue):
    rtype, records = catalogue
    count = await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=2)
    assert count == len(records)
    names = (
        (await db.execute(select(IndexText.value).where(IndexText.field_key == "name")))
        .scalars()
        .all()
    )
    assert sorted(names) == sorted(f"item-{n}" for n in range(6))


async def test_soft_deleted_records_are_reindexed_too(db, catalogue):
    """Their rows stay in the index while they are in the trash (§7.3), so a
    rebuild that skipped them would empty the index of a record a restore is
    meant to bring back whole."""
    rtype, records = catalogue
    records[0].is_deleted = True
    db.add(records[0])
    await db.flush()

    count = await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=10)
    assert count == len(records)
    rows = (
        (await db.execute(select(IndexText).where(IndexText.record_id == records[0].id)))
        .scalars()
        .all()
    )
    assert rows


async def test_reindex_drops_rows_of_a_field_that_stopped_being_indexed(db, catalogue, field_def):
    rtype, _records = catalogue
    await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=10)
    rtype.fields = [field_def("name", "text"), field_def("price", "number", indexed=False)]
    rtype.schema_version += 1
    db.add(rtype)
    await db.flush()

    await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=10)
    assert (await db.execute(select(IndexNumber))).scalars().all() == []
    assert {r.field_key for r in (await db.execute(select(IndexText))).scalars().all()} == {"name"}


async def test_a_type_change_moves_rows_between_tables(db, make_type, make_record, field_def):
    """Design doc §8.4: the payload keeps ``"123"`` forever, the read path
    coerces, and the reindex writes the coerced value into the *number* table.
    No row is rewritten and ``price > 100`` is correct the moment it finishes.
    """
    rtype = await make_type("item", [field_def("price", "text")])
    record = await make_record(rtype, {"price": "123"})
    await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
    assert [r.value for r in (await db.execute(select(IndexText))).scalars().all()] == ["123"]

    rtype.fields = [field_def("price", "number")]
    rtype.schema_version += 1
    db.add(rtype)
    await reindex_record(db, record, rtype, resolve_type_id=lambda _k: None)

    assert (await db.execute(select(IndexText))).scalars().all() == []
    assert [r.value for r in (await db.execute(select(IndexNumber))).scalars().all()] == [
        Decimal("123")
    ]
    assert record.data == {"price": "123"}


async def test_reindex_of_an_empty_type_is_a_no_op(db, make_type, field_def):
    rtype = await make_type("empty", [field_def("name", "text")])
    assert await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=5) == 0


async def test_field_keys_is_accepted_and_still_rebuilds_the_record(db, catalogue):
    rtype, records = catalogue
    await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=10)
    await delete_index(db, records[0].id)
    await reindex_type(
        db, rtype, resolve_type_id=lambda _k: None, batch_size=10, field_keys=["price"]
    )
    rows = (
        (await db.execute(select(IndexText).where(IndexText.record_id == records[0].id)))
        .scalars()
        .all()
    )
    assert {r.field_key for r in rows} == {"name", "tags"}


async def test_clear_pending_removes_only_the_named_keys(db, make_type, field_def):
    rtype = await make_type("item", [field_def("price", "number")])
    rtype.reindex_pending = ["price", "name"]
    db.add(rtype)
    await db.flush()

    await clear_pending(db, rtype, ["price"])
    assert rtype.reindex_pending == ["name"]

    # Read it back from the database: a JSON column has no mutation tracking,
    # so an in-place edit would pass the assertion above and never be written.
    from sm_records.models import RecordType

    stored = (
        await db.execute(select(RecordType.reindex_pending).where(RecordType.id == rtype.id))
    ).scalar_one()
    assert stored == ["name"]
