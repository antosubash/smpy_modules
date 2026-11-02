"""Taking points off a published map at once (Task 26, review fixes).

A removed point (an image trashed, its location cleared) and a change of the
redaction gate withdraw the archive in the same transaction and move the
generation on, so a build already in flight can never publish what it saw. An
archive is stamped with the gate it was built under, and one built under
another gate is never served. A located image that falls back into
redaction-pending counts as an urgent change.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_db import finalize_session
from sm_images.core.access import redaction
from sm_images.core.storage import ImageStore
from sm_images.core.tenancy import DEFAULT_TENANT, tenant_scope
from sm_images.map import build, recover
from sm_images.models import Collection, Image, StepRun, Visibility
from sm_images.models.enums import StepStatus
from sm_images.pipeline import cycle, publish
from sm_images.pipeline.runtime import bind_runtime
from sm_images.web.services import gallery
from sqlalchemy import select

from tests.support.access import OWNER, collection, headers
from tests.support.map import T, located, request, state
from tests.support.pipeline import Blur, use_steps

# --- 1. a removed point -------------------------------------------------------


async def _published(pipe, coll) -> str:
    gen = await request(pipe, coll)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.PUBLISHED
    return (await state(pipe, coll)).map_key


async def _remove(pipe, coll, image_id, how: str) -> None:
    with bind_runtime(pipe.runtime):
        async with pipe.db_state.session_factory() as s:
            c = (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()
            img = (await s.execute(select(Image).where(Image.id == image_id))).scalar_one()
            if how == "trash":
                await gallery.delete(s, c, img)
            else:
                await gallery.set_location(s, c, img, None, None)
            await finalize_session(s)


@pytest.mark.parametrize("how", ["trash", "clear"])
async def test_removing_a_point_mid_build_fences_the_build(pipe, fake_tippecanoe, monkeypatch, how):
    coll = await pipe.collection({})
    first, _ = await located(pipe, coll, 2)
    old = await _published(pipe, coll)
    gen = await request(pipe, coll)
    real_put = pipe.store.put
    uploaded: list[str] = []

    async def put(key, data, **kw):  # the image leaves while the build uploads
        await real_put(key, data, **kw)
        uploaded.append(key)
        await _remove(pipe, coll, first, how)

    monkeypatch.setattr(pipe.store, "put", put)
    assert await build.build_map_async(pipe.runtime, T, coll.id, gen) == build.SUPERSEDED
    row = await state(pipe, coll)
    assert row.map_key is None  # nothing is served until a fresh build publishes
    assert row.map_generation > gen
    assert row.map_urgent_mark == row.map_changes > row.map_built_changes
    assert not await pipe.store.exists(old) and not await pipe.store.exists(uploaded[0])


async def test_removing_a_point_withdraws_the_published_map(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    (pic,) = await located(pipe, coll, 1)
    old = await _published(pipe, coll)
    await _remove(pipe, coll, pic, "trash")
    row = await state(pipe, coll)
    assert row.map_key is None and row.map_generation == 2
    assert not await pipe.store.exists(old)


async def test_an_unlocated_image_leaving_keeps_the_map(pipe, fake_tippecanoe):
    coll = await pipe.collection({})
    await located(pipe, coll, 1)
    bare = await pipe.image(coll)
    kept = await _published(pipe, coll)
    await _remove(pipe, coll, bare, "trash")
    assert (await state(pipe, coll)).map_key == kept


# --- 2. an image falling back into redaction-pending ---------------------------


async def _blur_run(pipe, image_id, status=StepStatus.COMPLETED) -> None:
    async with pipe.db_state.session_factory() as s:
        s.add(StepRun(image_id=image_id, step="acme.blur", status=status, step_version=1))
        await s.commit()


@pytest.mark.parametrize("via", ["reset", "invalidate"])
async def test_a_located_image_reopening_its_mutator_is_urgent(pipe, via):
    use_steps(Blur())
    coll = await pipe.collection({"acme.blur": {}})
    (pic,) = await located(pipe, coll, 1)
    bare = await pipe.image(coll)
    await _blur_run(pipe, pic)
    await _blur_run(pipe, bare)
    async with pipe.db_state.session_factory() as s:
        for img in (bare, pic):
            if via == "reset":
                await cycle.reset_runs(s, T, img, ["acme.blur"], datetime.now(UTC))
            else:
                await publish.invalidate_other_mutators(s, T, img, "acme.crop")
        await finalize_session(s)
    row = await state(pipe, coll)
    assert row.map_changes == row.map_urgent_mark == 1  # the located one only


async def test_reopening_an_unsettled_run_is_not_a_change(pipe):
    use_steps(Blur())
    coll = await pipe.collection({"acme.blur": {}})
    (pic,) = await located(pipe, coll, 1)
    await _blur_run(pipe, pic, StepStatus.PENDING)
    async with pipe.db_state.session_factory() as s:
        await cycle.reset_runs(s, T, pic, ["acme.blur"], datetime.now(UTC))
        await finalize_session(s)
    assert (await state(pipe, coll)).map_changes == 0


# --- 3. the redaction gate an archive was built under ------------------------

ARCHIVE = b"pmtiles" * 8
PMTILES = "application/vnd.pmtiles"


@pytest.fixture
def blur_installed():
    use_steps(Blur())
    yield
    use_steps()


async def _seed(client, storage, *, stamp: str | None = None, slug="gate", **kw) -> Collection:
    from sm_images.core.storage import keys as storage_keys

    coll = collection(slug, Visibility.PRIVATE, OWNER, **kw)
    coll.map_key = storage_keys.map_key(DEFAULT_TENANT, str(coll.id), 1, "a")
    coll.map_generation = 1
    coll.map_policy_rev = redaction.gate_key(coll) if stamp is None else stamp
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.commit()
    await ImageStore(storage).put(coll.map_key, ARCHIVE, content_type=PMTILES, size=len(ARCHIVE))
    return coll


def _url(coll) -> str:
    return f"/api/images/collections/{coll.id}/map.pmtiles"


async def _row(client, coll) -> Collection:
    async with client.db_state.session_factory() as s:
        return (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()


async def test_an_archive_from_another_gate_is_not_served(client, storage, blur_installed):
    coll = await _seed(client, storage)
    assert (await client.get(_url(coll), headers=headers(OWNER))).status_code == 200
    stale = await _seed(client, storage, stamp="built-under-another-gate", slug="gate-2")
    assert (await client.get(_url(stale), headers=headers(OWNER))).status_code == 404


async def test_the_mutator_plugin_going_away_stops_the_archive(client, storage, blur_installed):
    coll = await _seed(client, storage, pipeline_config={"steps": {"acme.blur": {}}})
    assert (await client.get(_url(coll), headers=headers(OWNER))).status_code == 200
    use_steps()  # uninstalled: every image is pending again, the archive is stale
    assert (await client.get(_url(coll), headers=headers(OWNER))).status_code == 404


async def test_saving_a_gate_change_withdraws_and_fences_the_map(
    client, storage, blur_installed, web_runtime
):
    coll = await _seed(client, storage)
    url = f"/api/images/collections/{coll.id}/pipeline"
    got = await client.put(url, json={"steps": {"acme.blur": {}}}, headers=headers(OWNER))
    assert got.status_code == 200, got.text
    row = await _row(client, coll)
    assert row.map_key is None and row.map_generation == 2
    assert row.map_urgent_mark == row.map_changes > 0
    assert (await client.get(_url(coll), headers=headers(OWNER))).status_code == 404
    # a save that leaves the gate alone does not touch the map
    again = await client.put(url, json={"steps": {"acme.blur": {}}}, headers=headers(OWNER))
    assert again.status_code == 200
    assert (await _row(client, coll)).map_generation == 2


async def test_reconcile_withdraws_an_archive_from_another_gate(
    client, storage, monkeypatch, web_runtime
):
    from sm_images.map import pmtiles_build

    monkeypatch.setattr(pmtiles_build, "locate", lambda path: "/fake/tippecanoe")
    with tenant_scope(DEFAULT_TENANT):
        stale = await _seed(client, storage, stamp="old")
        fresh = await _seed(client, storage, slug="gate-fresh")
        await recover.reconcile_maps(web_runtime, T, datetime.now(UTC))
    assert (await _row(client, stale)).map_key is None
    assert (await _row(client, fresh)).map_key == fresh.map_key
