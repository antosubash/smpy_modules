"""Bulk composes the single-record path — the relations, and the events.

The value of a bulk endpoint that calls the single-record service is that
every rule already written stays written: the ``on_delete`` graph is walked
per record, a ``restrict`` refuses the batch instead of half-applying it, a
referrer whose type the caller may not write blocks the same way, and the bus
hears exactly what it would have heard from the same actions one at a time.
This file is those four, because they are what a second implementation would
have got wrong.
"""

from __future__ import annotations

import pytest_asyncio
from sm_records.contracts.events import RecordPurged, RecordRestored, RecordTrashed, RecordUpdated

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, roles
from tests.bulk_helpers import API, TYPES, bulk, field, make_product, make_records, read
from tests.events_harness import Recorder, recorder


async def _brands(client, *, on_delete: str, brand_roles: list[str] | None = None) -> None:
    """A ``brand`` type and a ``product`` type pointing at it with ``on_delete``."""
    brand = await client.post(
        TYPES,
        json={
            "key": "brand",
            "label": "Brand",
            "fields": [field("name", "text")],
            "display_field": "name",
            "allowed_roles": brand_roles or [],
        },
        headers=roles(ADMIN),
    )
    assert brand.status_code == 201, brand.text
    await make_product(client)
    product = await client.put(
        f"{TYPES}/product",
        json={
            "expected_version": 1,
            "fields": [
                field("name", "text"),
                field("topic", "text"),
                field("brand", "relation", target_type="brand", on_delete=on_delete),
            ],
        },
        headers=roles(ADMIN),
    )
    assert product.status_code == 200, product.text


