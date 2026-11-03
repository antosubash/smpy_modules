"""test_services_types cases."""

from __future__ import annotations

import pytest
from sm_records.models import Record, RecordType, RecordTypeRevision
from sm_records.records.services import records as record_service
from sm_records.records.services import types as service
from sm_records.records.services.errors import (
    Conflict,
    ReferencedByOthers,
    ValidationFailed,
)
from sqlalchemy import select

from tests.support.services_types_cases import product_fields as product_fields
from tests.support.services_types_cases import revisions


async def test_record_count_ignores_the_trash(db, settings, make_record, product_fields):
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    live = await make_record(rtype, {"title": "a"})
    await make_record(rtype, {"title": "b"}, is_deleted=True)
    assert await service.record_count(db, rtype) == 1
    assert live.id is not None


async def test_label_edit_bumps_version_but_not_schema_version(db, settings, product_fields):
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    await service.update_type(
        db, rtype, expected_version=1, settings=settings, label="Widget", actor="editor"
    )
    assert (rtype.label, rtype.version, rtype.schema_version) == ("Widget", 2, 1)
    # A label cannot damage a record, so it writes no schema snapshot.
    assert len(await revisions(db, rtype)) == 1


async def test_display_field_edit_writes_a_revision(db, settings, product_fields):
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    await service.update_type(
        db, rtype, expected_version=1, settings=settings, display_field="title"
    )
    assert rtype.display_field == "title"
    assert rtype.schema_version == 1
    assert len(await revisions(db, rtype)) == 2


async def test_fields_edit_on_an_empty_type_bumps_schema_version(
    db, settings, product_fields, field_def
):
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    await service.update_type(
        db,
        rtype,
        expected_version=1,
        settings=settings,
        fields_raw=[*product_fields, field_def("stock", "integer")],
    )
    assert (rtype.schema_version, rtype.version) == (2, 2)
    assert [f["key"] for f in rtype.fields] == ["title", "price", "stock"]
    snapshots = await revisions(db, rtype)
    assert [(r.version, r.schema_version) for r in snapshots] == [(1, 1), (2, 2)]


async def test_resending_the_same_fields_is_not_a_schema_change(
    db, settings, product_fields, make_record
):
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    await make_record(rtype, {"title": "held"})
    # Normalised comparison: the stored list is the validator's dump, so an
    # identical resend must not read as a change and trip the Phase 1 lock.
    await service.update_type(
        db, rtype, expected_version=1, settings=settings, fields_raw=product_fields
    )
    assert rtype.schema_version == 1


async def test_an_additive_change_applies_to_a_populated_type(
    db, settings, product_fields, make_record, field_def
):
    """Phase 1 refused this outright (``FieldsLocked``). Phase 3 classifies it:
    a new optional field cannot invalidate a record, so it is applied and the
    records are left alone — design §8.2."""
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    await make_record(rtype, {"title": "held"})
    updated = await service.update_type(
        db,
        rtype,
        expected_version=1,
        settings=settings,
        fields_raw=[*product_fields, field_def("stock", "integer", indexed=False)],
    )
    assert updated.schema_version == 2
    assert [f["key"] for f in updated.fields] == ["title", "price", "stock"]


async def test_key_is_immutable(db, settings):
    rtype = await service.create_type(db, key="product", label="Product", settings=settings)
    with pytest.raises(ValidationFailed, match="immutable"):
        await service.update_type(db, rtype, expected_version=1, settings=settings, key="widget")


async def test_a_stale_expected_version_conflicts_and_carries_the_current_row(db, settings):
    rtype = await service.create_type(db, key="product", label="Product", settings=settings)
    await service.update_type(db, rtype, expected_version=1, settings=settings, label="Widget")
    with pytest.raises(Conflict) as excinfo:
        await service.update_type(db, rtype, expected_version=1, settings=settings, label="Gadget")
    current = excinfo.value.current
    assert isinstance(current, RecordType)
    assert (current.version, current.label) == (2, "Widget")


async def test_delete_refuses_a_stale_record_count(db, settings, product_fields, make_record):
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    await make_record(rtype, {"title": "held"})
    with pytest.raises(Conflict, match="holds 1 record"):
        await service.delete_type(db, rtype, confirm_record_count=0)


async def test_delete_refuses_a_type_other_types_relate_to(db, settings, field_def):
    await service.create_type(db, key="brand", label="Brand", settings=settings)
    await service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("maker", "relation", target_type="brand")],
        settings=settings,
    )
    brand = await service.get_type(db, "brand")
    with pytest.raises(ReferencedByOthers) as excinfo:
        await service.delete_type(db, brand, confirm_record_count=0)
    assert excinfo.value.referrers == ["product"]


async def test_delete_purges_records_and_their_index_rows(db, settings, product_fields):
    from sm_records.models import IndexText

    # A key no other test creates records under: ``schema.compile``'s model
    # cache is process-global and keyed on ``(type key, schema_version)``, so
    # two differently-shaped types sharing a key in one test session would
    # share a validator (see compile.py's docstring).
    rtype = await service.create_type(
        db, key="purgeable", label="Purgeable", fields_raw=product_fields, settings=settings
    )
    await record_service.create_record(db, rtype, data={"title": "gone"}, settings=settings)
    assert (await db.execute(select(IndexText))).scalars().all()

    await service.delete_type(db, rtype, confirm_record_count=1)
    assert (await db.execute(select(IndexText))).scalars().first() is None
    stmt = select(Record).execution_options(include_deleted=True)
    assert (await db.execute(stmt)).scalars().first() is None
    assert (await db.execute(select(RecordTypeRevision))).scalars().first() is None
    assert (await db.execute(select(RecordType))).scalars().first() is None
