"""What ``Scheduler.stop`` swallows, and what it must not.

``stop`` used to suppress ``(CancelledError, Exception)``, which is every way
the polling task can end. Cancellation is the expected one and says nothing;
anything else means the task died before it ever reached the loop — ``_run``
catches and logs a failing *tick* itself — and a blanket catch at shutdown is
how a scheduler that stopped working weeks ago goes unnoticed.

The failure is logged rather than raised on purpose: the host's lifespan calls
every module's ``on_shutdown(app)`` — which is what actually invokes this, not
a FastAPI shutdown event handler, since the host builds the app with a custom
``lifespan=`` that bypasses the router's own event-handler list — in a plain
loop with no ``try`` around each call, so raising here would skip every
module's teardown that comes after pagebuilder's in shutdown order.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from pagebuilder.module import PagebuilderModule
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

    async def test_the_task_handle_is_dropped_even_when_the_await_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Otherwise a failed stop leaves a dead task on the object, and a
        second ``stop`` awaits it again and logs the same traceback twice.
        Ported from news' suite (#127)."""
        scheduler = Scheduler()
        scheduler._task = await _settled(_boom)

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await scheduler.stop()
            await scheduler.stop()

        assert len([r for r in caplog.records if r.name == LOGGER]) == 1


async def test_a_failed_teardown_does_not_strand_a_later_module(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reason the exception is swallowed, against the real module hook.

    Shaped like the host's lifespan teardown — a bare loop over each module's
    ``on_shutdown`` with no ``try`` of its own — so pagebuilder raising here
    would leave the neighbour (news' scheduler, say) never cancelled. Ported
    from news' suite (#127).
    """
    app = FastAPI()
    module = PagebuilderModule()
    module._scheduler._task = await _settled(_boom)
    neighbour = asyncio.create_task(_forever())

    async def neighbour_on_shutdown(_: FastAPI) -> None:
        neighbour.cancel()

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        for on_shutdown in (module.on_shutdown, neighbour_on_shutdown):
            await on_shutdown(app)

    # Awaited rather than inspected: ``cancelling()`` is truthy the instant
    # ``cancel`` is called, so it would pass without the cancellation landing.
    with pytest.raises(asyncio.CancelledError):
        await neighbour
    assert [r.message for r in caplog.records if r.name == LOGGER] == [
        "pagebuilder.scheduler.stop_failed"
    ]
