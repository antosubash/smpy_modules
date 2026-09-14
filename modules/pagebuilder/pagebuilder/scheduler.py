"""The in-process loop that flips pages on their scheduled times.

Lifted out of :mod:`pagebuilder.module` when that file crossed the repo's
300-line cap. It is a coherent piece to lift: everything here is about *when*
a page changes state, and nothing else in the module registration is.

A deployment that drives :meth:`PagesService.process_due` from a separate
worker (Celery beat, a k8s CronJob) turns this off with the
``scheduler_enabled`` setting — on the Settings screen, or
``scripts/set_setting.py pagebuilder scheduler_enabled false``. Not an
environment variable: this module reads none, so an
``SM_PAGEBUILDER_SCHEDULER_ENABLED`` in a deploy manifest would leave the
in-process loop running and racing the worker, which is exactly the
double-publish this switch exists to prevent.
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
        # Not wired through ``app.router.add_event_handler("shutdown", ...)``:
        # the host builds the app with a custom ``lifespan=``, and under a
        # custom lifespan FastAPI never installs the ``_DefaultLifespan`` that
        # drains the router's own shutdown-handler list, so a handler added
        # that way is never called. The host's lifespan instead calls every
        # module's ``on_shutdown(app)`` directly — see
        # :meth:`PagebuilderModule.on_shutdown`, which is what actually stops
        # this task.

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
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            # Only ``CancelledError`` is suppressed — it is the expected
            # outcome of the ``cancel`` above and says nothing. It used to be
            # ``(CancelledError, Exception)``, which swallowed everything, and
            # that is how a scheduler which stopped working weeks ago goes
            # unnoticed. ``_run`` already logs and continues past a failed
            # tick, so anything reaching here died *before* the loop — a
            # missing ``app.state.sm``, an import that failed — and has a
            # traceback worth seeing. Matches ``news.scheduler.Scheduler``.
            with contextlib.suppress(asyncio.CancelledError):
                await task
        except Exception:
            # Logged rather than re-raised. FastAPI runs shutdown handlers in
            # a plain loop with no ``try`` around each one, so raising here
            # would skip every handler registered after this module's —
            # including another module's scheduler, which would then never be
            # stopped at all.
            _log.exception("pagebuilder.scheduler.stop_failed")
        finally:
            self._task = None
