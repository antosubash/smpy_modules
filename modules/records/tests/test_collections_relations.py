"""Relations across a collection boundary — §6.4.

A ``relation`` names its target by ``(type, uuid)`` and nothing about that
says the two records share a table set, so every half of §9 has to work in
both directions at once:

* the **write** check, which resolves the target uuid — and now has to look in
  whichever set the target type lives in;
* **referrers**, where a ref row lives in the *referrer's* collection table and
  names ``target_uuid`` + ``target_type_id``, so "who references X" has to ask
  every set that can hold one — which since S5 is the sets holding a type with
  a relation to X's type, not every set the host has ever declared;
* **``on_delete``**, which trashes, nulls or blocks records in another set;
* **``?expand=``**, where the *target type* decides the table and the promise
  is still one batched query per field.

``venue`` points from the ``events`` collection at a global ``hall``;
``sponsor`` points the other way, from a global ``deal`` into the collection.
Both directions in one graph, because a loop that happened to work one way
round would look correct with only one.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from tests.app_harness import ADMIN, roles
from tests.collections_harness import COLLECTION_NAMES
from tests.relation_helpers import field, make_record, make_type


async def _graph(client, *, venue_on_delete: str = "restrict"):
    """``hall`` (global) <- ``gig`` (events) <- ``deal`` (global)."""
    await make_type(client, "hall", [field("name", "text")])
    await make_type(
        client,
        "gig",
        [
            field("name", "text"),
            field("venue", "relation", target_type="hall", on_delete=venue_on_delete),
        ],
        collection="events",
    )
    await make_type(
        client,
        "deal",
        [
            field("name", "text"),
            field("gig", "relation", target_type="gig", on_delete="restrict"),
        ],
    )


def _refs(uuid: str, type_key: str) -> str:
    return f"/api/records/types/{type_key}/records/{uuid}/referrers"


async def test_a_collection_record_may_point_at_a_global_one(client):
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    gig = await make_record(
        client, "gig", {"name": "Launch", "venue": {"type": "hall", "uuid": hall["uuid"]}}
    )
    assert gig["data"]["venue"]["uuid"] == hall["uuid"]


async def test_a_global_record_may_point_into_a_collection(client):
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    gig = await make_record(
        client, "gig", {"name": "Launch", "venue": {"type": "hall", "uuid": hall["uuid"]}}
    )
    deal = await make_record(
        client, "deal", {"name": "Sponsorship", "gig": {"type": "gig", "uuid": gig["uuid"]}}
    )
    assert deal["data"]["gig"]["uuid"] == gig["uuid"]


async def test_a_relation_to_a_uuid_that_is_not_a_record_of_the_target_type_is_refused(client):
    """The write check reads every table set, so a uuid belonging to a record
    of *another* type is found and reported as the wrong type rather than
    silently passing because it happened to be in another collection."""
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    refused = await client.post(
        "/api/records/types/deal/records",
        json={"data": {"name": "Bad", "gig": {"type": "gig", "uuid": hall["uuid"]}}},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 422
    assert "is not a 'gig'" in refused.json()["detail"]


async def test_referrers_finds_a_referrer_in_a_collection(client):
    """The ref row is in ``records_c_events_index_ref`` and the target is a
    global record — the query the loop over ``table_sets()`` exists for."""
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    gig = await make_record(
        client, "gig", {"name": "Launch", "venue": {"type": "hall", "uuid": hall["uuid"]}}
    )

    body = (await client.get(_refs(hall["uuid"], "hall"), headers=roles(ADMIN))).json()
    assert body["total"] == 1
    (item,) = body["items"]
    assert item["type_key"] == "gig"
    assert item["uuid"] == gig["uuid"]
    assert item["field_key"] == "venue"


async def test_referrers_finds_a_global_referrer_of_a_collection_record(client):
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    gig = await make_record(
        client, "gig", {"name": "Launch", "venue": {"type": "hall", "uuid": hall["uuid"]}}
    )
    deal = await make_record(
        client, "deal", {"name": "Sponsorship", "gig": {"type": "gig", "uuid": gig["uuid"]}}
    )

    body = (await client.get(_refs(gig["uuid"], "gig"), headers=roles(ADMIN))).json()
    assert body["total"] == 1
    assert body["items"][0]["uuid"] == deal["uuid"]
    assert body["items"][0]["type_key"] == "deal"


async def _ref_tables_asked(client, uuid: str, type_key: str) -> set[str]:
    """Which ``*_index_ref`` tables one referrers call actually reads."""
    seen: list[str] = []
    engine = client.db_state.engine.sync_engine

    def record(conn, cursor, statement, parameters, context, executemany):
        if "index_ref" in statement and "target_uuid" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        await client.get(_refs(uuid, type_key), headers=roles(ADMIN))
    finally:
        event.remove(engine, "before_cursor_execute", record)
    tables = {"records_index_ref"} | {f"records_c_{n}_index_ref" for n in COLLECTION_NAMES}
    return {name for name in tables if any(name in sql for sql in seen)}


async def test_referrers_asks_the_sets_that_can_hold_one_and_no_others(client):
    """One statement per table set **that can hold a referrer** — S5.

    The design says "union or loop, and say why", and this is still the loop:
    the ids a ref table returns are ids in *its own* record table, which a
    union would merge and lose. What changed is which tables the loop runs
    over. Only ``gig`` — in the ``events`` collection — declares a relation to
    ``hall``, so that is the one ref table worth reading; ``archive`` holds no
    type at all and the global set holds none that points at a ``hall``.

    Both halves are the assertion. Reading too few tables is a ``restrict``
    that lets a delete through and a ``cascade`` that misses a record, so the
    set that *can* hold one has to be there; reading them all is the cost §S5
    removed, and it grows with a host's Alembic history rather than with its
    content.
    """
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    gig = await make_record(
        client, "gig", {"name": "Launch", "venue": {"type": "hall", "uuid": hall["uuid"]}}
    )

    assert await _ref_tables_asked(client, hall["uuid"], "hall") == {"records_c_events_index_ref"}
    # ``gig`` is pointed at by the global ``deal`` and by nothing in either
    # collection — the mirror image, so the narrowing is not just "always the
    # collection".
    assert await _ref_tables_asked(client, gig["uuid"], "gig") == {"records_index_ref"}


async def test_a_type_nothing_relates_to_reads_no_ref_table_at_all(client):
    """A host that declares two collections and a type nothing points at pays
    for the schema read that establishes it, and for nothing else."""
    await _graph(client)
    await make_type(client, "memo", [field("name", "text")])
    memo = await make_record(client, "memo", {"name": "nobody points here"})
    assert await _ref_tables_asked(client, memo["uuid"], "memo") == set()
    body = (await client.get(_refs(memo["uuid"], "memo"), headers=roles(ADMIN))).json()
    assert body["total"] == 0 and body["items"] == []


@pytest.mark.parametrize("behaviour", ["restrict", "set_null", "cascade"])
async def test_on_delete_crosses_a_collection_boundary(client, behaviour):
    await _graph(client, venue_on_delete=behaviour)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    gig = await make_record(
        client, "gig", {"name": "Launch", "venue": {"type": "hall", "uuid": hall["uuid"]}}
    )

    deleted = await client.delete(
        f"/api/records/types/hall/records/{hall['uuid']}", headers=roles(ADMIN)
    )
    read_gig = await client.get(
        f"/api/records/types/gig/records/{gig['uuid']}", headers=roles(ADMIN)
    )

    if behaviour == "restrict":
        assert deleted.status_code == 409
        assert gig["uuid"] in str(deleted.json())
        assert read_gig.status_code == 200
    elif behaviour == "set_null":
        assert deleted.status_code == 204
        assert read_gig.status_code == 200
        assert read_gig.json()["data"]["venue"] is None
        # The rewrite is a real edit of somebody else's record, in another
        # table set: version bumped and a revision appended there.
        assert read_gig.json()["version"] == gig["version"] + 1
    else:
        assert deleted.status_code == 204
        # The cascade trashed a record of a *different* table set.
        assert read_gig.status_code == 404
        trashed = await client.get(
            "/api/records/types/gig/records?trashed=true", headers=roles(ADMIN)
        )
        assert [item["uuid"] for item in trashed.json()["items"]] == [gig["uuid"]]


async def test_expand_resolves_across_a_collection_in_both_directions(client):
    """The **target type** decides the table, and it is still one batched
    query per field, as §9 promised before collections existed."""
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    gig = await make_record(
        client, "gig", {"name": "Launch", "venue": {"type": "hall", "uuid": hall["uuid"]}}
    )
    await make_record(
        client, "deal", {"name": "Sponsorship", "gig": {"type": "gig", "uuid": gig["uuid"]}}
    )

    out = await client.get("/api/records/types/gig/records?expand=venue", headers=roles(ADMIN))
    (item,) = out.json()["items"]
    assert item["expanded"]["venue"][0]["display_title"] == "Barbican"

    back = await client.get("/api/records/types/deal/records?expand=gig", headers=roles(ADMIN))
    (deal_item,) = back.json()["items"]
    assert deal_item["expanded"]["gig"][0]["display_title"] == "Launch"


async def test_expand_into_a_collection_is_one_statement_for_the_whole_page(client):
    await _graph(client)
    hall = await make_record(client, "hall", {"name": "Barbican"})
    for i in range(4):
        gig = await make_record(
            client,
            "gig",
            {"name": f"Gig {i}", "venue": {"type": "hall", "uuid": hall["uuid"]}},
        )
        await make_record(
            client, "deal", {"name": f"Deal {i}", "gig": {"type": "gig", "uuid": gig["uuid"]}}
        )

    seen: list[str] = []
    engine = client.db_state.engine.sync_engine

    def record(conn, cursor, statement, parameters, context, executemany):
        if "records_c_events_record.uuid IN" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        page = await client.get("/api/records/types/deal/records?expand=gig", headers=roles(ADMIN))
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(page.json()["items"]) == 4
    assert len(seen) == 1, seen
