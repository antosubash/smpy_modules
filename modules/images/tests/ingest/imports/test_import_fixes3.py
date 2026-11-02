"""Review round 3: a fenced deferral, a fenced completion, a bounded heartbeat."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.ingest.imports import beat, claims, download, jobs, launch, terminal

from tests.support.imports import HOST, URL, b64, feature, serve_images

T = DEFAULT_TENANT


# -- 1. a deferral from before a generation change writes nothing ---------------


async def test_a_deferral_after_the_generation_moved_writes_nothing(
    imp, resolver, inner, monkeypatch
):
    from sm_images.ingest.imports import retrying

    sent: list[tuple[int, list[int]]] = []

    async def record(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", record)
    serve_images(
        resolver, inner, fail={"/busy.jpg": httpx.Response(429, headers={"retry-after": "3600"})}
    )
    job = await imp.job([feature({"url": f"https://{HOST}/busy.jpg"})], URL)
    await imp.run(job)
    real = retrying._fetch

    async def reclaimed_meanwhile(*a, **k):
        await claims.claim_stale(imp.runtime, T, job.id)  # reconcile took the job over
        return await real(*a, **k)

    monkeypatch.setattr(retrying, "_fetch", reclaimed_meanwhile)
    generation, ids = sent[0]
    await download.download_items_async(imp.runtime, T, job.id, generation, ids)
    (item,) = await imp.items(job)
    assert (item.status.value, item.attempts, item.last_error) == ("pending", 0, None)


# -- 2. a stale caller cannot complete a newer generation -----------------------


async def test_a_stale_caller_cannot_complete_a_newer_generation(imp):
    job = await imp.job([feature({"img": b64()})])
    old = job.generation
    newer = await claims.claim_stale(imp.runtime, T, job.id)
    assert await imp.run(job, newer) == "completed"  # the newer run did the work ...
    # ... on a fresh, eligible job a stale caller is refused:
    job2 = await imp.job([])
    started = await jobs.start(imp.runtime, T, job2.id, job2.generation)
    assert started is not None
    bumped = await claims.claim_stale(imp.runtime, T, job2.id)
    assert bumped == job2.generation + 1
    assert await terminal.try_complete(imp.runtime, T, job2.id, old) is False
    assert (await imp.reload(job2)).status.value == "running"
    assert await terminal.try_complete(imp.runtime, T, job2.id, bumped) is True


# -- 3. the heartbeat is bounded and never cancelled mid-query at shutdown ------


@pytest.fixture
def blocked_beat(monkeypatch):
    state = {"started": asyncio.Event(), "release": asyncio.Event(), "cancelled": False}

    async def stuck(*a, **k):
        state["started"].set()
        try:
            await state["release"].wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        return True

    monkeypatch.setattr(jobs, "heartbeat", stuck)
    monkeypatch.setattr(beat, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(beat, "SHUTDOWN_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(beat, "BEAT_TIMEOUT_SECONDS", 30.0)
    return state


async def test_shutdown_is_bounded_and_leaves_an_in_flight_beat_running(blocked_beat):
    async def step():
        async with beat.beating(None, T, uuid.uuid4(), 0):
            await blocked_beat["started"].wait()

    await asyncio.wait_for(step(), timeout=2)  # returns although the beat is stuck
    assert blocked_beat["cancelled"] is False
    blocked_beat["release"].set()
    await asyncio.sleep(0.01)
    assert blocked_beat["cancelled"] is False


async def test_cancelling_the_step_during_shutdown_does_not_cancel_the_beat(blocked_beat):
    async def step():
        async with beat.beating(None, T, uuid.uuid4(), 0):
            await blocked_beat["started"].wait()

    task = asyncio.create_task(step())
    await blocked_beat["started"].wait()
    await asyncio.sleep(0.01)  # the step is now waiting for the beat at shutdown
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert blocked_beat["cancelled"] is False
    blocked_beat["release"].set()


async def test_a_beat_that_never_answers_is_bounded(blocked_beat, monkeypatch):
    monkeypatch.setattr(beat, "BEAT_TIMEOUT_SECONDS", 0.02)
    async with beat.beating(None, T, uuid.uuid4(), 0):
        await blocked_beat["started"].wait()
        await asyncio.sleep(0.1)  # the stuck beat times out; the loop goes on
    assert blocked_beat["cancelled"] is True  # bounded: the stuck query was given up
