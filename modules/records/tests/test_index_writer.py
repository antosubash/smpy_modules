"""The writer: one record's payload becomes rows in the six index tables."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sm_records.constants import TEXT_INDEX_LEN
from sm_records.index import providers as provider_registry
from sm_records.index.providers import IndexEntry
from sm_records.index.writer import delete_index, write_index
from sm_records.models import (
    INDEX_TABLES,
    IndexBool,
    IndexDate,
    IndexDatetime,
    IndexNumber,
    IndexRef,
    IndexText,
)
from sm_records.schema.types import IndexKind
from sqlalchemy import select


async def rows(db, table):
    return list((await db.execute(select(table).order_by(table.id))).scalars().all())


@pytest.fixture
def every_kind(field_def):
    return [
        field_def("title", "text"),
        field_def("price", "number"),
        field_def("live", "boolean"),
        field_def("on", "date"),
        field_def("at", "datetime"),
        field_def("tags", "multiselect"),
        field_def("author", "relation", target_type="people"),
        field_def("notes", "longtext", indexed=False),
        field_def("secret", "text", indexed=False),
    ]


@pytest.fixture
async def article(db, make_type, make_record, every_kind, resolver):
    people = await make_type("people", [])
    rtype = await make_type("article", every_kind)
    record = await make_record(
        rtype,
        {
            "title": "Hello",
            "price": "19.99",
            "live": True,
            "on": "2026-09-19",
            "at": "2026-09-19T08:30:00+00:00",
            "tags": ["red", "blue"],
            "author": {"type": "people", "uuid": "a" * 32},
            "notes": "long prose",
            "secret": "not indexed",
        },
    )
    return record, rtype, resolver(people=people)


async def test_each_kind_lands_in_its_own_table(db, article):
    record, rtype, resolve = article
    await write_index(db, record, rtype, resolve_type_id=resolve)

    text = await rows(db, IndexText)
    assert sorted((r.field_key, r.value) for r in text) == [
        ("tags", "blue"),
        ("tags", "red"),
        ("title", "Hello"),
    ]
    assert [(r.field_key, r.value) for r in await rows(db, IndexNumber)] == [
        ("price", Decimal("19.99"))
    ]
    assert [(r.field_key, r.value) for r in await rows(db, IndexBool)] == [("live", True)]
    assert [(r.field_key, r.value) for r in await rows(db, IndexDate)] == [
        ("on", date(2026, 9, 19))
    ]
    stamped = await rows(db, IndexDatetime)
    assert [r.field_key for r in stamped] == ["at"]
    assert stamped[0].value.replace(tzinfo=None) == datetime(2026, 9, 19, 8, 30)
    refs = await rows(db, IndexRef)
    assert [(r.field_key, r.target_uuid) for r in refs] == [("author", "a" * 32)]

    # Every row carries the type discriminator, or no query finds it.
    for table in INDEX_TABLES:
        assert all(r.type_id == rtype.id for r in await rows(db, table))


async def test_unindexed_fields_produce_nothing(db, article):
    record, rtype, resolve = article
    await write_index(db, record, rtype, resolve_type_id=resolve)
    keys = {r.field_key for r in await rows(db, IndexText)}
    assert "notes" not in keys and "secret" not in keys


async def test_multiselect_yields_one_row_per_value(db, article):
    record, rtype, resolve = article
    await write_index(db, record, rtype, resolve_type_id=resolve)
    assert sorted(r.value for r in await rows(db, IndexText) if r.field_key == "tags") == [
        "blue",
        "red",
    ]


async def test_rewrite_replaces_rather_than_appends(db, article):
    record, rtype, resolve = article
    await write_index(db, record, rtype, resolve_type_id=resolve)
    record.data = {**record.data, "title": "Goodbye", "tags": ["green"]}
    await write_index(db, record, rtype, resolve_type_id=resolve)

    assert sorted((r.field_key, r.value) for r in await rows(db, IndexText)) == [
        ("tags", "green"),
        ("title", "Goodbye"),
    ]


async def test_long_text_splits_across_value_and_value_full(db, make_type, make_record, field_def):
    long = "x" * (TEXT_INDEX_LEN + 10)
    rtype = await make_type("note", [field_def("body", "text")])
    record = await make_record(rtype, {"body": long})
    await write_index(db, record, rtype, resolve_type_id=lambda _k: None)

    row = (await rows(db, IndexText))[0]
    assert row.value == "x" * TEXT_INDEX_LEN
    assert row.value_full == long


async def test_short_text_leaves_value_full_null(db, make_type, make_record, field_def):
    rtype = await make_type("note", [field_def("body", "text")])
    record = await make_record(rtype, {"body": "short"})
    await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
    assert (await rows(db, IndexText))[0].value_full is None


async def test_uncoercible_number_is_simply_absent(db, make_type, make_record, field_def):
    """Design doc §8.4: a value that fails coercion is not an error, it is a
    row that does not exist — which is what makes a type change reindexable
    without rewriting a payload."""
    rtype = await make_type("item", [field_def("price", "number")])
    record = await make_record(rtype, {"price": "about ten"})
    await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
    assert await rows(db, IndexNumber) == []


async def test_naive_datetime_is_absent(db, make_type, make_record, field_def):
    rtype = await make_type("event", [field_def("at", "datetime")])
    record = await make_record(rtype, {"at": "2026-09-19T08:30:00"})
    await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
    assert await rows(db, IndexDatetime) == []


async def test_unknown_relation_target_is_absent(db, make_type, make_record, field_def):
    rtype = await make_type("article", [field_def("author", "relation", target_type="ghosts")])
    record = await make_record(rtype, {"author": {"type": "ghosts", "uuid": "b" * 32}})
    await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
    assert await rows(db, IndexRef) == []


async def test_many_relation_yields_one_row_per_target(
    db, make_type, make_record, field_def, resolver
):
    people = await make_type("people", [])
    rtype = await make_type(
        "article", [field_def("authors", "relation", target_type="people", many=True)]
    )
    record = await make_record(
        rtype,
        {"authors": [{"type": "people", "uuid": "a" * 32}, {"type": "people", "uuid": "c" * 32}]},
    )
    await write_index(db, record, rtype, resolve_type_id=resolver(people=people))
    refs = await rows(db, IndexRef)
    assert sorted(r.target_uuid for r in refs) == ["a" * 32, "c" * 32]
    assert all(r.target_type_id == people.id for r in refs)


async def test_delete_index_clears_every_table(db, article):
    record, rtype, resolve = article
    await write_index(db, record, rtype, resolve_type_id=resolve)
    await delete_index(db, record.id)
    for table in INDEX_TABLES:
        assert await rows(db, table) == []


async def test_registered_provider_rows_are_written_too(db, make_type, make_record, field_def):
    """The §7.6 seam: a provider can index something the schema does not
    express. Registered here, dropped again by the autouse fixture."""

    def bucket(record, rtype):
        yield IndexEntry(kind=IndexKind.TEXT, field_key="_bucket", value="cheap")

    provider_registry.register(bucket)
    rtype = await make_type("item", [field_def("price", "number")])
    record = await make_record(rtype, {"price": 1})
    await write_index(db, record, rtype, resolve_type_id=lambda _k: None)

    assert {r.field_key for r in await rows(db, IndexText)} == {"_bucket"}
