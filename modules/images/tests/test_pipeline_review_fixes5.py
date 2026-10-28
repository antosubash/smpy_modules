"""Review round 5: the eager drain's *wait* for durable deliveries is bounded,
but the image work a handler already queued is not dropped when it expires."""

from __future__ import annotations

import asyncio

from sm_images.contracts import ImageProcessed
from sm_images.pipeline import eager_drain, orchestrate
from sm_images.tenancy import DEFAULT_TENANT

from tests.pipeline_support import Scripted, use_steps
from tests.test_pipeline_review_fixes2 import _bounded
from tests.test_pipeline_review_fixes3 import _transport

T = DEFAULT_TENANT
BOUND = 0.5
HARD = 15.0  # a regressed hang fails here instead of hanging the run


async def test_work_queued_by_a_handler_runs_although_the_drain_wait_times_out(pipe, monkeypatch):
    """Codex: the handler appends a submit for another image to the open drain,
    then keeps its delivery running past the bound. That image's pipeline must
    still run before the outer submit returns."""
    monkeypatch.setattr(eager_drain, "EAGER_DRAIN_TIMEOUT", BOUND)
    transport = await _transport(pipe)
    transport._services.settings.outbox_handler_timeout_seconds = 60
    step = Scripted("acme.x")
    use_steps(step)
    coll = await pipe.collection({"acme.x": {}})
    first, other = await pipe.image(coll), await pipe.image(coll)
    gate = asyncio.Event()

    async def handler(event, ctx):
        if event.image_id == str(first):
            # The delivery copied the drain's context: this appends to it.
            await orchestrate.submit(pipe.runtime, [orchestrate.Dispatch(T, other)])
            await gate.wait()  # outlive the bound

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.queues_then_waits")
    try:
        await asyncio.wait_for(pipe.run(first), timeout=HARD)
        status = await pipe.status(other)
    finally:
        gate.set()
        await _bounded(transport, asyncio.sleep(0), limit=HARD)
    assert status == {"acme.x": "completed"}
    assert step.calls == 2
