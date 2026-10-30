"""Regroup as a resumable background job, the role-only PATCH race and the counts
a regroup reports (Task 21 fix round 1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import constants
from sm_images.models import Collection, Group, RegroupJob
from sm_images.module import ImagesModule
from sm_images.regroup import jobs
from sm_images.regroup.runner import run_regroup
from sm_images.services import regroup_write as write
from sqlalchemy import update

from tests.groups.test_groups import (
    OLGA,
    regroup,
    rows_by_name,
    seed,
)
from tests.support.access import share
from tests.support.stub_auth import as_user
from tests.support.upload import all_rows

NAMES = [f"s{i % 3}_{('point', 'north', 'east')[i % 3]}_{i}.jpg" for i in range(7)]


@pytest.fixture
def web_runtime(uploads):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)


@pytest.fixture
def big(monkeypatch, web_runtime):
    """Every collection is 'big' and a chunk is three images."""
    monkeypatch.setattr(constants, "REGROUP_SYNC_MAX", 3)
    monkeypatch.setattr(constants, "REGROUP_CHUNK", 3)


@pytest.fixture
def held(monkeypatch):
    """Creating a job does not run it (a lost message): tests drive the runner."""

    real = jobs.launch

    async def first_send_lost(runtime, tenant, job_id, generation):
        if generation > 0:  # reconcile's relaunch gets through
            await real(runtime, tenant, job_id, generation)

    monkeypatch.setattr(jobs, "launch", first_send_lost)


async def the_job(client) -> RegroupJob:
    (job,) = await all_rows(client, RegroupJob)
    return job


async def job_state(client, job_id):
    got = await client.get(f"/api/images/regroups/{job_id}", headers=OLGA)
    assert got.status_code == 200, got.text
    return got.json()


async def test_a_big_collection_regroups_as_a_job(uploads, big):
    cid, _ = await seed(uploads, NAMES)
    got = await regroup(uploads, cid)
    assert got.status_code == 202, got.text
    state = await job_state(uploads, got.json()["job_id"])
    assert state["status"] == "completed" and state["error_code"] is None
    assert (state["scanned"], state["matched"], state["assigned"]) == (7, 7, 7)
    assert (state["groups_created"], state["groups_existing"]) == (3, 0)
    names = await rows_by_name(uploads)
    assert names[NAMES[0]] == ("s0", "point") and names[NAMES[2]] == ("s2", "east")


async def test_a_small_collection_still_answers_inline(uploads):
    cid, _ = await seed(uploads, NAMES)
    got = await regroup(uploads, cid)
    assert got.status_code == 200 and got.json()["assigned"] == 7


async def test_a_big_preview_is_a_job_that_writes_nothing(uploads, big):
    cid, _ = await seed(uploads, NAMES)
    got = await regroup(uploads, cid, dry_run=True)
    state = await job_state(uploads, got.json()["job_id"])
    assert (state["status"], state["dry_run"], state["assigned"]) == ("completed", True, 7)
    assert await all_rows(uploads, Group) == []  # and a preview job does not count groups


async def test_one_unfinished_job_per_collection(uploads, big, held):
    cid, _ = await seed(uploads, NAMES)
    first = await regroup(uploads, cid)
    assert first.status_code == 202
    second = await regroup(uploads, cid)
    assert second.status_code == 409 and second.json()["code"] == "regroup_active"
    # a finished one frees the collection
    job = await the_job(uploads)
    await run_regroup(_rt(uploads), "default", job.id, job.generation)
    assert (await regroup(uploads, cid)).status_code == 202


def _rt(client):
    from sm_images.pipeline.runtime import current_runtime

    runtime = current_runtime()
    assert runtime is not None
    return runtime


async def test_a_runner_that_died_is_resumed_without_double_counting(
    uploads, big, held, monkeypatch
):
    cid, _ = await seed(uploads, NAMES)
    started = await regroup(uploads, cid)
    job_id = uuid.UUID(started.json()["job_id"])
    rt = _rt(uploads)
    real = write.apply_chunk
    calls = {"n": 0}

    async def dies_on_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("worker killed")
        return await real(*args, **kwargs)

    monkeypatch.setattr(write, "apply_chunk", dies_on_second)
    with pytest.raises(RuntimeError):
        await run_regroup(rt, "default", job_id, 0)
    mid = await job_state(uploads, job_id)
    assert (mid["status"], mid["scanned"], mid["assigned"]) == ("running", 3, 3)  # chunk 1 only
    monkeypatch.setattr(write, "apply_chunk", real)
    # reconcile's takeover: stale heartbeat -> new generation -> relaunch from the cursor
    from sm_images.jobs.reconcile import _regroups

    async with rt.session_factory() as db:
        await db.execute(
            update(RegroupJob).values(heartbeat_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await db.commit()
    assert await _regroups(rt, "default", datetime.now(UTC) - timedelta(minutes=5)) == 1
    done = await job_state(uploads, job_id)
    assert (done["status"], done["scanned"], done["assigned"]) == ("completed", 7, 7)
    assert all(g is not None for g, _ in (await rows_by_name(uploads)).values())


async def test_a_replaced_runner_writes_nothing(uploads, big, held):
    cid, _ = await seed(uploads, NAMES)
    job_id = uuid.UUID((await regroup(uploads, cid)).json()["job_id"])
    rt = _rt(uploads)
    async with rt.session_factory() as db:
        await db.execute(update(RegroupJob).values(generation=RegroupJob.generation + 1))
        await db.commit()
    assert await run_regroup(rt, "default", job_id, 0) == 0  # generation 0 is stale
    assert await all_rows(uploads, Group) == []
    assert (await the_job(uploads)).scanned == 0


async def test_a_chunk_whose_fence_was_lost_rolls_back(uploads, big, held, monkeypatch):
    """A runner that read the job at generation 0 while the database is already at
    1 (the claim landed meanwhile): its chunk's groups and assignments vanish."""
    cid, _ = await seed(uploads, NAMES)
    job_id = uuid.UUID((await regroup(uploads, cid)).json()["job_id"])
    rt = _rt(uploads)
    stale = await jobs.snapshot(rt, "default", job_id)
    async with rt.session_factory() as db:
        await db.execute(update(RegroupJob).values(generation=RegroupJob.generation + 1))
        await db.commit()

    async def old_view(*_a, **_k):
        return stale

    monkeypatch.setattr(jobs, "snapshot", old_view)
    from sm_images.regroup import runner

    assert await runner._chunk(rt, "default", stale, 0) is False
    assert await all_rows(uploads, Group) == []
    assert set((await rows_by_name(uploads)).values()) == {(None, None)}
    assert (await the_job(uploads)).scanned == 0


