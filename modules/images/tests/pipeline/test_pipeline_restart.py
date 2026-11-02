"""A collection restart is durable: an interrupted one is finished by reconcile."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.jobs.reconcile import reconcile_async
from sm_images.models import PipelineRestart
from sm_images.pipeline import restart
from sqlalchemy import select, update

from tests.support.pipeline import Scripted, use_steps

T = DEFAULT_TENANT


async def _restarts(pipe) -> list[PipelineRestart]:
    async with pipe.db_state.session_factory() as s:
        return list((await s.execute(select(PipelineRestart))).scalars())


async def test_interrupted_restart_is_completed_by_reconcile(pipe, monkeypatch):
    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    imgs = [await pipe.image(coll) for _ in range(3)]
    for img in imgs:
        await pipe.run(img)
    real = restart.submit_dispatch
    calls = []

    async def dies_on_the_second(runtime, tenant, image_id):
        calls.append(image_id)
        if len(calls) == 2:
            raise RuntimeError("worker killed")
        await real(runtime, tenant, image_id)

    monkeypatch.setattr(restart, "submit_dispatch", dies_on_the_second)
    with pytest.raises(RuntimeError):
        await restart.restart_collection_async(pipe.runtime, T, coll.id, "force", chunk=1)
    monkeypatch.setattr(restart, "submit_dispatch", real)
    (row,) = await _restarts(pipe)
    assert row.finished_at is None and row.cursor is not None

    async with pipe.db_state.session_factory() as s:  # its worker is gone
        await s.execute(
            update(PipelineRestart).values(heartbeat_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()
    await reconcile_async(pipe.runtime, datetime.now(UTC))
    (row,) = await _restarts(pipe)
    assert row.finished_at is not None
    attempts = sorted([(await pipe.runs(img))["acme.x"].attempts for img in imgs])
    assert attempts == [2, 2, 2]  # every image re-ran exactly once
    assert x.calls == 6


async def test_broker_mode_reconcile_requeues_a_stale_restart(pipe, monkeypatch):
    from celery import current_app
    from sm_images.pipeline.runtime import Runtime
    from sm_images.task_config import RESTART_COLLECTION

    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    rid = await restart.start_restart(pipe.runtime, T, coll.id, "retry")
    async with pipe.db_state.session_factory() as s:
        stale = datetime.now(UTC) - timedelta(hours=1)
        await s.execute(update(PipelineRestart).values(heartbeat_at=stale))
        await s.commit()
    sent: list = []

    def apply_async(args=None, kwargs=None, **o):
        sent.append((tuple(args), o["queue"], o["headers"]))

    monkeypatch.setattr(current_app.tasks[RESTART_COLLECTION], "apply_async", apply_async)
    rt = pipe.runtime
    broker = Runtime(rt.session_factory, rt.store, rt.settings, rt.bus, eager=False)
    await reconcile_async(broker, datetime.now(UTC))
    await reconcile_async(broker, datetime.now(UTC))  # heartbeat moved: not sent twice
    assert sent == [((str(coll.id), "retry", str(rid)), "images_imports", {"sm_tenant_id": T})]


async def test_finished_restart_is_not_resumed(pipe):
    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert await restart.restart_collection_async(pipe.runtime, T, coll.id, "force") == 1
    await reconcile_async(pipe.runtime, datetime.now(UTC) + timedelta(hours=1))
    assert x.calls == 2


async def test_restart_and_overview_skip_trashed_images(pipe):
    from sm_images.models import Image
    from sm_images.pipeline.control import overview

    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    live, gone = await pipe.image(coll), await pipe.image(coll)
    for img in (live, gone):
        await pipe.run(img)
    await pipe.trash(Image, gone)

    await restart.restart_collection_async(pipe.runtime, T, coll.id, "force")
    assert (await pipe.runs(live))["acme.x"].attempts == 2
    assert (await pipe.runs(gone))["acme.x"].attempts == 1  # never reset nor re-run
    assert x.calls == 3
    async with pipe.db_state.session_factory() as s:
        body = await overview(s, coll)
    assert body["status"]["acme.x"] == {"completed": 1}


async def test_a_lost_first_restart_delivery_is_resumed_by_reconcile(pipe, monkeypatch):
    """Broker mode: the restart's record is stored before the message is sent
    and the message names it, so a lost first delivery is still finished."""
    from celery import current_app
    from sm_images.pipeline.control import launch_restart
    from sm_images.pipeline.runtime import Runtime
    from sm_images.task_config import RESTART_COLLECTION

    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    sent: list = []

    def lost(args=None, kwargs=None, **o):
        sent.append(tuple(args))  # published, never delivered

    monkeypatch.setattr(current_app.tasks[RESTART_COLLECTION], "apply_async", lost)
    rt = pipe.runtime
    broker = Runtime(rt.session_factory, rt.store, rt.settings, rt.bus, eager=False)
    await launch_restart(broker, T, coll.id, "all")
    (row,) = await _restarts(pipe)
    assert row.finished_at is None and row.scope == "force"
    assert sent == [(str(coll.id), "force", str(row.id))]

    await reconcile_async(pipe.runtime, datetime.now(UTC) + timedelta(hours=1))
    (row,) = await _restarts(pipe)
    assert row.finished_at is not None
    assert x.calls == 2 and (await pipe.runs(img))["acme.x"].attempts == 2
