"""The in-process loop that reconciles billing on a schedule (#122).

Off by default: ``reconcile_interval_minutes = 0`` starts no task. Set above
zero, each tick re-reads every Stripe subscription whose ``synced_at`` is older
than the interval — one fetch → ``apply_snapshot`` → quantity push per tenant,
through :func:`sm_billing.reconcile.reconcile_one`, bound to that tenant and
committed with ``finalize_session`` so a suspension publishes
``TenantStatusChanged``. A subscription a webhook refreshed inside the window
is skipped, so a quiet estate costs the provider almost nothing.

**Several app instances.** Every process that boots the module runs a loop.
Each tenant is claimed with one conditional ``UPDATE`` on its own
``synced_at`` (``WHERE synced_at IS NULL OR synced_at < cutoff``) before the
provider is called, so per window exactly one instance fetches a subscription;
the others' ``UPDATE`` matches no row and they move on. The claim stamps
``synced_at`` with the claim time; a failed sync hands it back (the previous
value is restored only if the stamp is still ours), so the next tick retries.
A process that dies mid-sync leaves the stamp — that tenant waits one interval.
Even a lost race would be harmless: the work is idempotent (``set_quantity``
sets, it does not add; a second identical snapshot changes nothing).

**Provider rate limits.** Tenants are reconciled one at a time with a short
pause between them (a few calls a second, far under Stripe's limits, which the
SDK's own retries already back off from). A ``ProviderError`` doubles the pause
up to a cap, and a run of them ends the tick early: an outage is waited out
until the next interval rather than hammered tenant by tenant. A subscription
that failed on the previous tick (one deleted at Stripe, say) is tried *after*
the rest, so a handful of permanently failing rows cannot trip the early stop
ahead of every healthy tenant on every tick.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from simple_module_db import finalize_session
from sqlalchemy import or_, select, update

from sm_billing import constants as c
from sm_billing.contracts.provider import ProviderError
from sm_billing.models import Subscription
from sm_billing.reconcile import ReconcileReport, reconcile_one

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("simple_module.billing.scheduler")

#: Seconds between two tenants in one tick.
PACE_SECONDS = 0.2
#: Ceiling of the doubled pause after provider errors.
MAX_BACKOFF_SECONDS = 30.0
#: Consecutive provider errors that end a tick early.
MAX_PROVIDER_ERRORS = 5


async def _pause(seconds: float) -> None:
    """``asyncio.sleep``, behind a seam tests replace."""
    await asyncio.sleep(seconds)


async def _stale(factory: Any, cutoff: datetime) -> list[tuple[int, str, str, datetime | None]]:
    """Subscriptions at the provider not synced since ``cutoff``, oldest first."""
    stmt = (
        select(
            Subscription.id,
            Subscription.tenant_id,
            Subscription.provider_subscription_id,
            Subscription.synced_at,
        )
        .where(
            Subscription.provider_subscription_id.is_not(None),
            or_(Subscription.synced_at.is_(None), Subscription.synced_at < cutoff),
        )
        .order_by(Subscription.synced_at.asc().nulls_first(), Subscription.id)
    )
    async with factory() as session:
        return list((await session.execute(stmt)).tuples().all())


async def _claim(factory: Any, row_id: int, cutoff: datetime, stamp: datetime) -> bool:
    """Stamp the row's ``synced_at`` if it is still stale; ``True`` if this call won."""
    stmt = (
        update(Subscription)
        .where(
            Subscription.id == row_id,
            or_(Subscription.synced_at.is_(None), Subscription.synced_at < cutoff),
        )
        .values(synced_at=stamp)
    )
    async with factory() as session:
        result = await session.execute(stmt)
        await finalize_session(session)
    return result.rowcount == 1  # ty: ignore[unresolved-attribute] - CursorResult


