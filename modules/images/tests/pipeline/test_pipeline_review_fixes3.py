"""Review round 3: "inside a delivery" is the framework's per-context flag
(``simple_module_core.durable_events.in_delivery``), not the transport's global
lock."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from background_tasks.models import Base as BackgroundBase
from background_tasks.outbox_transport import OutboxTransport
from background_tasks.settings import BackgroundTasksSettings
from simple_module_core.durable_events import in_delivery
from simple_module_db import finalize_session
from sm_images.contracts import ImageProcessed
from sm_images.core.tenancy import DEFAULT_TENANT

from tests.pipeline.test_pipeline_review_fixes2 import _bounded
from tests.support.pipeline import Scripted, use_steps

T = DEFAULT_TENANT


async def _transport(pipe) -> OutboxTransport:
    async with pipe.db_state.engine.begin() as conn:
        await conn.run_sync(BackgroundBase.metadata.create_all)
    settings = BackgroundTasksSettings(
        task_always_eager=True, outbox_lease_seconds=30, outbox_handler_timeout_seconds=5
    )
    transport = OutboxTransport(
        services=SimpleNamespace(settings=settings), bus=pipe.bus, db_state=pipe.db_state
    )
    pipe.bus.durable_transport = transport
    return transport


async def test_a_durable_handler_sees_itself_inside_a_delivery(pipe):
    transport = await _transport(pipe)
    seen: list[bool] = []

    async def handler(event, ctx):
        seen.append(in_delivery())

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.where_am_i")
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    await _bounded(transport, pipe.run(img))
    assert seen == [True] and in_delivery() is False


async def test_submit_waits_for_its_own_delivery_behind_an_unrelated_one(pipe):
    """An unrelated delivery holds the dispatcher lock; an independent eager
    submit must still return only once its own durable delivery is done."""
    transport = await _transport(pipe)
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    other = await pipe.image(coll)
    mine = await pipe.image(coll)
    gate = asyncio.Event()
    delivered: list[str] = []

    async def handler(event, ctx):
        if event.image_id == str(other):
            await gate.wait()  # the unrelated delivery, in flight
        delivered.append(event.image_id)

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.unrelated")
    async with pipe.db_state.session_factory() as s:
        await pipe.bus.publish_durable(ImageProcessed(T, str(coll.id), str(other), 0), s)
        await finalize_session(s)
    await asyncio.sleep(0.05)
    assert transport._dispatch_lock.locked()  # the unrelated delivery holds it

    asyncio.get_running_loop().call_later(0.2, gate.set)
    submit = asyncio.ensure_future(pipe.run(mine))
    done, _ = await asyncio.wait({submit}, timeout=10)
    returned_with = list(delivered)  # what was delivered when submit returned
    await _bounded(transport, asyncio.sleep(0))  # cleanup; fails on a hang
    assert done and submit.result() is None
    assert str(mine) in returned_with
