"""Lifespan-start work: seed the default plan, build the provider, install
entitlements, and start the periodic reconcile if one is configured.

Later settings changes rebuild the provider and re-sync the loop through
``sm_billing.live``, which calls :func:`sync_reconcile`.

Runs after settings hydration and after ``tenants``' own startup
(``depends_on``), so ``app.state.sm_billing.settings`` holds the DB values and
``app.state.tenants`` exists.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from sm_billing import constants as c
from sm_billing.entitlements import PlanEntitlements
from sm_billing.plans import seed_default_plan

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def run(app: FastAPI) -> None:
    session_factory = app.state.sm.db.session_factory
    await seed_default_plan(session_factory)
    app.state.tenants.entitlements = PlanEntitlements(session_factory)
    services = getattr(app.state, c.PACKAGE)
    from sm_billing.providers.factory import install_provider

    install_provider(services)
    start_reconcile(app)


def _wanted_interval(app: FastAPI) -> timedelta | None:
    """The interval the loop should run at now, or ``None`` if it should not run."""
    services = getattr(app.state, c.PACKAGE)
    minutes = services.settings.reconcile_interval_minutes
    if minutes <= 0:
        return None
    if services.provider is None or not services.provider.supports_checkout:
        logger.info(
            "billing: reconcile_interval_minutes is set but the provider has nothing to sync"
        )
        return None
    return timedelta(minutes=minutes)


def start_reconcile(app: FastAPI) -> None:
    """Start the reconcile loop when the interval is set and a provider can sync.

    Read here, not at construction: this is the first point the hydrated
    settings exist. Later changes go through :func:`sync_reconcile`.
    """
    interval = _wanted_interval(app)
    if interval is not None:
        _start(app, interval)


def _start(app: FastAPI, interval: timedelta) -> None:
    from sm_billing.scheduler import ReconcileScheduler

    services = getattr(app.state, c.PACKAGE)
    services.scheduler = ReconcileScheduler()
    services.scheduler.start(app, interval)


async def sync_reconcile(app: FastAPI) -> None:
    """Bring the loop in line with the live settings and provider (#85).

    Starts it, stops it, or restarts it at a new interval; a loop already
    running at the wanted interval is left alone, so its timer is not reset.
    """
    services = getattr(app.state, c.PACKAGE)
    current = services.scheduler
    running = current.interval if current is not None and current.running else None
    wanted = _wanted_interval(app)
    if wanted == running:
        return
    await stop_reconcile(app)
    if wanted is not None:
        _start(app, wanted)


async def stop_reconcile(app: FastAPI) -> None:
    services = getattr(app.state, c.PACKAGE, None)
    scheduler = getattr(services, "scheduler", None)
    if scheduler is not None:
        services.scheduler = None
        await scheduler.stop()
