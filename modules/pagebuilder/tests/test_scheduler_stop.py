"""What ``Scheduler.stop`` swallows, and what it must not.

``stop`` used to suppress ``(CancelledError, Exception)``, which is every way
the polling task can end. Cancellation is the expected one and says nothing;
anything else means the task died before it ever reached the loop — ``_run``
catches and logs a failing *tick* itself — and a blanket catch at shutdown is
how a scheduler that stopped working weeks ago goes unnoticed.

The failure is logged rather than raised on purpose: FastAPI runs shutdown
handlers in a plain loop with no ``try`` around each one, so raising here would
skip every handler registered after pagebuilder's.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from pagebuilder.scheduler import Scheduler

LOGGER = "simple_module.pagebuilder.scheduler"


async def _forever() -> None:
    await asyncio.sleep(3600)


async def _boom() -> None:
    raise RuntimeError("session_factory is missing")


async def _settled(coro_fn) -> asyncio.Task[None]:
    """A task that has already run to completion, so ``cancel`` is a no-op."""
    task = asyncio.create_task(coro_fn())
    while not task.done():
        await asyncio.sleep(0)
    return task


class TestStop:
    async def test_cancelling_a_running_task_says_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        scheduler = Scheduler()
        scheduler._task = asyncio.create_task(_forever())

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            await scheduler.stop()

        assert scheduler._task is None
        assert caplog.records == []

    async def test_a_task_that_died_for_another_reason_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        scheduler = Scheduler()
        scheduler._task = await _settled(_boom)

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            # Not raised: a raise here would skip the shutdown handlers
            # registered after this one.
            await scheduler.stop()

        assert scheduler._task is None
        assert [r.message for r in caplog.records] == ["pagebuilder.scheduler.stop_failed"]
        # The traceback is the point — an exception summary alone would not say
        # which teardown failed.
        assert caplog.records[0].exc_info is not None

    async def test_stopping_twice_is_harmless(self) -> None:
        scheduler = Scheduler()
        scheduler._task = asyncio.create_task(_forever())

        await scheduler.stop()
        await scheduler.stop()

        assert scheduler._task is None
