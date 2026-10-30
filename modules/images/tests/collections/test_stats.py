"""Collection counters and bounding box: incremental SQL, recompute for the rest."""

from __future__ import annotations

import asyncio

import pytest
from sm_images.models import Collection, Image, Visibility
from sm_images.services import stats
from sqlalchemy import select

from tests.support.pg import USING_POSTGRES


async def _seed(db) -> Collection:
    coll = Collection(slug="s", name="s", owner_id="u", visibility=Visibility.PRIVATE)
    db.add(coll)
    await db.commit()
    return coll


async def _row(db, coll) -> Collection:
    await db.refresh(coll)
    return coll


def _bbox(c: Collection):
    return (c.bbox_minx, c.bbox_miny, c.bbox_maxx, c.bbox_maxy)


async def test_added_counts_and_extends_the_bbox(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, None, None)
    await stats.on_image_added(db, coll.id, 10.0, 20.0)  # lat, lng
    await stats.on_image_added(db, coll.id, 12.0, 18.0)
    await stats.on_image_added(db, coll.id, -5.0, 25.0)
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (4, 3)
    # bbox is (minx=lng, miny=lat, maxx=lng, maxy=lat)
    assert _bbox(c) == (18.0, -5.0, 25.0, 12.0)


async def test_an_unlocated_image_never_touches_the_bbox(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, None, None)
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (1, 0)
    assert _bbox(c) == (None, None, None, None)


async def test_a_valid_zero_zero_coordinate_is_located(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, 0.0, 0.0)
    c = await _row(db, coll)
    assert c.located_count == 1
    assert _bbox(c) == (0.0, 0.0, 0.0, 0.0)


async def test_removed_is_clamped_at_zero(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, 1.0, 2.0)
    await stats.on_image_removed(db, coll.id, 1.0, 2.0)
    await stats.on_image_removed(db, coll.id, 1.0, 2.0)
    await stats.on_image_removed(db, coll.id, None, None)
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (0, 0)


async def test_location_gained_counts_and_extends(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, None, None)
    await stats.on_location_changed(db, coll.id, None, (3.0, 4.0))
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (1, 1)
    assert _bbox(c) == (4.0, 3.0, 4.0, 3.0)


async def test_location_lost_uncounts_but_keeps_the_box_until_recompute(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, 1.0, 2.0)
    await stats.on_location_changed(db, coll.id, (1.0, 2.0), None)
    c = await _row(db, coll)
    assert c.located_count == 0
    assert _bbox(c) == (2.0, 1.0, 2.0, 1.0)


async def test_location_moved_extends_and_keeps_the_count(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, 1.0, 2.0)
    await stats.on_location_changed(db, coll.id, (1.0, 2.0), (9.0, 8.0))
    c = await _row(db, coll)
    assert c.located_count == 1
    assert _bbox(c) == (2.0, 1.0, 8.0, 9.0)


async def test_recompute_shrinks_to_what_is_there(db):
    coll = await _seed(db)
    for lat, lng in ((1.0, 2.0), (50.0, 60.0), (None, None)):
        db.add(
            Image(
                collection_id=coll.id,
                storage_key=f"k/{lat}",
                filename="f",
                content_type="image/jpeg",
                size_bytes=1,
                lat=lat,
                lng=lng,
            )
        )
    await db.commit()
    await stats.recompute(db, coll.id)
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (3, 2)
    assert _bbox(c) == (2.0, 1.0, 60.0, 50.0)

    victim = (await db.execute(select(Image).where(Image.lat == 50.0))).scalars().one()
    await db.delete(victim)
    await db.commit()
    await stats.recompute(db, coll.id)
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (2, 1)
    assert _bbox(c) == (2.0, 1.0, 2.0, 1.0)


async def test_recompute_of_an_empty_collection_clears_the_bbox(db):
    coll = await _seed(db)
    await stats.on_image_added(db, coll.id, 1.0, 2.0)
    await stats.recompute(db, coll.id)
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (0, 0)
    assert _bbox(c) == (None, None, None, None)


def _image(coll: Collection, key: str, lat: float | None = None, **kw) -> Image:
    return Image(
        collection_id=coll.id,
        storage_key=key,
        filename="f",
        content_type="image/jpeg",
        size_bytes=1,
        lat=lat,
        lng=lat,
        **kw,
    )


@pytest.mark.skipif(
    USING_POSTGRES,
    reason="staged in one task: on Postgres the injected writer waits on recompute's row "
    "lock; the real-connection test below covers Postgres",
)
async def test_recompute_has_no_read_then_write_window(db, db_state):
    """P2-4: an image another transaction adds (and counts) while ``recompute``
    runs is never lost. The concurrent writer is let in before any statement
    after recompute's first; a single ``UPDATE ... (SELECT ...)`` has no second
    statement, so the counters always match the rows."""
    coll = await _seed(db)
    db.add(_image(coll, "a", 1.0))
    await db.commit()

    real_execute = db.execute
    calls: list[int] = []

    async def concurrent_upload() -> None:
        async with db_state.session_factory() as other:
            other.add(_image(coll, "b", 40.0))
            await other.flush()
            await stats.on_image_added(other, coll.id, 40.0, 40.0)
            await other.commit()

    async def interleaved(*args, **kwargs):
        if calls:
            await concurrent_upload()
        calls.append(1)
        return await real_execute(*args, **kwargs)

    db.execute = interleaved  # type: ignore[method-assign]
    try:
        await stats.recompute(db, coll.id)
        await db.commit()
    finally:
        db.execute = real_execute  # type: ignore[method-assign]
    rows = (await db.execute(select(Image).where(Image.collection_id == coll.id))).scalars().all()
    c = await _row(db, coll)
    assert c.image_count == len(rows)
    assert c.located_count == len([r for r in rows if r.lat is not None])
    assert c.bbox_maxx == max(r.lng for r in rows)


async def test_recompute_ignores_trashed_images(db):
    """The soft-delete filter does not reach the subqueries of an ``UPDATE``,
    so recompute must exclude the trash itself."""
    coll = await _seed(db)
    db.add_all([_image(coll, "a"), _image(coll, "b", 5.0, is_deleted=True)])
    await db.commit()
    await stats.recompute(db, coll.id)
    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (1, 0)
    assert _bbox(c) == (None, None, None, None)


@pytest.mark.skipif(not USING_POSTGRES, reason="needs real connections (Postgres)")
async def test_recompute_waits_for_an_inflight_upload_and_counts_it(db, db_state):
    """Round 2, P2-5, on real connections. An upload has inserted and counted
    an image but not committed; recompute must wait for it and then count it.
    An ``UPDATE`` that merely blocks on the row keeps the snapshot it started
    with (Read Committed) and overwrites the count without the image."""
    coll = await _seed(db)
    db.add(_image(coll, "a", 1.0))
    await db.commit()

    async with db_state.session_factory() as writer:
        writer.add(_image(coll, "b", 40.0))
        await writer.flush()
        await stats.on_image_added(writer, coll.id, 40.0, 40.0)

        async def run_recompute() -> None:
            async with db_state.session_factory() as other:
                await stats.recompute(other, coll.id)
                await other.commit()

        task = asyncio.create_task(run_recompute())
        await asyncio.sleep(0.3)
        assert not task.done()  # blocked behind the writer's row lock
        await writer.commit()
        await asyncio.wait_for(task, 10)

    c = await _row(db, coll)
    assert (c.image_count, c.located_count) == (2, 2)
    assert c.bbox_maxx == 40.0
