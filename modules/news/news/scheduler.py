"""The in-process loop that publishes articles at their scheduled times.

Lifted out of :mod:`news.module` when that file crossed the repo's 300-line
cap, and shaped like :mod:`pagebuilder.scheduler` for the same reason: it is a
coherent piece to lift, because everything here is about *when* an article
changes state and nothing else in the module registration is.

One of these runs per process, so a replica set runs several. That is no longer
a hazard: :meth:`ArticlesService.process_due` claims each due article with a
single conditional ``UPDATE`` before flipping it, so two ticks landing on the
same instant flip it exactly once — see :mod:`news.content._claims`. The same
holds for a separate worker driving ``process_due`` alongside the loop.

``scheduler_enabled`` turns this off anyway where a deployment would rather one
place did the polling — Celery beat, a cron job, a k8s CronJob. It is set on the
Settings screen or via ``scripts/set_setting.py news scheduler_enabled false``,
never an environment variable: this module reads none, so an
``SM_NEWS_SCHEDULER_ENABLED`` in a deploy manifest would leave the loop running
with nothing on screen saying so. The setting's own docstring has the detail.
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
        try:
            # Only ``CancelledError`` is suppressed, and that narrowness is the
            # point: cancelling is the expected outcome of the line above and
            # says nothing, while a task that died of something else has a
            # traceback worth seeing. ``_run`` already logs and continues past a
            # failed *tick*, so anything arriving here died before the loop — a
            # missing ``app.state.sm``, an import that failed — and quietly
            # discarding it is how a scheduler that stopped working weeks ago
            # goes unnoticed.
            with suppress(asyncio.CancelledError):
                await task
        except Exception:
            # Logged rather than re-raised, which is not general defensiveness:
            # FastAPI's ``Router._shutdown`` is a bare ``for`` over the
            # registered shutdown handlers with no ``try`` around each one
            # (``fastapi/routing.py``), so an exception escaping this handler
            # aborts that loop and every handler registered after news' never
            # runs — including another module's scheduler, whose polling task
            # would then never be cancelled at all. Nothing about this failure
            # is lost; only its blast radius. Pagebuilder's ``stop`` does the
            # same, for the same reason and in the other direction.
            logger.exception("news.scheduler.stop_failed")
        finally:
            self._task = None
