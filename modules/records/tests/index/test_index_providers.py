"""Index-provider index_providers cases."""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from sm_records.models import INDEX_TABLES, IndexNumber, IndexText, tables_for
from sm_records.records.index.query import Filter, FilterOp, QueryError, Sort
from sm_records.records.index.reindex import reindex_type
from sm_records.records.index.writer import delete_index, write_index
from sqlalchemy import delete

from tests.support.index_providers_cases import (
    BUCKET,
    TAGS_UPPER,
    found,
    rows,
    snapshot,
)
from tests.support.index_providers_cases import catalogue as catalogue
from tests.support.index_providers_cases import registered as registered


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
        rtype, records = catalogue
        await delete_index(db, tables_for(rtype), records[0].id)
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
