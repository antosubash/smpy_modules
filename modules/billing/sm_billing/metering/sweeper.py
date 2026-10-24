"""The hold sweeper: expire lapsed holds, and purge the ledger once a day.

Started from ``startup.run`` next to the reconcile loop and stopped in
``on_shutdown``. Every ``usage_sweep_interval_seconds`` (re-read each tick;
``0`` idles it, for a host that sweeps elsewhere) it selects up to
``BATCH`` holds that are ``held`` past ``expires_at`` and expires each through
``HoldsMixin.expire``, the guarded transition.

**Several app instances.** Every process runs a loop, and two of them may
pick the same hold. The guard is the claim, as in the reconcile scheduler:
``UPDATE … WHERE id = :id AND status = 'held' AND expires_at <= now`` moves
the row for exactly one of them, and only that one lowers the gauge. The
others match no row and move on, so a hold is released once.

**Retention.** Once a day per process, ledger rows recorded more than
``usage_event_retention_days`` ago (``0`` keeps them forever) and holds
settled more than ``SETTLED_HOLD_DAYS`` ago are deleted. The counter and
gauge rollups are never purged. Two instances purging at once delete the
same rows; the second finds nothing. A purged event frees its idempotency
key, which is why the retention is far longer than any retry.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from simple_module_db import finalize_session, mark_written
from sqlalchemy import delete, select

from sm_billing import constants as c
from sm_billing.contracts.metering import HoldStatus
from sm_billing.models import UsageEvent, UsageHold

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sm_billing.metering.service import UsageService

logger = logging.getLogger("simple_module.billing.usage_sweeper")

#: Holds expired per tick at most; the next tick takes the rest.
BATCH = 500
#: Released and expired holds are kept this long, for the admin screens.
SETTLED_HOLD_DAYS = 30
PURGE_EVERY = timedelta(days=1)
#: How often an idle loop (interval 0) looks at the setting again.
IDLE_SECONDS = 60


async def _sleep(seconds: float) -> None:
    """``asyncio.sleep``, behind a seam tests replace."""
    await asyncio.sleep(seconds)


@dataclass
class SweepReport:
    expired: int = 0
    events_purged: int = 0
    holds_purged: int = 0


async def expire_due(usage: UsageService, *, limit: int = BATCH) -> int:
    """Expire up to ``limit`` lapsed holds; how many this call expired."""
    now = usage.now()
    stmt = (
        select(UsageHold.id)
        .where(UsageHold.status == HoldStatus.HELD.value, UsageHold.expires_at <= now)
        .order_by(UsageHold.expires_at)
        .limit(limit)
    )
    async with usage.session_factory() as session:
        due = list((await session.scalars(stmt)).all())
    expired = 0
    for hold_id in due:
        expired += int(await usage.expire(hold_id))
    return expired


async def purge(usage: UsageService, retention_days: int) -> tuple[int, int]:
    """Delete old ledger rows and settled holds; ``(events, holds)`` deleted."""
    now = usage.now()
    holds_before = now - timedelta(days=SETTLED_HOLD_DAYS)
    async with usage.session_factory() as session:
        events = 0
        if retention_days > 0:
            result = await session.execute(
                delete(UsageEvent).where(
                    UsageEvent.recorded_at < now - timedelta(days=retention_days)
                )
            )
            events = result.rowcount  # ty: ignore[unresolved-attribute] - CursorResult
        settled = (HoldStatus.RELEASED.value, HoldStatus.EXPIRED.value)
        result = await session.execute(
            delete(UsageHold).where(
                UsageHold.status.in_(settled), UsageHold.settled_at < holds_before
            )
        )
        holds = result.rowcount  # ty: ignore[unresolved-attribute] - CursorResult
        mark_written(session)
        await finalize_session(session)
    return int(events or 0), int(holds or 0)


class UsageSweeper:
    """Owns the sweep task; shaped like ``ReconcileScheduler``."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._purged_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, app: FastAPI) -> None:
        self._task = asyncio.create_task(self._run(app))

    async def tick(self, app: FastAPI) -> SweepReport:
        usage: UsageService = getattr(app.state, c.USAGE_STATE_ATTR)
        settings = getattr(app.state, c.PACKAGE).settings
        report = SweepReport(expired=await expire_due(usage))
        now = usage.now()
        if self._purged_at is None or now - self._purged_at >= PURGE_EVERY:
            self._purged_at = now
            retention = settings.usage_event_retention_days
            report.events_purged, report.holds_purged = await purge(usage, retention)
        return report

    async def _run(self, app: FastAPI) -> None:
        """Sleep, then sweep, forever. A failed tick is logged and the loop goes on."""
        while True:
            try:
                interval = getattr(app.state, c.PACKAGE).settings.usage_sweep_interval_seconds
                await _sleep(interval or IDLE_SECONDS)
                if not getattr(app.state, c.PACKAGE).settings.usage_sweep_interval_seconds:
                    continue
                report = await self.tick(app)
                if report.expired or report.events_purged or report.holds_purged:
                    logger.info(
                        "billing: usage sweep expired %d hold(s), purged %d event(s) "
                        "and %d settled hold(s)",
                        report.expired,
                        report.events_purged,
                        report.holds_purged,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("billing.usage_sweeper.tick_failed")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        # Logged, never raised: the host calls every module's ``on_shutdown``
        # in a bare loop (see ``ReconcileScheduler.stop``).
        try:
            with suppress(asyncio.CancelledError):
                await task
        except Exception:
            logger.exception("billing.usage_sweeper.stop_failed")
