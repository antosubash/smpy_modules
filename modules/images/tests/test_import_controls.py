"""Job controls, grouping, backpressure, and recovery by reconcile and the janitor
(ports of the portal's ``test_import_restart_requeue``, ``test_import_heartbeat``
and ``test_import_resume`` claim cases)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sm_images.errors import Conflict
from sm_images.imports import controls, jobs, launch, runner, terminal
from sm_images.models import ImportItem, ImportJob
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.fetch_support import body
from tests.import_support import B64, HOST, URL, b64, feature, serve_images
from tests.pipeline_support import jpeg

pytestmark = pytest.mark.asyncio
T = DEFAULT_TENANT


async def _age(imp, job, minutes: int = 30) -> None:
    """Make the job's heartbeat (and its items' last touch) old."""
    old = datetime.now(UTC) - timedelta(minutes=minutes)
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(
            update(ImportJob).where(ImportJob.id == job.id).values(heartbeat_at=old, updated_at=old)
        )
        await s.execute(
            update(ImportItem).where(ImportItem.job_id == job.id).values(updated_at=old)
        )
        await s.commit()


async def test_retry_failed_decrements_the_failed_counter_and_reopens_the_job(imp, resolver, inner):
    state = {"down": True}

    def maybe(request):
        return httpx.Response(404) if state["down"] else body(jpeg())

    serve_images(resolver, inner, fail={"/x.jpg": maybe})
    job = await imp.job(
        [feature({"url": f"https://{HOST}/x.jpg"}), feature({"url": f"https://{HOST}/y.jpg"})], URL
    )
    await imp.run(job)
    assert await imp.counts(job) == ("completed", 2, 2, 1, 0, 1)
    state["down"] = False
    out = await controls.retry_failed(imp.runtime, T, job.id)
    assert out.status.value in ("running", "completed")
    assert await imp.counts(job) == ("completed", 2, 2, 2, 0, 0)
    assert await imp.statuses(job) == ["done", "done"]


async def test_retry_failed_needs_the_source_for_a_base64_job(imp):
    job = await imp.job([feature({"img": "!!"})])
    await imp.run(job)
    with pytest.raises(Conflict):
        await controls.retry_failed(imp.runtime, T, job.id)


async def test_restart_deletes_unfinished_items_in_chunks_and_replays(
    imp, monkeypatch, resolver, inner
):
    monkeypatch.setattr(controls, "RESET_CHUNK", 2)
    real = launch.launch_downloads

    async def lost(runtime, tenant, job_id, ids):
        return None

    monkeypatch.setattr(launch, "launch_downloads", lost)
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": f"https://{HOST}/{i}.jpg"}) for i in range(5)], URL)
    assert await imp.run(job) == "running"
    out = await controls.restart(imp.runtime, T, job.id, launch=False)
    assert (out.status.value, out.checkpoint_index, out.generation) == (
        "pending",
        0,
        job.generation + 1,
    )
    assert await imp.items(job) == []  # 5 rows, deleted 2 at a time
    monkeypatch.setattr(launch, "launch_downloads", real)
    assert await imp.run(job, out.generation) == "completed"
    assert len(seen) == 5
    assert await imp.counts(job) == ("completed", 5, 5, 5, 0, 0)


async def test_restart_of_a_finished_url_job_resets_from_its_rows(
    imp, monkeypatch, resolver, inner
):
    from sm_images.imports import retry

    monkeypatch.setattr(retry, "RESET_CHUNK", 1)
    state = {"down": True}
    serve_images(
        resolver,
        inner,
        fail={"/bad.jpg": lambda r: httpx.Response(404) if state["down"] else body(jpeg())},
    )
    feats = [feature({"url": f"https://{HOST}/bad.jpg"})] + [
        feature({"url": f"https://{HOST}/{i}.jpg"}) for i in range(4)
    ]
    job = await imp.job([*feats, feature(None)], URL)
    await imp.run(job)
    assert await imp.counts(job) == ("completed", 6, 6, 4, 0, 2)
    state["down"] = False
    resolver.clear()
    serve_images(resolver, inner, fail={})
    out = await controls.restart(imp.runtime, T, job.id)
    assert out.generation == job.generation + 1
    assert await imp.counts(job) == ("completed", 6, 6, 5, 0, 1)
    assert len(await imp.images()) == 5


async def test_restart_of_a_completed_upload_job_without_its_source_is_refused(imp):
    job = await imp.job([feature({"img": b64()})])
    await imp.run(job)
    with pytest.raises(Conflict):
        await controls.restart(imp.runtime, T, job.id)


async def test_delete_removes_the_job_its_items_and_its_staging(imp, monkeypatch):
    monkeypatch.setattr(runner, "CHUNK", 1)
    job = await imp.job([feature({"img": b64()}), feature({"img": b64("blue")})])
    staged = (await imp.reload(job)).source_key
    assert staged in imp.stored()
    await controls.delete_job(imp.runtime, T, job.id)
    async with imp.pipe.db_state.session_factory() as s:
        assert (await s.execute(select(ImportJob))).first() is None
        assert (await s.execute(select(ImportItem))).first() is None
    assert staged not in imp.stored()
    assert await imp.run(job) == "stale"  # a message still in flight does nothing


async def test_filename_pattern_groups(imp):
    pattern = r"^(?P<group>P\d+)_(?P<role>[a-z]+)"
    feats = [
        feature({"img": b64("red"), "id": "P1_north"}),
        feature({"img": b64("blue"), "id": "P1_point"}),
        feature({"img": b64("green"), "id": "P2_up"}),
        feature({"img": b64("white"), "id": "loose"}),
    ]
    job = await imp.job(feats, image_prop="img", external_id_prop="id", filename_pattern=pattern)
    assert await imp.run(job) == "completed"
    groups = await imp.groups()
    assert set(groups) == {"P1", "P2"}
    by_name = {i.filename: i for i in await imp.images()}
    assert (by_name["P1_north"].group_id, by_name["P1_north"].group_role) == (groups["P1"], "north")
    assert (by_name["P1_point"].group_id, by_name["P1_point"].group_role) == (groups["P1"], "point")
    assert (by_name["P2_up"].group_id, by_name["P2_up"].group_role) == (groups["P2"], None)
    assert by_name["loose"].group_id is None


async def test_property_groups_are_created_when_the_chunk_is_recorded(imp, monkeypatch):
    sent = []

    async def broker(runtime, tenant, job_id, ids):
        sent.append(ids)

    monkeypatch.setattr(launch, "launch_downloads", broker)
    feats = [feature({"url": f"https://{HOST}/a.jpg", "site": 7, "dir": "North"})]
    job = await imp.job(feats, URL, url_prop="url", group_key_prop="site", group_role_prop="dir")
    await imp.run(job)
    assert set(await imp.groups()) == {"7"}
    (item,) = await imp.items(job)
    assert (item.group_key, item.group_role) == ("7", "north")


async def test_capacity_wait_heartbeats_and_is_bounded(imp, monkeypatch):
    monkeypatch.setattr(runner, "CHUNK", 1)
    monkeypatch.setattr(runner, "CEILING", 1)
    waits, beats, counts = [], [], iter([5, 5, 0, 0, 0])

    async def fake_sleep(s):
        waits.append(s)

    async def pending(runtime, tenant, job_id):
        return next(counts, 0)

    real_beat = jobs.heartbeat

    async def beat(*a, **k):
        beats.append(1)
        return await real_beat(*a, **k)

    async def broker(runtime, tenant, job_id, ids):
        return None

    monkeypatch.setattr(runner, "_sleep", fake_sleep)
    monkeypatch.setattr(jobs, "pending_count", pending)
    monkeypatch.setattr(jobs, "heartbeat", beat)
    monkeypatch.setattr(launch, "launch_downloads", broker)
    broker_rt = dataclasses.replace(imp.runtime, eager=False)
    job = await imp.job([feature({"url": f"https://{HOST}/{i}.jpg"}) for i in range(2)], URL)
    out = await runner.import_geojson_async(broker_rt, T, job.id, job.generation)
    assert out == "running"
    assert len(waits) == 2 and len(beats) >= 2


async def test_reconcile_resumes_a_stale_job_in_its_tenant(imp, monkeypatch):
    from sm_images.reconcile import reconcile_async

    monkeypatch.setattr(runner, "CHUNK", 1)
    job = await imp.job([feature({"img": b64(c)}) for c in ("red", "blue")])
    await jobs.start(imp.runtime, T, job.id, job.generation)  # a runner took it, then died
    assert await reconcile_async(imp.runtime, datetime.now(UTC)) is not None
    assert (await imp.counts(job))[0] == "running"  # fresh heartbeat: left alone
    await _age(imp, job)
    summary = await reconcile_async(imp.runtime, datetime.now(UTC))
    assert summary["import_jobs"] == 1
    assert await imp.counts(job) == ("completed", 2, 2, 2, 0, 0)
    assert (await imp.reload(job)).generation == job.generation + 1


async def test_reconcile_redispatches_stale_pending_items(imp, resolver, inner, monkeypatch):
    from sm_images.reconcile import reconcile_async

    sent = []
    real = launch.launch_downloads

    async def lost(runtime, tenant, job_id, ids):
        sent.append(ids)  # the message never arrives

    monkeypatch.setattr(launch, "launch_downloads", lost)
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    assert await imp.run(job) == "running"
    monkeypatch.setattr(launch, "launch_downloads", real)
    await _age(imp, job)
    await jobs.touch(imp.runtime, T, job.id)  # the runner is fine; only the item is stale
    summary = await reconcile_async(imp.runtime, datetime.now(UTC))
    assert summary["import_items"] == 1
    assert len(seen) == 1
    assert await imp.counts(job) == ("completed", 1, 1, 1, 0, 0)


async def test_janitor_reaps_staging_a_terminal_job_left_behind(imp, monkeypatch):
    from sm_images.janitor import janitor_async

    async def broken(*a, **k):
        raise OSError("storage down")

    job = await imp.job([feature({"img": b64()})])
    monkeypatch.setattr(terminal, "_delete_objects", broken)
    await imp.run(job)
    monkeypatch.undo()
    left = (await imp.reload(job)).source_key
    assert left in imp.stored()
    await janitor_async(imp.runtime, datetime.now(UTC))
    assert left in imp.stored()  # within the grace period
    await janitor_async(imp.runtime, datetime.now(UTC) + timedelta(days=8))
    assert left not in imp.stored()
    assert (await imp.reload(job)).source_key is None


async def test_a_job_with_no_source_and_a_base64_kind(imp):
    """``B64`` with a URL mapping is refused at mapping time (sanity of ``imp.job``)."""
    from sm_images.imports.mapping import Mapping, MappingError

    with pytest.raises(MappingError):
        Mapping(url_prop="u").require(B64)
