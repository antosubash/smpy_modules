"""The keyset half of ``index._sorting`` and the cursor codec — F11, F5.

At the SQL layer rather than through HTTP: what has to be right here is that
the predicate agrees with the ordering for *every* shape of sort — ascending,
descending, mixed, over a nullable column and over an index table — and that
is a property of the two functions, not of the endpoint.
"""

from __future__ import annotations

import pytest
from sm_records.index._cursor import CursorError, decode_cursor, encode_cursor, sort_signature
from sm_records.index.query import Sort, page_query, sort_plan
from sm_records.index.writer import write_index
from sm_records.models import Record


async def _walk(db, rtype, fields, sorts, *, size: int) -> list[str]:
    """Page the whole type with ``?after=``, returning the titles in order."""
    signature = sort_signature(rtype.key, sorts)
    seen: list[str] = []
    after = None
    for _ in range(50):
        terms_for_decode = sort_plan(rtype, fields, sorts)
        decoded = decode_cursor(after, signature, terms_for_decode) if after else None
        stmt, terms = page_query(rtype, fields, [], sorts, after=decoded)
        rows = (await db.execute(stmt.limit(size))).all()
        if not rows:
            return seen
        seen += [row[0].display_title for row in rows]
        after = encode_cursor(signature, [*rows[-1][1 : len(terms) + 1], rows[-1][0].id])
    raise AssertionError("cursor walk did not terminate")


async def _seeded(db, make_type, make_record, field_def):
    """Six records, indexed. Deliberately messy: duplicate ranks (so the
    tiebreaker has to carry the order), one record with no ``rank`` at all
    (the ``LEFT JOIN`` NULL branch), and titles that do not sort the way the
    ranks do."""
    fields = [
        field_def("name", "text"),
        field_def("rank", "integer"),
        field_def("seen", "datetime"),
        field_def("cost", "number"),
    ]
    rtype = await make_type("thing", fields, display_field="name")
    for title, rank in [("a", 2), ("b", 1), ("c", 2), ("d", None), ("e", 3), ("f", 1)]:
        data: dict = {"name": title}
        if rank is not None:
            data |= {
                "rank": rank,
                # A *naive* timestamp on purpose: SQLite hands one back for a
                # ``DateTime(timezone=True)`` column written without a zone,
                # and a cursor has to survive that round trip.
                "seen": f"2026-0{rank}-01T09:00:00",
                "cost": f"{rank}.50",
            }
        record = await make_record(rtype, data, display_title=title)
        await write_index(db, record, rtype, resolve_type_id=lambda _key: None)
    return rtype, fields


@pytest.mark.parametrize(
    "sorts",
    [
        (),
        (Sort("display_title"),),
        (Sort("display_title", desc=True),),
        (Sort("position"), Sort("display_title", desc=True)),
        (Sort("rank"),),
        (Sort("rank", desc=True),),
        (Sort("rank"), Sort("display_title", desc=True)),
        (Sort("seen"),),
        (Sort("seen", desc=True),),
        (Sort("cost"),),
        (Sort("created_at", desc=True),),
    ],
    ids=[
        "none",
        "title",
        "-title",
        "position+-title",
        "rank",
        "-rank",
        "rank+-title",
        "seen",
        "-seen",
        "cost",
        "-created_at",
    ],
)
async def test_the_cursor_walk_reproduces_the_ordering(
    db, make_type, make_record, field_def, sorts
):
    rtype, fields = await _seeded(db, make_type, make_record, field_def)
    stmt, _terms = page_query(rtype, fields, [], list(sorts))
    whole = [row[0].display_title for row in (await db.execute(stmt)).all()]
    assert await _walk(db, rtype, fields, list(sorts), size=2) == whole
    # Page size must not change the answer — a boundary that lands inside a
    # group of ties is exactly where a keyset predicate goes wrong.
    assert await _walk(db, rtype, fields, list(sorts), size=1) == whole


