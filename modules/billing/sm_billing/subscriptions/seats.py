"""Per-seat quantity sync on membership changes.

The tenants module publishes ``MembershipAdded``/``MembershipRemoved`` after
its commit, inline in the request. The handler opens its own session, and a
provider failure is logged, never raised: the membership change already
happened and must stand. The drift stays until a reconcile pushes it: the
periodic one if ``reconcile_interval_minutes`` is set, else ``smpy billing
reconcile`` or the admin Resync.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from simple_module_db import finalize_session

from sm_billing.core import constants as c
from sm_billing.core import subjects
from sm_billing.models import Subscription
from sm_billing.plans.resolve import effective_plan
from sm_billing.subscriptions.lifecycle import tenant_gone, tenant_service

if TYPE_CHECKING:
    from fastapi import FastAPI
    from simple_module_core.events import EventBus

logger = logging.getLogger(__name__)


async def push_quantity(app: FastAPI, tenant_id: str) -> bool:
    """Make the provider's quantity equal the member count. ``True`` if pushed.

    Never for a user subject (#274): a user has no members, and checkout and
    plan changes refuse it a per-seat plan.
    """
    if subjects.kind(tenant_id) == c.SUBJECT_MODE_USER:
        return False
    provider = getattr(app.state, c.PACKAGE).provider
    if provider is None or not provider.supports_checkout:
        return False
    # The provider call runs between two short transactions, never inside one:
    # the first only reads, and ends before the network call so no connection
    # or row lock is held while the provider answers.
    async with app.state.sm.db.session_factory() as session:
        if await tenant_gone(session, app, tenant_id):
            # ``delete_tenant`` publishes a ``MembershipRemoved`` per member
            # before ``TenantDeleted``; resizing a subscription about to be
            # canceled would only leave a proration behind.
            return False
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
        sub_id, provider_sub_id = sub.id, sub.provider_subscription_id
        await finalize_session(session)  # read-only: ends the transaction
    await provider.set_quantity(provider_sub_id, members)
    async with app.state.sm.db.session_factory() as session:
        sub = await session.get(Subscription, sub_id)
        if sub is not None:
            sub.quantity = members
        await finalize_session(session)
    return True


def subscribe(bus: EventBus, app: FastAPI) -> None:
    """Subscribe the membership handlers."""
    from tenants.contracts.events import MembershipAdded, MembershipRemoved

    async def _sync(event: MembershipAdded | MembershipRemoved) -> None:
        from sm_billing.core.live import ensure_current

        try:
            await ensure_current(app)  # not through a provider another worker replaced
            await push_quantity(app, event.tenant_id)
        except Exception:
            logger.warning(
                "billing: seat sync failed for tenant %s; the next reconcile pushes it "
                "(scheduled only if reconcile_interval_minutes is set)",
                event.tenant_id,
                exc_info=True,
            )

    bus.subscribe(MembershipAdded, _sync)
    bus.subscribe(MembershipRemoved, _sync)
