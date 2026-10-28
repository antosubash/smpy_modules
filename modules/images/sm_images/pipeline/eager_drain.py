"""Eager mode's wait for durable deliveries, and "are we inside one?".

An eager :func:`~sm_images.pipeline.orchestrate.submit` waits for the durable
deliveries its work published (``ImageProcessed`` subscribers), unless it runs
inside a delivery itself - waiting there would wait on that very delivery.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextvars import ContextVar
from typing import Any

from sm_images.pipeline.runtime import Runtime

__all__ = ["EAGER_DRAIN_TIMEOUT", "IN_DELIVERY", "deliver_code", "drain_durable", "in_delivery"]

logger = logging.getLogger(__name__)

# Set while an outermost drain runs inside a durable delivery, so the tasks it
# (or anything it calls) spawns inherit "inside a delivery" with the context.
IN_DELIVERY: ContextVar[bool] = ContextVar("sm_images_in_delivery", default=False)

#: Longest an eager drain waits for durable deliveries (see :func:`drain_durable`).
EAGER_DRAIN_TIMEOUT = 5.0
_orphans: set[asyncio.Future[Any]] = set()  # shielded drains outliving their wait


def deliver_code() -> Any:
    """The code object of the framework coroutine that runs a durable handler."""
    try:
        from background_tasks.outbox_dispatch import deliver_one
    except ImportError:  # pragma: no cover - background_tasks is a dependency
        return None
    return deliver_one.__code__


def in_delivery() -> bool:
    """Is this code running inside a durable delivery (an outbox handler)?

    Decided by the **call path**, not by the transport's global state: while a
    coroutine runs, its awaiting callers' frames are on the stack, so a
    handler - delivered on its own task or inline on a request's - finds
    ``deliver_one`` below it. Waiting for the transport from there would wait
    on that very delivery (or the dispatcher lock it holds), so the caller
    leaves delivery to the dispatcher already running. Code that merely runs
    while some *unrelated* delivery is in flight is not inside one, and waits.

    A task does not inherit its creator's frames, so a task spawned inside a
    handler is invisible to the walk. ``IN_DELIVERY`` covers the ones spawned
    while images code runs inside a delivery; the rest (a handler that spawns
    a submitting task before calling into images) are caught only by the
    ``EAGER_DRAIN_TIMEOUT`` bound in :func:`drain_durable`.
    """
    if IN_DELIVERY.get():
        return True
    target = deliver_code()
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code is target:
            return True
        frame = frame.f_back
    return False


async def drain_durable(runtime: Runtime) -> bool:
    """Wait for the eager durable deliveries the drained work published (the
    web outbox transport starts them as tasks from ``after_commit``), so an
    eager caller returns with ``ImageProcessed``'s durable subscribers done.

    ``True`` when the wait finished; ``False`` when there was nothing to wait
    for, it must not wait, or the wait timed out - the caller then runs what
    is already queued and stops waiting.

    The wait is bounded and shielded: a submit from a task spawned inside a
    durable handler cannot tell it is in one, and its ``drain()`` gathers the
    parent delivery that is awaiting it. After ``EAGER_DRAIN_TIMEOUT`` it gives
    up (the deliveries carry on uncancelled), turning a deadlock into a delay.
    """
    transport = getattr(runtime.bus(), "durable_transport", None)
    drain = getattr(transport, "drain", None)
    if drain is None or in_delivery():
        return False
    waiting = asyncio.ensure_future(drain())
    try:
        await asyncio.wait_for(asyncio.shield(waiting), timeout=EAGER_DRAIN_TIMEOUT)
    except TimeoutError:
        _orphans.add(waiting)
        waiting.add_done_callback(_orphans.discard)
        logger.warning(
            "images.pipeline.eager_drain_timeout after %ss: durable deliveries are "
            "still running, most likely because this submit runs in a task spawned "
            "inside a durable handler and is waiting on its own parent delivery; "
            "running the work already queued and returning without them",
            EAGER_DRAIN_TIMEOUT,
        )
        return False
    except Exception:
        logger.exception("images.pipeline.durable_drain_failed")
    return True
