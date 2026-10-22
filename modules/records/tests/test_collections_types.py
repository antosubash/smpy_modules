"""Assigning a type to a collection: at creation, or by a move (#82).

Three rules, all of them HTTP-visible:

* ``POST /types`` takes ``collection`` and validates it against what the host
  declared (422 naming the declared set).
* ``PUT /types/{key}`` with a changed value *moves* the type and its
  records (#82, ``test_collections_move.py``); an echo is a no-op.
* ``TypeRead.collection`` carries it back, and the type-editor view carries
  the declared set so the "new type" form can offer it.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles, seed_type
from tests.collections_harness import COLLECTION_NAMES, seed_collection_record

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def test_a_type_can_be_created_in_a_declared_collection(client, field_def):
    body = {
        "key": "gig",
        "label": "Gig",
        "collection": "events",
        "fields": [field_def("name", "text")],
    }
    created = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert created.status_code == 201
    assert created.json()["collection"] == "events"

    read = await client.get("/api/records/types/gig", headers=roles(ADMIN))
    assert read.json()["collection"] == "events"


async def test_omitting_collection_puts_the_type_in_the_shared_tables(client, field_def):
    body = {"key": "gig", "label": "Gig", "fields": [field_def("name", "text")]}
    created = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert created.status_code == 201
    assert created.json()["collection"] is None


async def test_an_undeclared_collection_is_refused_and_names_what_is_declared(client, field_def):
    body = {
        "key": "gig",
        "label": "Gig",
        "collection": "concerts",
        "fields": [field_def("name", "text")],
    }
    refused = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert "concerts" in detail
    for name in COLLECTION_NAMES:
        assert name in detail


async def test_changing_a_types_collection_moves_it(client, field_def):
    """#82: a changed ``collection`` is a move, not a 409 — the records go
    with it (``test_collections_move.py`` covers what moves)."""
    rtype = await seed_type(
        client.db_state, "gig", [field_def("name", "text")], collection="events"
    )
    await seed_collection_record(client.db_state, rtype, {"name": "One"})
    moved = await client.put(
        f"/api/records/types/{rtype.key}",
        json={"expected_version": rtype.version, "collection": "archive"},
        headers=roles(ADMIN),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["collection"] == "archive"
    assert moved.json()["record_count"] == 1


async def test_moving_a_type_out_of_a_collection_works_too(client, field_def):
    """``null`` is a value like any other here — it names the shared tables."""
    rtype = await seed_type(
        client.db_state, "gig", [field_def("name", "text")], collection="events"
    )
    moved = await client.put(
        f"/api/records/types/{rtype.key}",
        json={"expected_version": rtype.version, "collection": None},
        headers=roles(ADMIN),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["collection"] is None


async def test_echoing_the_current_collection_back_is_accepted(client, field_def):
    """Clients send back the whole type they just read, so a 409 for changing
    nothing would make every save of an unmodified form fail."""
    rtype = await seed_type(
        client.db_state, "gig", [field_def("name", "text")], collection="events"
    )
    saved = await client.put(
        f"/api/records/types/{rtype.key}",
        json={"expected_version": rtype.version, "collection": "events", "label": "Gigs"},
        headers=roles(ADMIN),
    )
    assert saved.status_code == 200
    assert saved.json()["label"] == "Gigs"
    assert saved.json()["collection"] == "events"


async def test_the_type_editor_view_carries_the_declared_collections(client, field_def):
    await seed_type(client.db_state, "gig", [field_def("name", "text")], collection="events")

    new = await client.get("/admin/records/types/new", headers={**roles(ADMIN), **_INERTIA})
    assert new.json()["props"]["collections"] == list(COLLECTION_NAMES)

    edit = await client.get("/admin/records/types/gig", headers={**roles(ADMIN), **_INERTIA})
    assert edit.json()["props"]["type"]["collection"] == "events"


async def test_deleting_a_collection_type_purges_its_own_tables(client, field_def):
    """``DELETE /types/{key}`` confirms against what the type holds and then
    purges it — from the collection's record table, which is the one
    ``record_count`` counted."""
    rtype = await seed_type(
        client.db_state, "gig", [field_def("name", "text")], collection="events"
    )
    await seed_collection_record(client.db_state, rtype, {"name": "One"})

    read = await client.get("/api/records/types/gig", headers=roles(ADMIN))
    assert read.json()["record_count"] == 1

    deleted = await client.delete(
        "/api/records/types/gig?confirm_record_count=1", headers=roles(ADMIN)
    )
    assert deleted.status_code == 204
    assert (await client.get("/api/records/types/gig", headers=roles(ADMIN))).status_code == 404
