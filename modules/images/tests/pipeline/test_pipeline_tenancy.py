"""Tenant delivery and recovery: tasks run in the enqueuer's tenant; reconcile
works each tenant in its own scope and repairs lost hand-offs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db.listeners import current_tenant_id
from sm_images import pipeline
from sm_images.contracts import ImageProcessed
from sm_images.jobs.reconcile import reconcile_async
from sm_images.models import Collection, StepRun
from sm_images.pipeline.advance import plan_and_claim
from sm_images.pipeline.orchestrate import dispatch_ready
from sm_images.pipeline.runtime import Runtime, use_runtime
from sm_images.tenancy import tenant_scope
from sqlalchemy import select, update

from tests.support.pipeline import Scripted, use_steps

ACME, GLOBEX = "acme", "globex"
OLD = timedelta(minutes=10)


def _recording(sid: str = "acme.x") -> tuple[Scripted, list[str]]:
    step = Scripted(sid)
    seen: list[str] = []

    async def record(ctx):
        seen.append(f"{ctx.tenant_id}/{current_tenant_id.get()}")
        return step.outcome

    step.fn = record
    return step, seen


async def _seed(pipe, tenant: str, steps: dict, *, backdate: bool = True):
    with tenant_scope(tenant):
        coll = await pipe.collection(steps)
        img = await pipe.image(coll)
        async with pipe.db_state.session_factory() as s:
            for sid in steps:
                s.add(StepRun(image_id=img, step=sid))
            await s.flush()
            if backdate:
                await s.execute(
                    update(StepRun)
                    .where(StepRun.image_id == img)
                    .values(created_at=datetime.now(UTC) - OLD)
                )
            await s.commit()
    return img


@pytest.mark.unbound_tenant
async def test_task_runs_in_enqueuer_tenant(pipe):
    step, seen = _recording()
    use_steps(step)
    pipe.db_state.tenant_strict = True
    use_runtime(pipe.runtime)
    with tenant_scope(ACME):
        coll = await pipe.collection({"acme.x": {}})
        img = await pipe.image(coll)
        async with pipe.db_state.session_factory() as s:  # what ingest does
            from simple_module_db import finalize_session

            s.add(StepRun(image_id=img, step="acme.x"))
            pipeline.dispatch(s, img)
            await finalize_session(s)
        assert await pipe.status(img) == {"acme.x": "completed"}
    assert seen == [f"{ACME}/{ACME}"]


@pytest.mark.unbound_tenant
async def test_broker_mode_enqueues_on_the_step_queue_with_the_tenant(pipe, monkeypatch):
    from celery import current_app
    from sm_images.jobs.task_config import RUN_STEP

    step = Scripted("acme.gpu", queue="images_gpu")
    use_steps(step)
    sent: list[dict] = []

    def apply_async(args=None, kwargs=None, **options):
        sent.append({"args": tuple(args), **options})

    monkeypatch.setattr(current_app.tasks[RUN_STEP], "apply_async", apply_async)
    broker = Runtime(
        pipe.db_state.session_factory, pipe.runtime.store, pipe.runtime.settings, eager=False
    )
    with tenant_scope(ACME):
        coll = await pipe.collection({"acme.gpu": {}})
        img = await pipe.image(coll)
        claims = await dispatch_ready(broker, ACME, img)
    assert len(sent) == 1 and step.calls == 0
    assert sent[0]["args"] == (str(img), "acme.gpu", str(claims[0].token))
    assert sent[0]["queue"] == "images_gpu"
    assert sent[0]["headers"]["sm_tenant_id"] == ACME


@pytest.mark.unbound_tenant
async def test_reconcile_scopes_each_tenant(pipe):
    """Two tenants, no tenant bound, strict isolation: each tenant's stranded
    work runs inside that tenant only."""
    step, seen = _recording()
    use_steps(step)
    pipe.db_state.tenant_strict = True
    a = await _seed(pipe, ACME, {"acme.x": {}})
    g = await _seed(pipe, GLOBEX, {"acme.x": {}})
    assert current_tenant_id.get() is None
    await reconcile_async(pipe.runtime, datetime.now(UTC))
    assert sorted(seen) == [f"{ACME}/{ACME}", f"{GLOBEX}/{GLOBEX}"]
    with tenant_scope(ACME):
        assert await pipe.status(a) == {"acme.x": "completed"}
    with tenant_scope(GLOBEX):
        assert await pipe.status(g) == {"acme.x": "completed"}


async def test_reconcile_redispatches_lost_message(pipe):
    x = Scripted("acme.x")
    use_steps(x)
    lost = await _seed(pipe, "default", {"acme.x": {}})
    async with pipe.db_state.session_factory() as s:  # claimed, then the message vanished
        await plan_and_claim(s, "default", lost, datetime.now(UTC), 1800)
        await s.execute(
            update(StepRun)
            .where(StepRun.image_id == lost)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    never = await _seed(pipe, "default", {"acme.x": {}})  # committed, dispatch never sent
    fresh = await _seed(pipe, "default", {"acme.x": {}}, backdate=False)
    await reconcile_async(pipe.runtime, datetime.now(UTC))
    assert await pipe.status(lost) == {"acme.x": "completed"}
    assert await pipe.status(never) == {"acme.x": "completed"}
    assert await pipe.status(fresh) == {"acme.x": "pending"}  # younger than the cutoff
    assert x.calls == 2


async def test_reconcile_repairs_running_rows_without_a_lease(pipe):
    use_steps(Scripted("acme.x"))
    img = await _seed(pipe, "default", {"acme.x": {}})
    async with pipe.db_state.session_factory() as s:
        from sm_images.models.enums import StepStatus

        await s.execute(
            update(StepRun)
            .where(StepRun.image_id == img)
            .values(status=StepStatus.RUNNING, started_at=datetime.now(UTC) - OLD)
        )
        await s.commit()
    await reconcile_async(pipe.runtime, datetime.now(UTC))
    assert await pipe.status(img) == {"acme.x": "completed"}


async def test_reconcile_concludes_an_image_whose_dispatch_was_lost(pipe):
    seen: list[ImageProcessed] = []

    async def on(event):
        seen.append(event)

    pipe.bus.subscribe(ImageProcessed, on)
    coll = await pipe.collection({})
    img = await pipe.image(coll)  # an empty pipeline, never dispatched
    await reconcile_async(pipe.runtime, datetime.now(UTC) + OLD)
    await reconcile_async(pipe.runtime, datetime.now(UTC) + OLD)
    assert (await pipe.row(img)).processed_generation == 1
    assert [e.image_id for e in seen] == [str(img)]


async def test_reconcile_recomputes_collection_stats(pipe):
    coll = await pipe.collection({})
    await pipe.image(coll, lat=1.0, lng=2.0)
    await pipe.image(coll, is_deleted=True)
    await reconcile_async(pipe.runtime, datetime.now(UTC))
    async with pipe.db_state.session_factory() as s:
        c = (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()
    assert (c.image_count, c.located_count, c.bbox_minx) == (1, 1, 2.0)


async def test_restart_collection_in_chunks(pipe):
    from sm_images.pipeline.restart import restart_collection_async

    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    imgs = [await pipe.image(coll) for _ in range(3)]
    for img in imgs:
        await pipe.run(img)
    assert x.calls == 3
    n = await restart_collection_async(pipe.runtime, "default", coll.id, "force", chunk=2)
    assert n == 3 and x.calls == 6
    assert {r.attempts for img in imgs for r in (await pipe.runs(img)).values()} == {2}
