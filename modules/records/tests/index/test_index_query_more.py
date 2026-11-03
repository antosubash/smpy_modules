"""test_index_query cases."""

from __future__ import annotations

import pytest
from sm_records.records.index.query import (
    QueryError,
    Sort,
    build_query,
    count_query,
)
from sm_records.records.index.writer import write_index
from sqlalchemy import select

from tests.support.index_query_cases import fields as fields
from tests.support.index_query_cases import flt, found
from tests.support.index_query_cases import world as world


async def test_sort_by_multi_valued_field_returns_each_record_once(db, world):
    rtype, fields, (first, second, third), _ = world
    assert sorted(await found(db, rtype, fields, sorts=[Sort("tags")])) == sorted(
        [first.id, second.id, third.id]
    )


async def test_soft_deleted_records_are_filtered_by_the_listener(db, world):
    """No predicate here mentions ``is_deleted`` — the framework's
    ``with_loader_criteria`` hook adds it because the statement selects the
    ``Record`` entity. Design doc §7.3: the index rows stay put."""
    rtype, fields, (first, second, third), _ = world
    from sm_records.models import IndexText

    first.is_deleted = True
    db.add(first)
    await db.flush()

    assert await found(db, rtype, fields) == [second.id, third.id]
    assert await found(db, rtype, fields, flt("title", "eq", "Alpha")) == []
    still_indexed = (
        (await db.execute(select(IndexText).where(IndexText.value == "Alpha"))).scalars().all()
    )
    assert len(still_indexed) == 1


async def test_count_matches_the_list(db, world):
    rtype, fields, _records, _ = world
    for filters in ([], [flt("tags", "eq", "blue")], [flt("price", "gt", 5)]):
        listed = await found(db, rtype, fields, *filters)
        counted = (await db.execute(count_query(rtype, fields, filters))).scalar_one()
        assert counted == len(listed)


async def test_count_excludes_soft_deleted(db, world):
    rtype, fields, (first, _, _), _ = world
    first.is_deleted = True
    db.add(first)
    await db.flush()
    assert (await db.execute(count_query(rtype, fields))).scalar_one() == 2


async def test_other_types_records_are_not_returned(db, world, make_type, make_record, fields):
    rtype, type_fields, _records, resolve = world
    other = await make_type("memo", fields)
    stray = await make_record(other, {"title": "Alpha"})
    await write_index(db, stray, other, resolve_type_id=resolve)
    assert stray.id not in await found(db, rtype, type_fields, flt("title", "eq", "Alpha"))


@pytest.mark.parametrize(
    ("field", "reason"),
    [("notes", "not_indexed"), ("draft_note", "not_indexed"), ("nope", "unknown")],
)
async def test_unqueryable_fields_are_refused(db, world, field, reason):
    rtype, fields, _, _ = world
    with pytest.raises(QueryError) as caught:
        build_query(rtype, fields, [flt(field, "eq", "x")])
    assert caught.value.field == field
    assert caught.value.reason == reason


async def test_sorting_by_an_unindexed_field_is_refused(db, world):
    rtype, fields, _, _ = world
    with pytest.raises(QueryError) as caught:
        build_query(rtype, fields, [], [Sort("notes")])
    assert caught.value.field == "notes"


async def test_a_field_mid_reindex_is_refused_loudly(db, world):
    """Design doc §8.5: while the rows move between tables the answer would be
    partial, so the API refuses by name rather than returning half of it."""
    rtype, fields, _, _ = world
    rtype.reindex_pending = {"price": "2026-09-19T10:00:00+00:00"}
    with pytest.raises(QueryError) as caught:
        build_query(rtype, fields, [flt("price", "gt", 1)])
    assert caught.value.reason == "reindexing"
    assert caught.value.field == "price"


@pytest.mark.parametrize(
    ("field", "op", "value"),
    [
        ("price", "contains", "1"),
        ("live", "gt", True),
        ("title", "gt", "A"),
        ("author", "contains", "a"),
        ("price", "eq", "not a number"),
        ("status", "eq", "archived"),
        ("position", "contains", 1),
    ],
)
async def test_unsupported_combinations_raise(db, world, field, op, value):
    rtype, fields, _, _ = world
    with pytest.raises(QueryError):
        build_query(rtype, fields, [flt(field, op, value)])


async def test_empty_in_matches_nothing(db, world):
    rtype, fields, _, _ = world
    assert await found(db, rtype, fields, flt("title", "in", [])) == []
