"""The loop that runs the submission retention sweep (#101, design §10).

Shaped like news' and pagebuilder's schedulers: one task per process, started
from ``on_startup`` (:func:`start`) and cancelled from ``on_shutdown``
(:func:`stop`) — not through the router's shutdown handlers, which a host with
a custom ``lifespan=`` never runs. Several processes each run one; the sweep's
lease makes all but one of them a no-op (:mod:`.retention`).

The settings are read **every tick** from ``app.state.sm_records.settings``,
so switching the sweep off or changing its interval on the Settings screen
takes effect on the next tick, without a restart. A failed tick is logged and
the loop goes on; cancellation propagates, because that is shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from sm_records import constants
from sm_records.public_submissions.retention import sweep
from sm_records.settings import RecordsSettings

__all__ = ["TASK_ATTR", "start", "stop"]

logger = logging.getLogger(__name__)

TASK_ATTR = "retention_task"
"""Where the module instance keeps its task."""

FIRST_SWEEP_AFTER = 60
"""Seconds from startup to the first sweep — past the boot's own work."""


def _settings(app: Any, module: Any) -> RecordsSettings:
    services = getattr(app.state, constants.PACKAGE, None)
    current = getattr(services, "settings", None) or getattr(module, "settings", None)
    return current if isinstance(current, RecordsSettings) else RecordsSettings()


async def _run(app: Any, module: Any) -> None:
    factory = app.state.sm.db.session_factory
    bus = getattr(app.state.sm, "event_bus", None)
    # The first sweep soon after startup rather than a whole interval later:
    # a host restarted more often than the interval would otherwise never sweep.
    delay = FIRST_SWEEP_AFTER
    while True:
        await asyncio.sleep(delay)
        settings = _settings(app, module)
        delay = settings.public_submissions_retention_interval_seconds
        if not settings.public_submissions_retention_enabled:
            continue
        try:
            await sweep(factory, settings, bus=bus)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("records: the retention sweep failed")


def start(module: Any, app: Any) -> None:
    """Start the loop once per module instance — ``on_startup`` may run again
    in-process — and only with a database to sweep."""
    if getattr(getattr(app.state, "sm", None), "db", None) is None:
        return
    task = getattr(module, TASK_ATTR, None)
    if task is not None and not task.done():
        return
    setattr(module, TASK_ATTR, asyncio.create_task(_run(app, module)))


async def stop(module: Any) -> None:
    task = getattr(module, TASK_ATTR, None)
    if task is None:
        return
    task.cancel()
    try:
        with suppress(asyncio.CancelledError):
            await task
    except Exception:
        # Logged, not raised: the host calls every module's ``on_shutdown`` in
        # a bare loop, so raising here would skip the modules after this one.
        logger.exception("records: the retention loop died before shutdown")
    finally:
        setattr(module, TASK_ATTR, None)
