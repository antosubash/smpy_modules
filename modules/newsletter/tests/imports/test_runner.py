"""The runner (R13-R15, D2, D6; Review Focus 4): claim, tags once, resumable batches, release
before ``more``, completion, sanitised failures. The lease races are in ``test_runner_races``."""

from __future__ import annotations

import json
import logging

import pytest
from sm_newsletter.core.errors_import import ImportFailed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports import apply, runner, tags_step
from sm_newsletter.imports.archive import sources
from sm_newsletter.imports.staging import stage

from tests.imports.world import FIELDS, upload
from tests.support.import_world import (
    CLEAN,
    NOW,
    SUB,
    UNSUB,
    counts,
    export,
    job_row,
    people,
    queue,
    queued,
    records_of,
    run,
    run_all,
    staged_count,
    staged_outcomes,
    suppression_rows,
)
from tests.support.records_seed import seed_list, seed_subscriber

pytestmark = pytest.mark.unbound_tenant

SENTINEL = "sentinel-7f3a"


async def test_run_to_done_deletes_staged_rows(state):
    jid = await export(state)
    assert await run(state.session_factory, jid) == "done"
    job = await job_row(state, jid)
    assert job.status == "done"
    assert job.finished_at is not None and job.started_at is not None
    assert (job.lease_owner, job.lease_until) == (None, None)
    assert await staged_count(state, jid) == 0
    assert job.processed == job.total == 6
    assert sum(counts(job)) == job.total
    assert counts(job) == (3, 0, 0, 3, 0)


async def test_slices_resume(state, monkeypatch):
    monkeypatch.setattr(runner, "BATCH_SIZE", 2)
    jid = await export(state)
    assert await run(state.session_factory, jid, slice_seconds=0) == "more"
    assert (await job_row(state, jid)).processed == 2
    assert sum(o is not None for o in await staged_outcomes(state, jid)) == 2
    seen = await run_all(state.session_factory, jid)
    assert seen == ["done"]
    assert (await job_row(state, jid)).processed == 6


async def test_consecutive_slices_with_fixed_clock(state, monkeypatch):
    monkeypatch.setattr(runner, "BATCH_SIZE", 2)
    jid = await export(state)
    seen = []
    for _ in range(10):
        seen.append(await run(state.session_factory, jid, slice_seconds=0))
        job = await job_row(state, jid)
        if seen[-1] == "done":
            break
        assert seen[-1] == "more"
        assert job.lease_owner is None and job.lease_until == NOW
        assert job.status == "running"
    assert seen == ["more", "more", "more", "done"]
    assert counts(await job_row(state, jid)) == (3, 0, 0, 3, 0)


async def test_crash_mid_batch_resumes_without_duplicates(state, monkeypatch):
    monkeypatch.setattr(runner, "BATCH_SIZE", 2)
    calls = {"n": 0}
    real = apply.suppress_many

    async def flaky(session, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("worker died")
        return await real(session, **kw)

    monkeypatch.setattr(apply, "suppress_many", flaky)
    jid = await queued(state, upload(UNSUB, people("u", 3)), upload(SUB, people("s", 3)))
    with pytest.raises(ImportFailed):
        await run_all(state.session_factory, jid)
    job = await job_row(state, jid)
    assert (job.status, job.error_code, job.processed) == ("failed", "import_failed", 2)
    assert sum(o is not None for o in await staged_outcomes(state, jid)) == 2
    assert len(await records_of(state)) == 2  # the failed batch left nothing
    await queue(state, jid)
    assert await run_all(state.session_factory, jid) == ["done"]
    job = await job_row(state, jid)
    assert job.processed == job.total == 6 and sum(counts(job)) == 6
    records = await records_of(state)
    assert len(records) == 6
    assert len(await suppression_rows(state)) == 3


async def test_rerun_same_export_changes_nothing(state):
    files = lambda: (  # noqa: E731 - fresh streams each time
        upload(SUB, people("s", 3, "VIP")),
        upload(UNSUB, people("u", 2)),
        upload(CLEAN, people("c", 1)),
    )
    first = await queued(state, *files())
    assert await run_all(state.session_factory, first) == ["done"]
    records = {e: (r.uuid, r.version, dict(r.data)) for e, r in (await records_of(state)).items()}
    rows = await suppression_rows(state)
    second = await queued(state, *files())
    assert await run_all(state.session_factory, second) == ["done"]
    job = await job_row(state, second)
    assert (job.created, job.updated) == (0, 0)
    assert sum(counts(job)) == job.total == 6
    after = {e: (r.uuid, r.version, dict(r.data)) for e, r in (await records_of(state)).items()}
    assert after == records
    assert await suppression_rows(state) == rows


async def test_failure_is_sanitised(state, monkeypatch, caplog):
    async def boom(*_a, **_kw):
        raise RuntimeError(f"boom {SENTINEL}@example.org")

    monkeypatch.setattr(apply, "import_subscribers", boom)
    jid = await export(state)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ImportFailed) as caught:
        await run(state.session_factory, jid)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert SENTINEL not in caplog.text
    assert str(jid) in caplog.text and "RuntimeError" in caplog.text
    job = await job_row(state, jid)
    assert (job.status, job.error_code, job.lease_owner) == ("failed", "import_failed", None)
    assert SENTINEL not in json.dumps(job.model_dump(mode="json"))


async def test_tags_added_once_and_unavailable_turns_tags_off(state, monkeypatch):
    monkeypatch.setattr(runner, "BATCH_SIZE", 1)
    calls = []
    real = tags_step.add_tag_choices

    async def counted(session, **kw):
        calls.append(list(kw["labels"]))
        return await real(session, **kw)

    monkeypatch.setattr(tags_step, "add_tag_choices", counted)
    jid = await queued(state, upload(SUB, people("s", 3, "Brand new")))
    assert await run_all(state.session_factory, jid, slice_seconds=0) == ["more"] * 3 + ["done"]
    assert calls == [["Brand new"]]
    job = await job_row(state, jid)
    assert job.tags_added is True
    assert {r.data["tags"][0] for r in (await records_of(state)).values()} == {"Brand new"}

    # A list with no tags field gains a record after staging: tags are off for that import.
    await seed_list(state, "default", "bare", fields=FIELDS[:2])
    with tenant_scope("default"):
        async with state.session_factory() as s:
            job = await stage(
                s,
                tenant_id="default",
                list_type_key="bare",
                sources=sources([upload(SUB, people("b", 2, "VIP"))]),
                created_by="u",
                now=NOW,
            )
            await s.commit()
            bare = job.id
    assert (await job_row(state, bare)).mapping["tags"] is True
    await seed_subscriber(state, "default", "early@example.org", "confirmed", "bare")
    await queue(state, bare)
    calls.clear()
    assert await run_all(state.session_factory, bare) == ["done"]
    job = await job_row(state, bare)
    assert job.mapping["tags"] is False and job.tags_added is False
    assert job.errors == [{"file": None, "line": None, "code": "tags_unavailable", "field": "tags"}]
    assert job.created == 2
    bare_records = await records_of(state, key="bare")
    assert all(not r.data.get("tags") for r in bare_records.values())


async def test_runner_pins_the_tenant(state):
    jid = await export(state)
    before = (await job_row(state, jid)).model_dump()
    assert await run(state.session_factory, jid, tenant="other") == "gone"
    assert (await job_row(state, jid)).model_dump() == before
