"""Eager mode's wait for durable deliveries, and "are we inside one?".

An eager :func:`~sm_images.pipeline.orchestrate.submit` waits for the durable
deliveries its work published (``ImageProcessed`` subscribers), unless it runs
inside a delivery itself - waiting there would wait on that very delivery.

"Inside a delivery" is the framework's
:func:`simple_module_core.durable_events.in_delivery`: every delivery path
(the outbox dispatcher on a worker or on a request's task, and inline
delivery without a transport) sets it around the handler call, and tasks the
handler spawns inherit it with the context. Code that merely runs while some
*unrelated* delivery is in flight is not inside one, and waits.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from simple_module_core.durable_events import in_delivery

from sm_images.pipeline.runtime import Runtime

__all__ = ["EAGER_DRAIN_TIMEOUT", "drain_durable"]

logger = logging.getLogger(__name__)

#: Longest an eager drain waits for durable deliveries (see :func:`drain_durable`).
EAGER_DRAIN_TIMEOUT = 5.0
_orphans: set[asyncio.Future[Any]] = set()  # shielded drains outliving their wait


async def drain_durable(runtime: Runtime) -> bool:
    """Wait for the eager durable deliveries the drained work published (the
    web outbox transport starts them as tasks from ``after_commit``), so an
    eager caller returns with ``ImageProcessed``'s durable subscribers done.

    ``True`` when the wait finished; ``False`` when there was nothing to wait
    for, it must not wait, or the wait timed out - the caller then runs what
    is already queued and stops waiting.

    The wait is bounded and shielded as a safety net: code that runs on behalf
    of a delivery in a context that lost the framework's flag (a task started
    with a fresh ``Context``, say) would have its ``drain()`` gather the parent
    delivery that is awaiting it. After ``EAGER_DRAIN_TIMEOUT`` it gives up
    (the deliveries carry on uncancelled), turning that deadlock into a delay;
    a handler that simply outlives the bound is cut off the same way.
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
            "still running (a slow handler, or this submit runs on behalf of a durable "
            "delivery in a context without the framework's in_delivery flag); "
            "running the work already queued and returning without them",
            EAGER_DRAIN_TIMEOUT,
        )
        return False
    except Exception:
        logger.exception("images.pipeline.durable_drain_failed")
    return True
