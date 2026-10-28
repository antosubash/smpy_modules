"""Review round 2: a disabled prerequisite's old result, and re-entrant
durable delivery in eager mode."""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace

from background_tasks.models import Base as BackgroundBase
from background_tasks.models import OutboxMessage
from background_tasks.outbox_transport import OutboxTransport
from background_tasks.settings import BackgroundTasksSettings
from simple_module_db import all_tenants
from sm_images.contracts import ImageProcessed
from sm_images.models import Collection
from sm_images.pipeline.orchestrate import rerun_image
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.pipeline_support import Scripted, use_steps

T = DEFAULT_TENANT


async def _bounded(transport, aw, limit: float = 10.0) -> None:
    """Await ``aw`` (then the transport's deliveries) but never hang the suite:
    a regressed deadlock cancels everything and fails instead."""
    task = asyncio.ensure_future(aw)
    done, _ = await asyncio.wait({task}, timeout=limit)
    deadline = time.monotonic() + limit
    while getattr(transport, "_tasks", None) and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    hung = [task] if not done else []
    hung += list(getattr(transport, "_tasks", ()))
    for t in hung:
        t.cancel()
    assert not hung, "the pipeline or a durable delivery deadlocked"
    task.result()


async def test_disabled_completed_prerequisite_blocks_its_dependant(pipe):
    base = Scripted("acme.base")
    after = Scripted("acme.after", requires=("acme.base",))
    use_steps(base, after)
    coll = await pipe.collection({"acme.base": {}, "acme.after": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert await pipe.status(img) == {"acme.base": "completed", "acme.after": "completed"}

    async with pipe.db_state.session_factory() as s:  # disable A after it completed
        cfg = {"steps": {"acme.base": {"enabled": False}, "acme.after": {}}}
        await s.execute(
            update(Collection).where(Collection.id == coll.id).values(pipeline_config=cfg)
        )
        await s.commit()
    await rerun_image(pipe.runtime, T, img, "force")
    run = (await pipe.runs(img))["acme.after"]
    assert (run.status.value, run.error_code) == ("skipped", "dependency_unavailable")
    assert after.calls == 1


async def test_durable_handler_that_reruns_eagerly_does_not_deadlock(pipe):
    """A durable ``ImageProcessed`` handler re-running the image eagerly reaches
    the images drain inside its own delivery; waiting there for the transport's
    deliveries would wait on itself until the handler timeout."""
    async with pipe.db_state.engine.begin() as conn:
        await conn.run_sync(BackgroundBase.metadata.create_all)
    settings = BackgroundTasksSettings(
        task_always_eager=True, outbox_lease_seconds=30, outbox_handler_timeout_seconds=3
    )
    pipe.bus.durable_transport = OutboxTransport(
        services=SimpleNamespace(settings=settings), bus=pipe.bus, db_state=pipe.db_state
    )
    seen: list[int] = []

    async def handler(event, ctx):
        if event.processing_generation == 1:
            await rerun_image(pipe.runtime, event.tenant_id, uuid.UUID(event.image_id), "force")
        seen.append(event.processing_generation)

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.rerun_on_processed")
    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)

    started = time.monotonic()
    await _bounded(pipe.bus.durable_transport, pipe.run(img))
    assert time.monotonic() - started < 2.5  # no handler sat out its timeout
    assert sorted(seen) == [1, 2] and x.calls == 2
    with all_tenants():
        async with pipe.db_state.session_factory() as s:
            rows = (await s.execute(select(OutboxMessage.status))).scalars().all()
    assert [r.value if hasattr(r, "value") else r for r in rows] == ["delivered", "delivered"]


async def test_rerun_from_a_delivery_started_outside_any_drain(pipe):
    """The delivery task was not started by an images drain, so the handler's
    rerun opens its own drain inside the delivery: it must not wait for the
    transport's deliveries, its own among them."""
    from simple_module_db import finalize_session

    async with pipe.db_state.engine.begin() as conn:
        await conn.run_sync(BackgroundBase.metadata.create_all)
    settings = BackgroundTasksSettings(
        task_always_eager=True, outbox_lease_seconds=30, outbox_handler_timeout_seconds=3
    )
    transport = OutboxTransport(
        services=SimpleNamespace(settings=settings), bus=pipe.bus, db_state=pipe.db_state
    )
    pipe.bus.durable_transport = transport
    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    seen: list[int] = []

    async def handler(event, ctx):
        if event.processing_generation == 0:
            await rerun_image(pipe.runtime, T, img, "retry")
        seen.append(event.processing_generation)

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.rerun_outside")
    started = time.monotonic()
    async with pipe.db_state.session_factory() as s:  # a publish from outside the pipeline
        await pipe.bus.publish_durable(ImageProcessed(T, str(coll.id), str(img), 0), s)
        await finalize_session(s)
    await _bounded(transport, asyncio.sleep(0))
    assert time.monotonic() - started < 2.5
    assert sorted(seen) == [0, 1] and x.calls == 1
