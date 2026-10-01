"""Write a provider snapshot onto the local mirror.

One function, used by webhooks, reconcile and the admin "Resync" button, so
there is exactly one place that decides how provider state becomes local
state. Failures raise ``SyncError`` rather than guessing: an unknown price or
tenant must never quietly hand a paying customer the default plan.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from tenants.models import Tenant

from sm_billing.constants import STRIPE_STATUS_MAP, SubscriptionStatus
from sm_billing.lifecycle import apply_lifecycle
from sm_billing.models import Customer, Subscription
from sm_billing.plans import PlanService

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.contracts.provider import SubscriptionSnapshot


class SyncError(Exception):
    """The snapshot cannot be mapped onto a tenant and plan."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


async def _tenant_for(db: AsyncSession, snap: SubscriptionSnapshot) -> str:
    if snap.tenant_id and await db.get(Tenant, snap.tenant_id) is not None:
        return snap.tenant_id
    if snap.customer_id:
        stmt = select(Customer).where(Customer.provider_customer_id == snap.customer_id)
        customer = (await db.execute(stmt)).scalar_one_or_none()
        if customer is not None:
            return customer.tenant_id
    raise SyncError("unknown_tenant", f"subscription {snap.id}")


async def _link_customer(db: AsyncSession, tenant_id: str, customer_id: str | None, provider: str):
    if not customer_id:
        return
    customer = await db.get(Customer, tenant_id)
    if customer is None:
        db.add(Customer(tenant_id=tenant_id, provider=provider, provider_customer_id=customer_id))
    elif customer.provider_customer_id != customer_id:
        customer.provider_customer_id = customer_id
        customer.provider = provider


async def apply_snapshot(
    db: AsyncSession, app: FastAPI, snap: SubscriptionSnapshot, *, provider: str
) -> Subscription:
    """Upsert the tenant's subscription from ``snap`` and apply the lifecycle.

    Flushes, never commits (see ``apply_lifecycle`` for why the caller must
    finalize). Returns the tenant's subscription row.
    """
    status = STRIPE_STATUS_MAP.get(snap.status)
    if status is None:
        raise SyncError("unknown_status", snap.status)
    tenant_id = await _tenant_for(db, snap)
    stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
    sub = (await db.execute(stmt)).scalar_one_or_none()

    # A late event for a tenant's *previous* subscription (canceled before
    # they re-subscribed) must not overwrite the live one.
    if (
        sub is not None
        and sub.provider_subscription_id not in (None, snap.id)
        and status == SubscriptionStatus.CANCELED
    ):
        return sub

    match = await PlanService(db).by_price(snap.price_id) if snap.price_id else None
    if match is None:
        raise SyncError("unknown_price", snap.price_id or "(none)")
    plan, interval = match

    await _link_customer(db, tenant_id, snap.customer_id, provider)
    if sub is None:
        sub = Subscription(tenant_id=tenant_id, plan_id=plan.id)
        db.add(sub)
    sub.plan_id = plan.id
    sub.status = status
    sub.interval = interval
    sub.provider_subscription_id = snap.id
    sub.quantity = max(1, snap.quantity)
    sub.trial_end = snap.trial_end
    sub.current_period_end = snap.current_period_end
    sub.cancel_at_period_end = snap.cancel_at_period_end
    sub.synced_at = datetime.now(UTC)
    await db.flush()
    await apply_lifecycle(db, app, sub)
    return sub
