"""The fence (D3): a worker that lost its lease writes nothing, on both backends.

Two real sessions (a file database on SQLite): worker A pauses mid-step, its lease is expired,
worker B claims and finishes, A resumes; A must change nothing at all.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sm_newsletter.imports import runner
from sm_newsletter.models import ImportJob
from sqlalchemy import update

from tests.imports.world import upload
from tests.pg_support import USING_POSTGRES
from tests.support.import_world import (
    CLEAN,
    NOW,
    SETTINGS,
    SUB,
    UNSUB,
    counts,
    export,
    job_row,
    list_shape,
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

pytestmark = pytest.mark.unbound_tenant

SENTINEL = "sentinel-7f3a"


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

    async def gate(self) -> bool:
        """Whether this was the paused call."""
        self.calls += 1
        if self.calls != 1:
            return False
        self.paused.set()
        await self.resume.wait()
        if self.fail:
            raise RuntimeError(f"boom {SENTINEL}@example.org")
        return True


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
    """A's tags step, resumed after B finished, adds a choice B never added ("A only"): the
    fence must roll that records write back, which ``list_shape`` in the snapshot would show."""
    from sm_records.public_submissions import campaign_lists

    pause = _Pause()
    real = campaign_lists.add_choices

    async def gated(db, rtype, labels, **kw):
        if await pause.gate():
            labels = [*labels, "A only"]
        return await real(db, rtype, labels, **kw)

    monkeypatch.setattr(campaign_lists, "add_choices", gated)
    jid = await queued(
        state,
        upload(SUB, people("s", 3, "Brand new")),
        upload(UNSUB, people("u", 2)),
        upload(CLEAN, people("c", 1)),
    )
    assert await _race(state, jid, pause) == "busy"
    job = await job_row(state, jid)
    assert job.tags_added is True
    assert {t["value"] for t in job.tags_found} == {"Brand new"}  # B's, not A's
    assert "A only" not in dict((await list_shape(state))[1])


async def test_tag_choice_added_concurrently_is_not_misattributed(state, monkeypatch):
    """Between the tags step deciding "Gold" -> ``Gold`` and appending it, another writer adds
    the value ``Gold`` under the label "Gold members". The step must resolve against the
    choices as they are under records' type lock, so this import's subscribers carry a value
    whose label is "Gold", never the other writer's choice."""
    from sm_records.core import events
    from sm_records.core.tenancy import tenant_scope as records_scope
    from sm_records.public_submissions import campaign_lists
    from sm_records.records.services import types as type_service

    real = campaign_lists.add_choices

    async def add_gold(db) -> None:
        listed = await type_service.get_type(db, "news")
        fields = [dict(f) for f in listed.fields]
        tags = next(f for f in fields if f["key"] == "tags")
        choices = [*tags["options"]["choices"], {"value": "Gold", "label": "Gold members"}]
        tags["options"] = {**tags["options"], "choices": choices}
        await type_service.update_type(
            db, listed, fields_raw=fields, expected_version=listed.version, settings=SETTINGS
        )

    async def concurrent(db, rtype, *args, **kw):
        if USING_POSTGRES:  # a second transaction, committed before the append
            with records_scope("default"):
                async with state.session_factory() as other:
                    await add_gold(other)
                    await events.commit(other)
        else:  # SQLite's one writer: the same change, in the step's own transaction
            await add_gold(db)
        return await real(db, rtype, *args, **kw)

    monkeypatch.setattr(campaign_lists, "add_choices", concurrent)
    jid = await queued(state, upload(SUB, people("s", 2, "Gold")))
    assert await run_all(state.session_factory, jid) == ["done"]
    labels = dict((await list_shape(state))[1])
    assert labels["Gold"] == "Gold members"  # the other writer's choice, untouched
    values = {t["label"]: t["value"] for t in (await job_row(state, jid)).tags_found}
    assert values["Gold"] != "Gold" and labels[values["Gold"]] == "Gold"
    assert {tuple(r.data["tags"]) for r in (await records_of(state)).values()} == {
        (values["Gold"],)
    }