async def test_cancel_stops_the_job(uploads, big, held):
    cid, _ = await seed(uploads, NAMES)
    job_id = (await regroup(uploads, cid)).json()["job_id"]
    got = await uploads.post(f"/api/images/regroups/{job_id}/cancel", headers=OLGA)
    assert got.status_code == 200 and got.json()["status"] == "cancelled"
    job = await the_job(uploads)
    assert await run_regroup(_rt(uploads), "default", job.id, 0) == 0
    assert await all_rows(uploads, Group) == []


async def test_a_job_stops_when_its_editor_loses_the_right(uploads, big, held):
    cid, _ = await seed(uploads, NAMES)
    async with uploads.db_state.session_factory() as s:
        coll = await s.get(Collection, uuid.UUID(cid))
        grant = share(coll, "eddie", "edit")
        s.add(grant)
        await s.commit()
        grant_id = grant.id
    editor = as_user("eddie", ("images.view",))
    job_id = uuid.UUID((await regroup(uploads, cid, editor)).json()["job_id"])
    async with uploads.db_state.session_factory() as s:
        await s.delete(await s.get(type(grant), grant_id))
        await s.commit()
    await run_regroup(_rt(uploads), "default", job_id, 0)
    state = await job_state(uploads, job_id)
    assert (state["status"], state["error_code"]) == ("cancelled", "access_revoked")
    assert await all_rows(uploads, Group) == []


async def test_a_stalled_job_is_failed_not_relaunched_forever(uploads, big, held, monkeypatch):
    cid, _ = await seed(uploads, NAMES)
    job_id = (await regroup(uploads, cid)).json()["job_id"]
    rt = _rt(uploads)
    from sm_images.jobs.reconcile import _regroups
    from sm_images.regroup import runner

    async def dies_at_once(*_a, **_k):
        return 0

    monkeypatch.setattr(runner, "run_regroup", dies_at_once)
    for _ in range(constants.REGROUP_RELAUNCH_LIMIT + 1):
        async with rt.session_factory() as db:
            await db.execute(
                update(RegroupJob)
                .where(RegroupJob.finished_at.is_(None))
                .values(heartbeat_at=datetime.now(UTC) - timedelta(hours=1))
            )
            await db.commit()
        await _regroups(rt, "default", datetime.now(UTC) - timedelta(minutes=5))
    state = await job_state(uploads, job_id)
    assert state["status"] == "failed" and state["error_code"] == "stalled"


async def test_the_sync_deadline_is_checked_before_every_match(uploads, monkeypatch):
    seen = []
    from sm_images.imports import filename_pattern as fp

    real = fp.derive

    def slow(compiled, name, roles, *, budget=None):
        seen.append(budget)
        return real(compiled, name, roles, budget=budget)

    monkeypatch.setattr(fp, "derive", slow)
    cid, _ = await seed(uploads, NAMES)
    assert (await regroup(uploads, cid)).status_code == 200
    # every match got a remaining-time cap
    assert len(seen) == 7 and all(
        b is not None and 0 < b <= constants.REGROUP_BUDGET_SECONDS for b in seen
    )
