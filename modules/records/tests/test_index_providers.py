"""Index providers as a real extension point (design doc §7.6).

A host module projects rows this module knows nothing about, and those rows
are queryable — which is the half that did not exist before Phase 4: a
provider could always *write* under a key no type declares, and the filter
grammar, which resolves a key through the type's ``fields``, could never read
it back.

The sample provider below is the one the README documents: a NUMBER bucket
computed from ``price`` and a TEXT projection of ``tags``, uppercased and
multi-valued. The HTTP half — filters, sorts and the 422 — lives in
``test_index_providers_api.py`` for the 300-line cap.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from sm_records.index import (
    IndexEntry,
    IndexKind,
    VirtualField,
    register_index_provider,
    virtual_fields,
)
from sm_records.index import providers as providers_registry
from sm_records.index.query import Filter, FilterOp, QueryError, Sort, build_query
from sm_records.index.reindex import reindex_type
from sm_records.index.writer import delete_index, write_index
from sm_records.models import INDEX_TABLES, IndexNumber, IndexText
from sm_records.schema.fields import FieldSchemaError, validate_fields
from sqlalchemy import delete, select

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


class TestWritePath:
    async def test_provider_rows_are_written_on_create(self, db, catalogue):
        buckets = await rows(db, IndexNumber, BUCKET)
        assert [row.value for row in buckets] == [Decimal(0), Decimal(1), Decimal(2)]
        tags = await rows(db, IndexText, TAGS_UPPER)
        assert sorted(row.value for row in tags) == ["BLUE", "BLUE", "RED", "RED"]

    async def test_provider_rows_are_replaced_on_update(self, db, catalogue):
        rtype, records = catalogue
        records[0].data = {"name": "cheap", "price": "900", "tags": ["green"]}
        db.add(records[0])
        await write_index(db, records[0], rtype, resolve_type_id=lambda _k: None)

        buckets = await rows(db, IndexNumber, BUCKET)
        assert sorted(row.value for row in buckets) == [Decimal(1), Decimal(2), Decimal(9)]
        mine = [
            row.value
            for row in await rows(db, IndexText, TAGS_UPPER)
            if row.record_id == records[0].id
        ]
        assert mine == ["GREEN"]

    async def test_purge_removes_provider_rows_too(self, db, catalogue):
        _rtype, records = catalogue
        await delete_index(db, records[0].id)
        remaining = {row.record_id for row in await rows(db, IndexNumber, BUCKET)}
        assert records[0].id not in remaining
        assert not [
            row for row in await rows(db, IndexText, TAGS_UPPER) if row.record_id == records[0].id
        ]

    async def test_reindex_reprojects_provider_rows_byte_for_byte(self, db, catalogue):
        rtype, _records = catalogue
        written = await snapshot(db, rtype)
        assert any(row[0] == IndexNumber.__tablename__ for row in written)

        for table in INDEX_TABLES:
            await db.execute(delete(table))
        await db.flush()
        await reindex_type(db, rtype, resolve_type_id=lambda _k: None, batch_size=2)
        assert await snapshot(db, rtype) == written


class TestQuerying:
    async def test_filters_and_sorts_resolve_a_virtual_field(self, db, catalogue):
        rtype, _records = catalogue
        fields = rtype.fields
        assert await found(db, rtype, fields, Filter(BUCKET, FilterOp.EQ, "2")) == ["dear"]
        assert await found(db, rtype, fields, Filter(BUCKET, FilterOp.GTE, "1")) == ["mid", "dear"]
        assert await found(db, rtype, fields, sorts=[Sort(BUCKET, desc=True)]) == [
            "dear",
            "mid",
            "cheap",
        ]
        assert await found(db, rtype, fields, sorts=[Sort(BUCKET)]) == ["cheap", "mid", "dear"]

    async def test_many_decides_any_of_and_none_of(self, db, catalogue):
        rtype, _records = catalogue
        fields = rtype.fields
        assert await found(db, rtype, fields, Filter(TAGS_UPPER, FilterOp.EQ, "RED")) == [
            "cheap",
            "mid",
        ]
        assert await found(db, rtype, fields, Filter(TAGS_UPPER, FilterOp.NE, "RED")) == ["dear"]

    async def test_operator_matrix_is_the_kind_s(self, db, catalogue):
        """A TEXT virtual field refuses ``gt`` exactly as a declared one does
        — the value column holds 512 characters, whoever wrote the row."""
        rtype, _records = catalogue
        with pytest.raises(QueryError) as exc:
            await found(db, rtype, rtype.fields, Filter(TAGS_UPPER, FilterOp.GT, "A"))
        assert exc.value.reason == "unsupported_op"

    async def test_truncation_recheck_applies(self, db, make_type, make_record, registered):
        """§7.4: two values differing only after character 512 are one row to
        the indexed column, so equality must re-check ``value_full``."""
        rtype = await make_type("long", [])
        long_a, long_b = "x" * 600 + "a", "x" * 600 + "b"
        for value in (long_a, long_b):
            record = await make_record(rtype, {"tags": [value], "name": value[-1]})
            await write_index(db, record, rtype, resolve_type_id=lambda _k: None)
        hits = await found(db, rtype, [], Filter(TAGS_UPPER, FilterOp.EQ, long_a.upper()))
        assert hits == ["a"]

    async def test_a_virtual_field_is_never_refused_as_reindexing(self, db, catalogue):
        """A provider change is a deployment, not a schema edit, so no marker
        is ever set for a virtual key — even while the type has one."""
        rtype, _records = catalogue
        rtype.reindex_pending = {"price": "2026-09-20T00:00:00+00:00"}
        assert await found(db, rtype, rtype.fields, Filter(BUCKET, FilterOp.EQ, "2")) == ["dear"]

    async def test_an_unknown_key_is_still_unknown(self, db, catalogue):
        rtype, _records = catalogue
        with pytest.raises(QueryError) as exc:
            await found(db, rtype, rtype.fields, Filter("nope", FilterOp.EQ, "1"))
        assert exc.value.reason == "unknown"

    async def test_a_declared_field_wins_and_warns_once(
        self, db, make_type, make_record, field_def, registered, caplog
    ):
        """Only reachable for a type stored before the key was registered —
        ``validate_fields`` refuses it now. The declared field has real rows
        under the key, so it is what answers, and the collision is logged
        once per type rather than once per request."""
        fields = [field_def(BUCKET, "text"), field_def("name", "text")]
        rtype = await make_type("legacy", fields)
        record = await make_record(rtype, {BUCKET: "declared", "name": "one", "price": "250"})
        await write_index(db, record, rtype, resolve_type_id=lambda _k: None)

        with caplog.at_level(logging.WARNING):
            assert await found(db, rtype, fields, Filter(BUCKET, FilterOp.EQ, "declared")) == [
                "one"
            ]
            assert await found(db, rtype, fields, Filter(BUCKET, FilterOp.EQ, "declared")) == [
                "one"
            ]
        warnings = [rec for rec in caplog.records if "virtual field" in rec.getMessage()]
        assert len(warnings) == 1
        assert "legacy" in warnings[0].getMessage()


class TestRegistry:
    def test_two_providers_claiming_one_key_is_a_value_error(self, registered):
        def other_provider(record, rtype):
            yield IndexEntry(kind=IndexKind.NUMBER, field_key=BUCKET, value=1)

        with pytest.raises(ValueError, match=BUCKET):
            register_index_provider(other_provider, fields=[VirtualField(BUCKET, IndexKind.NUMBER)])
        assert other_provider not in providers_registry.providers()

    def test_registering_the_same_provider_twice_is_idempotent(self, registered):
        register_index_provider(sample_provider, fields=VIRTUAL_FIELDS)
        assert providers_registry.providers().count(sample_provider) == 1

    def test_clear_restores_the_builtin_and_drops_virtual_fields(self, registered):
        assert set(virtual_fields()) == {BUCKET, TAGS_UPPER}
        providers_registry.clear()
        assert providers_registry.providers() == (providers_registry.schema_provider,)
        assert virtual_fields() == {}

    def test_a_virtual_key_is_refused_as_a_declared_field(self, registered, field_def):
        with pytest.raises(FieldSchemaError, match="index provider") as exc:
            validate_fields([field_def(BUCKET, "number")])
        assert exc.value.key == BUCKET

    def test_the_same_key_is_fine_once_the_provider_is_gone(self, registered, field_def):
        providers_registry.clear()
        assert validate_fields([field_def(BUCKET, "number")])[0].key == BUCKET


class TestFailureIsolation:
    async def test_a_raising_provider_is_logged_and_the_write_survives(
        self, db, make_type, make_record, field_def, registered, caplog
    ):
        register_index_provider(broken_provider)
        rtype = await make_type("product", [field_def("price", "number")])
        record = await make_record(rtype, {"price": "250", "tags": ["red"]})

        with caplog.at_level(logging.ERROR):
            await write_index(db, record, rtype, resolve_type_id=lambda _k: None)

        assert [row.value for row in await rows(db, IndexNumber, BUCKET)] == [Decimal(2)]
        assert [row.value for row in await rows(db, IndexText, TAGS_UPPER)] == ["RED"]
        logged = [rec for rec in caplog.records if "index provider" in rec.getMessage()]
        assert len(logged) == 1
        assert "broken_provider" in logged[0].getMessage()
        assert record.uuid in logged[0].getMessage()
        assert logged[0].exc_info is not None
