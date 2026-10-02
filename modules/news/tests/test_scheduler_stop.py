"""What ``Scheduler.stop`` swallows, what it reports, and what it must not do
to its neighbours.

Two separate decisions meet in four lines, and they pull in opposite directions.

Only ``CancelledError`` is suppressed, which is deliberately narrow: cancelling
is the expected outcome of ``stop`` and says nothing, while a task that ended any
other way died *before* the polling loop — ``_run`` catches and logs a failing
tick itself — and quietly discarding that is how a scheduler which stopped
working weeks ago goes unnoticed.

But the failure is *logged*, not raised. The host's lifespan calls every
module's ``on_shutdown(app)`` in a bare ``for`` loop with no ``try`` around
each one (see :mod:`simple_module_hosting.app_builder`), so an exception
escaping :meth:`NewsModule.on_shutdown` would abort that loop and every
module after news' in shutdown order never gets torn down — including
pagebuilder's own polling task. News stranding pagebuilder's scheduler
because news' own teardown went wrong is a worse outcome than a line in the
log, and the last test here is the one that says so — it is the regression
test for the bug, not a restatement of the first two.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from news.module import NewsModule
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

    The host's own shutdown loop (``for mod in reversed(modules): await
    mod.on_shutdown(app)``) has no isolation between modules either, so this
    is not a hypothetical: news raising out of ``on_shutdown`` leaves every
    module after it in shutdown order — including pagebuilder's own
    scheduler — never torn down.
    """

    async def test_a_failed_teardown_does_not_strand_a_later_module(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = FastAPI()
        news = NewsModule()
        news._scheduler._task = await _settled()
        neighbour = asyncio.create_task(_forever())

        async def neighbour_on_shutdown(_: FastAPI) -> None:
            neighbour.cancel()

        # Shaped like the host's actual lifespan teardown: a bare loop over
        # each module's ``on_shutdown``, reverse start order, news before its
        # neighbour — no ``try`` of its own around either call.
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            for on_shutdown in (news.on_shutdown, neighbour_on_shutdown):
                await on_shutdown(app)

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

    async def test_the_host_lifespan_really_has_no_guard_between_modules(self) -> None:
        """The premise of everything above, pinned against the real hook.

        If the host ever wraps each module's ``on_shutdown`` in its own
        ``try``, this fails and the swallow in ``Scheduler.stop`` can be
        reconsidered — which is the only circumstance in which it should be.
        """
        from simple_module_core.module import ModuleBase

        reached: list[str] = []

        class Raises(ModuleBase):
            async def on_shutdown(self, app: FastAPI) -> None:
                raise RuntimeError("boom")

        class After(ModuleBase):
            async def on_shutdown(self, app: FastAPI) -> None:
                reached.append("after")

        app = FastAPI()
        with pytest.raises(RuntimeError):
            for mod in (Raises(), After()):
                await mod.on_shutdown(app)

        assert reached == []
