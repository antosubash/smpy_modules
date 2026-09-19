"""The filter grammar: what the index tables can be asked, and what they refuse."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_records.constants import TEXT_INDEX_LEN
from sm_records.index.query import (
    FIXED_COLUMNS,
    Filter,
    FilterOp,
    QueryError,
    Sort,
    build_query,
    count_query,
)
from sm_records.index.writer import write_index
from sm_records.models import RecordStatus
from sqlalchemy import select


@pytest.fixture
def fields(field_def):
    return [
        field_def("title", "text"),
        field_def("price", "number"),
        field_def("live", "boolean"),
        field_def("on", "date"),
        field_def("at", "datetime"),
        field_def("tags", "multiselect"),
        field_def("author", "relation", target_type="people"),
        field_def("notes", "longtext", indexed=False),
        field_def("draft_note", "text", indexed=False),
    ]


@pytest.fixture
async def world(db, make_type, make_record, fields, resolver):
    """Three articles, indexed. Everything below filters over these."""
    people = await make_type("people", fields=[])
    rtype = await make_type("article", fields)
    resolve = resolver(people=people)

    async def add(**payload):
        columns = {k: payload.pop(k) for k in ("status", "display_title", "slug") if k in payload}
        record = await make_record(rtype, payload, **columns)
        await write_index(db, record, rtype, resolve_type_id=resolve)
        return record

    first = await add(
        title="Alpha",
        price="10.00",
        live=True,
        on="2026-01-01",
        at="2026-01-01T09:00:00+00:00",
        tags=["red", "blue"],
        author={"type": "people", "uuid": "a" * 32},
        display_title="Alpha",
        slug="alpha",
        status=RecordStatus.PUBLISHED,
    )
    second = await add(
        title="Beta",
        price="25.50",
        live=False,
        on="2026-06-01",
        at="2026-06-01T09:00:00+00:00",
        tags=["blue"],
        author={"type": "people", "uuid": "b" * 32},
        display_title="Beta",
        slug="beta",
    )
    third = await add(title="Gamma", display_title="Gamma")
    return rtype, fields, [first, second, third], resolve


async def found(db, rtype, fields, *filters, sorts=()):
    stmt = build_query(rtype, fields, list(filters), list(sorts))
    return [r.id for r in (await db.execute(stmt)).scalars().all()]


def flt(field, op, value=None):
    return Filter(field=field, op=FilterOp(op), value=value)


async def test_text_eq_ne_in_contains(db, world):
    rtype, fields, (first, second, third), _ = world
    assert await found(db, rtype, fields, flt("title", "eq", "Alpha")) == [first.id]
    assert await found(db, rtype, fields, flt("title", "ne", "Alpha")) == [second.id, third.id]
    assert await found(db, rtype, fields, flt("title", "in", ["Alpha", "Gamma"])) == [
        first.id,
        third.id,
    ]
    assert await found(db, rtype, fields, flt("title", "contains", "et")) == [second.id]


async def test_contains_escapes_wildcards(db, world):
    rtype, fields, _, _ = world
    assert await found(db, rtype, fields, flt("title", "contains", "%")) == []


async def test_number_comparisons(db, world):
    rtype, fields, (first, second, _), _ = world
    assert await found(db, rtype, fields, flt("price", "gt", 20)) == [second.id]
    assert await found(db, rtype, fields, flt("price", "gte", "10.00")) == [first.id, second.id]
    assert await found(db, rtype, fields, flt("price", "lt", 20)) == [first.id]
    assert await found(db, rtype, fields, flt("price", "lte", "10.00")) == [first.id]
    assert await found(db, rtype, fields, flt("price", "eq", "25.5")) == [second.id]


async def test_bool_and_date_and_datetime_and_ref(db, world):
    rtype, fields, (first, second, _), _ = world
    assert await found(db, rtype, fields, flt("live", "eq", True)) == [first.id]
    assert await found(db, rtype, fields, flt("live", "eq", "false")) == [second.id]
    assert await found(db, rtype, fields, flt("on", "gt", "2026-03-01")) == [second.id]
    assert await found(db, rtype, fields, flt("on", "eq", "2026-01-01")) == [first.id]
    cut = datetime(2026, 3, 1, tzinfo=UTC)
    assert await found(db, rtype, fields, flt("at", "lt", cut)) == [first.id]
    assert await found(db, rtype, fields, flt("author", "eq", "a" * 32)) == [first.id]
    assert await found(db, rtype, fields, flt("author", "in", ["a" * 32, "b" * 32])) == [
        first.id,
        second.id,
    ]


async def test_is_null_is_absence_of_any_row(db, world):
    rtype, fields, (first, second, third), _ = world
    assert await found(db, rtype, fields, flt("price", "is_null")) == [third.id]
    assert await found(db, rtype, fields, flt("price", "is_null", False)) == [first.id, second.id]


async def test_multi_valued_eq_does_not_duplicate_rows(db, world):
    """``blue`` is one of two tags on the first record. An EXISTS returns it
    once; the JOIN this deliberately is not would return it twice."""
    rtype, fields, (first, second, third), _ = world
    assert await found(db, rtype, fields, flt("tags", "eq", "blue")) == [first.id, second.id]
    # ``ne`` is NOT EXISTS, so it reads "no value equals blue" — which the
    # untagged record satisfies. Absence matching ``ne`` is the documented
    # choice; the alternative ("some value differs") would return the record
    # that *is* tagged blue as well, because it is also tagged red.
    assert await found(db, rtype, fields, flt("tags", "ne", "blue")) == [third.id]
    assert await found(db, rtype, fields, flt("tags", "ne", "red")) == [second.id, third.id]


async def test_values_differing_after_the_cut_are_distinguishable(
    db, make_type, make_record, field_def
):
    """Design doc §7.4. Without the ``value_full`` re-check these two records
    are the same row to every query, which is the bug the split creates."""
    shared = "y" * TEXT_INDEX_LEN
    rtype = await make_type("note", [field_def("body", "text")])
    first = await make_record(rtype, {"body": shared + "-one"})
    second = await make_record(rtype, {"body": shared + "-two"})
    short = await make_record(rtype, {"body": shared})
    for record in (first, second, short):
        await write_index(db, record, rtype, resolve_type_id=lambda _k: None)

    fields = rtype.fields
    assert await found(db, rtype, fields, flt("body", "eq", shared + "-one")) == [first.id]
    assert await found(db, rtype, fields, flt("body", "eq", shared)) == [short.id]
    assert await found(db, rtype, fields, flt("body", "contains", "-two")) == [second.id]


async def test_fixed_columns_filter_directly(db, world):
    rtype, fields, (first, second, third), _ = world
    assert {"status", "slug"} <= FIXED_COLUMNS
    assert await found(db, rtype, fields, flt("status", "eq", "published")) == [first.id]
    assert await found(db, rtype, fields, flt("slug", "contains", "et")) == [second.id]
    assert await found(db, rtype, fields, flt("slug", "is_null")) == [third.id]
    assert await found(db, rtype, fields, flt("display_title", "in", ["Beta", "Gamma"])) == [
        second.id,
        third.id,
    ]


async def test_sort_by_indexed_field_and_by_fixed_column(db, world):
    rtype, fields, (first, second, third), _ = world
    by_price = await found(db, rtype, fields, sorts=[Sort("price", desc=True)])
    # Nulls last, whichever direction: the record with no price is not "the
    # cheapest" and must not lead the list.
    assert by_price == [second.id, first.id, third.id]
    by_title = await found(db, rtype, fields, sorts=[Sort("title")])
    assert by_title == [first.id, second.id, third.id]
    by_slug = await found(db, rtype, fields, sorts=[Sort("slug", desc=True)])
    assert by_slug[:2] == [second.id, first.id]


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
