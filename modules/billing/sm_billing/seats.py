"""Per-seat quantity sync on membership changes.

The tenants module publishes ``MembershipAdded``/``MembershipRemoved`` after
its commit, inline in the request. The handler opens its own session, and a
provider failure is logged, never raised: the membership change already
happened and must stand. ``reconcile`` pushes any drift left behind.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sm_billing import constants as c
from sm_billing.lifecycle import tenant_service
from sm_billing.resolve import effective_plan

if TYPE_CHECKING:
    from fastapi import FastAPI
    from simple_module_core.events import EventBus

logger = logging.getLogger(__name__)


async def push_quantity(app: FastAPI, tenant_id: str) -> bool:
    """Make the provider's quantity equal the member count. ``True`` if pushed."""
    provider = getattr(app.state, c.PACKAGE).provider
    if provider is None or not provider.supports_checkout:
        return False
    async with app.state.sm.db.session_factory() as session:
        plan, sub = await effective_plan(session, tenant_id)
        if (
            sub is None
            or sub.provider_subscription_id is None
            or plan.pricing_model != c.PricingModel.PER_SEAT
        ):
            return False
        counts = await tenant_service(session, app).member_counts([tenant_id])
        members = max(1, counts.get(tenant_id, 0))
        if members == sub.quantity:
            return False
        await provider.set_quantity(sub.provider_subscription_id, members)
        sub.quantity = members
        await session.commit()
    return True


def subscribe(bus: EventBus, app: FastAPI) -> None:
    """Subscribe the membership handlers."""
    from tenants.contracts.events import MembershipAdded, MembershipRemoved

    async def _sync(event: MembershipAdded | MembershipRemoved) -> None:
        try:
            await push_quantity(app, event.tenant_id)
        except Exception:
            logger.warning(
                "billing: seat sync failed for tenant %s; reconcile will retry",
                event.tenant_id,
                exc_info=True,
            )

    bus.subscribe(MembershipAdded, _sync)
    bus.subscribe(MembershipRemoved, _sync)
