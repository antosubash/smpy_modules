"""The storage gauge at the executor's fenced publication and the janitor's purge.

A published display copy or rendition set swaps the image's hold to the new
total (billing commits the new hold and releases the old one at once); one
that does not fit fails the step ``quota_exceeded`` with the new objects gone
and the previous display kept; the purge releases the hold;
``storage_bytes`` is right with or without billing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.jobs.janitor import purge_expired
from sm_images.models import Image, ObjectIntent
from sm_images.pipeline.orchestrate import rerun_image
from sqlalchemy import select

from tests.support.billing import assert_counted_once, held_image
from tests.support.pipeline import Blur, use_steps

QUOTA = "quota_exceeded"


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


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
    img, first = await held_image(pipe, gauge, coll)
    await pipe.run(img)
    row, rends = await pipe.row(img), await pipe.renditions(img)
    (live,) = gauge.live()
    assert (live.id, live.status) == (row.storage_hold_id, "committed")
    assert live.quantity == row.storage_bytes == _expected(row, rends)
    assert gauge.holds[first].status == "released"
    # Regenerated: a new display copy and new renditions of the same total -
    # the hold already fits it, so billing is not asked again.
    swaps = len(gauge.calls)
    await rerun_image(pipe.runtime, DEFAULT_TENANT, img, "force")
    again = await pipe.row(img)
    assert again.display_generation == 2
    (same,) = gauge.live()
    assert same.id == again.storage_hold_id == live.id and len(gauge.calls) == swaps
    assert same.quantity == again.storage_bytes == _expected(again, await pipe.renditions(img))
    await assert_counted_once(pipe.db_state, gauge)


async def test_a_hold_that_does_not_fit_fails_the_step_and_keeps_the_display(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, first = await held_image(pipe, gauge, coll)
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


async def test_a_lost_fence_shrinks_the_swapped_hold_back(pipe, blur, gauge, monkeypatch):
    from sm_images.pipeline import finish

    coll = await pipe.collection({"acme.blur": {}})
    img, first = await held_image(pipe, gauge, coll)
    real, calls = finish.publish.publish_display, []

    async def fenced_once(*args, **kwargs):
        calls.append(1)
        return False if len(calls) == 1 else await real(*args, **kwargs)

    monkeypatch.setattr(finish.publish, "publish_display", fenced_once)
    await pipe.run(img)  # the first attempt loses the fence and is requeued
    assert len(calls) == 2
    row = await pipe.row(img)
    # The seed, the lost attempt's swap, its shrink back, the winner's swap.
    statuses = sorted(h.status for h in gauge.holds.values())
    assert statuses == ["committed", "released", "released", "released"]
    assert [h.id for h in gauge.live()] == [row.storage_hold_id]
    assert gauge.holds[first].status == "released"
    await assert_counted_once(pipe.db_state, gauge)


async def test_the_purge_releases_the_hold(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, _ = await held_image(pipe, gauge, coll)
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
