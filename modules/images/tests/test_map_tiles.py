"""``GET …/collections/{id}/map.pmtiles`` and its public twin (Task 26).

Range requests (206, ``Accept-Ranges``, 416), an ETag tied to the build
generation, and Task 12's cache split - but ``no-cache`` on both sides, so a
cache revalidates every time and a revocation takes effect at once. The route
re-reads the collection through the policy on every request, and a visibility
change withdraws the archive in its own transaction (the portal's revocation
lesson): nothing is served again until a fresh map is built.
"""

from __future__ import annotations

import uuid

import pytest
from sm_images import redaction, storage_keys
from sm_images.models import Collection, Group, ObjectIntent, Visibility
from sm_images.storage import ImageStore
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
from sqlalchemy import select, update

from tests.access_support import OWNER, STRANGER, collection, headers
from tests.stub_auth import as_user

ARCHIVE = bytes(range(256)) * 4
PMTILES = "application/vnd.pmtiles"
PUBLISHER = as_user("olga", ("images.view", "images.create", "images.publish"))


async def _seed(client, storage, visibility=Visibility.PUBLIC, *, data=ARCHIVE, generation=1):
    coll = collection(f"t-{uuid.uuid4().hex[:8]}", visibility, OWNER)
    key = storage_keys.map_key(DEFAULT_TENANT, str(coll.id), generation, "a1")
    coll.map_key, coll.map_generation, coll.map_image_count = key, generation, 3
    coll.map_policy_rev = redaction.gate_key(coll)  # built under the current gate
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.commit()
    await ImageStore(storage).put(key, data, content_type=PMTILES, size=len(data))
    return coll, key


def _url(coll) -> str:
    return f"/api/images/collections/{coll.id}/map.pmtiles"


def _public(coll) -> str:
    return f"/api/images/public/c/{coll.slug}/map.pmtiles"


async def _row(client, coll) -> Collection:
    async with client.db_state.session_factory() as s:
        return (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()


async def test_range_request_206(client, storage):
    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    got = await client.get(_url(coll), headers={**headers(OWNER), "Range": "bytes=0-9"})
    assert got.status_code == 206, got.text
    assert got.content == ARCHIVE[:10]
    assert got.headers["content-range"] == f"bytes 0-9/{len(ARCHIVE)}"
    assert got.headers["accept-ranges"] == "bytes"
    assert got.headers["content-type"] == PMTILES
    assert got.headers["cache-control"] == "private, no-cache"
    assert got.headers["etag"]
    tail = await client.get(_url(coll), headers={**headers(OWNER), "Range": "bytes=-4"})
    assert (tail.status_code, tail.content) == (206, ARCHIVE[-4:])
    whole = await client.get(_url(coll), headers=headers(OWNER))
    assert (whole.status_code, whole.content) == (200, ARCHIVE)
    assert whole.headers["accept-ranges"] == "bytes"


async def test_range_past_the_end_is_416(client, storage):
    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    got = await client.get(
        _url(coll), headers={**headers(OWNER), "Range": f"bytes={len(ARCHIVE)}-"}
    )
    assert got.status_code == 416
    assert got.headers["content-range"] == f"bytes */{len(ARCHIVE)}"


async def test_a_huge_range_number_is_416_not_500(client, storage):
    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    nines = "9" * 5000
    got = await client.get(_url(coll), headers={**headers(OWNER), "Range": f"bytes={nines}-"})
    assert got.status_code == 416
    assert got.headers["content-range"] == f"bytes */{len(ARCHIVE)}"
    whole = await client.get(_url(coll), headers={**headers(OWNER), "Range": f"bytes=0-{nines}"})
    assert (whole.status_code, whole.content) == (206, ARCHIVE)


async def test_etag_is_tied_to_the_build_generation(client, storage):
    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    first = await client.get(_url(coll), headers=headers(OWNER))
    tag = first.headers["etag"]
    again = await client.get(_url(coll), headers={**headers(OWNER), "If-None-Match": tag})
    assert (again.status_code, again.headers["etag"]) == (304, tag)
    assert again.headers["cache-control"] == "private, no-cache"
    newer = storage_keys.map_key(DEFAULT_TENANT, str(coll.id), 2, "b2")
    await ImageStore(storage).put(newer, ARCHIVE, content_type=PMTILES, size=len(ARCHIVE))
    async with client.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == coll.id)
            .values(map_key=newer, map_generation=2)
        )
        await s.commit()
    rebuilt = await client.get(_url(coll), headers={**headers(OWNER), "If-None-Match": tag})
    assert rebuilt.status_code == 200
    assert rebuilt.headers["etag"] != tag
    # a resumed range against the old generation gets the whole new archive
    resumed = await client.get(
        _url(coll), headers={**headers(OWNER), "Range": "bytes=0-9", "If-Range": tag}
    )
    assert resumed.status_code == 200


