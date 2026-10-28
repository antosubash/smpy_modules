"""Collection counters and bounding box: incremental SQL, recompute for the rest."""

from __future__ import annotations

from sm_images.models import Collection, Image, Visibility
from sm_images.services import stats
from sqlalchemy import select


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
