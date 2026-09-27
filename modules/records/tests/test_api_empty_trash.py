"""``POST /types/{key}/records/trash/empty`` — all of the trash, or part of it.

Three things distinguish it from a ``purge`` batch and each has a test here:
it names nothing (so ``max_bulk_records`` does not bound it), it takes the
listing grammar's ``?filter=`` (so "empty what this screen shows" is the query
the screen listed it with), and it is set-based (so it must still publish the
one event per record that a subscriber cannot reconstruct afterwards).
"""

from __future__ import annotations

from sm_records.contracts.events import RecordPurged
from sm_records.models import IndexText, Record, RecordRevision
from sqlalchemy import func, select

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, ROLE_VIEWER, roles
from tests.bulk_helpers import API, EMPTY, bulk, make_product, make_records, read, trash_listing


async def _empty(client, *, actor: str = ADMIN, params: str = ""):
    return await client.post(f"{EMPTY}{params}", headers=roles(actor))


async def _count(db_state, model, **where) -> int:
    async with db_state.session_factory() as session:
        stmt = select(func.count()).select_from(model)
        for column, value in where.items():
            stmt = stmt.where(getattr(model, column) == value)
        return int((await session.execute(stmt)).scalar_one())


async def test_it_purges_the_whole_trash_and_leaves_live_records_alone(client, product):
    trashed = await make_records(client, 3)
    live = await make_records(client, 2)
    assert (await bulk(client, "trash", trashed)).status_code == 200

    resp = await _empty(client)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"purged": 3, "filtered": False}
    assert (await trash_listing(client))["total"] == 0
    for uuid in live:
        assert (await read(client, uuid)).status_code == 200


async def test_a_filter_narrows_what_it_empties(client, product):
    news = await make_records(client, 2, topic="news")
    sport = await make_records(client, 3, topic="sport")
    assert (await bulk(client, "trash", [*news, *sport])).status_code == 200

    resp = await _empty(client, params="?filter=topic:eq:news")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"purged": 2, "filtered": True}
    # The rest of the trash is still the trash: an operator who emptied the
    # part they were looking at did not empty the part they were not.
    remaining = await trash_listing(client)
    assert remaining["total"] == 3
    assert {item["uuid"] for item in remaining["items"]} == set(sport)


async def test_a_filter_matching_nothing_purges_nothing(client, product):
    uuids = await make_records(client, 2, topic="news")
    assert (await bulk(client, "trash", uuids)).status_code == 200

    resp = await _empty(client, params="?filter=topic:eq:sport")

    assert resp.json() == {"purged": 0, "filtered": True}
    assert (await trash_listing(client))["total"] == 2


async def test_an_empty_trash_is_not_an_error(client, product):
    await make_records(client, 2)
    resp = await _empty(client)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"purged": 0, "filtered": False}


async def test_a_filter_on_an_unqueryable_field_is_refused_by_name(client, product):
    uuids = await make_records(client, 1)
    assert (await bulk(client, "trash", uuids)).status_code == 200

    resp = await _empty(client, params="?filter=nosuchfield:eq:x")

    assert resp.status_code == 400, resp.text
    assert resp.json()["field"] == "nosuchfield"
    assert resp.json()["reason"] == "unknown"
    # Refused means refused: the trash is untouched.
    assert (await trash_listing(client))["total"] == 1


async def test_it_removes_the_index_and_revision_rows_too(client, product):
    uuids = await make_records(client, 2)
    assert (await bulk(client, "trash", uuids)).status_code == 200
    # Index rows survive a soft delete on purpose (§7.3) — which is exactly
    # why a purge has to remove them itself.
    assert await _count(client.db_state, IndexText) > 0
    assert await _count(client.db_state, RecordRevision) > 0

    assert (await _empty(client)).status_code == 200

    assert await _count(client.db_state, Record) == 0
    assert await _count(client.db_state, RecordRevision) == 0
    assert await _count(client.db_state, IndexText) == 0


async def test_it_publishes_one_purge_event_per_record(client, product, bus):
    uuids = await make_records(client, 3)
    assert (await bulk(client, "trash", uuids)).status_code == 200
    bus.seen.clear()
    bus.committed.clear()

    assert (await _empty(client)).status_code == 200

    purged = bus.only(RecordPurged)
    assert {event.uuid for event in purged} == set(uuids)
    # The set-based purge reads the identity columns before it deletes, so the
    # event still carries what the row held — nobody can look it up now.
    assert all(event.type_key == "product" and event.locale == "en" for event in purged)
    assert all(event.translation_group for event in purged)
    assert all(bus.committed)


async def test_max_bulk_records_does_not_bound_it(client, product):
    """The point of emptying the trash is not having to name what is in it."""
    uuids = await make_records(client, 3)
    assert (await bulk(client, "trash", uuids)).status_code == 200
    client.app.state.sm_records.settings.max_bulk_records = 1

    resp = await _empty(client)

    assert resp.status_code == 200, resp.text
    assert resp.json()["purged"] == 3


async def test_it_costs_records_edit(client, product):
    assert (await _empty(client, actor=ROLE_VIEWER)).status_code == 403


async def test_allowed_roles_narrow_it(client):
    await make_product(client, allowed_roles=[ROLE_EDITOR])
    uuids = await make_records(client, 1, actor=ROLE_EDITOR)
    assert (await bulk(client, "trash", uuids, actor=ROLE_EDITOR)).status_code == 200

    assert (await _empty(client, actor=ROLE_EDITOR_TWO)).status_code == 403
    assert (await _empty(client, actor=ROLE_EDITOR)).status_code == 200


async def test_an_unknown_type_is_a_404(client, product):
    resp = await client.post("/api/records/types/nope/records/trash/empty", headers=roles(ADMIN))
    assert resp.status_code == 404


async def test_the_route_is_not_read_as_a_record_uuid(client, product):
    """``/records/trash/empty`` under the path ``records`` claims for one
    record: registration order is what keeps them apart."""
    resp = await client.get(f"{API}/trash", headers=roles(ADMIN))
    assert resp.status_code == 404
    assert (await _empty(client)).status_code == 200
