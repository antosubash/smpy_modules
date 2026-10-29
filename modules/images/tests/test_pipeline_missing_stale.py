"""A step enabled after images were processed counts as stale for them (QA TEST-007).

The image has no run of that step at all; "Re-run stale" must still reach it
(and say so), and the overview's stale count must include it, so the owner
sees why a restart is offered.
"""

from __future__ import annotations

from sm_images.models import Collection, Image
from sm_images.pipeline import restart
from sm_images.pipeline.control import overview
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.pipeline_support import Scripted, use_steps


async def _enable(pipe, coll, steps: dict) -> Collection:
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Collection).where(Collection.id == coll.id).values(pipeline_config={"steps": steps})
        )
        await s.commit()
        return await s.get(Collection, coll.id)


async def test_newly_enabled_step_is_stale_and_rerun_stale_runs_it(pipe):
    x, y = Scripted("acme.x"), Scripted("acme.y")
    use_steps(x, y)
    coll = await pipe.collection({"acme.x": {}})
    imgs = [await pipe.image(coll) for _ in range(2)]
    for img in imgs:
        await pipe.run(img)
    for img in imgs:
        assert "acme.y" not in await pipe.runs(img)
    coll = await _enable(pipe, coll, {"acme.x": {}, "acme.y": {}})

    async with pipe.db_state.session_factory() as s:
        body = await overview(s, coll)
    assert body["stale"] == 2  # one missing run per image

    changed = await restart.restart_collection_async(pipe.runtime, DEFAULT_TENANT, coll.id, "stale")
    assert changed == 2
    for img in imgs:
        runs = await pipe.runs(img)
        assert runs["acme.y"].status.value == "completed"
        assert runs["acme.x"].attempts == 1  # an up-to-date run is left alone
    async with pipe.db_state.session_factory() as s:
        assert (await overview(s, coll))["stale"] == 0


async def test_a_trashed_image_is_not_counted(pipe):
    x, y = Scripted("acme.x"), Scripted("acme.y")
    use_steps(x, y)
    coll = await pipe.collection({"acme.x": {}})
    live, gone = await pipe.image(coll), await pipe.image(coll)
    for img in (live, gone):
        await pipe.run(img)
    await pipe.trash(Image, gone)
    coll = await _enable(pipe, coll, {"acme.x": {}, "acme.y": {}})
    async with pipe.db_state.session_factory() as s:
        assert (await overview(s, coll))["stale"] == 1
