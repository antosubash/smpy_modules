"""Builders shared by the tenant-deletion tests: a paying tenant, the real
``TenantService.delete_tenant``, and read-backs of the kept rows."""

from __future__ import annotations

from dataclasses import replace

from helpers import make_plan, make_sub, make_tenant
from simple_module_db import finalize_session
from sm_billing.lifecycle import tenant_service
from sm_billing.models import Customer, Subscription
from sqlalchemy import select
from subscription_helpers import _snap


async def _paying_tenant(
    app, fake, *, sid="sub_1", status="active", with_sub=True, slug="acme", **sub_kw
) -> str:
    """A per-seat tenant with three members and a Stripe customer with an open
    checkout; mirrored and live at the provider unless told otherwise.

    ``sid=None`` makes a local-only subscription row; ``with_sub=False`` none
    at all (a subscription not mirrored yet, for instance).
    """
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, slug, members=3)
        if with_sub:
            plan = await make_plan(session, f"team-{slug}", pricing_model="per_seat")
            fields = {"provider_subscription_id": sid, "quantity": 3, **sub_kw}
            await make_sub(session, tenant, plan, **fields)
        session.add(
            Customer(
                tenant_id=tenant.id,
                provider="stripe",
                provider_customer_id=f"cus_{slug}",
                checkout_session_id="cs_open",
            )
        )
        await session.commit()
        tenant_id = tenant.id
    if with_sub and sid:
        snap = _snap(tenant_id, status=status, sid=sid, quantity=3)
        fake.snapshots[sid] = replace(snap, customer_id=f"cus_{slug}")
    return tenant_id


async def _delete(app, tenant_id: str) -> None:
    """Delete through the tenants module, publishing what it publishes."""
    async with app.state.sm.db.session_factory() as session:
        await tenant_service(session, app).delete_tenant(tenant_id)
        await finalize_session(session)


async def _sub(app, tenant_id: str) -> Subscription | None:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def _customer(app, tenant_id: str) -> Customer | None:
    async with app.state.sm.db.session_factory() as session:
        return await session.get(Customer, tenant_id)
