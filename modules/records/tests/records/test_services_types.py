"""Record Type CRUD: validation, optimistic concurrency, and what routes where.

The interesting cases are the refusals. A type is a schema, so everything that
goes wrong here goes wrong for every record of that type at once. Phase 1
answered that by locking ``fields`` the moment a record existed; Phase 3
replaced the lock with design §8's pipeline, so what this file checks at the
boundary is that a populated type's schema edit *goes* there — the pipeline
itself is ``test_schema_change.py``.
"""

from __future__ import annotations

import pytest
from sm_records.core.settings import RecordsSettings
from sm_records.records.services import types as service
from sm_records.records.services.errors import (
    Conflict,
    NotFound,
    ValidationFailed,
)

from tests.support.services_types_cases import product_fields as product_fields
from tests.support.services_types_cases import revisions


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
