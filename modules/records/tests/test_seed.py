"""The demo-data seeder: types, counts, relations, uniqueness, idempotency.

Runs against the same in-memory ``db_state``/``settings`` fixtures every other
test file uses (``tests/conftest.py``) rather than a fresh ``:memory:``
database of its own — this *is* the in-process entry point
(``sm_records.seed.seed_database``) a test or perf harness is meant to call,
so exercising it any other way would test something else.
"""

from __future__ import annotations

from typing import Any

import pytest
from sm_records.models import Record, RecordType
from sm_records.seed import seed_database
from sm_records.seed.types import TYPE_DEFS
from sm_records.settings import RecordsSettings
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


async def _types_by_key(db: AsyncSession) -> dict[str, RecordType]:
    rows = (await db.execute(select(RecordType))).scalars().all()
    return {row.key: row for row in rows}


async def _records_of(db: AsyncSession, rtype: RecordType) -> list[Record]:
    stmt = select(Record).where(Record.type_id == rtype.id).execution_options(include_deleted=True)
    return list((await db.execute(stmt)).scalars().all())


async def _total_record_count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count(Record.id)))).scalar_one())


async def test_seed_creates_the_five_types_with_declared_fields(db_state, settings, db):
    await seed_database(db_state, settings, records=60, seed=1, reset=True)

    types = await _types_by_key(db)
    assert set(types) == {"company", "contact", "product", "store", "order"}
    for type_def in TYPE_DEFS:
        stored_keys = {field["key"] for field in types[type_def.key].fields}
        expected_keys = {field["key"] for field in type_def.fields}
        assert stored_keys == expected_keys
        assert types[type_def.key].display_field == type_def.display_field
        assert types[type_def.key].slug_field == type_def.slug_field


async def test_seed_writes_exactly_n_records_total(db_state, settings, db):
    summary = await seed_database(db_state, settings, records=60, seed=1, reset=True)

    assert summary.total == 60
    assert sum(summary.created.values()) == 60
    assert await _total_record_count(db) == 60
    # Every type got at least one record — the task's "minimum 1 each".
    assert all(count >= 1 for count in summary.created.values())


async def test_relations_resolve_to_real_records_of_the_declared_type(db_state, settings, db):
    await seed_database(db_state, settings, records=80, seed=2, reset=True)

    types = await _types_by_key(db)
    uuids_by_type = {
        key: {record.uuid for record in await _records_of(db, rtype)}
        for key, rtype in types.items()
    }

    contacts = await _records_of(db, types["contact"])
    for record in contacts:
        company = record.data.get("company")
        if company is not None:
            assert company["type"] == "company"
            assert company["uuid"] in uuids_by_type["company"]

    stores = await _records_of(db, types["store"])
    for record in stores:
        manager = record.data.get("manager")
        if manager is not None:
            assert manager["type"] == "contact"
            assert manager["uuid"] in uuids_by_type["contact"]

    orders = await _records_of(db, types["order"])
    assert orders, "the 45% share of 80 records should not be empty"
    for record in orders:
        customer = record.data["customer"]
        assert customer["type"] == "contact"
        assert customer["uuid"] in uuids_by_type["contact"]
        for item in record.data.get("products") or []:
            assert item["type"] == "product"
            assert item["uuid"] in uuids_by_type["product"]


async def _unique_values(db: AsyncSession, rtype: RecordType, field_key: str) -> list[Any]:
    records = await _records_of(db, rtype)
    return [record.data[field_key] for record in records if field_key in record.data]


async def test_unique_fields_are_actually_unique(db_state, settings, db):
    await seed_database(db_state, settings, records=80, seed=3, reset=True)

    types = await _types_by_key(db)
    for type_key, field_key in (("contact", "email"), ("product", "sku"), ("order", "order_no")):
        values = await _unique_values(db, types[type_key], field_key)
        assert len(values) == len(set(values)), f"{type_key}.{field_key} has a duplicate"


async def test_rerunning_adds_more_records_without_collisions(db_state, settings, db):
    await seed_database(db_state, settings, records=60, seed=42, reset=True)
    first_total = await _total_record_count(db)

    await seed_database(db_state, settings, records=60, seed=42, reset=False)
    second_total = await _total_record_count(db)

    assert first_total == 60
    assert second_total == 120

    types = await _types_by_key(db)
    for type_key, field_key in (("contact", "email"), ("product", "sku"), ("order", "order_no")):
        values = await _unique_values(db, types[type_key], field_key)
        assert len(values) == len(set(values)), f"{type_key}.{field_key} collided across runs"


async def test_reset_purges_every_seeded_record(db_state, settings, db):
    await seed_database(db_state, settings, records=60, seed=7, reset=True)
    assert await _total_record_count(db) == 60

    summary = await seed_database(db_state, settings, records=0, seed=7, reset=True)

    assert summary.total == 0
    assert await _total_record_count(db) == 0
    # The types themselves are recreated empty, not left missing — a second
    # ``--reset``-less run should be able to top them up immediately.
    types = await _types_by_key(db)
    assert set(types) == {"company", "contact", "product", "store", "order"}


async def test_deterministic_for_the_same_seed(db_state, settings, db):
    summary_a = await seed_database(db_state, settings, records=30, seed=99, reset=True)
    types = await _types_by_key(db)
    companies_a = sorted(record.data["name"] for record in await _records_of(db, types["company"]))

    summary_b = await seed_database(db_state, settings, records=30, seed=99, reset=True)
    types = await _types_by_key(db)
    companies_b = sorted(record.data["name"] for record in await _records_of(db, types["company"]))

    assert summary_a.created == summary_b.created
    assert companies_a == companies_b
