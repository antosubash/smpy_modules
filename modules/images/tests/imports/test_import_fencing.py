"""Review round 1: fencing and resumability (items 1-5 of the fix brief)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images.errors import Conflict
from sm_images.imports import (
    claims,
    controls,
    jobs,
    launch,
    reset,
    retrying,
    settle,
    staging,
    terminal,
)
from sm_images.imports.mapping import Mapping
from sm_images.models import ImportItem, ImportJob, ObjectIntent
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.support.fetch import PUBLIC_IP, body
from tests.support.imports import HOST, URL, b64, feature, geojson, serve_images

T = DEFAULT_TENANT


class Killed(BaseException):
    pass


@pytest.fixture
def broker(monkeypatch):
    sent: list[tuple[int, list[int]]] = []

    async def fake(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", fake)
    return sent


async def _age(imp, job) -> None:
    old = datetime.now(UTC) - timedelta(minutes=30)
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(update(ImportJob).where(ImportJob.id == job.id).values(heartbeat_at=old))
        await s.commit()


def _originals(imp) -> list[str]:
    return [k for k in imp.stored() if "/original." in k]


# -- 1. settlement is fenced on the job's generation and status ---------------


async def test_a_download_settling_after_a_pause_rolls_back(
    imp, resolver, inner, broker, monkeypatch
):
    serve_images(resolver, inner)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    assert await imp.run(job) == "running"
    real = retrying._fetch

    async def pause_meanwhile(*a, **k):
        data = await real(*a, **k)
        await controls.pause(imp.runtime, T, job.id)
        return data

    monkeypatch.setattr(retrying, "_fetch", pause_meanwhile)
    generation, ids = broker[0]
    from sm_images.imports import download

    await download.download_items_async(imp.runtime, T, job.id, generation, ids)
    assert await imp.images() == []
    assert await imp.statuses(job) == ["pending"]
    assert (await imp.counts(job))[3:] == (0, 0, 0)
    assert _originals(imp) == []  # its object went with the rolled-back row


async def test_a_base64_settlement_after_the_generation_moved_rolls_back(imp, monkeypatch):
    job = await imp.job([feature({"img": b64()})])
    real = settle.pending_items

    async def restart_meanwhile(*a, **k):
        rows = await real(*a, **k)
        await claims.claim_stale(imp.runtime, T, job.id)  # reconcile took the job over
        return rows

    monkeypatch.setattr(settle, "pending_items", restart_meanwhile)
    await imp.run(job)
    assert await imp.images() == [] and _originals(imp) == []
    assert await imp.statuses(job) == ["pending"]


# -- 2./3. resets are resumable and fenced --------------------------------------


_real_batch = reset.reset_batch


def _kill_batches_after(monkeypatch, n: int) -> None:
    real, calls = reset.reset_batch, {"n": 0}

    async def wrapper(*a, **k):
        calls["n"] += 1
        if calls["n"] > n:
            raise Killed()
        return await real(*a, **k)

    monkeypatch.setattr(reset, "reset_batch", wrapper)


async def test_a_restart_killed_mid_reset_is_resumed_by_reconcile(imp, monkeypatch):
    from sm_images.jobs.reconcile import reconcile_async

    monkeypatch.setattr(reset, "RESET_CHUNK", 1)
    job = await imp.job([feature({"img": c}) for c in ("!!", "??", b64())])
    await imp.run(job)
    _kill_batches_after(monkeypatch, 1)
    with pytest.raises(Killed):
        await controls.restart(imp.runtime, T, job.id)
    assert (await imp.reload(job)).status.value == "resetting"
    monkeypatch.setattr(reset, "reset_batch", _real_batch)
    await _age(imp, job)
    summary = await reconcile_async(imp.runtime, datetime.now(UTC))
    assert summary["import_jobs"] == 1
    assert await imp.counts(job) == ("completed", 3, 3, 1, 0, 2)
    assert len(await imp.images()) == 1  # the done item was kept, not re-ingested


async def test_an_older_restart_never_deletes_a_newer_ones_work(imp):
    job = await imp.job([feature({"img": "!!"}), feature({"img": b64()})])
    await imp.run(job)
    first = await controls.restart(imp.runtime, T, job.id, launch=False)
    second = await controls.restart(imp.runtime, T, job.id, launch=False)
    assert second.generation == first.generation + 1
    before = [i.id for i in await imp.items(job)]
    assert await reset.run_reset(imp.runtime, T, job.id, first.generation) == "stopped"
    assert [i.id for i in await imp.items(job)] == before
    assert await reset.run_reset(imp.runtime, T, job.id, second.generation) == "reset"
    assert await imp.counts(job) == ("completed", 2, 2, 1, 0, 1)


async def test_a_retry_killed_mid_reset_is_resumed(imp, resolver, inner, monkeypatch):
    import httpx
    from sm_images.jobs.reconcile import reconcile_async

    monkeypatch.setattr(reset, "RESET_CHUNK", 1)
    state = {"down": True}
    serve_images(
        resolver,
        inner,
        fail={
            f"/{i}.jpg": (lambda r: httpx.Response(404) if state["down"] else body_jpeg())
            for i in range(3)
        },
    )
    job = await imp.job([feature({"url": f"https://{HOST}/{i}.jpg"}) for i in range(3)], URL)
    await imp.run(job)
    assert await imp.counts(job) == ("completed", 3, 3, 0, 0, 3)
    state["down"] = False
    _kill_batches_after(monkeypatch, 1)
    with pytest.raises(Killed):
        await controls.retry_failed(imp.runtime, T, job.id)
    row = await imp.reload(job)
    assert (row.status.value, row.reset_mode) == ("resetting", "retry")
    monkeypatch.setattr(reset, "reset_batch", _real_batch)
    await _age(imp, job)
    await reconcile_async(imp.runtime, datetime.now(UTC))
    assert await imp.counts(job) == ("completed", 3, 3, 3, 0, 0)


def body_jpeg():
    from tests.support.pipeline import jpeg

    return body(jpeg())


# -- 4. every staging attempt writes its own key --------------------------------


async def test_a_staging_race_never_shares_or_overwrites_a_key(imp, resolver, inner, monkeypatch):
    from sm_images.jobs.janitor import janitor_async

    resolver["src.example"] = [PUBLIC_IP]
    serve_images(resolver, inner, fail={"/p.geojson": lambda r: body(geojson([]))})
    job = await jobs.create_job(
        imp.runtime,
        T,
        imp.coll.id,
        kind=URL,
        mapping=Mapping(url_prop="url"),
        source_url="https://src.example/p.geojson",
    )
    real = staging.put_spool
    loser: list[str] = []

    async def overtaken(*a, **k):
        key = await real(*a, **k)
        loser.append(key)
        await claims.claim_stale(imp.runtime, T, job.id)  # another runner took over
        return key

    monkeypatch.setattr(staging, "put_spool", overtaken)
    assert await imp.run(job) == "stopped"
    monkeypatch.setattr(staging, "put_spool", real)
    assert await imp.run(job, job.generation + 1) == "completed"
    assert loser[0] in imp.stored()  # untouched, never attached
    async with imp.pipe.db_state.session_factory() as s:
        intents = set((await s.execute(select(ObjectIntent.key))).scalars())
    assert loser[0] in intents
    await janitor_async(imp.runtime, datetime.now(UTC) + timedelta(days=8))
    assert loser[0] not in imp.stored()


# -- 5. clean-up detaches before it deletes --------------------------------------


async def test_cleanup_loses_to_a_job_reopened_meanwhile(imp, monkeypatch):
    """Clean-up read a terminal job, then a retry reopened it: nothing is deleted."""
    import contextlib

    job = await imp.job([feature({"img": "!!"}), feature({"img": b64()})])
    await imp.run(job)
    kept = (await imp.reload(job)).source_key
    assert kept in imp.stored()  # finished with a failure: kept for retry-failed
    real = terminal.object_intent

    @contextlib.asynccontextmanager
    async def reopened_meanwhile(keys, **kw):
        async with real(keys, **kw):
            await controls.retry_failed(imp.runtime, T, job.id, launch=False)
            yield

    monkeypatch.setattr(terminal, "object_intent", reopened_meanwhile)
    generation = (await imp.reload(job)).generation
    past_grace = datetime.now(UTC) + timedelta(days=1)  # the janitor's sweep: eligible
    released = await terminal.release_staging(
        imp.runtime, T, job.id, generation, grace_cutoff=past_grace
    )
    assert released is False
    assert (await imp.reload(job)).source_key == kept and kept in imp.stored()


async def test_a_terminal_job_detached_by_cleanup_cannot_be_restarted_onto_it(imp, monkeypatch):
    """The restart read the source, then clean-up detached it: the restart loses."""
    job = await imp.job([feature({"img": "!!"})])
    await imp.run(job)
    row = await controls.get(imp.runtime, T, job.id)
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(update(ImportJob).where(ImportJob.id == job.id).values(source_key=None))
        await s.commit()

    async def stale_get(*a, **k):
        return row

    monkeypatch.setattr(controls, "get", stale_get)
    with pytest.raises(Conflict):
        await controls.restart(imp.runtime, T, job.id, launch=False)
    async with imp.pipe.db_state.session_factory() as s:
        items = list((await s.execute(select(ImportItem))).scalars())
    assert len(items) == 1
