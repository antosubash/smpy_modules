"""Which plan is in force for a tenant.

A subscription whose status is trialing, active or past_due grants its plan;
anything else — no row, canceled, incomplete, unpaid — falls back to the
default plan. One indexed lookup plus the default; no cache, because a
per-process cache would go stale across workers.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_billing.constants import ENTITLED_STATUSES
from sm_billing.models import Plan, Subscription
from sm_billing.plans import PlanService


async def subscription_for(db: AsyncSession, tenant_id: str) -> Subscription | None:
    stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def effective_plan(db: AsyncSession, tenant_id: str) -> tuple[Plan, Subscription | None]:
    sub = await subscription_for(db, tenant_id)
    if sub is not None and sub.status in ENTITLED_STATUSES:
        plan = await db.get(Plan, sub.plan_id)
        if plan is not None:
            return plan, sub
    return await PlanService(db).default(), sub
