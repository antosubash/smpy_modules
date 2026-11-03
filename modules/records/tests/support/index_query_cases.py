"""Shared setup for test_index_query."""

from __future__ import annotations

import pytest
from sm_records.models import RecordStatus
from sm_records.records.index.query import (
    Filter,
    FilterOp,
    build_query,
)
from sm_records.records.index.writer import write_index


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
