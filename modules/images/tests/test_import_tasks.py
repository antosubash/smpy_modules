"""Broker mode: the import messages, their tenant header and queues, a broker
that refuses, a late duplicate download message, and the worker runtime binding."""

from __future__ import annotations

import dataclasses
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from background_tasks.tenant_context import TENANT_HEADER
from sm_images import task_config
from sm_images.errors import ServiceUnavailable
from sm_images.imports import download, launch, staging
from sm_images.imports import tasks as import_tasks
from sm_images.imports.service import start_import
from sm_images.tenancy import DEFAULT_TENANT

from tests.import_support import HOST, URL, feature, geojson, serve_images


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
    await launch.launch_downloads(broker, "acme", job_id, [1, 2, 3])
    ((args, kw),) = runner_msgs.calls
    assert args == (str(job_id), 3)
    assert kw == {"queue": task_config.QUEUE_IMPORTS, "headers": {TENANT_HEADER: "acme"}}
    assert [c[0][1] for c in download_msgs.calls] == [[1, 2], [3]]
    assert all(c[1]["headers"] == {TENANT_HEADER: "acme"} for c in download_msgs.calls)
    assert all(c[1]["queue"] == task_config.QUEUE_DEFAULT for c in download_msgs.calls)
    datetime.fromisoformat(download_msgs.calls[0][0][2])  # carries when it was sent


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


async def test_a_late_duplicate_download_message_does_not_fetch_again(
    imp, resolver, inner, monkeypatch
):
    sent: list[list[int]] = []

    async def record(runtime, tenant, job_id, ids):
        sent.append(list(ids))

    monkeypatch.setattr(launch, "launch_downloads", record)
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    await imp.run(job)
    # The item was handed out again after this message was sent: it is not this
    # message's to fetch any more.
    early = datetime.now(UTC) - timedelta(minutes=10)
    await download.download_items_async(imp.runtime, DEFAULT_TENANT, job.id, sent[0], early)
    assert seen == [] and await imp.statuses(job) == ["pending"]
    await download.download_items_async(
        imp.runtime, DEFAULT_TENANT, job.id, sent[0], datetime.now(UTC)
    )
    assert len(seen) == 1 and await imp.statuses(job) == ["done"]


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
    key, total = await staging.put_upload(
        imp.runtime, DEFAULT_TENANT, job_id, io.BytesIO(geojson([])), 5
    )
    assert key == f"images/{DEFAULT_TENANT}/imports/{job_id}/source.geojson" and total == 0
