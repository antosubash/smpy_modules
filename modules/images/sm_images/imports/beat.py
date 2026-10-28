"""A background heartbeat for the long steps of a run (count, store, read back)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Final

from sm_images.imports import jobs
from sm_images.pipeline.runtime import Runtime

__all__ = ["BEAT_TIMEOUT_SECONDS", "HEARTBEAT_SECONDS", "SHUTDOWN_WAIT_SECONDS", "Beat", "beating"]

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS: Final = 30.0
BEAT_TIMEOUT_SECONDS: Final = 20.0
"""Longest one heartbeat ``UPDATE`` may take: a beat stuck on a lock is given up
(and counted as missed) rather than holding the loop."""
SHUTDOWN_WAIT_SECONDS: Final = 5.0
"""How long leaving :func:`beating` waits for a beat already in flight; after
that the beat is left to finish on its own, never cancelled mid-query."""

_orphans: set[asyncio.Task[None]] = set()  # beats outliving their step


class Beat:
    """Set by :func:`beating` when the job was taken from this worker."""

    lost = False


@contextlib.asynccontextmanager
async def beating(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int
) -> AsyncIterator[Beat]:
    """Heartbeat every :data:`HEARTBEAT_SECONDS` in the background while a long
    step (counting, storing or reading back the source) runs.

    Each beat is bounded by :data:`BEAT_TIMEOUT_SECONDS`. Leaving signals the
    loop to stop and waits at most :data:`SHUTDOWN_WAIT_SECONDS` for a beat in
    flight, through a shield: neither that timeout nor a cancellation of the
    step itself cancels a beat mid-query (which would leave its connection
    unusable). A beat still running then finishes on its own."""
    beat = Beat()
    stop = asyncio.Event()

    async def loop() -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
                return
            except TimeoutError:
                pass
            try:
                alive = await asyncio.wait_for(
                    jobs.heartbeat(runtime, tenant, job_id, generation),
                    timeout=BEAT_TIMEOUT_SECONDS,
                )
                if not alive:
                    beat.lost = True
                    return
            except TimeoutError:
                logger.warning("images.import.heartbeat_timeout job=%s", job_id)
            except Exception:  # a missed beat is not worth failing the step
                logger.warning("images.import.heartbeat_failed job=%s", job_id, exc_info=True)

    task = asyncio.create_task(loop())
    try:
        yield beat
    finally:
        stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=SHUTDOWN_WAIT_SECONDS)
        except TimeoutError:
            logger.warning("images.import.heartbeat_left_running job=%s", job_id)
            _orphans.add(task)
            task.add_done_callback(_orphans.discard)
        except asyncio.CancelledError:
            _orphans.add(task)  # the step was cancelled; its beat carries on
            task.add_done_callback(_orphans.discard)
            raise