async def _release(factory: Any, row_id: int, stamp: datetime, previous: datetime | None) -> None:
    """Hand a failed claim back, unless something synced the row since."""
    stmt = (
        update(Subscription)
        .where(Subscription.id == row_id, Subscription.synced_at == stamp)
        .values(synced_at=previous)
    )
    async with factory() as session:
        await session.execute(stmt)
        await finalize_session(session)


async def reconcile_stale(
    app: FastAPI, max_age: timedelta, failing: set[int] | None = None
) -> ReconcileReport:
    """One tick: reconcile every subscription not synced within ``max_age``.

    ``failing`` holds the row ids that failed last tick; they go last, and the
    set is updated in place with this tick's outcome.
    """
    report = ReconcileReport()
    provider = getattr(app.state, c.PACKAGE).provider
    if provider is None or not provider.supports_checkout:
        report.skipped = f"{getattr(provider, 'name', 'no')} provider"
        return report
    factory = app.state.sm.db.session_factory
    cutoff = datetime.now(UTC) - max_age
    failing = set() if failing is None else failing
    pause, provider_errors = PACE_SECONDS, 0
    rows = sorted(await _stale(factory, cutoff), key=lambda r: r[0] in failing)  # stable
    for row_id, tenant_id, subscription_id, previous in rows:
        stamp = datetime.now(UTC)
        if not await _claim(factory, row_id, cutoff, stamp):
            continue  # another instance has it, or a webhook just synced it
        try:
            pushed = await reconcile_one(app, tenant_id, subscription_id)
        except asyncio.CancelledError:
            # Shutdown mid-sync: hand the claim back so the tenant is not parked
            # for an interval by a stamp nobody will finish.
            await asyncio.shield(_release(factory, row_id, stamp, previous))
            raise
        except Exception as exc:
            logger.warning(
                "billing: scheduled reconcile failed for tenant %s", tenant_id, exc_info=True
            )
            report.errors.append((tenant_id, f"{type(exc).__name__}: {exc}"))
            await _release(factory, row_id, stamp, previous)
            failing.add(row_id)
            if isinstance(exc, ProviderError):
                provider_errors += 1
                pause = min(pause * 2, MAX_BACKOFF_SECONDS)
                if provider_errors >= MAX_PROVIDER_ERRORS:
                    report.skipped = "provider failing"
                    logger.warning("billing: provider failing; reconcile resumes next interval")
                    break
        else:
            failing.discard(row_id)
            report.synced += 1
            report.pushed += int(pushed)
            pause, provider_errors = PACE_SECONDS, 0
        await _pause(pause)
    return report


class ReconcileScheduler:
    """Owns the polling task and its shutdown; shaped like news' ``Scheduler``."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        #: Row ids that failed on the last tick; tried last on the next one.
        self._failing: set[int] = set()
        #: The interval the running loop was started with (``None`` until started).
        self.interval: timedelta | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, app: FastAPI, interval: timedelta) -> None:
        # Stopped from ``BillingModule.on_shutdown``: the host's custom lifespan
        # never runs router shutdown handlers (see ``news.scheduler``).
        self.interval = interval
        self._task = asyncio.create_task(self._run(app, interval))

    async def _run(self, app: FastAPI, interval: timedelta) -> None:
        """Sleep, then tick, forever. A failed tick is logged and the loop goes on."""
        while True:
            try:
                await asyncio.sleep(interval.total_seconds())
                report = await reconcile_stale(app, interval, self._failing)
                if report.synced or report.errors:
                    logger.info(
                        "billing: scheduled reconcile synced %d, pushed %d, failed %d",
                        report.synced,
                        report.pushed,
                        len(report.errors),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("billing.scheduler.tick_failed")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        # Logged, never raised: the host calls every module's ``on_shutdown`` in
        # a bare loop, so an exception here would skip the rest and the engine
        # disposal after it.
        try:
            with suppress(asyncio.CancelledError):
                await task
        except Exception:
            logger.exception("billing.scheduler.stop_failed")
