"""Phase 4 review fixes (P1): a nested base64 property is never kept, the
poison-job breaker counts only relaunches a worker started, and a job stops
once the principal it runs as loses edit on the collection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sharing.models import ResourceShare
from sm_images.access import starter_right
from sm_images.imports import access, features, launch, recover, runner, settle
from sm_images.imports.mapping import Mapping
from sm_images.models import ImportJob
from sm_images.models.enums import ImportKind, JobStatus
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import delete, update

from tests.support.access import share
from tests.support.imports import b64, feature
from tests.support.stub_auth import user_uuid

pytestmark = pytest.mark.asyncio
T = DEFAULT_TENANT


# --- 1. the image property never survives into properties ---------------------


def _props(image_prop: str, props: dict) -> dict | None:
    got = features.extract(
        {"type": "Feature", "properties": props, "geometry": None},
        0,
        kind=ImportKind.GEOJSON_BASE64,
        mapping=Mapping(image_prop=image_prop),
        job_id=uuid.uuid4(),
    )
    assert got.error is None and got.payload
    return got.properties


async def test_a_nested_image_property_is_dropped_from_properties():
    props = {"media": {"data": b64(), "caption": "hi"}, "site": 7}
    assert _props("media.data", props) == {"media": {"caption": "hi"}, "site": 7}
    assert props["media"]["data"]  # the feature itself is not mutated


async def test_the_exact_key_wins_and_both_spellings_are_dropped():
    props = {"media.data": b64(), "media": {"data": b64("blue"), "x": 1}}
    assert _props("media.data", props) == {"media": {"x": 1}}


async def test_an_emptied_parent_is_dropped_too():
    assert _props("a.b.c", {"a": {"b": {"c": b64()}}, "k": 1}) == {"k": 1}


async def test_imported_images_never_carry_the_nested_payload(imp):
    payload = b64()
    feats = [feature({"media": {"data": payload, "caption": "c"}, "n": 1})]
    job = await imp.job(feats, image_prop="media.data")
    assert await imp.run(job) == "completed"
    (image,) = await imp.images()
    assert image.properties == {"media": {"caption": "c"}, "n": 1}
    (item,) = await imp.items(job)
    assert payload not in repr(item.properties)


# --- 2. the breaker counts only relaunches a worker started ------------------


async def _stale(imp, job) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        old = datetime.now(UTC) - timedelta(hours=1)
        await s.execute(update(ImportJob).where(ImportJob.id == job.id).values(heartbeat_at=old))
        await s.commit()


async def _reconcile(imp) -> None:
    await recover.recover_imports(imp.runtime, T, datetime.now(UTC) - timedelta(minutes=30))


async def test_queued_but_never_started_relaunches_do_not_trip_the_breaker(imp, monkeypatch):
    launched: list[int] = []

    async def backlog(runtime, tenant, job_id, generation):
        launched.append(generation)  # the message sits in the queue, never run

    monkeypatch.setattr(launch, "launch_runner", backlog)
    job = await imp.job([feature({"img": b64()})])
    for _ in range(recover.RELAUNCH_LIMIT + 1):
        await _stale(imp, job)
        await _reconcile(imp)
    row = await imp.reload(job)
    assert row.status is JobStatus.PENDING and row.errors == []
    assert len(launched) == recover.RELAUNCH_LIMIT + 1
    assert row.started_generation is None


async def test_a_start_is_stamped_with_its_generation(imp):
    job = await imp.job([feature({"img": b64()})])
    assert await imp.run(job) == "completed"
    row = await imp.reload(job)
    assert row.started_generation == job.generation and row.started_at is not None


# --- 3. a revoked right stops the job ------------------------------------------


async def _run_as(imp, job, who: str | None, basis: str | None) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        stmt = update(ImportJob).where(ImportJob.id == job.id)
        await s.execute(stmt.values(run_as=who, access_basis=basis))
        await s.commit()


async def _share(imp, who: str) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        s.add(share(imp.coll, who, "edit"))
        await s.commit()


async def _unshare(imp) -> None:
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(delete(ResourceShare))
        await s.commit()


def _three() -> list[dict]:
    return [feature({"img": b64(c)}) for c in ("red", "blue", "green")]


async def test_a_share_revoked_mid_import_cancels_the_job(imp, monkeypatch):
    monkeypatch.setattr(runner, "CHUNK", 1)
    await _share(imp, "eddie")
    job = await imp.job(_three())
    await _run_as(imp, job, user_uuid("eddie"), access.SHARE)
    real = settle.ingest_item

    async def revoke_after_first(*a, **k):
        out = await real(*a, **k)
        await _unshare(imp)
        return out

    monkeypatch.setattr(settle, "ingest_item", revoke_after_first)
    assert await imp.run(job) == "stopped"
    row = await imp.reload(job)
    assert row.status is JobStatus.CANCELLED
    assert [e["code"] for e in row.errors] == [access.ACCESS_REVOKED]
    assert row.generation == job.generation + 1  # fenced: anything in flight loses
    assert len(await imp.images()) == 1


async def test_a_revoked_right_is_refused_at_runner_start(imp):
    job = await imp.job(_three())
    await _run_as(imp, job, user_uuid("eddie"), access.SHARE)  # no share at all
    assert await imp.run(job) == "cancelled"
    row = await imp.reload(job)
    assert (row.status, row.errors[-1]["code"]) == (JobStatus.CANCELLED, access.ACCESS_REVOKED)
    assert await imp.images() == []


async def test_the_owner_and_a_live_share_keep_running(imp):
    job = await imp.job(_three())
    await _run_as(imp, job, "olga", access.OWNER)
    assert await imp.run(job) == "completed"
    await _share(imp, "eddie")
    job2 = await imp.job([feature({"img": b64("white")})])
    await _run_as(imp, job2, user_uuid("eddie"), access.SHARE)
    assert await imp.run(job2) == "completed"


async def test_a_manager_who_leaves_mid_run_is_stopped(imp, monkeypatch):
    held = {"v": True}

    async def active(runtime, tenant, user_id):
        return held["v"]

    monkeypatch.setattr(starter_right, "manager_active", active)  # the shared re-check
    job = await imp.job(_three())
    await _run_as(imp, job, user_uuid("max"), access.MANAGE)
    monkeypatch.setattr(runner, "CHUNK", 1)
    real = settle.ingest_item

    async def lose_after_first(*a, **k):
        out = await real(*a, **k)
        held["v"] = False
        return out

    monkeypatch.setattr(settle, "ingest_item", lose_after_first)
    assert await imp.run(job) == "stopped"
    assert (await imp.reload(job)).status is JobStatus.CANCELLED
    assert len(await imp.images()) == 1


async def test_a_download_batch_checks_the_right_first(imp, monkeypatch):
    from sm_images.imports import download

    job = await imp.job([feature({"url": "https://img.example/a.jpg"})], ImportKind.GEOJSON_URL)
    sent: list = []

    async def broker(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", broker)
    assert await imp.run(job) == "running"
    await _run_as(imp, job, user_uuid("eddie"), access.SHARE)
    ((generation, ids),) = sent
    assert await download.download_items_async(imp.runtime, T, job.id, generation, ids) == 0
    row = await imp.reload(job)
    assert (row.status, row.errors[-1]["code"]) == (JobStatus.CANCELLED, access.ACCESS_REVOKED)
