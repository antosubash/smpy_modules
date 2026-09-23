"""The record events this module publishes, and when.

Two things are asserted about each one: the payload — identifiers plus the few
fields a subscriber can act on without a second query — and the *timing*. The
timing is the harder half and the reason this module publishes through
:mod:`sm_records.deferred` rather than inline: a handler that fires inside the
request's transaction sees a write that may still roll back, and reading the
record back from any other session would not find it at all. So the recorder
in ``tests/events_harness.py`` opens a session of its own per event and asserts
the write is already visible from it, which is only true after the commit.

The bus is the framework's (``simple_module_core.events``), reached where
production reaches it: ``request.app.state.sm.event_bus``, which
``tests.app_harness`` provides.

Type-level events and the bulk paths are in ``test_events_types.py``.
"""

from __future__ import annotations

import pytest_asyncio
from sm_records.contracts.events import (
    RecordCreated,
    RecordPurged,
    RecordRestored,
    RecordTrashed,
    RecordUpdated,
)

from tests.app_harness import ADMIN, roles
from tests.events_harness import API, TYPES, Recorder, _create, _field, make_note, recorder


@pytest_asyncio.fixture
async def bus(client) -> Recorder:
    """A subscriber to every event this module publishes, attached to the
    app's real bus — the same object ``events.publish`` reaches."""
    return recorder(client)


@pytest_asyncio.fixture
async def note(client) -> dict:
    return await make_note(client)


async def test_record_created_carries_the_identity_and_lands_after_the_commit(client, note, bus):
    record = await _create(client, "One", status="published")

    assert [type(event) for event in bus.seen] == [RecordCreated]
    event = bus.seen[0]
    assert event.type_key == "note"
    # A single-tenant host: every row, and so every event, is in ``default``
    # (tenancy design §A.5). The two-tenant case is ``test_tenancy_deferred``.
    assert event.tenant_id == "default"
    assert event.uuid == record["uuid"]
    assert event.locale == record["locale"]
    # A record alone in a group carries a group named after its own uuid
    # (§4.3), so a subscriber grouping by it needs no special case.
    assert event.translation_group == record["uuid"]
    assert event.status == "published"
    assert bus.committed == [True]


async def test_record_updated_carries_the_status_pair(client, note, bus):
    record = await _create(client, "One")
    bus.seen.clear()
    bus.committed.clear()

    updated = await client.put(
        f"{API}/{record['uuid']}",
        json={
            "expected_version": record["version"],
            "data": {"title": "Two"},
            "status": "published",
        },
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200, updated.text

    assert [type(event) for event in bus.seen] == [RecordUpdated]
    event = bus.seen[0]
    assert (event.status_before, event.status_after) == ("draft", "published")
    assert event.version == record["version"] + 1
    assert bus.committed == [True]
    # A create-as-published is one event, not two: this is why publishing is
    # not its own event type.
    assert bus.only(RecordCreated) == []


async def test_a_revision_restore_is_an_ordinary_update(client, note, bus):
    record = await _create(client, "One")
    await client.put(
        f"{API}/{record['uuid']}",
        json={"expected_version": record["version"], "data": {"title": "Two"}},
        headers=roles(ADMIN),
    )
    bus.seen.clear()

    restored = await client.post(
        f"{API}/{record['uuid']}/revisions/1/restore",
        json={"expected_version": 2},
        headers=roles(ADMIN),
    )
    assert restored.status_code == 200, restored.text
    assert [type(event) for event in bus.seen] == [RecordUpdated]
    assert bus.seen[0].version == 3


async def test_a_translation_is_a_record_created(client, note, bus):
    from tests.i18n_helpers import use_locales

    use_locales(client, "en", "de")
    record = await _create(client, "One")
    bus.seen.clear()

    sibling = await client.post(
        f"{API}/{record['uuid']}/translations", json={"locale": "de"}, headers=roles(ADMIN)
    )
    assert sibling.status_code == 201, sibling.text
    assert [type(event) for event in bus.seen] == [RecordCreated]
    event = bus.seen[0]
    assert event.locale == "de"
    assert event.translation_group == record["uuid"]
    assert event.uuid != record["uuid"]


async def test_trash_names_the_record_and_distinguishes_a_cascade(client, bus):
    """The event no other layer could produce: a delete cascades into records
    of types the URL never names (§9), and ``cascaded_from`` is what tells a
    subscriber which record the operator actually asked about."""
    brand = await client.post(
        TYPES,
        json={
            "key": "brand",
            "label": "Brand",
            "fields": [_field("name", "text")],
            "display_field": "name",
        },
        headers=roles(ADMIN),
    )
    assert brand.status_code == 201, brand.text
    product = await client.post(
        TYPES,
        json={
            "key": "product",
            "label": "Product",
            "fields": [
                _field("name", "text"),
                _field("brand", "relation", target_type="brand", on_delete="cascade"),
            ],
            "display_field": "name",
        },
        headers=roles(ADMIN),
    )
    assert product.status_code == 201, product.text
    made = await client.post(
        f"{TYPES}/brand/records", json={"data": {"name": "Acme"}}, headers=roles(ADMIN)
    )
    child = await client.post(
        f"{TYPES}/product/records",
        json={"data": {"name": "Widget", "brand": {"type": "brand", "uuid": made.json()["uuid"]}}},
        headers=roles(ADMIN),
    )
    assert child.status_code == 201, child.text
    bus.seen.clear()
    bus.committed.clear()

    gone = await client.delete(f"{TYPES}/brand/records/{made.json()['uuid']}", headers=roles(ADMIN))
    assert gone.status_code == 204, gone.text

    trashed = bus.only(RecordTrashed)
    assert len(trashed) == 2
    by_uuid = {event.uuid: event for event in trashed}
    assert by_uuid[made.json()["uuid"]].cascaded_from is None
    cascaded = by_uuid[child.json()["uuid"]]
    assert cascaded.type_key == "product"
    assert {event.tenant_id for event in trashed} == {"default"}
    assert cascaded.cascaded_from == made.json()["uuid"]
    assert all(bus.committed)


async def test_restore_and_purge(client, note, bus):
    record = await _create(client, "One")
    await client.delete(f"{API}/{record['uuid']}", headers=roles(ADMIN))
    bus.seen.clear()
    bus.committed.clear()

    back = await client.post(f"{API}/{record['uuid']}/restore", headers=roles(ADMIN))
    assert back.status_code == 200, back.text
    assert [type(event) for event in bus.seen] == [RecordRestored]
    assert bus.seen[0].uuid == record["uuid"]

    await client.delete(f"{API}/{record['uuid']}", headers=roles(ADMIN))
    bus.seen.clear()
    bus.committed.clear()
    purged = await client.delete(f"{API}/{record['uuid']}/purge", headers=roles(ADMIN))
    assert purged.status_code == 204, purged.text

    assert [type(event) for event in bus.seen] == [RecordPurged]
    event = bus.seen[0]
    # The one event whose subject is gone, so it has to be complete in itself.
    assert (event.type_key, event.uuid) == ("note", record["uuid"])
    assert event.locale == record["locale"]
    assert event.translation_group == record["uuid"]
    assert bus.committed == [True]
