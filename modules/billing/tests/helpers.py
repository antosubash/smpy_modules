"""Row builders shared by the billing tests."""

from __future__ import annotations

from typing import Any

from sm_billing.constants import PricingModel
from sm_billing.models import Plan, Subscription
from tenants.models import Membership, Tenant


async def make_tenant(session, slug: str = "acme", *, members: int = 0) -> Tenant:
    tenant = Tenant(slug=slug, name=slug.title())
    session.add(tenant)
    await session.flush()
    for i in range(members):
        session.add(Membership(tenant_id=tenant.id, user_id=f"u{i}-{slug}", role="member"))
    await session.flush()
    return tenant


async def make_plan(session, key: str = "team", **kw: Any) -> Plan:
    fields: dict[str, Any] = {
        "name": key.title(),
        "pricing_model": PricingModel.FLAT,
        "currency": "eur",
        "stripe_price_month": f"price_{key}_m",
        "stripe_price_year": f"price_{key}_y",
    }
    fields.update(kw)
    plan = Plan(key=key, **fields)
    session.add(plan)
    await session.flush()
    return plan


async def make_sub(session, tenant: Tenant, plan: Plan, **kw: Any) -> Subscription:
    sub = Subscription(tenant_id=tenant.id, plan_id=plan.id, **kw)
    session.add(sub)
    await session.flush()
    return sub
