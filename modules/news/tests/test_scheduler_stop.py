"""What ``Scheduler.stop`` swallows, what it reports, and what it must not do
to its neighbours.

Two separate decisions meet in four lines, and they pull in opposite directions.

Only ``CancelledError`` is suppressed, which is deliberately narrow: cancelling
is the expected outcome of ``stop`` and says nothing, while a task that ended any
other way died *before* the polling loop — ``_run`` catches and logs a failing
tick itself — and quietly discarding that is how a scheduler which stopped
working weeks ago goes unnoticed.

But the failure is *logged*, not raised. FastAPI's ``Router._shutdown`` is a
bare ``for`` over the registered shutdown handlers with no ``try`` around each
one, so an exception escaping this handler aborts the loop and every handler
registered after news' never runs. News stranding pagebuilder's polling task
because news' own teardown went wrong is a worse outcome than a line in the log,
and the last test here is the one that says so — it is the regression test for
the bug, not a restatement of the first two.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from news.scheduler import Scheduler

pytestmark = pytest.mark.asyncio

LOGGER = "simple_module.news.scheduler"


async def _forever() -> None:
    await asyncio.sleep(3600)


async def _boom() -> None:
    raise RuntimeError("app.state.sm is missing")


async def _settled() -> asyncio.Task[None]:
    """A task that has already failed, so ``cancel`` on it is a no-op.

    Which is the real shape of this case: the task did not survive to be
    cancelled, and ``stop`` only learns that when it awaits it.
    """
    task = asyncio.create_task(_boom())
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
        assert [r for r in caplog.records if r.name == LOGGER] == []

    async def test_a_task_that_died_another_way_is_logged_not_raised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        scheduler = Scheduler()
        scheduler._task = await _settled()

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await scheduler.stop()

        records = [r for r in caplog.records if r.name == LOGGER]
        assert [r.message for r in records] == ["news.scheduler.stop_failed"]
        # The traceback is the point. "Something went wrong during shutdown"
        # without it does not say which teardown failed or why.
        assert records[0].exc_info is not None
        assert scheduler._task is None

    async def test_the_task_handle_is_dropped_even_when_the_await_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Otherwise a failed stop leaves a dead task on the object, and a
        second ``stop`` — or a restart in the same process — awaits it again and
        logs the same traceback a second time."""
        scheduler = Scheduler()
        scheduler._task = await _settled()

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await scheduler.stop()
            await scheduler.stop()

        assert len([r for r in caplog.records if r.name == LOGGER]) == 1


class TestTheNeighbours:
    """The reason the exception is swallowed at this one call site.

    ``Router._shutdown`` has no isolation between handlers, so this is not a
    hypothetical: news raising on shutdown leaves another module's scheduler
    polling task never cancelled.
    """

    async def test_a_failed_teardown_does_not_strand_a_later_handler(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = FastAPI()
        scheduler = Scheduler()
        scheduler._task = await _settled()
        neighbour = asyncio.create_task(_forever())

        async def stop_the_neighbour() -> None:
            neighbour.cancel()

        # Registered in the order the host registers modules: news first, so a
        # raise from it is exactly what would swallow the one after.
        app.router.add_event_handler("shutdown", scheduler.stop)
        app.router.add_event_handler("shutdown", stop_the_neighbour)

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            async with app.router.lifespan_context(app):
                pass

        # Awaited rather than inspected: ``cancelling()`` is already truthy the
        # instant ``cancel`` is called, so it would pass without the
        # cancellation ever landing.
        with pytest.raises(asyncio.CancelledError):
            await neighbour
        # And news' own failure is still on the record rather than traded away
        # for the neighbour's teardown.
        assert [r.message for r in caplog.records if r.name == LOGGER] == [
            "news.scheduler.stop_failed"
        ]

    async def test_the_framework_really_has_no_guard_between_handlers(self) -> None:
        """The premise of everything above, pinned.

        If FastAPI ever wraps each handler, this fails and the swallow in
        ``stop`` can be reconsidered — which is the only circumstance in which
        it should be.
        """
        app = FastAPI()
        reached: list[str] = []

        async def raises() -> None:
            raise RuntimeError("boom")

        async def after() -> None:
            reached.append("after")

        app.router.add_event_handler("shutdown", raises)
        app.router.add_event_handler("shutdown", after)

        with pytest.raises(RuntimeError):
            async with app.router.lifespan_context(app):
                pass

        assert reached == []
