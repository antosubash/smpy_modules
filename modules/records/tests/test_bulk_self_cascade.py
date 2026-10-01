"""A bulk trash naming both ends of a cascade inside one type.

``on_delete: cascade`` on a self-relation — a category tree, a threaded type —
means trashing a record trashes the records pointing at it, and those are
records of the *same* type, so a list screen can perfectly well have selected
them too. Sent ``[child, parent]`` the batch always worked: the child was
trashed on its own turn and the parent's cascade then skipped it, because the
referrer walk filters the trash. Sent ``[parent, child]`` the child was
already gone by its own turn, ``get_record`` raised ``NotFound``, and the
whole batch was refused with a 404 about a row the caller could see on screen
and the batch itself had removed. A selection has no safe order to send, so
this is the module's problem and not the caller's.

Both orders now answer the same thing, and this file is that claim from three
sides: the response, the database, and the bus. What has *not* changed is a
record that was in the trash before the request — that is still a refusal, the
same one the single-record endpoint gives, because there the caller really is
acting on a state they never read.
"""

from __future__ import annotations

import pytest
from sm_records.contracts.events import RecordTrashed

from tests.app_harness import ADMIN, roles
from tests.bulk_helpers import TYPES, field

CAT = f"{TYPES}/category"
RECORDS = f"{CAT}/records"


async def _tree_type(client) -> None:
    """A ``category`` type pointing at itself with ``on_delete: cascade``.

    Two steps because a relation's target has to exist when the field is
    declared (``services._schema.check_targets``), and at creation it does not.
    """
    created = await client.post(
        TYPES,
        json={
            "key": "category",
            "label": "Category",
            "fields": [field("name", "text")],
            "display_field": "name",
        },
        headers=roles(ADMIN),
    )
    assert created.status_code == 201, created.text
    grown = await client.put(
        CAT,
        json={
            "expected_version": 1,
            "fields": [
                field("name", "text"),
                field("parent", "relation", target_type="category", on_delete="cascade"),
            ],
        },
        headers=roles(ADMIN),
    )
    assert grown.status_code == 200, grown.text


async def _node(client, name: str, parent: str | None = None) -> str:
    data: dict = {"name": name}
    if parent is not None:
        data["parent"] = {"type": "category", "uuid": parent}
    resp = await client.post(RECORDS, json={"data": data}, headers=roles(ADMIN))
    assert resp.status_code == 201, resp.text
    return resp.json()["uuid"]


async def _pair(client) -> tuple[str, str]:
    await _tree_type(client)
    parent = await _node(client, "Parent")
    return parent, await _node(client, "Child", parent)


async def _trash(client, uuids: list[str]):
    return await client.post(
        f"{RECORDS}/bulk",
        json={"action": "trash", "uuids": uuids},
        headers=roles(ADMIN),
    )


async def _in_trash(client) -> set[str]:
    listing = await client.get(f"{RECORDS}?trashed=true", headers=roles(ADMIN))
    assert listing.status_code == 200, listing.text
    return {row["uuid"] for row in listing.json()["items"]}


@pytest.mark.parametrize("order", ["parent first", "child first"])
async def test_both_ends_of_a_cascade_in_one_batch_are_accepted(client, order):
    parent, child = await _pair(client)
    named = [parent, child] if order == "parent first" else [child, parent]

    resp = await _trash(client, named)

    assert resp.status_code == 200, (resp.status_code, resp.text)
    # ``cascaded`` counts what the caller could not have worked out for
    # itself, so a record it named is not in it however it was reached.
    assert resp.json() == {
        "action": "trash",
        "requested": 2,
        "changed": 2,
        "unchanged": 0,
        "cascaded": 0,
    }
    assert await _in_trash(client) == {parent, child}
    for uuid in (parent, child):
        assert (await client.get(f"{RECORDS}/{uuid}", headers=roles(ADMIN))).status_code == 404


@pytest.mark.parametrize("order", ["parent first", "child first"])
async def test_each_record_is_trashed_once_on_the_bus(client, bus, order):
    """One ``RecordTrashed`` per record, and ``cascaded_from`` unset on both.

    The cascade did reach the child in one of the two orders and not in the
    other, and the event must not say so: ``cascaded_from`` exists to name the
    records a request never mentioned (``events.trashed``), and this request
    mentioned both. Attributing it would make the bus order-dependent for a
    pair of batches that are otherwise the same write.
    """
    parent, child = await _pair(client)
    named = [parent, child] if order == "parent first" else [child, parent]
    bus.seen.clear()
    bus.committed.clear()

    assert (await _trash(client, named)).status_code == 200

    trashed = bus.only(RecordTrashed)
    assert [event.uuid for event in trashed] == named
    assert {event.cascaded_from for event in trashed} == {None}
    assert all(bus.committed)


async def test_a_record_trashed_before_the_request_still_refuses_the_batch(client):
    parent, child = await _pair(client)
    gone = await client.delete(f"{RECORDS}/{child}", headers=roles(ADMIN))
    assert gone.status_code in (200, 204), gone.text

    resp = await _trash(client, [parent, child])

    assert resp.status_code == 409, resp.text
    failed = resp.json()["report"]["failed"]
    assert [entry["uuid"] for entry in failed] == [child]
    assert failed[0]["status"] == 404
    # All or nothing: the parent the batch had already trashed came back.
    assert await _in_trash(client) == {child}


async def test_a_cascade_into_a_record_nobody_named_is_still_reported(client):
    """The other half of the count, so the fix cannot have flattened it: an
    unnamed record the cascade reached is what ``cascaded`` is for."""
    parent, child = await _pair(client)

    resp = await _trash(client, [parent])

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "action": "trash",
        "requested": 1,
        "changed": 1,
        "unchanged": 0,
        "cascaded": 1,
    }
    assert await _in_trash(client) == {parent, child}
