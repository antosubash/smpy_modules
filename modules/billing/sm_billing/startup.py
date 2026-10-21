"""Lifespan-start work: seed the default plan, build the provider, install
entitlements, and start the periodic reconcile if one is configured.

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


def start_reconcile(app: FastAPI) -> None:
    """Start the reconcile loop when the interval is set and a provider can sync.

    Read here, not at construction: this is the first point the hydrated
    settings exist. ``reconcile_interval_minutes`` is therefore restart-only.
    """
    from sm_billing.scheduler import ReconcileScheduler

    services = getattr(app.state, c.PACKAGE)
    minutes = services.settings.reconcile_interval_minutes
    if minutes <= 0:
        return
    if services.provider is None or not services.provider.supports_checkout:
        logger.info(
            "billing: reconcile_interval_minutes is set but the provider has nothing to sync"
        )
        return
    services.scheduler = ReconcileScheduler()
    services.scheduler.start(app, timedelta(minutes=minutes))


async def stop_reconcile(app: FastAPI) -> None:
    services = getattr(app.state, c.PACKAGE, None)
    scheduler = getattr(services, "scheduler", None)
    if scheduler is not None:
        services.scheduler = None
        await scheduler.stop()
