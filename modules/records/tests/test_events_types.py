"""Type-level events, and the bulk paths that emit one event per record.

The companion to ``test_events.py``: everything here is about a write that is
not one record — a schema change, a type delete, an import file — and about
the rule the reviewer's design turns on, that each of them still speaks in
records.
"""

from __future__ import annotations

import pytest_asyncio
from sm_records.contracts.events import (
    RecordCreated,
    RecordPurged,
    RecordTypeChanged,
    RecordTypeDeleted,
    RecordUpdated,
)

from tests.app_harness import ADMIN, roles
from tests.events_harness import (
    API,
    TYPES,
    Recorder,
    _create,
    _document,
    _field,
    make_note,
    recorder,
)
from tests.io_helpers import post_import


@pytest_asyncio.fixture
async def bus(client) -> Recorder:
    """A subscriber to every event this module publishes, attached to the
    app's real bus — the same object ``events.publish`` reaches."""
    return recorder(client)


@pytest_asyncio.fixture
async def note(client) -> dict:
    return await make_note(client)


async def test_record_type_changed_names_the_keys_whose_index_moved(client, note, bus):
    bus.seen.clear()
    fields = [*note["fields"], _field("views", "integer")]
    updated = await client.put(
        f"{TYPES}/note",
        json={"expected_version": note["version"], "fields": fields},
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200, updated.text

    assert [type(event) for event in bus.seen] == [RecordTypeChanged]
    event = bus.seen[0]
    assert event.type_key == "note"
    assert event.schema_version == note["schema_version"] + 1
    # A new *indexed* field is additive in what it can break and
    # index-affecting in what it makes stale, and the diff's kind is the most
    # severe change in it — which is exactly the pair a projection cares about.
    assert event.kind == "index_affecting"
    assert event.index_affecting_keys == ("views",)
    assert bus.committed == [True]


async def test_a_retyped_indexed_field_is_index_affecting(client, note, bus):
    """The case the event exists for: a host's own index or reduce provider
    projects from field values, and this is what tells it the projection is
    stale without diffing anything itself."""
    await _create(client, "One")
    bus.seen.clear()
    retyped = [{**note["fields"][0], "type": "longtext", "indexed": False}]
    updated = await client.put(
        f"{TYPES}/note",
        json={"expected_version": note["version"], "fields": retyped, "display_field": None},
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200, updated.text
    event = bus.only(RecordTypeChanged)[0]
    assert event.kind == "restrictive"
    assert event.index_affecting_keys == ("title",)


async def test_deleting_a_type_purges_every_record_and_then_says_the_type_is_gone(
    client, note, bus
):
    first = await _create(client, "One")
    second = await _create(client, "Two")
    bus.seen.clear()
    bus.committed.clear()

    gone = await client.delete(f"{TYPES}/note?confirm_record_count=2", headers=roles(ADMIN))
    assert gone.status_code == 204, gone.text

    assert [type(event) for event in bus.seen] == [RecordPurged, RecordPurged, RecordTypeDeleted]
    assert {event.uuid for event in bus.only(RecordPurged)} == {first["uuid"], second["uuid"]}
    deleted = bus.only(RecordTypeDeleted)[0]
    assert (deleted.type_key, deleted.purged) == ("note", 2)
    # The type row is gone by then; the tenant is the one the request was bound to.
    assert {event.tenant_id for event in bus.seen} == {"default"}
    assert all(bus.committed)


async def test_an_import_emits_one_event_per_row_that_wrote(client, note, bus):
    existing = await _create(client, "One")
    bus.seen.clear()

    rows = [
        {
            "uuid": existing["uuid"],
            "version": existing["version"],
            "data": {"title": "One renamed"},
        },
        {"data": {"title": "Fresh"}},
    ]
    resp = await post_import(client, "note", _document(rows), dry_run="false")
    assert resp.status_code == 200, resp.text
    assert (resp.json()["created"], resp.json()["updated"]) == (1, 1)

    assert [type(event) for event in bus.seen] == [RecordUpdated, RecordCreated]
    assert bus.only(RecordUpdated)[0].uuid == existing["uuid"]
    assert bus.only(RecordCreated)[0].type_key == "note"
    assert all(bus.committed)


async def test_a_dry_run_import_publishes_nothing(client, note, bus):
    await _create(client, "One")
    bus.seen.clear()

    resp = await post_import(client, "note", _document([{"data": {"title": "Fresh"}}]))
    assert resp.status_code == 200, resp.text
    assert bus.seen == []


async def test_a_refused_write_publishes_nothing(client, note, bus):
    record = await _create(client, "One")
    bus.seen.clear()
    stale = await client.put(
        f"{API}/{record['uuid']}",
        json={"expected_version": record["version"] + 5, "data": {"title": "Nope"}},
        headers=roles(ADMIN),
    )
    assert stale.status_code == 409
    assert bus.seen == []


async def test_publishing_is_a_no_op_without_a_bus(client, note, bus):
    """A host that never wired one — or a harness that mounted the routers by
    hand — must still serve the write."""
    client.app.state.sm.event_bus = None
    record = await _create(client, "One")
    assert record["uuid"]
    assert bus.seen == []
