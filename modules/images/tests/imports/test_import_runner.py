"""``images.import_geojson``'s body: chunks, checkpoints, generations, resume.

Ports of the portal's ``test_import_resume`` and ``test_base64_import`` cases;
review focus 4 ("an interrupted import replays") lives here.
"""

from __future__ import annotations

import pytest
from sm_images.imports import chunk, claims, runner, settle
from sm_images.models import LocationSource
from sm_images.tenancy import DEFAULT_TENANT

from tests.support.imports import b64, feature

pytestmark = pytest.mark.asyncio


class Killed(BaseException):
    """A worker killed mid-task (not an Exception: nothing may swallow it)."""


def kill_after(monkeypatch, module, name: str, n: int):
    real = getattr(module, name)
    calls = {"n": 0}

    async def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > n:
            raise Killed()
        return await real(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return calls


async def test_base64_import_creates_images_and_completes(imp):
    feats = [
        feature({"img": b64("red"), "site": "P1"}, (8.5, 47.3)),
        feature({"img": "not base64!!"}),
        feature(None),
        feature({"img": b64("blue")}),
    ]
    job = await imp.job(feats)
    assert await imp.run(job) == "completed"
    assert await imp.statuses(job) == ["done", "failed", "failed", "done"]
    assert await imp.counts(job) == ("completed", 4, 4, 2, 0, 2)
    items = await imp.items(job)
    assert [i.last_error for i in items] == [None, "invalid_base64", "missing_image", None]
    images = await imp.images()
    assert len(images) == 2
    first = next(i for i in images if i.id == items[0].image_id)
    assert (first.lat, first.lng, first.external_source) == (47.3, 8.5, "import")
    assert first.properties == {"site": "P1"}  # the image data itself is not retained
    assert first.location_source == LocationSource.IMPORT_
    # It finished with failures: it keeps its source for retry-failed (the
    # janitor removes it after the grace period).
    assert (await imp.reload(job)).source_key in imp.stored()


async def test_empty_and_all_invalid_jobs_reach_a_terminal_state(imp):
    empty = await imp.job([])
    assert await imp.run(empty) == "completed"
    # No failures: the source is deleted at once.
    assert (await imp.reload(empty)).staged_keys == []
    assert not [k for k in imp.stored() if "/imports/" in k]
    job = await imp.job([feature(None), "x"])
    assert await imp.run(job) == "completed"
    assert await imp.counts(job) == ("completed", 2, 2, 0, 0, 2)


async def test_resume_after_kill_no_duplicates_base64_without_ids(imp, monkeypatch):
    """Killed after one ingest of the second chunk: the chunk's items and the
    checkpoint committed, one image too. The replay skips what has an image and
    finds the rest by their job-scoped default ids - no duplicate, exact counts."""
    monkeypatch.setattr(runner, "CHUNK", 2)
    feats = [feature({"img": b64(c)}) for c in ("red", "blue", "green", "white", "black")]
    job = await imp.job(feats)
    kill_after(monkeypatch, settle, "ingest_item", 3)
    with pytest.raises(Killed):
        await imp.run(job)
    assert len(await imp.images()) == 3
    status, _total, checkpoint, done, _, _ = await imp.counts(job)
    assert (status, checkpoint, done) == ("running", 4, 3)

    monkeypatch.undo()
    monkeypatch.setattr(runner, "CHUNK", 2)
    calls = kill_after(monkeypatch, settle, "ingest_item", 100)
    claimed = await claims.claim_stale(imp.runtime, DEFAULT_TENANT, job.id)
    assert claimed == job.generation + 1
    assert await imp.run(job, claimed) == "completed"
    assert calls["n"] == 2  # only the two items that never got an image
    assert len(await imp.images()) == 5
    assert await imp.counts(job) == ("completed", 5, 5, 5, 0, 0)
    ids = [i.image_id for i in await imp.items(job)]
    assert None not in ids and len(set(ids)) == 5


async def test_kill_between_image_commit_and_item_is_impossible(imp, monkeypatch):
    """The image, its item and the counter commit together: a failure after
    ``add_image`` but before the commit leaves neither."""
    job = await imp.job([feature({"img": b64()})])
    kill_after(monkeypatch, settle, "mark_item", 0)
    with pytest.raises(Killed):
        await imp.run(job)
    assert await imp.images() == []
    assert await imp.statuses(job) == ["pending"]
    monkeypatch.undo()
    assert (
        await imp.run(job, await claims.claim_stale(imp.runtime, DEFAULT_TENANT, job.id))
        == "completed"
    )
    assert len(await imp.images()) == 1


async def test_checkpoint_atomic_with_items(imp, monkeypatch):
    """A chunk's items and its checkpoint commit in one transaction: a failure
    while advancing leaves neither, and the replay starts at that chunk."""
    monkeypatch.setattr(runner, "CHUNK", 2)
    job = await imp.job([feature({"img": b64(c)}) for c in ("red", "blue", "green")])
    kill_after(monkeypatch, chunk, "advance_checkpoint", 1)
    with pytest.raises(Killed):
        await imp.run(job)
    assert [i.feature_index for i in await imp.items(job)] == [0, 1]
    assert (await imp.reload(job)).checkpoint_index == 2
    monkeypatch.undo()
    assert (
        await imp.run(job, await claims.claim_stale(imp.runtime, DEFAULT_TENANT, job.id))
        == "completed"
    )
    assert await imp.counts(job) == ("completed", 3, 3, 3, 0, 0)


async def test_restart_bumps_generation_old_task_aborts(imp, monkeypatch):
    monkeypatch.setattr(runner, "CHUNK", 1)
    job = await imp.job([feature({"img": b64(c)}) for c in ("red", "blue")])
    kill_after(monkeypatch, settle, "ingest_item", 1)
    with pytest.raises(Killed):
        await imp.run(job)
    monkeypatch.undo()
    from sm_images.imports import controls, reset

    restarted = await controls.restart(imp.runtime, DEFAULT_TENANT, job.id, launch=False)
    assert restarted.generation == job.generation + 1
    assert (restarted.status.value, restarted.checkpoint_index) == ("resetting", 0)
    # The old message arrives late: it must not write a thing.
    assert await imp.run(job, job.generation) == "stale"
    assert [i.feature_index for i in await imp.items(job)] == [0, 1]
    real_launch = reset.handoff.launch_runner
    launched = []

    async def hold(runtime, tenant, job_id, generation):
        launched.append(generation)

    monkeypatch.setattr(reset.handoff, "launch_runner", hold)
    assert (
        await reset.run_reset(imp.runtime, DEFAULT_TENANT, job.id, restarted.generation) == "reset"
    )
    after = await imp.reload(job)
    assert (after.status.value, after.done_count) == ("pending", 1)  # the success is counted back
    assert [i.feature_index for i in await imp.items(job)] == [0]
    monkeypatch.setattr(reset.handoff, "launch_runner", real_launch)
    assert await imp.run(job, launched[0]) == "completed"
    assert await imp.counts(job) == ("completed", 2, 2, 2, 0, 0)
    assert len(await imp.images()) == 2


async def test_a_paused_job_stops_at_the_next_chunk(imp, monkeypatch):
    from sm_images.imports import controls

    monkeypatch.setattr(runner, "CHUNK", 1)
    job = await imp.job([feature({"img": b64(c)}) for c in ("red", "blue", "green")])
    real = settle.ingest_chunk

    async def pause_after_first(*args, **kwargs):
        out = await real(*args, **kwargs)
        await controls.pause(imp.runtime, DEFAULT_TENANT, job.id)
        return out

    monkeypatch.setattr(settle, "ingest_chunk", pause_after_first)
    assert await imp.run(job) == "stopped"
    assert (await imp.counts(job))[:4] == ("paused", 3, 1, 1)
    monkeypatch.undo()
    resumed = await controls.resume(imp.runtime, DEFAULT_TENANT, job.id, launch=False)
    assert await imp.run(job, resumed.generation) == "completed"
    assert await imp.counts(job) == ("completed", 3, 3, 3, 0, 0)


async def test_a_job_whose_collection_is_trashed_is_cancelled(imp):
    from sm_images.models import Collection

    job = await imp.job([feature({"img": b64()})])
    await imp.pipe.trash(Collection, imp.coll.id)
    assert await imp.run(job) == "cancelled"
    assert (await imp.reload(job)).status.value == "cancelled"
    assert await imp.images() == []


async def test_every_imported_image_gets_its_steps_planned_and_auto_run_queued(imp, monkeypatch):
    """Imports ingest through the one entry point, so an imported image is
    planned (its step rows) and handed to the auto-run hook like an upload."""
    from sm_images import pipeline

    queued = []

    async def queue(db, coll, image_id, *, enabled=True):
        queued.append(image_id)

    monkeypatch.setattr(pipeline, "queue_auto_run", queue)
    coll = await imp.pipe.collection({"exif": {"enabled": True}})
    job = await imp.job([feature({"img": b64("red")}), feature({"img": b64("blue")})], coll=coll)
    assert await imp.run(job) == "completed"
    images = await imp.images(coll)
    assert len(images) == 2
    assert sorted(queued) == sorted(i.id for i in images)
    for image in images:
        assert "exif" in await imp.pipe.runs(image.id)
