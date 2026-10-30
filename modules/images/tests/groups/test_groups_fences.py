"""Regroup job fences, round 2: a cancel names its generation, group counts are
per job rather than per chunk, and a trashed collection stops its jobs."""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sm_images.models import Collection, Group, RegroupJob
from sm_images.regroup import jobs, runner
from sm_images.regroup.runner import run_regroup
from sm_images.services import regroup_write as write
from sqlalchemy import update

from tests.groups.test_groups import OLGA, regroup, rows_by_name, seed
from tests.groups.test_groups_jobs import (  # noqa: F401 - fixtures
    NAMES,
    _rt,
    big,
    held,
    job_state,
    the_job,
    web_runtime,
)
from tests.support.upload import BASE, all_rows


@pytest.mark.usefixtures("big", "held")
async def test_a_replaced_worker_cannot_cancel_its_successor(uploads, monkeypatch):
    """The access check says no, but the claim has moved the job on meanwhile."""
    cid, _ = await seed(uploads, NAMES)
    job_id = uuid.UUID((await regroup(uploads, cid)).json()["job_id"])
    rt = _rt(uploads)

    async def revoked_while_replaced(runtime, tenant, snap):
        async with runtime.session_factory() as db:
            await db.execute(update(RegroupJob).values(generation=RegroupJob.generation + 1))
            await db.commit()
        return False

    monkeypatch.setattr(runner, "may_edit", revoked_while_replaced)
    assert await run_regroup(rt, "default", job_id, 0) == 0
    job = await the_job(uploads)
    assert (job.status, job.error_code, job.finished_at) == ("running", None, None)
    # and a cancel that names a stale generation does nothing by itself
    assert await jobs.cancel(rt, "default", job_id, generation=0) is False
    assert await jobs.cancel(rt, "default", job_id, generation=job.generation) is True


@pytest.mark.usefixtures("big", "held")
async def test_a_group_spanning_chunks_is_counted_once(uploads):
    cid, _ = await seed(uploads, NAMES)  # seven images in s0, s1, s2; chunks of three
    async with uploads.db_state.session_factory() as s:
        s.add_all([Group(collection_id=uuid.UUID(cid), key=k) for k in ("s0", "s1")])
        await s.commit()
    job_id = (await regroup(uploads, cid)).json()["job_id"]
    job = await the_job(uploads)
    await run_regroup(_rt(uploads), "default", job.id, job.generation)
    state = await job_state(uploads, job_id)
    assert state["status"] == "completed"
    assert (state["groups_created"], state["groups_existing"]) == (1, 2)
    assert {v[0] for v in (await rows_by_name(uploads)).values()} == {"s0", "s1", "s2"}


@pytest.mark.usefixtures("big", "held")
async def test_a_resumed_job_does_not_recount_its_groups(uploads, monkeypatch):
    cid, _ = await seed(uploads, NAMES)
    async with uploads.db_state.session_factory() as s:
        s.add(Group(collection_id=uuid.UUID(cid), key="s0"))
        await s.commit()
    job_id = uuid.UUID((await regroup(uploads, cid)).json()["job_id"])
    rt = _rt(uploads)
    real = write.apply_chunk
    calls = {"n": 0}

    async def dies_on_third(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("killed")
        return await real(*args, **kwargs)

    monkeypatch.setattr(write, "apply_chunk", dies_on_third)
    with contextlib.suppress(RuntimeError):
        await run_regroup(rt, "default", job_id, 0)
    monkeypatch.setattr(write, "apply_chunk", real)
    await run_regroup(rt, "default", job_id, 0)
    state = await job_state(uploads, job_id)
    assert (state["status"], state["groups_created"], state["groups_existing"]) == (
        "completed",
        2,
        1,
    )


@pytest.mark.usefixtures("big", "held")
async def test_deleting_the_collection_cancels_its_regroup(uploads):
    cid, _ = await seed(uploads, NAMES)
    job_id = (await regroup(uploads, cid)).json()["job_id"]
    before = await the_job(uploads)
    assert (await uploads.delete(f"{BASE}/{cid}", headers=OLGA)).status_code == 204
    after = await the_job(uploads)
    assert (after.status, after.generation, after.finished_at is not None) == (
        "cancelled",
        before.generation + 1,
        True,
    )
    assert await run_regroup(_rt(uploads), "default", uuid.UUID(job_id), before.generation) == 0
    assert await all_rows(uploads, Group) == []


@pytest.mark.usefixtures("big", "held")
async def test_a_chunk_cannot_commit_into_a_trashed_collection(uploads, monkeypatch):
    """The collection is trashed during the chunk (no cancel ran): the fence says no."""
    cid, _ = await seed(uploads, NAMES)
    job_id = uuid.UUID((await regroup(uploads, cid)).json()["job_id"])
    real = write.settle

    async def trash_then_settle(db, *args, **kwargs):
        done = await real(db, *args, **kwargs)
        await db.execute(
            update(Collection)
            .where(Collection.id == uuid.UUID(cid))
            .values(is_deleted=True)
            .execution_options(include_deleted=True)
        )
        return done

    monkeypatch.setattr(write, "settle", trash_then_settle)
    assert await run_regroup(_rt(uploads), "default", job_id, 0) == 0
    job = await the_job(uploads)
    assert (job.scanned, job.status) == (0, "running")
    assert await all_rows(uploads, Group) == []
    assert set((await rows_by_name(uploads)).values()) == {(None, None)}
