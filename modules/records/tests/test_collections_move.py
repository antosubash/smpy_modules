"""Moving a populated type between collections — ``PUT /types/{key}`` (#82).

The move copies a type's records, revisions and index rows into the target
table set and deletes them from the source, in the request's transaction. The
tests below each pin one thing that has to survive it: the records and their
trash, their revisions, the index (a filter still answers), relations in both
directions (an outbound ``?expand=``, an inbound one, the referrers panel),
the event, and — for every refusal — that nothing moved.
"""

from __future__ import annotations

import pytest
from sm_records.contracts.events import RecordTypeChanged, RecordTypeMoved
from sm_records.models import table_set
from sqlalchemy import func, select

from tests.app_harness import ADMIN, roles
from tests.collections_harness import COLLECTION_NAMES
from tests.events_harness import recorder
from tests.relation_helpers import make_record, make_type, rel_field, text_field

TYPES = "/api/records/types"
assert COLLECTION_NAMES  # the import declares ``events`` and ``archive``


async def _graph(client, *, collection: str | None = None) -> dict:
    """``author`` (to be moved) pointing at ``house``; ``book`` pointing at
    ``author``. Two authors, one trashed, one with two revisions."""
    await make_type(client, "house", [text_field("name")])
    await make_type(
        client,
        "author",
        [text_field("name"), rel_field("publisher", "house", "restrict")],
        collection=collection,
    )
    await make_type(client, "book", [text_field("name"), rel_field("author", "author", "restrict")])
    house = await make_record(client, "house", {"name": "Gollancz"})
    pub = {"type": "house", "uuid": house["uuid"]}
    kept = await make_record(client, "author", {"name": "Herbert", "publisher": pub})
    edited = await client.put(
        f"{TYPES}/author/records/{kept['uuid']}",
        json={"expected_version": kept["version"], "data": {"name": "Frank", "publisher": pub}},
        headers=roles(ADMIN),
    )
    assert edited.status_code == 200, edited.text
    binned = await make_record(client, "author", {"name": "Binned"})
    assert (
        await client.delete(f"{TYPES}/author/records/{binned['uuid']}", headers=roles(ADMIN))
    ).status_code == 204
    book = await make_record(
        client, "book", {"name": "Dune", "author": {"type": "author", "uuid": kept["uuid"]}}
    )
    return {"kept": kept, "binned": binned, "book": book, "house": house}


async def _move(client, target: str | None, **extra):
    current = (await client.get(f"{TYPES}/author", headers=roles(ADMIN))).json()
    return await client.put(
        f"{TYPES}/author",
        json={"expected_version": current["version"], "collection": target, **extra},
        headers=roles(ADMIN),
    )


async def _rows(client, collection: str | None) -> int:
    """Rows of every table of ``collection``'s set — the record table, its
    revisions and its six index tables."""
    tables = table_set(collection)
    total = 0
    async with client.db_state.session_factory() as session:
        for cls in (tables.record, tables.revision, *tables.index_tables):
            total += await session.scalar(select(func.count()).select_from(cls.__table__)) or 0
    return total


@pytest.mark.parametrize(
    ("source", "target"), [(None, "events"), ("events", None), ("events", "archive")]
)
async def test_a_populated_type_moves_with_everything_it_holds(client, source, target):
    graph = await _graph(client, collection=source)
    before = await _rows(client, source)
    moved = await _move(client, target)
    assert moved.status_code == 200, moved.text
    assert moved.json()["collection"] == target
    assert moved.json()["record_count"] == 1

    # The type's rows left the source set and every one of them arrived.
    if source is not None and target is not None:
        assert await _rows(client, source) == 0
        assert await _rows(client, target) == before

    kept = graph["kept"]["uuid"]
    one = await client.get(f"{TYPES}/author/records/{kept}?expand=publisher", headers=roles(ADMIN))
    assert one.status_code == 200, one.text
    assert one.json()["data"]["name"] == "Frank"
    assert one.json()["expanded"]["publisher"][0]["display_title"] == "Gollancz"

    revisions = await client.get(f"{TYPES}/author/records/{kept}/revisions", headers=roles(ADMIN))
    assert revisions.status_code == 200
    assert len(revisions.json()["items"]) == 2

    trash = await client.get(f"{TYPES}/author/records?trashed=true", headers=roles(ADMIN))
    assert [item["uuid"] for item in trash.json()["items"]] == [graph["binned"]["uuid"]]

    found = await client.get(f"{TYPES}/author/records?filter=name:eq:Frank", headers=roles(ADMIN))
    assert [item["uuid"] for item in found.json()["items"]] == [kept]

    # Inbound: the book's reference and the referrers panel follow the move.
    book = await client.get(f"{TYPES}/book/records?expand=author", headers=roles(ADMIN))
    assert book.json()["items"][0]["expanded"]["author"][0]["display_title"] == "Frank"
    referrers = await client.get(f"{TYPES}/author/records/{kept}/referrers", headers=roles(ADMIN))
    assert referrers.json()["total"] == 1
    # Outbound: the house still knows the author points at it.
    house = graph["house"]["uuid"]
    back = await client.get(f"{TYPES}/house/records/{house}/referrers", headers=roles(ADMIN))
    assert back.json()["total"] == 1


