"""The filter grammar: what the index tables can be asked, and what they refuse."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_records.core.constants import TEXT_INDEX_LEN
from sm_records.records.index.query import (
    FIXED_COLUMNS,
    Filter,
    FilterOp,
    QueryError,
    Sort,
    build_query,
    count_query,
)
from sm_records.records.index.writer import write_index
from sm_records.models import RecordStatus
from sqlalchemy import select

from tests.support.index_query_cases import fields, world, found, flt


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
