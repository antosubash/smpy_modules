"""Points that leave or move withdraw the map at once (Task 26, review fixes 2).

* A located image whose settled display mutator reopens is redaction-pending
  again: the archive that places it is withdrawn in the reset's transaction
  and any build in flight is fenced, not merely counted as urgent.
* A located image *moved* (by hand, or by a later EXIF read) would otherwise
  keep its old coordinates in the published archive until the next rebuild:
  the move withdraws as a removal does. An unlocated image gaining a location
  only arrives, so it stays a counted change.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_db import finalize_session
from sm_images.core.access import redaction
from sm_images.core.storage import ImageStore
from sm_images.core.storage import keys as storage_keys
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.map import build
from sm_images.models import Collection, Image, StepRun, Visibility
from sm_images.models.enums import LocationSource, StepStatus
from sm_images.pipeline import cycle, publish
from sm_images.pipeline.processing.exif import ExifData
from sm_images.pipeline.runtime import bind_runtime
from sm_images.web.services import gallery
from sqlalchemy import select

from tests.support.access import OWNER, collection, headers, image
from tests.support.map import T, located, request, state
from tests.support.pipeline import Blur, use_steps


async def _reopen(factory, image_id, via: str) -> None:
    async with factory() as s:
        if via == "reset":
            await cycle.reset_runs(s, T, image_id, ["acme.blur"], datetime.now(UTC))
        else:
            await publish.invalidate_other_mutators(s, T, image_id, "acme.crop")
        await finalize_session(s)


async def _blur_done(factory, image_id) -> None:
    async with factory() as s:
        s.add(
            StepRun(
                image_id=image_id, step="acme.blur", status=StepStatus.COMPLETED, step_version=1
            )
        )
        await s.commit()


async def _published(pipe, coll) -> str:
    gen = await request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.PUBLISHED
    return (await state(pipe, coll)).map_key


async def _superseded_by(pipe, coll, monkeypatch, change) -> None:
    """A build in flight while ``change`` commits (during its upload) can
    never publish, and nothing is served afterwards."""
    gen = await request(pipe, coll)
    real_put = pipe.store.put

    async def put(key, data, **kw):
        await real_put(key, data, **kw)
        await change()

    monkeypatch.setattr(pipe.store, "put", put)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.SUPERSEDED
    row = await state(pipe, coll)
    assert row.map_key is None and row.map_generation > gen


# --- 1. falling back into redaction-pending ---------------------------------


@pytest.fixture
def blur_installed():
    use_steps(Blur())
    yield
    use_steps()


@pytest.mark.parametrize("via", ["reset", "invalidate"])
async def test_reopening_a_located_mutator_stops_the_tiles_at_once(
    client, storage, blur_installed, via
):
    coll = collection(
        "reopen", Visibility.PRIVATE, OWNER, pipeline_config={"steps": {"acme.blur": {}}}
    )
    coll.map_key = storage_keys.map_key(DEFAULT_TENANT, str(coll.id), 1, "a")
    coll.map_generation = 1
    coll.map_policy_rev = redaction.gate_key(coll)
    pic = image(coll, "a.jpg", lat=1.0, lng=2.0)
    factory = client.db_state.session_factory
    async with factory() as s:
        s.add_all([coll, pic])
        await s.commit()
    await ImageStore(storage).put(coll.map_key, b"pm" * 8, content_type="x", size=16)
    await _blur_done(factory, pic.id)
    url = f"/api/images/collections/{coll.id}/map.pmtiles"
    assert (await client.get(url, headers=headers(OWNER))).status_code == 200
    await _reopen(factory, pic.id, via)
    assert (await client.get(url, headers=headers(OWNER))).status_code == 404
    async with factory() as s:
        row = (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()
    assert row.map_key is None and row.map_generation == 2


@pytest.mark.parametrize("via", ["reset", "invalidate"])
async def test_a_reopen_mid_build_fences_the_build(pipe, fake_tippecanoe, monkeypatch, via):
    use_steps(Blur())
    coll = await pipe.collection({"acme.blur": {}})
    (pic,) = await located(pipe, coll, 1)
    await _blur_done(pipe.db_state.session_factory, pic)

    async def change():
        await _reopen(pipe.db_state.session_factory, pic, via)

    await _superseded_by(pipe, coll, monkeypatch, change)


# --- 2. a located image moved ------------------------------------------------


async def _move(pipe, coll, image_id, lat, lng) -> None:
    with bind_runtime(pipe.runtime):
        async with pipe.db_state.session_factory() as s:
            c = (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()
            img = (await s.execute(select(Image).where(Image.id == image_id))).scalar_one()
            await gallery.set_location(s, c, img, lat, lng)
            await finalize_session(s)


async def test_moving_a_located_image_withdraws_the_map(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    (pic,) = await located(pipe, coll, 1)
    old = await _published(pipe, coll)
    await _move(pipe, coll, pic, 45.0, 7.0)
    row = await state(pipe, coll)
    assert row.map_key is None and row.map_generation == 2
    assert not await pipe.store.exists(old)


async def test_a_move_mid_build_fences_the_build(pipe, fake_tippecanoe, monkeypatch):
    coll = await pipe.collection({})
    (pic,) = await located(pipe, coll, 1)

    async def change():
        await _move(pipe, coll, pic, 45.0, 7.0)

    await _superseded_by(pipe, coll, monkeypatch, change)


async def test_locating_an_unlocated_image_keeps_the_map(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    await located(pipe, coll, 1)
    bare = await pipe.image(coll)
    kept = await _published(pipe, coll)
    await _move(pipe, coll, bare, 45.0, 7.0)
    row = await state(pipe, coll)
    assert row.map_key == kept and row.map_urgent_mark == row.map_changes == 1


async def _exif(pipe, image_id, lat, lng) -> None:
    with bind_runtime(pipe.runtime):
        async with pipe.db_state.session_factory() as s:
            await publish.store_exif(s, T, image_id, ExifData(lat=lat, lng=lng))
            await finalize_session(s)


async def test_an_exif_read_moving_a_located_image_withdraws_the_map(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    (pic,) = await located(pipe, coll, 1, location_source=LocationSource.EXIF)
    old = await _published(pipe, coll)
    await _exif(pipe, pic, 10.0, 20.0)  # the same place: nothing leaves
    assert (await state(pipe, coll)).map_key == old
    await _exif(pipe, pic, 45.0, 7.0)
    row = await state(pipe, coll)
    assert row.map_key is None and row.map_generation == 2
    assert not await pipe.store.exists(old)


async def test_an_exif_read_never_moves_a_manual_location(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    (pic,) = await located(pipe, coll, 1, location_source=LocationSource.MANUAL)
    old = await _published(pipe, coll)
    await _exif(pipe, pic, 45.0, 7.0)
    assert (await state(pipe, coll)).map_key == old
