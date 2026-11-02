"""Tearing down a lease keep-alive task without eating an outer cancellation."""

from __future__ import annotations

import asyncio


async def stop(keeper: asyncio.Future[None]) -> None:
    """Cancel ``keeper`` and wait for it to finish.

    ``asyncio.wait`` never raises the awaited task's own outcome, so the keeper's
    ``CancelledError`` is not mistaken for ours: a cancellation of the *current*
    task still propagates out of the wait."""
    keeper.cancel()
    await asyncio.wait([keeper])
    if not keeper.cancelled():
        keeper.exception()  # retrieved: a failed keeper was logged by its own handler
