"""The pipeline from the web process: an upload drains its pipeline eagerly,
and the cycle/rendition bookkeeping holds across re-runs."""

from __future__ import annotations

import uuid

from sm_images.models import Collection, Image, StepRun
from sm_images.module import ImagesModule
from sm_images.pipeline.cycle import mark_processed
from sm_images.pipeline.orchestrate import rerun_image
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.pipeline_support import FIX, use_steps
from tests.upload_support import all_rows, make_collection, post_files, stored


async def test_an_upload_runs_its_pipeline_after_the_commit(uploads):
    """``on_startup``'s runtime + ingest's ``pipeline.dispatch``: the eager
    drain runs on the request's loop once the upload commits."""
    use_steps()
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)
    cid = await make_collection(uploads)
    async with uploads.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == uuid.UUID(cid))
            .values(pipeline_config={"steps": {"exif": {}, "renditions": {}}})
        )
        await s.commit()
    data = (FIX / "geotagged.jpg").read_bytes()
    got = await post_files(uploads, cid, [("g.jpg", data, "image/jpeg")])
    assert got.status_code == 200, got.text
    (row,) = await all_rows(uploads)
    runs = {r.step: r.status.value for r in await all_rows(uploads, StepRun)}
    assert runs == {"exif": "completed", "renditions": "completed"}
    assert row.camera_make == "Acme" and row.lat is not None
    assert row.processed_generation == 1
    assert len(stored(uploads.storage)) == 1 + 4  # original + the default four sizes


async def test_rendition_retry_at_the_same_display_generation_replaces_its_objects(pipe):
    coll = await pipe.collection({"renditions": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    first = {s: r.storage_key for s, r in (await pipe.renditions(img)).items()}
    await rerun_image(pipe.runtime, DEFAULT_TENANT, img, "force")
    second = {s: r.storage_key for s, r in (await pipe.renditions(img)).items()}
    assert first.keys() == second.keys()
    assert not set(first.values()) & set(second.values())  # a new attempt, new keys
    row = await pipe.row(img)
    assert set(pipe.keys()) == {row.storage_key, *second.values()}  # the old ones deleted
    async with pipe.db_state.session_factory() as s:
        from sm_images.models import ObjectIntent

        assert (await s.execute(select(ObjectIntent))).scalars().all() == []


async def test_the_cycle_is_concluded_once(pipe):
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    async with pipe.db_state.session_factory() as s:
        assert await mark_processed(s, DEFAULT_TENANT, img) == (coll.id, 1)
        assert await mark_processed(s, DEFAULT_TENANT, img) is None
        await s.commit()
    async with pipe.db_state.session_factory() as s:
        assert await mark_processed(s, DEFAULT_TENANT, img) is None
        await s.execute(update(Image).where(Image.id == img).values(processing_generation=2))
        assert await mark_processed(s, DEFAULT_TENANT, img) == (coll.id, 2)
