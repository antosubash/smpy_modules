"""The storage gauge at the executor's fenced publication and the janitor's purge.

A published display copy or rendition set takes a hold for the image's new
total, then releases the old one; a hold that does not fit fails the step
``quota_exceeded`` with the new objects gone and the previous display kept;
the purge releases the hold; ``storage_bytes`` is right with or without billing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_images import billing
from sm_images.janitor import purge_expired
from sm_images.models import Image, ObjectIntent
from sm_images.pipeline.orchestrate import rerun_image
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.pipeline_support import Blur, use_steps

QUOTA = "quota_exceeded"


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


async def _held_image(pipe, gauge, coll):
    """An ingested image: its original under a committed hold, as ingest leaves it."""
    img = await pipe.image(coll)
    row = await pipe.row(img)
    hold = await gauge.reserve(DEFAULT_TENANT, billing.METER, row.size_bytes, "seed", source="t")
    await gauge.commit(hold.id)
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Image)
            .where(Image.id == img)
            .values(storage_hold_id=hold.id, storage_bytes=row.size_bytes)
        )
        await s.commit()
    return img, hold.id


def _expected(row, renditions) -> int:
    return row.size_bytes + row.display_bytes + sum(r.size_bytes for r in renditions.values())


async def _object_size(pipe, key: str) -> int:
    return len(await pipe.store.read(key))


async def test_storage_bytes_is_kept_without_billing(pipe, blur):
    coll = await pipe.collection({"acme.blur": {}, "renditions": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    row, rends = await pipe.row(img), await pipe.renditions(img)
    assert row.display_key and set(rends) == {"small", "medium"}
    assert row.display_bytes == await _object_size(pipe, row.display_key)
    for r in rends.values():
        assert r.size_bytes == await _object_size(pipe, r.storage_key) > 0
    assert row.storage_bytes == _expected(row, rends) > row.size_bytes
    assert row.storage_hold_id is None


async def test_a_regenerated_display_moves_the_hold(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}, "renditions": {}})
    img, first = await _held_image(pipe, gauge, coll)
    await pipe.run(img)
    row, rends = await pipe.row(img), await pipe.renditions(img)
    (live,) = gauge.live()
    assert (live.id, live.status) == (row.storage_hold_id, "committed")
    assert live.quantity == row.storage_bytes == _expected(row, rends)
    assert gauge.holds[first].status == "released"
    # Regenerated: a new display copy and new renditions, one hold again.
    await rerun_image(pipe.runtime, DEFAULT_TENANT, img, "force")
    again = await pipe.row(img)
    assert again.display_generation == 2
    (moved,) = gauge.live()
    assert moved.id == again.storage_hold_id != live.id
    assert moved.quantity == again.storage_bytes == _expected(again, await pipe.renditions(img))
    assert gauge.holds[live.id].status == "released"


async def test_a_hold_that_does_not_fit_fails_the_step_and_keeps_the_display(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, first = await _held_image(pipe, gauge, coll)
    before = set(pipe.keys())
    gauge.limit = (await pipe.row(img)).size_bytes  # no room for a second copy
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.blur"]
    assert (run.status.value, run.error_code) == ("failed", QUOTA)
    row = await pipe.row(img)
    assert (row.display_key, row.display_generation) == (None, 0)
    assert (row.storage_hold_id, row.storage_bytes) == (first, row.size_bytes)
    assert set(pipe.keys()) == before  # the staged display copy is gone
    async with pipe.db_state.session_factory() as s:
        assert (await s.execute(select(ObjectIntent.key))).scalars().all() == []
    assert [h.id for h in gauge.live()] == [first]


async def test_a_lost_fence_releases_the_new_hold(pipe, blur, gauge, monkeypatch):
    from sm_images.pipeline import finish

    coll = await pipe.collection({"acme.blur": {}})
    img, first = await _held_image(pipe, gauge, coll)
    real, calls = finish.publish.publish_display, []

    async def fenced_once(*args, **kwargs):
        calls.append(1)
        return False if len(calls) == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(finish.publish, "publish_display", fenced_once)
    await pipe.run(img)  # the first attempt loses the fence and is requeued
    assert len(calls) == 2
    row = await pipe.row(img)
    statuses = sorted(h.status for h in gauge.holds.values())
    assert statuses == ["committed", "released", "released"]  # seed, lost attempt, winner
    assert [h.id for h in gauge.live()] == [row.storage_hold_id]
    assert gauge.holds[first].status == "released"


async def test_the_purge_releases_the_hold(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await _held_image(pipe, gauge, coll)
    await pipe.run(img)
    held = (await pipe.row(img)).storage_hold_id
    assert [h.id for h in gauge.live()] == [held]
    old = datetime.now(UTC) - timedelta(days=8)
    await pipe.trash(Image, img, old)
    async with pipe.db_state.session_factory() as db:
        report = await purge_expired(db, pipe.store, now=datetime.now(UTC), grace_days=7)
        assert gauge.live()  # not before the commit
        await finalize_session(db)
    assert report.images == [img]
    assert gauge.live() == [] and gauge.holds[held].status == "released"