async def _brand_record(client, name: str = "Acme") -> str:
    resp = await client.post(
        f"{TYPES}/brand/records", json={"data": {"name": name}}, headers=roles(ADMIN)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["uuid"]


async def _product_for(client, brand_uuid: str, name: str = "Widget") -> str:
    resp = await client.post(
        API,
        json={"data": {"name": name, "brand": {"type": "brand", "uuid": brand_uuid}}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["uuid"]


async def _bulk_brands(client, action: str, uuids: list[str], *, actor: str = ADMIN):
    return await client.post(
        f"{TYPES}/brand/records/bulk",
        json={"action": action, "uuids": uuids},
        headers=roles(actor),
    )


# --- relations -------------------------------------------------------------


async def test_a_cascade_reaches_records_the_batch_never_named(client):
    await _brands(client, on_delete="cascade")
    brands = [await _brand_record(client, "Acme"), await _brand_record(client, "Other")]
    child = await _product_for(client, brands[0])

    resp = await _bulk_brands(client, "trash", brands)

    assert resp.status_code == 200, resp.text
    # Two named, three trashed: ``cascaded`` is the number the caller could
    # not have worked out for itself.
    assert resp.json() == {"action": "trash", "requested": 2, "changed": 2, "cascaded": 1}
    assert (await read(client, child)).status_code == 404


async def test_a_restrict_referrer_refuses_the_whole_batch(client):
    await _brands(client, on_delete="restrict")
    brands = [await _brand_record(client, "Acme"), await _brand_record(client, "Other")]
    await _product_for(client, brands[0])

    resp = await _bulk_brands(client, "trash", brands)

    assert resp.status_code == 409, resp.text
    failed = resp.json()["report"]["failed"]
    assert [entry["uuid"] for entry in failed] == [brands[0]]
    assert failed[0]["status"] == 409
    assert "still reference" in failed[0]["message"]
    # The unblocked brand stayed put: all or nothing, including the half of
    # the batch that had nothing wrong with it.
    for uuid in brands:
        got = await client.get(f"{TYPES}/brand/records/{uuid}", headers=roles(ADMIN))
        assert got.status_code == 200


async def test_a_set_null_rewrite_is_rolled_back_with_the_batch(client):
    """The referrer rewrite happens *before* the refusal it cannot foresee —
    so the rollback is what makes "nothing was written" true of it too."""
    await _brands(client, on_delete="set_null")
    keep = await _brand_record(client, "Acme")
    child = await _product_for(client, keep)

    resp = await _bulk_brands(client, "trash", [keep, "f" * 32])

    assert resp.status_code == 409, resp.text
    assert (await read(client, child)).json()["data"]["brand"] is not None


async def test_a_referrer_the_caller_may_not_write_blocks_the_batch(client):
    """Design §10 reaching a type the URL never names: the ``product`` type
    narrows to one role, so a ``cascade`` into it from a caller holding
    another is treated as ``restrict``."""
    await _brands(client, on_delete="cascade")
    brand = await _brand_record(client)
    # Written before the narrowing, because ``allowed_roles`` has no admin
    # bypass — the seeding caller would be refused by the very rule under test.
    await _product_for(client, brand)
    narrowed = await client.put(
        f"{TYPES}/product",
        json={"expected_version": 2, "allowed_roles": [ROLE_EDITOR]},
        headers=roles(ADMIN),
    )
    assert narrowed.status_code == 200, narrowed.text

    refused = await _bulk_brands(client, "trash", [brand], actor=ROLE_EDITOR_TWO)
    assert refused.status_code == 409, refused.text
    assert refused.json()["report"]["failed"][0]["uuid"] == brand

    allowed = await _bulk_brands(client, "trash", [brand], actor=ROLE_EDITOR)
    assert allowed.status_code == 200, allowed.text


# --- events ----------------------------------------------------------------


@pytest_asyncio.fixture
async def bus(client) -> Recorder:
    return recorder(client)


@pytest_asyncio.fixture
async def product(client) -> dict:
    return await make_product(client)


async def test_a_bulk_trash_publishes_one_event_per_record(client, product, bus):
    uuids = await make_records(client, 3)
    bus.seen.clear()
    bus.committed.clear()

    assert (await bulk(client, "trash", uuids)).status_code == 200

    trashed = bus.only(RecordTrashed)
    assert [event.uuid for event in trashed] == uuids
    # Every one of them was named by the caller, so none is a cascade.
    assert {event.cascaded_from for event in trashed} == {None}
    # And every one landed after the commit — the whole reason this module
    # publishes through ``deferred``.
    assert all(bus.committed)


async def test_a_bulk_cascade_marks_the_record_it_cascaded_from(client, bus):
    await _brands(client, on_delete="cascade")
    brand = await _brand_record(client)
    child = await _product_for(client, brand)
    bus.seen.clear()
    bus.committed.clear()

    assert (await _bulk_brands(client, "trash", [brand])).status_code == 200

    by_uuid = {event.uuid: event for event in bus.only(RecordTrashed)}
    assert by_uuid[brand].cascaded_from is None
    assert by_uuid[child].cascaded_from == brand


async def test_bulk_restore_and_purge_publish_theirs(client, product, bus):
    uuids = await make_records(client, 2)
    assert (await bulk(client, "trash", uuids)).status_code == 200
    bus.seen.clear()
    bus.committed.clear()

    assert (await bulk(client, "restore", uuids)).status_code == 200
    assert [event.uuid for event in bus.only(RecordRestored)] == uuids

    assert (await bulk(client, "trash", uuids)).status_code == 200
    bus.seen.clear()
    bus.committed.clear()
    assert (await bulk(client, "purge", uuids)).status_code == 200

    purged = bus.only(RecordPurged)
    assert [event.uuid for event in purged] == uuids
    # The one event whose subject is gone: it carries what the row held.
    assert all(event.locale == "en" and event.translation_group for event in purged)
    assert all(bus.committed)


async def test_bulk_publish_publishes_the_status_transition(client, product, bus):
    uuids = await make_records(client, 2)
    bus.seen.clear()
    bus.committed.clear()

    assert (await bulk(client, "publish", uuids)).status_code == 200

    updated = bus.only(RecordUpdated)
    assert [event.uuid for event in updated] == uuids
    assert {(event.status_before, event.status_after) for event in updated} == {
        ("draft", "published")
    }
    assert all(bus.committed)


async def test_a_refused_batch_publishes_nothing(client, product, bus):
    uuids = await make_records(client, 2)
    bus.seen.clear()
    bus.committed.clear()

    refused = await bulk(client, "trash", [*uuids, "f" * 32])

    assert refused.status_code == 409
    assert bus.seen == []
