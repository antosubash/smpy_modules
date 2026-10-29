"""An archive older than the collection's points says so while a rebuild is pending.

QA (ship round 1, TEST-003): right after an upload the Map tab drew the archive
built from the first few located images while the rebuild with the rest was
still queued - 4 of 20 points until a reload. The archive is still served (a
viewer mid-session keeps its ranges), but with ``X-Map-Stale: 1`` so the
client reads the fresh points instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sm_images.models import Collection, Visibility
from sqlalchemy import update

from tests.access_support import OWNER, headers
from tests.test_map_tiles import _seed, _url


async def _state(client, coll, **values) -> None:
    async with client.db_state.session_factory() as s:
        await s.execute(update(Collection).where(Collection.id == coll.id).values(**values))
        await s.commit()


async def test_up_to_date_archive_is_not_stale(client, storage):
    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    await _state(client, coll, map_changes=4, map_built_changes=4)
    head = await client.head(_url(coll), headers=headers(OWNER))
    assert head.status_code == 200
    assert "x-map-stale" not in head.headers


async def test_archive_behind_a_pending_rebuild_is_marked_stale(client, storage):
    coll, _ = await _seed(client, storage, Visibility.PRIVATE)
    claimed = datetime.now(UTC) + timedelta(minutes=5)
    await _state(client, coll, map_changes=20, map_built_changes=4, map_claimed_until=claimed)
    head = await client.head(_url(coll), headers=headers(OWNER))
    assert head.status_code == 200
    assert head.headers["x-map-stale"] == "1"
    got = await client.get(_url(coll), headers={**headers(OWNER), "Range": "bytes=0-9"})
    assert got.status_code == 206 and got.headers["x-map-stale"] == "1"