async def test_an_index_sort_keeps_records_without_a_value(db, make_type, make_record, field_def):
    """A ``LEFT OUTER JOIN`` and not an inner one: the record with no ``rank``
    is still in the listing, last."""
    rtype, fields = await _seeded(db, make_type, make_record, field_def)
    stmt, _ = page_query(rtype, fields, [], [Sort("rank")])
    titles = [row[0].display_title for row in (await db.execute(stmt)).all()]
    assert len(titles) == 6
    assert titles[-1] == "d"


async def test_a_multi_valued_sort_returns_each_record_once(db, make_type, make_record, field_def):
    fields = [field_def("tags", "multiselect", choices=["x", "y", "z"])]
    rtype = await make_type("tagged", fields)
    for title, tags in [("one", ["x", "z"]), ("two", ["y"]), ("three", [])]:
        record = await make_record(rtype, {"tags": tags}, display_title=title)
        await write_index(db, record, rtype, resolve_type_id=lambda _key: None)
    stmt, _ = page_query(rtype, fields, [], [Sort("tags")])
    rows = (await db.execute(stmt)).all()
    assert sorted(row[0].display_title for row in rows) == ["one", "three", "two"]


async def test_a_cursor_is_bound_to_its_sort(db, make_type, make_record, field_def):
    rtype, _fields = await _seeded(db, make_type, make_record, field_def)
    one = sort_signature(rtype.key, [Sort("rank")])
    raw = encode_cursor(one, [1, 5])
    with pytest.raises(CursorError):
        decode_cursor(raw, sort_signature(rtype.key, [Sort("rank", desc=True)]), [])


async def test_a_cursor_is_bound_to_the_trash_flag(db, make_type, make_record, field_def):
    rtype, _fields = await _seeded(db, make_type, make_record, field_def)
    live = sort_signature(rtype.key, [Sort("rank")])
    trash = sort_signature(rtype.key, [Sort("rank")], trashed=True)
    assert live != trash


@pytest.mark.parametrize("raw", ["", "!!!", "eyJ4IjogMX0", "x" * 5])
async def test_garbage_is_a_cursor_error(db, make_type, make_record, field_def, raw):
    rtype, fields = await _seeded(db, make_type, make_record, field_def)
    with pytest.raises(CursorError):
        decode_cursor(raw, sort_signature(rtype.key, []), sort_plan(rtype, fields, []))


async def test_the_id_tiebreaker_reverses_only_for_an_index_served_sort(
    db, make_type, make_record, field_def
):
    """``ORDER BY x DESC, id DESC`` only where one index can produce the whole
    order — see ``_sorting.tiebreak_desc`` for what it costs anywhere else.
    Observable as the order of a tie."""
    rtype, fields = await _seeded(db, make_type, make_record, field_def)

    async def tied(sorts: list[Sort], titles: tuple[str, ...]) -> list[int]:
        stmt, _ = page_query(rtype, fields, [], sorts)
        rows = (await db.execute(stmt)).all()
        return [row[0].id for row in rows if row[0].display_title in titles]

    # ``display_title`` has a ``(type_id, display_title, id)`` index, and
    # every seeded title is distinct — so tie on ``position`` instead, which
    # has one too and is ``0`` on every record.
    descending = await tied([Sort("position", desc=True)], ("b", "f"))
    assert descending == sorted(descending, reverse=True)
    ascending = await tied([Sort("position")], ("b", "f"))
    assert ascending == sorted(ascending)

    # An indexed *field* sort is never index-served, whatever its direction.
    by_rank = await tied([Sort("rank", desc=True)], ("b", "f"))
    assert by_rank == sorted(by_rank)
    # Neither is a two-term ordering, even when both terms are fixed columns
    # and both tie (every seeded record is a draft at position 0).
    two = await tied([Sort("position"), Sort("status", desc=True)], ("b", "f"))
    assert two == sorted(two)


async def test_the_page_carries_the_record_first(db, make_type, make_record, field_def):
    """``page_query`` rows are ``(Record, *sort values)`` — the service reads
    ``row[0]`` and the rest by position, so the shape is part of the contract."""
    rtype, fields = await _seeded(db, make_type, make_record, field_def)
    stmt, terms = page_query(rtype, fields, [], [Sort("rank")])
    row = (await db.execute(stmt.limit(1))).all()[0]
    assert isinstance(row[0], Record)
    assert len(row) == len(terms) + 1
