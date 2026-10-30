"""Broker mode: the import messages, their tenant header and queues, a broker
that refuses, a late duplicate download message, and the worker runtime binding."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from background_tasks.tenant_context import TENANT_HEADER
from sm_images import task_config
from sm_images.core.errors import ServiceUnavailable
from sm_images.imports import download, launch, staging
from sm_images.imports import tasks as import_tasks
from sm_images.imports.service import start_import
from sm_images.tenancy import DEFAULT_TENANT

from tests.support.imports import HOST, URL, feature, geojson, serve_images


class Sent:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def s(self, *args):
        outer = self

        class Sig:
            def apply_async(self, **kw):
                outer.calls.append((args, kw))

        return Sig()


def test_import_tasks_are_registered_and_routed():
    from sm_images import tasks  # noqa: F401 - what background_tasks autodiscovers

    assert import_tasks.import_geojson.name == task_config.IMPORT_GEOJSON
    assert import_tasks.download_items.name == task_config.DOWNLOAD_ITEMS
    assert task_config.TASK_ROUTES[task_config.IMPORT_GEOJSON]["queue"] == task_config.QUEUE_IMPORTS
    assert task_config.TASK_ROUTES[task_config.DOWNLOAD_ITEMS]["queue"] == task_config.QUEUE_DEFAULT


async def test_broker_mode_sends_the_runner_and_batched_downloads_with_the_tenant(imp, monkeypatch):
    runner_msgs, download_msgs = Sent(), Sent()
    monkeypatch.setattr(import_tasks, "import_geojson", runner_msgs)
    monkeypatch.setattr(import_tasks, "download_items", download_msgs)
    monkeypatch.setattr(launch, "DOWNLOAD_BATCH", 2)
    broker = dataclasses.replace(imp.runtime, eager=False)
    job_id = uuid.uuid4()
    await launch.launch_runner(broker, "acme", job_id, 3)
    await launch.launch_downloads(broker, "acme", job_id, 3, [1, 2, 3])
    ((args, kw),) = runner_msgs.calls
    assert args == (str(job_id), 3)
    assert kw == {"queue": task_config.QUEUE_IMPORTS, "headers": {TENANT_HEADER: "acme"}}
    assert [c[0][1] for c in download_msgs.calls] == [[1, 2], [3]]
    assert all(c[1]["headers"] == {TENANT_HEADER: "acme"} for c in download_msgs.calls)
    assert all(c[1]["queue"] == task_config.QUEUE_DEFAULT for c in download_msgs.calls)
    assert {c[0][2] for c in download_msgs.calls} == {3}  # the generation they serve


async def test_a_broker_that_refuses_fails_the_job_and_deletes_its_staging(imp, monkeypatch):
    def refuse(*a, **k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(import_tasks.import_geojson, "apply_async", refuse)
    broker = dataclasses.replace(imp.runtime, eager=False)
    with pytest.raises(ServiceUnavailable):
        await start_import(
            broker,
            DEFAULT_TENANT,
            imp.coll,
            kind="geojson_base64",
            mapping='{"image_prop": "img"}',
            source_url=None,
            upload=io.BytesIO(geojson([])),
        )
    from sm_images.models import ImportJob
    from sqlalchemy import select

    async with imp.pipe.db_state.session_factory() as s:
        (job,) = (await s.execute(select(ImportJob))).scalars()
    assert (job.status.value, job.errors[0]["code"], job.source_key) == (
        "failed",
        "dispatch_failed",
        None,
    )
    assert not [k for k in imp.stored() if "/imports/" in k]


async def test_duplicate_download_messages_fetch_an_item_once(
    file_imp, resolver, inner, monkeypatch
):
    """Reconcile's re-send and the original both arrive: the claim lets one fetch."""
    from sm_images.imports import item_claim, retrying

    imp = file_imp  # two messages settle through sessions of their own
    sent: list[list[int]] = []

    async def record(runtime, tenant, job_id, generation, ids):
        sent.append(list(ids))

    monkeypatch.setattr(launch, "launch_downloads", record)
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    await imp.run(job)
    real_claim, real_fetch = item_claim.claim, retrying._fetch
    claims, both_tried = 0, asyncio.Event()

    async def counted(*a, **k):
        nonlocal claims
        try:
            return await real_claim(*a, **k)
        finally:
            claims += 1
            if claims == 2:
                both_tried.set()

    async def held_until_both_tried(*a, **k):
        # The winner's fetch outlasts the loser's claim attempt - by event, not by clock.
        await asyncio.wait_for(both_tried.wait(), timeout=30)
        return await real_fetch(*a, **k)

    monkeypatch.setattr(item_claim, "claim", counted)
    monkeypatch.setattr(retrying, "_fetch", held_until_both_tried)
    calls = [
        download.download_items_async(imp.runtime, DEFAULT_TENANT, job.id, job.generation, sent[0])
        for _ in range(2)
    ]
    assert sorted(await asyncio.gather(*calls)) == [0, 1]
    assert claims == 2 and len(seen) == 1 and await imp.statuses(job) == ["done"]


async def test_an_expired_claim_can_be_taken_over_and_the_old_holder_loses(
    imp, resolver, inner, monkeypatch
):
    from sm_images.models import ImportItem
    from sqlalchemy import update

    sent: list[list[int]] = []

    async def record(runtime, tenant, job_id, generation, ids):
        sent.append(list(ids))

    monkeypatch.setattr(launch, "launch_downloads", record)
    serve_images(resolver, inner)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    await imp.run(job)
    claimed = await download._claim(imp.runtime, DEFAULT_TENANT, job.id, job.generation, sent[0][0])
    assert claimed is not None
    assert (
        await download._claim(imp.runtime, DEFAULT_TENANT, job.id, job.generation, sent[0][0])
        is None
    )
    async with imp.pipe.db_state.session_factory() as s:
        old = datetime.now(UTC) - timedelta(seconds=1)
        await s.execute(update(ImportItem).values(claim_expires_at=old))
        await s.commit()
    assert (
        await download.download_items_async(
            imp.runtime, DEFAULT_TENANT, job.id, job.generation, sent[0]
        )
        == 1
    )
    from sm_images.imports import settle

    async with imp.pipe.db_state.session_factory() as s:  # the first holder settles too late
        assert not await settle.mark_item(
            s, DEFAULT_TENANT, sent[0][0], settle.ItemStatus.DONE, token=claimed[1]
        )
    assert await imp.statuses(job) == ["done"]


def test_run_task_binds_its_runtime_for_ingest_dispatch(monkeypatch):
    from sm_images.pipeline import worker_runtime as wr
    from sm_images.pipeline.runtime import Runtime, current_runtime

    fake = Runtime(session_factory=None, store=lambda: None, settings=lambda: None)
    monkeypatch.setattr(wr, "worker_runtime", lambda: fake)
    monkeypatch.setattr(wr, "task_tenant", lambda: DEFAULT_TENANT)

    async def body(runtime, tenant):
        return current_runtime()

    assert wr.run_task(body) is fake
    assert current_runtime() is None


async def test_staging_keeps_the_source_under_the_jobs_prefix(imp):
    job_id = uuid.uuid4()
    first, total = await staging.put_upload(
        imp.runtime, DEFAULT_TENANT, job_id, io.BytesIO(geojson([])), 5
    )
    again = await staging.put_spool(imp.runtime, DEFAULT_TENANT, job_id, io.BytesIO(b"{}"), 0)
    prefix = f"images/{DEFAULT_TENANT}/imports/{job_id}/source.0."
    assert first.startswith(prefix) and again.startswith(prefix) and total == 0
    assert first != again  # every staging attempt writes its own object
