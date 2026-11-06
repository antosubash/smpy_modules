"""The fence (D3): a worker that lost its lease writes nothing, on both backends.

Two real sessions (a file database on SQLite): worker A pauses mid-step, its lease is expired,
worker B claims and finishes, A resumes; A must change nothing at all.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
import pytest_asyncio
from sm_newsletter.imports import runner, tags_step
from sm_newsletter.models import ImportJob
from sqlalchemy import update

from tests.imports.world import FIELDS, upload
from tests.support.app import build_app
from tests.support.import_world import (
    CLEAN,
    NOW,
    SUB,
    UNSUB,
    counts,
    export,
    job_row,
    people,
    queued,
    records_of,
    run,
    run_all,
    set_job,
    snapshot,
    staged_outcomes,
    suppression_rows,
)
from tests.support.records_seed import seed_list

pytestmark = pytest.mark.unbound_tenant

SENTINEL = "sentinel-7f3a"


@pytest_asyncio.fixture
async def state(tmp_path):
    _app, st = await build_app(file=tmp_path / "runner.db")
    await seed_list(st, "default", fields=FIELDS)
    yield st
    await st.engine.dispose()


async def test_busy_when_leased(state):
    jid = await export(state)
    await set_job(
        state, jid, status="running", lease_owner="x", lease_until=NOW + timedelta(minutes=1)
    )
    assert await run(state.session_factory, jid) == "busy"
    assert (await job_row(state, jid)).lease_owner == "x"
    await set_job(state, jid, lease_until=NOW - timedelta(seconds=1))
    assert await run(state.session_factory, jid) == "done"


async def test_lease_lost_rolls_back_batch(state, monkeypatch):
    jid = await export(state)
    real = runner.apply_batch

    async def stolen(session, **kw):
        result = await real(session, **kw)
        await session.execute(
            update(ImportJob).where(ImportJob.id == jid).values(lease_owner="thief")
        )
        return result

    monkeypatch.setattr(runner, "apply_batch", stolen)
    assert await run(state.session_factory, jid) == "busy"
    job = await job_row(state, jid)
    assert job.processed == 0 and job.status == "running"
    assert set(await staged_outcomes(state, jid)) == {None}
    assert await records_of(state) == {}
    assert await suppression_rows(state) == []


class _Pause:
    """The first call waits for ``resume`` after signalling ``paused``; later calls run through."""

    def __init__(self, fail: bool = False) -> None:
        self.paused, self.resume, self.calls, self.fail = asyncio.Event(), asyncio.Event(), 0, fail

    async def gate(self) -> None:
        self.calls += 1
        if self.calls == 1:
            self.paused.set()
            await self.resume.wait()
            if self.fail:
                raise RuntimeError(f"boom {SENTINEL}@example.org")


async def _race(state, jid, pause: _Pause) -> str:
    """Worker A pauses at ``pause``; its lease expires; B claims and finishes; A resumes."""
    task = asyncio.create_task(run(state.session_factory, jid))
    await asyncio.wait_for(pause.paused.wait(), 10)
    await set_job(state, jid, lease_until=NOW - timedelta(seconds=1))
    assert await run_all(state.session_factory, jid) == ["done"]
    before = await snapshot(state, jid)
    pause.resume.set()
    result = await asyncio.wait_for(task, 10)
    assert await snapshot(state, jid) == before
    job = await job_row(state, jid)
    assert job.status == "done" and job.error_code is None
    assert counts(job) == (3, 0, 0, 3, 0)
    return result


@pytest.mark.parametrize("fail", [False, True], ids=["batch", "failure-write"])
async def test_stale_worker_after_takeover_changes_nothing(state, monkeypatch, fail):
    pause = _Pause(fail=fail)
    real = runner.apply_batch

    async def gated(session, **kw):
        await pause.gate()
        return await real(session, **kw)

    monkeypatch.setattr(runner, "apply_batch", gated)
    jid = await export(state)
    assert await _race(state, jid, pause) == "busy"


async def test_stale_worker_in_tags_step_changes_nothing(state, monkeypatch):
    pause = _Pause()
    real = tags_step.list_fields

    async def gated(session, **kw):
        fields = await real(session, **kw)
        await pause.gate()
        return fields

    monkeypatch.setattr(tags_step, "list_fields", gated)
    jid = await queued(
        state,
        upload(SUB, people("s", 3, "Brand new")),
        upload(UNSUB, people("u", 2)),
        upload(CLEAN, people("c", 1)),
    )
    assert await _race(state, jid, pause) == "busy"
    job = await job_row(state, jid)
    assert job.tags_added is True