async def test_a_moved_type_keeps_working(client):
    graph = await _graph(client)
    assert (await _move(client, "events")).status_code == 200
    created = await make_record(client, "author", {"name": "Le Guin"})
    listed = await client.get(f"{TYPES}/author/records", headers=roles(ADMIN))
    assert {item["uuid"] for item in listed.json()["items"]} == {
        created["uuid"],
        graph["kept"]["uuid"],
    }
    # ``restrict`` still sees the book, wherever the author now lives.
    blocked = await client.delete(
        f"{TYPES}/author/records/{graph['kept']['uuid']}", headers=roles(ADMIN)
    )
    assert blocked.status_code == 409


async def test_the_move_is_published_after_the_commit(client):
    """Published once the move committed: a handler reading through a second
    session already finds the rows in the target set, and the type-changed
    event every accepted type write produces follows it."""
    await _graph(client)
    seen = recorder(client)
    moved_rows: list[int] = []

    async def on_moved(event) -> None:
        seen.seen.append(event)
        moved_rows.append(await _rows(client, "events"))

    client.app.state.sm.event_bus.subscribe(RecordTypeMoved, on_moved)
    assert (await _move(client, "events")).status_code == 200
    assert moved_rows and moved_rows[0] > 0
    assert [type(e) for e in seen.seen if isinstance(e, RecordTypeMoved | RecordTypeChanged)] == [
        RecordTypeMoved,
        RecordTypeChanged,
    ]
    (event,) = seen.only(RecordTypeMoved)
    assert (event.type_key, event.source, event.target, event.moved) == (
        "author",
        None,
        "events",
        2,
    )
    assert event.tenant_id == "default"
    assert seen.only(RecordTypeChanged)


async def test_an_undeclared_collection_is_a_422_and_nothing_moves(client):
    await _graph(client)
    refused = await _move(client, "concerts")
    assert refused.status_code == 422
    assert "concerts" in refused.json()["detail"]
    assert (await client.get(f"{TYPES}/author", headers=roles(ADMIN))).json()["collection"] is None


async def test_a_move_and_a_schema_change_in_one_request_is_a_409(client):
    await _graph(client)
    before = await _rows(client, None)
    fields = [text_field("name"), text_field("bio"), rel_field("publisher", "house", "restrict")]
    refused = await _move(client, "events", fields=fields)
    assert refused.status_code == 409
    assert "separate" in refused.json()["detail"]
    assert await _rows(client, None) == before


async def test_a_stale_version_moves_nothing(client):
    await _graph(client)
    current = (await client.get(f"{TYPES}/author", headers=roles(ADMIN))).json()
    refused = await client.put(
        f"{TYPES}/author",
        json={"expected_version": current["version"] - 1, "collection": "events"},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 409
    assert await _rows(client, "events") == 0


async def test_a_pending_reindex_is_a_409(client):
    await _graph(client)
    async with client.db_state.session_factory() as session:
        from sm_records.models import RecordType

        rtype = (
            await session.execute(select(RecordType).where(RecordType.key == "author"))
        ).scalar_one()
        rtype.reindex_pending = {"name": "2026-10-21T00:00:00+00:00"}
        await session.commit()
    refused = await _move(client, "events")
    assert refused.status_code == 409
    assert "reindex" in refused.json()["detail"]


async def test_a_failure_part_way_rolls_the_whole_move_back(client, monkeypatch):
    """One transaction is the rollback story: the copies are written, the
    sources deleted, and then the request fails — and none of it happened."""
    from sm_records.services import _type_move

    await _graph(client)
    before = await _rows(client, None)

    def boom(*_args, **_kwargs):
        raise RuntimeError("injected after the rows moved")

    monkeypatch.setattr(_type_move.events, "emit", boom)
    failed = await _move(client, "events")
    assert failed.status_code == 500
    assert await _rows(client, None) == before
    assert await _rows(client, "events") == 0
    assert (await client.get(f"{TYPES}/author", headers=roles(ADMIN))).json()["collection"] is None
