"""The in-process loop that flips pages on their scheduled times.

Lifted out of :mod:`pagebuilder.module` when that file crossed the repo's
300-line cap. It is a coherent piece to lift: everything here is about *when*
a page changes state, and nothing else in the module registration is.

A deployment that drives :meth:`PagesService.process_due` from a separate
worker (Celery beat, a k8s CronJob) turns this off with
``SM_PAGEBUILDER_SCHEDULER_ENABLED=false`` — otherwise both would race and
double-publish.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from fastapi import FastAPI

from pagebuilder.settings import PagebuilderSettings

_log = logging.getLogger("simple_module.pagebuilder.scheduler")


class Scheduler:
    """Owns the polling task and its shutdown."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self, app: FastAPI, settings: PagebuilderSettings) -> None:
        self._task = asyncio.create_task(self._run(app, settings))
        # FastAPI 0.136 no longer exposes ``add_event_handler`` on the app
        # itself; the router still carries it for ASGI lifespan hooks, which is
        # what we want here — the task lives as long as the app does and gets
        # cancelled on shutdown.
        app.router.add_event_handler("shutdown", self.stop)

    async def _run(self, app: FastAPI, settings: PagebuilderSettings) -> None:
        """Poll for scheduled publish / unpublish flips.

        One DB session per tick — short, write-or-rollback. Errors on a single
        tick are logged and the loop continues; cancellation (shutdown) is
        propagated.
        """
        from pagebuilder.service import PagesService

        factory = app.state.sm.db.session_factory
        interval = max(1, settings.scheduler_interval_seconds)
        while True:
            try:
                await asyncio.sleep(interval)
                async with factory() as session:
                    try:
                        service = PagesService(session)
                        flipped = await service.process_due(datetime.now(UTC))
                        # The trash promises to empty itself after the retention
                        # window. Swept on the same tick as the flips rather than
                        # only at startup, so the promise holds for a process that
                        # stays up for months as well as one that restarts nightly.
                        purged = await service.purge_expired()
                        if flipped or purged:
                            await session.commit()
                            _log.info(
                                "pagebuilder.scheduler.flipped",
                                extra={"count": len(flipped), "purged": purged},
                            )
                        else:
                            await session.rollback()
                    except Exception:
                        await session.rollback()
                        raise
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("pagebuilder.scheduler.tick_failed")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        # CancelledError is listed explicitly because it derives from
        # BaseException, not Exception, so it isn't covered by the latter.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None
