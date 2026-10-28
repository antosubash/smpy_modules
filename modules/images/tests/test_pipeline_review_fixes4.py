"""Review round 4: a task spawned inside a durable handler does not inherit its
frame stack, so the frame walk cannot see the delivery. Its eager ``submit``
waits on ``transport.drain()``, which gathers the parent delivery that is
awaiting the child: every such wait is bounded instead of hanging."""

from __future__ import annotations

import asyncio
import logging
import time

from simple_module_db import finalize_session
from simple_module_db.transaction import SESSION_START_KEY
from sm_images.contracts import ImageProcessed
from sm_images.pipeline import eager_drain, orchestrate
from sm_images.tenancy import DEFAULT_TENANT

from tests.pipeline_support import Scripted, use_steps
from tests.test_pipeline_review_fixes2 import _bounded
from tests.test_pipeline_review_fixes3 import _transport

T = DEFAULT_TENANT
BOUND = 0.5  # the eager drain bound under test (the module default is 5 s)
HARD = 15.0  # a regressed deadlock fails here instead of hanging the run


async def _setup(pipe, monkeypatch):
    monkeypatch.setattr(eager_drain, "EAGER_DRAIN_TIMEOUT", BOUND)
    transport = await _transport(pipe)
    # Far above the bound, so the handler timeout cannot be what unblocks it.
    transport._services.settings.outbox_handler_timeout_seconds = 60
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    parent, child = await pipe.image(coll), await pipe.image(coll)
    delivered: list[str] = []
    finished: list[float] = []

    async def handler(event, ctx):
        if event.image_id == str(parent):
            started = time.monotonic()
            # A fresh task: it copies the context, not the frame stack.
            await asyncio.get_running_loop().create_task(pipe.run(child))
            finished.append(time.monotonic() - started)
        delivered.append(event.image_id)

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.spawns_submit")
    return transport, coll, parent, child, delivered, finished


async def _publish(pipe, coll, image, *, request: bool) -> None:
    async with pipe.db_state.session_factory() as s:
        if request:  # a request's session: on_commit delivers inline, holding the lock
            s.info[SESSION_START_KEY] = time.perf_counter()
        await pipe.bus.publish_durable(ImageProcessed(T, str(coll.id), str(image), 0), s)
        await finalize_session(s)


async def test_task_spawned_in_a_durable_handler_does_not_deadlock(pipe, monkeypatch, caplog):
    """Codex P1: the delivery runs on the transport's task and holds the
    dispatcher lock; the handler's child task submits and its drain gathers
    that very delivery."""
    transport, coll, parent, child, delivered, finished = await _setup(pipe, monkeypatch)
    caplog.set_level(logging.WARNING, logger=eager_drain.__name__)
    await _publish(pipe, coll, parent, request=False)
    await _bounded(transport, asyncio.sleep(0), limit=HARD)
    assert finished and finished[0] < BOUND + 1.0
    assert sorted(delivered) == sorted([str(parent), str(child)])
    assert "eager_drain_timeout" in caplog.text


async def test_request_inline_delivery_whose_handler_awaits_a_submitting_task(pipe, monkeypatch):
    """The request variant: the delivery runs inline on the publisher's task
    holding the dispatcher lock; the child's own delivery queues behind it."""
    transport, coll, parent, child, delivered, finished = await _setup(pipe, monkeypatch)
    await _bounded(transport, _publish(pipe, coll, parent, request=True), limit=HARD)
    assert finished and finished[0] < BOUND + 1.0
    assert sorted(delivered) == sorted([str(parent), str(child)])


async def test_submit_inside_a_delivery_marks_tasks_it_spawns(pipe, monkeypatch):
    """Tasks started while images code runs inside a delivery inherit the mark,
    so their own submit leaves delivery to the running dispatcher at once."""
    transport = await _transport(pipe)
    seen: list[bool] = []

    async def probe():
        seen.append(eager_drain.in_delivery())

    async def spawn(runtime, item):
        await asyncio.get_running_loop().create_task(probe())

    monkeypatch.setattr(orchestrate, "_execute", spawn)

    async def handler(event, ctx):
        await orchestrate.submit(pipe.runtime, [orchestrate.Dispatch(T, pipe.images["x"])])

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.marks_children")
    coll = await pipe.collection({})
    pipe.images["x"] = await pipe.image(coll)
    await _publish(pipe, coll, pipe.images["x"], request=False)
    await _bounded(transport, asyncio.sleep(0), limit=HARD)
    assert seen == [True] and eager_drain.in_delivery() is False
