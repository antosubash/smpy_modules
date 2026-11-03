"""test_collections_crud cases."""

from __future__ import annotations
import pytest
from sm_records.models import GLOBAL, RecordStatus, tables_for
from sqlalchemy import func, select
from tests.support.app_harness import ADMIN, roles, seed_type
from tests.support.collections_harness import EVENTS
from tests.support.collections_crud_cases import gig, _count, note, API


async def test_a_slug_is_claimed_per_type_and_locale_inside_the_collection(client, gig):
    first = await client.post(
        API, json={"data": {"name": "Launch"}, "slug": "launch"}, headers=roles(ADMIN)
    )
    assert first.status_code == 201
    second = await client.post(
        API, json={"data": {"name": "Launch 2"}, "slug": "launch"}, headers=roles(ADMIN)
    )
    assert second.status_code == 409
    assert "launch" in second.json()["detail"]


async def test_trash_restore_and_purge_walk_the_collections_tables(client, gig):
    created = (
        await client.post(API, json={"data": {"name": "Launch"}}, headers=roles(ADMIN))
    ).json()
    uuid = created["uuid"]

    assert (await client.delete(f"{API}/{uuid}", headers=roles(ADMIN))).status_code == 204
    assert (await client.get(f"{API}/{uuid}", headers=roles(ADMIN))).status_code == 404

    trashed = await client.get(f"{API}?trashed=true", headers=roles(ADMIN))
    assert [item["uuid"] for item in trashed.json()["items"]] == [uuid]

    restored = await client.post(f"{API}/{uuid}/restore", headers=roles(ADMIN))
    assert restored.status_code == 200
    assert (await client.get(f"{API}/{uuid}", headers=roles(ADMIN))).status_code == 200

    await client.delete(f"{API}/{uuid}", headers=roles(ADMIN))
    purged = await client.delete(f"{API}/{uuid}/purge", headers=roles(ADMIN))
    assert purged.status_code == 204
    tables = tables_for(gig)
    assert await _count(client.db_state, tables.record) == 0
    assert await _count(client.db_state, tables.revision) == 0


async def test_a_trashed_collection_record_is_hidden_from_a_plain_select(client, gig, db_state):
    """The framework's soft-delete filter is attached per mapper by
    ``issubclass(cls, SoftDeleteMixin)`` (``simple_module_db.listeners``), so a
    generated class inherits it with nothing to register — and this is the
    proof, read straight off the collection's own table rather than through a
    service that might be filtering for its own reasons."""
    created = (
        await client.post(API, json={"data": {"name": "Launch"}}, headers=roles(ADMIN))
    ).json()
    await client.delete(f"{API}/{created['uuid']}", headers=roles(ADMIN))

    cls = tables_for(gig).record
    async with client.db_state.session_factory() as session:
        visible = (await session.execute(select(cls))).scalars().all()
        assert visible == []
        lifted = (
            (await session.execute(select(cls).execution_options(include_deleted=True)))
            .scalars()
            .all()
        )
        assert [row.uuid for row in lifted] == [created["uuid"]]
        assert lifted[0].is_deleted is True
        assert lifted[0].status is RecordStatus.DRAFT


async def test_revision_detail_and_restore_read_the_collections_own_revision_log(client, gig, note):
    """Regression: ``restore`` and the detail endpoint named the module-level
    ``RecordRevision`` while every other revision helper resolved the table
    from the row. Two collections number their records independently and so
    does the global set, so ``RecordRevision.record_id == record.id`` matched
    an unrelated record's snapshot — which the detail then showed and the
    restore then *wrote over the record*, with a revision, an index rewrite
    and a version bump. Nothing in the UI could reveal it: ``list_revisions``
    was already correct, so the history panel showed the right ids and
    clicking one opened the wrong payload."""
    global_api = "/api/records/types/note/records"
    created_global = (
        await client.post(global_api, json={"data": {"name": "global-v1"}}, headers=roles(ADMIN))
    ).json()
    await client.put(
        f"{global_api}/{created_global['uuid']}",
        json={"expected_version": created_global["version"], "data": {"name": "global-v2"}},
        headers=roles(ADMIN),
    )

    created = (
        await client.post(API, json={"data": {"name": "coll-v1"}}, headers=roles(ADMIN))
    ).json()
    uuid = created["uuid"]
    await client.put(
        f"{API}/{uuid}",
        json={"expected_version": created["version"], "data": {"name": "coll-v2"}},
        headers=roles(ADMIN),
    )

    # Both logs really do hand out the same ids — otherwise the two asserts
    # below would pass against a still-broken lookup.
    async with client.db_state.session_factory() as session:
        for cls in (GLOBAL.revision, tables_for(gig).revision):
            ids = (await session.execute(select(cls.id).order_by(cls.id))).scalars().all()
            assert list(ids) == [1, 2]

    detail = await client.get(f"{API}/{uuid}/revisions/1", headers=roles(ADMIN))
    assert detail.status_code == 200
    assert detail.json()["data"]["name"] == "coll-v1"

    restored = await client.post(
        f"{API}/{uuid}/revisions/1/restore",
        json={"expected_version": 2},
        headers=roles(ADMIN),
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["name"] == "coll-v1"
    assert restored.json()["display_title"] == "coll-v1"

    # …and the global record was left alone by all of it.
    still = await client.get(f"{global_api}/{created_global['uuid']}", headers=roles(ADMIN))
    assert still.json()["data"]["name"] == "global-v2"


async def test_a_revision_id_from_another_table_is_a_404_not_a_silent_restore(client, gig, note):
    """The global record has revision id 1; the collection record has none at
    all beyond its own, so id 1 of *its* log is the only thing that may
    answer. Here the collection record is created after a global one whose log
    is longer, so id 2 exists globally and nowhere else."""
    global_api = "/api/records/types/note/records"
    first = (
        await client.post(global_api, json={"data": {"name": "g1"}}, headers=roles(ADMIN))
    ).json()
    await client.put(
        f"{global_api}/{first['uuid']}",
        json={"expected_version": first["version"], "data": {"name": "g2"}},
        headers=roles(ADMIN),
    )

    created = (
        await client.post(API, json={"data": {"name": "Launch"}}, headers=roles(ADMIN))
    ).json()
    uuid = created["uuid"]

    assert (await client.get(f"{API}/{uuid}/revisions/2", headers=roles(ADMIN))).status_code == 404
    refused = await client.post(
        f"{API}/{uuid}/revisions/2/restore",
        json={"expected_version": created["version"]},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 404
