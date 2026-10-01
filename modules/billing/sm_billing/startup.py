"""Lifespan-start work: seed the default plan, build the provider, install entitlements.

Runs after settings hydration and after ``tenants``' own startup
(``depends_on``), so ``app.state.sm_billing.settings`` holds the DB values and
``app.state.tenants`` exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sm_billing import constants as c
from sm_billing.entitlements import PlanEntitlements
from sm_billing.plans import seed_default_plan

if TYPE_CHECKING:
    from fastapi import FastAPI


async def run(app: FastAPI) -> None:
    session_factory = app.state.sm.db.session_factory
    await seed_default_plan(session_factory)
    app.state.tenants.entitlements = PlanEntitlements(session_factory)
    services = getattr(app.state, c.PACKAGE)
    from sm_billing.providers.factory import install_provider

    install_provider(services)
