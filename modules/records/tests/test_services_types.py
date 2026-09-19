"""Record Type CRUD: validation, optimistic concurrency, and the Phase 1 lock.

The interesting cases are the refusals. A type is a schema, so everything that
goes wrong here goes wrong for every record of that type at once — which is
why design §16 makes ``fields`` read-only the moment one exists.
"""

from __future__ import annotations

import pytest
from sm_records.models import Record, RecordType, RecordTypeRevision
from sm_records.services import records as record_service
from sm_records.services import types as service
from sm_records.services.errors import (
    Conflict,
    FieldsLocked,
    NotFound,
    ReferencedByOthers,
    ValidationFailed,
)
from sm_records.settings import RecordsSettings
from sqlalchemy import select


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


@pytest.fixture
def product_fields(field_def):
    return [field_def("title", "text"), field_def("price", "number", indexed=False)]


async def revisions(db, rtype):
    stmt = (
        select(RecordTypeRevision)
        .where(RecordTypeRevision.type_id == rtype.id)
        .order_by(RecordTypeRevision.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def test_create_writes_the_row_and_its_first_revision(db, settings, product_fields):
    rtype = await service.create_type(
        db,
        key="product",
        label="Product",
        label_plural="Products",
        fields_raw=product_fields,
        display_field="title",
        settings=settings,
        actor="admin",
    )
    assert (rtype.schema_version, rtype.version) == (1, 1)
    assert [f["key"] for f in rtype.fields] == ["title", "price"]

    first = await revisions(db, rtype)
    assert len(first) == 1
    assert (first[0].version, first[0].schema_version) == (1, 1)
    assert first[0].created_by == "admin"
    # Written aware; SQLite has no timezone type, so it reads back naive there.
    assert first[0].created_at is not None


async def test_create_normalises_unique_into_indexed(db, settings, field_def):
    raw = field_def("sku", "text", indexed=False)
    raw["unique"] = True
    rtype = await service.create_type(
        db, key="item", label="Item", fields_raw=[raw], settings=settings
    )
    assert rtype.fields[0]["indexed"] is True


@pytest.mark.parametrize("key", ["Product", "9lives", "with-dash", ""])
async def test_create_refuses_a_bad_key(db, settings, key):
    with pytest.raises(ValidationFailed):
        await service.create_type(db, key=key, label="X", settings=settings)


async def test_create_refuses_a_duplicate_key(db, settings):
    await service.create_type(db, key="product", label="Product", settings=settings)
    with pytest.raises(Conflict):
        await service.create_type(db, key="product", label="Other", settings=settings)


async def test_create_refuses_a_display_field_that_is_not_a_field(db, settings, product_fields):
    with pytest.raises(ValidationFailed) as excinfo:
        await service.create_type(
            db,
            key="product",
            label="Product",
            fields_raw=product_fields,
            display_field="nope",
            settings=settings,
        )
    assert excinfo.value.errors[0]["field"] == "display_field"


async def test_create_refuses_a_relation_to_an_unknown_type(db, settings, field_def):
    with pytest.raises(ValidationFailed) as excinfo:
        await service.create_type(
            db,
            key="product",
            label="Product",
            fields_raw=[field_def("maker", "relation", target_type="brand")],
            settings=settings,
        )
    assert excinfo.value.errors[0]["field"] == "maker"


async def test_create_allows_a_self_relation(db, settings, field_def):
    rtype = await service.create_type(
        db,
        key="page",
        label="Page",
        fields_raw=[field_def("parent", "relation", target_type="page")],
        settings=settings,
    )
    assert rtype.fields[0]["options"]["target_type"] == "page"


async def test_create_enforces_the_field_ceilings(db, field_def):
    settings = RecordsSettings(max_fields_per_type=2, max_indexed_fields_per_type=1)
    three = [field_def(f"f{n}", "text", indexed=False) for n in range(3)]
    with pytest.raises(ValidationFailed, match="exceeds the limit of 2"):
        await service.create_type(db, key="wide", label="Wide", fields_raw=three, settings=settings)

    two_indexed = [field_def("a", "text"), field_def("b", "text")]
    with pytest.raises(ValidationFailed, match="indexed fields exceeds"):
        await service.create_type(
            db, key="wide", label="Wide", fields_raw=two_indexed, settings=settings
        )


async def test_get_type_and_lookups(db, settings):
    rtype = await service.create_type(db, key="product", label="Product", settings=settings)
    assert (await service.get_type(db, "product")).id == rtype.id
    assert (await service.get_type_by_id(db, rtype.id)).key == "product"
    assert await service.type_id_map(db) == {"product": rtype.id}
    with pytest.raises(NotFound):
        await service.get_type(db, "missing")


async def test_list_types_orders_by_label(db, settings):
    await service.create_type(db, key="zebra", label="Aardvark", settings=settings)
    await service.create_type(db, key="aardvark", label="Zebra", settings=settings)
    assert [t.key for t in await service.list_types(db)] == ["zebra", "aardvark"]


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


async def test_fields_are_locked_once_the_type_holds_a_record(
    db, settings, product_fields, make_record, field_def
):
    rtype = await service.create_type(
        db, key="product", label="Product", fields_raw=product_fields, settings=settings
    )
    await make_record(rtype, {"title": "held"})
    with pytest.raises(FieldsLocked) as excinfo:
        await service.update_type(
            db,
            rtype,
            expected_version=1,
            settings=settings,
            fields_raw=[*product_fields, field_def("stock", "integer")],
        )
    assert excinfo.value.status_code == 409
    assert "read-only" in excinfo.value.detail
    assert rtype.schema_version == 1


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
