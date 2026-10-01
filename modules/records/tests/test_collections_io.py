"""Export and import against a collection type — §6.3's last two callers.

Both are walks over records with their own statement builders: the export
keysets by ``id`` over the document table, and the import matches rows against
it by uuid, slug or a unique field. Neither has a ``Record`` left in it; this
is what says so.

The round trip is the strong form of the test — export, purge the type,
recreate it *in the same collection*, re-import — because it exercises the
write path and the read path against each other rather than either against an
assertion written by hand.
"""

from __future__ import annotations

import json

from sm_records.models import GLOBAL
from sqlalchemy import func, select

from tests.app_harness import ADMIN, roles
from tests.collections_harness import EVENTS
from tests.io_helpers import (
    data_by_uuid,
    drop_type,
    export_text,
    field,
    make_record,
    make_type,
    post_import,
)

GIG = "gig"


def _fields() -> list[dict]:
    return [
        field("name", "text", required=True, indexed=True),
        field("capacity", "integer", indexed=True),
        field("outdoors", "boolean"),
    ]


async def _gigs(client, count: int = 3) -> list[dict]:
    await make_type(
        client,
        GIG,
        _fields(),
        collection="events",
        display_field="name",
        slug_field="name",
    )
    return [
        await make_record(
            client,
            GIG,
            {"name": f"Gig {i}", "capacity": i * 10, "outdoors": i % 2 == 0},
            status="published" if i == 0 else "draft",
        )
        for i in range(count)
    ]


async def test_export_streams_a_collections_records(client):
    made = await _gigs(client)
    document = json.loads(await export_text(client, GIG))
    assert document["type"]["key"] == GIG
    assert {row["uuid"] for row in document["records"]} == {r["uuid"] for r in made}
    assert [row["data"]["capacity"] for row in document["records"]] == [0, 10, 20]


async def test_a_round_trip_through_a_purge_restores_the_collections_rows(client):
    made = await _gigs(client)
    document = await export_text(client, GIG)
    before = await data_by_uuid(client, GIG)

    await drop_type(client, GIG, len(made))
    async with client.db_state.session_factory() as session:
        remaining = (await session.execute(select(func.count(EVENTS.record.id)))).scalar_one()
    assert remaining == 0

    await make_type(
        client,
        GIG,
        _fields(),
        collection="events",
        display_field="name",
        slug_field="name",
    )
    resp = await post_import(client, GIG, document, dry_run="false")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["created"] == len(made)
    assert report["failed"] == 0

    after = await data_by_uuid(client, GIG)
    assert set(after) == set(before)
    for uuid, item in after.items():
        assert item["data"] == before[uuid]["data"]
        assert item["slug"] == before[uuid]["slug"]
        assert item["status"] == before[uuid]["status"]


async def test_an_import_writes_into_the_collections_tables_and_not_the_shared_ones(client):
    await _gigs(client, count=0)
    document = json.dumps(
        {"records": [{"data": {"name": "Imported", "capacity": 5}, "slug": "imported"}]}
    )
    resp = await post_import(client, GIG, document, dry_run="false")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1

    read = await client.get(f"/api/records/types/{GIG}", headers=roles(ADMIN))
    assert read.json()["collection"] == "events"
    async with client.db_state.session_factory() as session:
        theirs = (await session.execute(select(func.count(EVENTS.record.id)))).scalar_one()
        ours = (await session.execute(select(func.count(GLOBAL.record.id)))).scalar_one()
    assert theirs == 1
    assert ours == 0


async def test_an_update_import_matches_by_uuid_inside_the_collection(client):
    made = await _gigs(client, count=2)
    rows = [
        {
            "uuid": made[0]["uuid"],
            "version": made[0]["version"],
            "data": {"name": "Renamed", "capacity": 99, "outdoors": True},
        }
    ]
    resp = await post_import(
        client, GIG, json.dumps({"records": rows}), dry_run="false", mode="update"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1

    after = await data_by_uuid(client, GIG)
    assert after[made[0]["uuid"]]["data"]["name"] == "Renamed"
    assert after[made[1]["uuid"]]["data"]["name"] == "Gig 1"
