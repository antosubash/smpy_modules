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

__all__ = ["HEARTBEAT_SECONDS", "Beat", "beating"]

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS: Final = 30.0


class Beat:
    """Set by :func:`beating` when the job was taken from this worker."""

    lost = False


@contextlib.asynccontextmanager
async def beating(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int
) -> AsyncIterator[Beat]:
    """Heartbeat every :data:`HEARTBEAT_SECONDS` in the background while a long
    step (counting, storing or reading back the source) runs.

    Stopped cooperatively, never cancelled: a beat already talking to the
    database finishes first. Cancelling a query mid-flight would leave its
    connection unusable."""
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
                if not await jobs.heartbeat(runtime, tenant, job_id, generation):
                    beat.lost = True
                    return
            except Exception:  # a missed beat is not worth failing the step
                logger.warning("images.import.heartbeat_failed job=%s", job_id, exc_info=True)

    task = asyncio.create_task(loop())
    try:
        yield beat
    finally:
        stop.set()
        await task