async def test_no_map_yet_is_404(client, storage):
    coll = collection("bare", Visibility.PRIVATE, OWNER)
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.commit()
    assert (await client.get(_url(coll), headers=headers(OWNER))).status_code == 404


async def test_a_stranger_gets_404_on_a_private_map(client, storage):
    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    got = await client.get(_url(coll), headers=headers(STRANGER))
    assert got.status_code == 404
    assert (await client.get(_public(coll))).status_code == 404


@pytest.mark.unbound_tenant
async def test_public_twin_ranges_and_head(client, storage):
    with tenant_scope(DEFAULT_TENANT):
        coll, _ = await _seed(client, storage)
    got = await client.get(_public(coll), headers={"Range": "bytes=10-19"})
    assert (got.status_code, got.content) == (206, ARCHIVE[10:20])
    assert got.headers["cache-control"] == "public, no-cache"
    head = await client.head(_public(coll))
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(ARCHIVE))
    assert head.headers["accept-ranges"] == "bytes"
    assert head.headers["etag"] == got.headers["etag"]


async def test_the_route_rechecks_visibility_on_every_request(client, storage):
    coll, _ = await _seed(client, storage)
    assert (await client.get(_public(coll))).status_code == 200
    async with client.db_state.session_factory() as s:  # bypassing the API entirely
        await s.execute(
            update(Collection).where(Collection.id == coll.id).values(visibility=Visibility.PRIVATE)
        )
        await s.commit()
    gone = await client.get(_public(coll), headers={"Range": "bytes=0-9"})
    assert gone.status_code == 404
    assert gone.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (Visibility.PUBLIC, Visibility.PRIVATE),
        (Visibility.PUBLIC, Visibility.INTERNAL),
        (Visibility.PRIVATE, Visibility.PUBLIC),
    ],
)
async def test_a_visibility_change_withdraws_the_map_until_rebuilt(
    client, storage, web_runtime, before, after
):
    coll, key = await _seed(client, storage, before)
    put = await client.put(
        f"/api/images/collections/{coll.id}/visibility",
        json={"visibility": after.value},
        headers=PUBLISHER,
    )
    assert put.status_code == 200, put.text
    row = await _row(client, coll)
    assert row.map_key is None and row.map_generation == 2
    assert row.map_urgent_mark == row.map_changes > 0  # a rebuild may not wait
    for url, who in ((_public(coll), None), (_url(coll), OWNER)):
        assert (await client.get(url, headers=headers(who))).status_code == 404
    # with a runtime the withdrawn archive is deleted after the commit, intent and all
    async with client.db_state.session_factory() as s:
        intent = (
            await s.execute(select(ObjectIntent).where(ObjectIntent.key == key))
        ).scalar_one_or_none()
    assert intent is None
    assert not await ImageStore(storage).exists(key)


async def test_a_move_and_a_removal_do_not_wait_for_the_threshold(client, storage):
    from tests.access_support import image

    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    async with client.db_state.session_factory() as s:
        pic = image(coll, "p.jpg", lat=1.0, lng=2.0)
        s.add(pic)
        await s.commit()
    url = f"/api/images/images/{pic.id}"
    moved = await client.patch(url, json={"lat": 3.0, "lng": 4.0}, headers=headers(OWNER))
    assert moved.status_code == 200, moved.text
    row = await _row(client, coll)
    assert row.map_changes == row.map_urgent_mark == 1
    async with client.db_state.session_factory() as s:
        site = Group(collection_id=coll.id, key="site")
        s.add(site)
        await s.commit()
    grouped = await client.patch(url, json={"group_id": str(site.id)}, headers=headers(OWNER))
    assert grouped.status_code == 200, grouped.text
    row = await _row(client, coll)  # a group change waits for the threshold
    assert (row.map_changes, row.map_urgent_mark) == (2, 1)
    assert (await client.delete(url, headers=headers(OWNER))).status_code == 204
    row = await _row(client, coll)
    assert row.map_changes == row.map_urgent_mark == 3
    assert row.map_key is None  # a removed point is withdrawn at once (review fix 1)
