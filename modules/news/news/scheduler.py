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
from typing import Any

from fastapi import FastAPI

from news.settings import NewsSettings

logger = logging.getLogger("simple_module.news.scheduler")


async def _due_tenants(factory: Any, now: datetime) -> list[str]:
    """Distinct tenants with a scheduled flip due or a missed window to retire.

    Read unscoped on a session of its own, closed before any tenant's work
    starts, so nothing read here is carried into a tenant's transaction.
    """
    from simple_module_db import all_tenants
    from sqlalchemy import select

    from news.content._claims import any_due
    from news.models import NewsArticle

    with all_tenants():
        async with factory() as session:
            rows = await session.execute(
                select(NewsArticle.tenant_id).where(any_due(now)).distinct()
            )
            return sorted(rows.scalars().all())


class Scheduler:
    """Owns the polling task and its shutdown."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def start(self, app: FastAPI, settings: NewsSettings) -> None:
        self._task = asyncio.create_task(self._run(app, settings))
        # Not wired through ``app.router.add_event_handler("shutdown", ...)``:
        # the host builds the app with a custom ``lifespan=``, and under a
        # custom lifespan FastAPI never installs the ``_DefaultLifespan`` that
        # drains the router's own shutdown-handler list, so a handler added
        # that way is never called. The host's lifespan instead calls every
        # module's ``on_shutdown(app)`` directly — see :meth:`NewsModule.on_shutdown`,
        # which is what actually stops this task.

    async def _run(self, app: FastAPI, settings: NewsSettings) -> None:
        """Publish and unpublish articles at their scheduled times.

        One short session per tick. A failed tick is logged and the loop
        continues — a transient database error must not silently stop every
        future schedule — while cancellation propagates, because that is
        shutdown.
        """
        factory = app.state.sm.db.session_factory
        interval = max(1, settings.scheduler_interval_seconds)
        while True:
            try:
                await asyncio.sleep(interval)
                await self.tick(factory)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("news.scheduler.tick_failed")

    async def tick(self, factory: Any) -> None:
        """Find the tenants with work, then run each in its own tenant context.

        The tick runs outside any request, so nothing binds a tenant for it, and
        the claim sweep in :mod:`news.content._claims` only sees the bound one.
        One code path for single- and multi-tenant hosts: a single-tenant host's
        rows are all :data:`~news.tenancy.DEFAULT_TENANT`. A tenant that fails
        is logged and does not stop the rest.
        """
        from simple_module_db import tenant_context

        for tenant_id in await _due_tenants(factory, datetime.now(UTC)):
            try:
                with tenant_context(tenant_id):
                    await self._tick_tenant(factory)
            except Exception:
                logger.exception("news.scheduler.tenant_failed", extra={"tenant_id": tenant_id})

    async def _tick_tenant(self, factory: Any) -> None:
        """One pass in the bound tenant: flip what is due, in one short session.

        Always committed, never only when something flipped. ``process_due``
        also writes without flipping — it retires a draft whose whole window
        passed while no scheduler ran, and it hands a refused claim back — and
        a rollback on an empty tick would discard the retirement, so the same
        row would be found, warned about and rolled back again every interval,
        forever.
        """
        from news.content import ArticlesService

        async with factory() as session:
            try:
                flipped = await ArticlesService(session).process_due(datetime.now(UTC))
                await session.commit()
                if flipped:
                    logger.info("news.scheduler.flipped", extra={"count": len(flipped)})
            except Exception:
                await session.rollback()
                raise

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
            # Logged rather than re-raised, which is not general defensiveness.
            # This is reached from ``NewsModule.on_shutdown``, which the host's
            # lifespan calls in a bare ``for mod in reversed(modules)`` with no
            # ``try`` around each one — and then disposes the database engine
            # *after* the loop (``simple_module_hosting/app_builder.py``). An
            # exception escaping here therefore skips every module registered
            # before news' — another scheduler's polling task never cancelled —
            # and skips the engine disposal too. Nothing about this failure is
            # lost; only its blast radius. Pagebuilder's ``stop`` does the
            # same, for the same reason and in the other direction.
            logger.exception("news.scheduler.stop_failed")
        finally:
            self._task = None
