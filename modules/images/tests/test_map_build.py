"""Building a collection's PMTiles (Task 26): thresholds, tippecanoe, fencing.

The archive is built per collection from NDJSON by tippecanoe (the portal's
exact arguments), stored under a generation-specific ``map_key`` and published
by a compare-and-set on ``map_generation``: a build that a newer request or a
visibility change superseded never replaces the map.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_images.map import build, pmtiles_build, schedule
from sm_images.models import Collection, Image
from sm_images.pipeline import registry
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.pipeline_support import make_pipe, use_steps

T = DEFAULT_TENANT


async def _located(pipe, coll, n: int, **kw) -> list[uuid.UUID]:
    out = []
    for i in range(n):
        out.append(await pipe.image(coll, lat=10.0 + i, lng=20.0 + i, **kw))
    return out


async def _state(pipe, coll) -> Collection:
    async with pipe.db_state.session_factory() as s:
        return (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()


async def _request(pipe, coll, *, force: bool = False) -> int | None:
    async with pipe.db_state.session_factory() as s:
        gen = await schedule.request(s, pipe.runtime, T, coll.id, force=force)
        await finalize_session(s)
    return gen


# --- the threshold ------------------------------------------------------------


@pytest.mark.parametrize(
    ("pending", "baseline", "urgent", "expected"),
    [
        (0, 0, False, False),  # nothing changed
        (0, 0, True, False),
        (1, 0, False, True),  # zero baseline: the first change builds
        (49, 1000, False, False),  # 4.9%, under 100
        (50, 1000, False, True),  # 5%
        (99, 10_000, False, False),  # under both
        (100, 10_000, False, True),  # 100 points, whichever comes first
        (1, 10_000, True, True),  # a removal or a move never waits
    ],
)
def test_rebuild_threshold(pending, baseline, urgent, expected):
    assert schedule.due(pending, baseline, urgent=urgent, pct=5, abs_=100) is expected


async def test_image_processed_requests_a_build_at_the_threshold(tmp_path, monkeypatch):
    use_steps()
    pipe = await make_pipe(tmp_path, map_rebuild_threshold_abs=3, map_rebuild_threshold_pct=100)
    pipe.runtime = replace(pipe.runtime, maps=True)
    calls: list[int] = []

    async def fake(runtime, tenant, collection_id, generation):
        calls.append(generation)
        return build.PUBLISHED

    monkeypatch.setattr(build, "build_map_async", fake)
    try:
        coll = await pipe.collection({}, map_image_count=100)
        await pipe.run(await pipe.image(coll))  # no location: not a map change
        assert (await _state(pipe, coll)).map_changes == 0
        for img in await _located(pipe, coll, 2):
            await pipe.run(img)
        assert calls == [] and (await _state(pipe, coll)).map_changes == 2
        for img in await _located(pipe, coll, 1):
            await pipe.run(img)
        assert calls == [1]
        for img in await _located(pipe, coll, 3):  # a build is claimed: no second one
            await pipe.run(img)
        assert calls == [1]
    finally:
        await pipe.db_state.engine.dispose()
        registry.reset_registry()


async def test_reconcile_requests_a_due_map(pipe, monkeypatch):
    monkeypatch.setattr(pmtiles_build, "locate", lambda path: "/usr/bin/tippecanoe")
    coll = await pipe.collection({}, map_changes=4, map_urgent_mark=4)
    idle = await pipe.collection({}, map_changes=0)
    assert await schedule.reconcile_maps(pipe.runtime, T, datetime.now(UTC)) == 1
    assert (await _state(pipe, coll)).map_generation == 1
    assert (await _state(pipe, idle)).map_generation == 0
    # claimed: the next pass leaves it alone
    assert await schedule.reconcile_maps(pipe.runtime, T, datetime.now(UTC)) == 0


# --- the build and its fence ----------------------------------------------------


@pytest.fixture
def fake_tippecanoe(monkeypatch):
    """No binary needed: ``convert`` copies the NDJSON to the output."""
    monkeypatch.setattr(pmtiles_build, "locate", lambda path: "/fake/tippecanoe")

    def convert(binary, src, out, count):
        shutil.copyfile(src, out)

    monkeypatch.setattr(pmtiles_build, "convert", convert)


async def test_a_build_publishes_and_replaces_the_previous_map(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    await _located(pipe, coll, 2)
    gen = await _request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.PUBLISHED
    row = await _state(pipe, coll)
    assert row.map_key and row.map_key.startswith(f"images/{T}/{coll.id}/map.{gen}.")
    assert row.map_image_count == 2 and row.map_built_at is not None
    assert row.map_claimed_until is None
    first = row.map_key
    gen2 = await _request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen2) == build.PUBLISHED
    row = await _state(pipe, coll)
    assert row.map_key != first and not await pipe.store.exists(first)
    assert await pipe.store.exists(row.map_key)


async def test_a_superseded_build_is_not_published(pipe, fake_tippecanoe, monkeypatch):
    coll = await pipe.collection({})
    await _located(pipe, coll, 2)
    gen = await _request(pipe, coll)
    real_put = pipe.store.put
    uploaded: list[str] = []

    async def put(key, data, **kw):  # a visibility change lands mid-upload
        await real_put(key, data, **kw)
        uploaded.append(key)
        await _request(pipe, coll, force=True)

    monkeypatch.setattr(pipe.store, "put", put)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.SUPERSEDED
    row = await _state(pipe, coll)
    assert row.map_key is None and row.map_generation == gen + 1
    assert uploaded and not await pipe.store.exists(uploaded[0])


async def test_a_stale_message_does_nothing(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    await _located(pipe, coll, 1)
    old = await _request(pipe, coll)
    await _request(pipe, coll, force=True)
    assert await build.build_map_async(pipe.runtime, T, coll.id, old) == build.SUPERSEDED
    assert (await _state(pipe, coll)).map_key is None


async def test_an_emptied_collection_drops_its_map(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    (img,) = await _located(pipe, coll, 1)
    gen = await _request(pipe, coll)
    await build.build_map_async(pipe.runtime, T, coll.id, gen)
    old = (await _state(pipe, coll)).map_key
    await pipe.trash(Image, img)
    gen = await _request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.PUBLISHED
    row = await _state(pipe, coll)
    assert row.map_key is None and row.map_image_count == 0
    assert not await pipe.store.exists(old)


async def test_missing_tippecanoe_cools_down(pipe, monkeypatch):
    monkeypatch.setattr(pmtiles_build, "locate", lambda path: None)
    coll = await pipe.collection({})
    await _located(pipe, coll, 1)
    gen = await _request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.UNAVAILABLE
    row = await _state(pipe, coll)
    assert row.map_key is None
    assert row.map_claimed_until > datetime.now(UTC) + timedelta(minutes=5)


async def test_a_failing_tippecanoe_keeps_the_old_map(pipe, fake_tippecanoe, monkeypatch):
    coll = await pipe.collection({})
    await _located(pipe, coll, 1)
    gen = await _request(pipe, coll)
    await build.build_map_async(pipe.runtime, T, coll.id, gen)
    kept = (await _state(pipe, coll)).map_key

    def broken(binary, src, out, count):
        raise pmtiles_build.TippecanoeError("exit 1")

    monkeypatch.setattr(pmtiles_build, "convert", broken)
    gen = await _request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.FAILED
    row = await _state(pipe, coll)
    assert row.map_key == kept and row.map_claimed_until > datetime.now(UTC)


async def test_a_trashed_collection_is_not_built(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    await _located(pipe, coll, 1)
    gen = await _request(pipe, coll)
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Collection).where(Collection.id == coll.id).values(is_deleted=True))
        await s.commit()
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.SUPERSEDED


async def test_the_janitor_keeps_the_published_map_and_reaps_a_lost_one(pipe):
    from simple_module_db import all_tenants
    from sm_images import storage_keys
    from sm_images.janitor import reap_intents
    from sm_images.models import ObjectIntent

    coll = await pipe.collection({})
    live = storage_keys.map_key(T, str(coll.id), 1, "a")
    lost = storage_keys.map_key(T, str(coll.id), 2, "b")
    old = datetime.now(UTC) - timedelta(days=30)
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Collection).where(Collection.id == coll.id).values(map_key=live))
        s.add_all([ObjectIntent(key=k, created_at=old) for k in (live, lost)])
        await s.commit()
    for key in (live, lost):
        await pipe.store.put(key, b"m", content_type="application/octet-stream", size=1)
    with all_tenants():
        async with pipe.db_state.session_factory() as s:
            report = await reap_intents(s, pipe.store, now=datetime.now(UTC), grace_days=7)
            await s.commit()
    assert (report.reaped, report.referenced) == ([lost], [live])
    assert await pipe.store.exists(live) and not await pipe.store.exists(lost)
