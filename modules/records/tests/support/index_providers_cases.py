"""Shared setup for test_index_providers."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sm_records.index import (
    IndexEntry,
    IndexKind,
    VirtualField,
    register_index_provider,
)
from sm_records.models import INDEX_TABLES
from sm_records.records.index.query import build_query
from sm_records.records.index.writer import write_index
from sqlalchemy import select

BUCKET = "price_bucket"


TAGS_UPPER = "tags_upper"


VIRTUAL_FIELDS = [
    VirtualField(BUCKET, IndexKind.NUMBER),
    VirtualField(TAGS_UPPER, IndexKind.TEXT, many=True),
]


def sample_provider(record, rtype):
    """``floor(price / 100)`` and the record's tags uppercased — a computed
    bucket and a normalised sort key, the two examples §7.6 names."""
    data = record.data or {}
    price = data.get("price")
    if price is not None:
        yield IndexEntry(kind=IndexKind.NUMBER, field_key=BUCKET, value=Decimal(str(price)) // 100)
    for tag in data.get("tags") or []:
        yield IndexEntry(kind=IndexKind.TEXT, field_key=TAGS_UPPER, value=str(tag).upper())


def broken_provider(record, rtype):
    raise RuntimeError("provider is broken")
    yield  # pragma: no cover - unreachable, but keeps this a generator


@pytest.fixture
def registered():
    register_index_provider(sample_provider, fields=VIRTUAL_FIELDS)
    return VIRTUAL_FIELDS


@pytest.fixture
async def catalogue(db, make_type, make_record, field_def, registered):
    """Three products, indexed through the built-in provider and the sample
    one. ``price`` and ``tags`` are declared fields; the two virtual keys are
    derived from them and declared by nobody."""
    rtype = await make_type(
        "product",
        [field_def("name", "text"), field_def("price", "number"), field_def("tags", "multiselect")],
    )
    records = []
    for name, price, tags in (
        ("cheap", "50", ["red"]),
        ("mid", "150", ["red", "blue"]),
        ("dear", "250", ["blue"]),
    ):
        record = await make_record(rtype, {"name": name, "price": price, "tags": tags})
        await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
        records.append(record)
    return rtype, records


async def rows(db, table, field_key: str) -> list:
    stmt = select(table).where(table.field_key == field_key).order_by(table.record_id)
    return list((await db.execute(stmt)).scalars().all())


async def found(db, rtype, fields, *filters, sorts=()):
    stmt = build_query(rtype, fields, list(filters), list(sorts))
    return [record.data["name"] for record in (await db.execute(stmt)).scalars().all()]


async def snapshot(db, rtype) -> list[tuple]:
    """Every index row of a type, id-free — the same comparison
    ``test_index_reindex`` makes between the writer and the rebuild."""
    out: list[tuple] = []
    for table in INDEX_TABLES:
        found_rows = (
            (await db.execute(select(table).where(table.type_id == rtype.id))).scalars().all()
        )
        for row in found_rows:
            data = row.model_dump()
            data.pop("id", None)
            out.append((table.__tablename__, tuple(sorted(data.items()))))
    return sorted(out)
