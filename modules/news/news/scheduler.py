"""The in-process loop that publishes articles at their scheduled times.

Lifted out of :mod:`news.module` when that file crossed the repo's 300-line
cap, and shaped like :mod:`pagebuilder.scheduler` for the same reason: it is a
coherent piece to lift, because everything here is about *when* an article
changes state and nothing else in the module registration is.

A deployment that drives :meth:`ArticlesService.process_due` from a separate
worker — Celery beat, a cron job, a k8s CronJob — turns this off with the
``scheduler_enabled`` setting, on the Settings screen or via
``scripts/set_setting.py news scheduler_enabled false``. Not an environment
variable: this module reads none, so an ``SM_NEWS_SCHEDULER_ENABLED`` in a
deploy manifest would leave the in-process loop running and racing the worker,
which is exactly the double publish that switch exists to prevent. The setting's
own docstring has the full warning.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from fastapi import FastAPI

from news.settings import NewsSettings

logger = logging.getLogger("simple_module.news.scheduler")


class Scheduler:
    """Owns the polling task and its shutdown."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self, app: FastAPI, settings: NewsSettings) -> None:
        self._task = asyncio.create_task(self._run(app, settings))
        # FastAPI no longer exposes ``add_event_handler`` on the app itself; the
        # router still carries it for ASGI lifespan hooks, which is what this
        # wants — the task lives as long as the app and is cancelled on shutdown
        # rather than outliving it.
        app.router.add_event_handler("shutdown", self.stop)

    async def _run(self, app: FastAPI, settings: NewsSettings) -> None:
        """Publish and unpublish articles at their scheduled times.

        One short session per tick. A failed tick is logged and the loop
        continues — a transient database error must not silently stop every
        future schedule — while cancellation propagates, because that is
        shutdown.
        """
        from news.content import ArticlesService

        factory = app.state.sm.db.session_factory
        interval = max(1, settings.scheduler_interval_seconds)
        while True:
            try:
                await asyncio.sleep(interval)
                async with factory() as session:
                    try:
                        flipped = await ArticlesService(session).process_due(
                            datetime.now(UTC)
                        )
                        if flipped:
                            await session.commit()
                            logger.info(
                                "news.scheduler.flipped",
                                extra={"count": len(flipped)},
                            )
                        else:
                            await session.rollback()
                    except Exception:
                        await session.rollback()
                        raise
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("news.scheduler.tick_failed")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        # Only ``CancelledError`` is suppressed, deliberately narrower than
        # pagebuilder's catch-all: cancelling is the expected outcome here and
        # says nothing, but a tick that died of something else has a traceback
        # worth seeing, and swallowing it at shutdown is how a scheduler that
        # stopped working weeks ago goes unnoticed.
        with suppress(asyncio.CancelledError):
            await task
        self._task = None
