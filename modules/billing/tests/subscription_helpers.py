"""Builders shared by the subscription tests: a snapshot, a seeded plan and
subscription, a suspension, and a signed webhook delivery."""

from __future__ import annotations

import httpx
from fake_provider import GOOD_SIGNATURE, SIGNATURE_HEADER, FakeProvider
from helpers import make_plan
from sm_billing import constants as c
from sm_billing.contracts.provider import SubscriptionSnapshot, WebhookEvent
from sm_billing.models import Customer, Subscription
from tenants.constants import TenantStatus
from tenants.models import Tenant
from tenants.resolver import forget

HEADERS = {SIGNATURE_HEADER: GOOD_SIGNATURE}


def _snap(tenant_id, *, status="active", price="price_team_m", sid="sub_1", quantity=1):
    return SubscriptionSnapshot(
        id=sid,
        customer_id="cus_1",
        tenant_id=tenant_id,
        status=status,
        price_id=price,
        quantity=quantity,
        trial_end=None,
        current_period_end=None,
        cancel_at_period_end=False,
    )


def _fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def _subscribed(app, subject: str, *, pricing_model="flat", **kw) -> int:
    """``subject`` on a ``team`` plan mirrored as ``sub_1`` (customer ``cus_1``)."""
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team", pricing_model=pricing_model)
        fields = {"provider_subscription_id": "sub_1", **kw}
        session.add(Subscription(tenant_id=subject, plan_id=plan.id, **fields))
        session.add(Customer(tenant_id=subject, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()
        return plan.id


async def _team(app, **kw) -> int:
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team", **kw)
        await session.commit()
        return plan.id


async def _subscribe(app, tenant_id, plan_id, **kw) -> None:
    fields = {"provider_subscription_id": "sub_1", **kw}
    async with app.state.sm.db.session_factory() as session:
        session.add(Subscription(tenant_id=tenant_id, plan_id=plan_id, **fields))
        session.add(Customer(tenant_id=tenant_id, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()


async def _suspend(app, tenant_id) -> None:
    async with app.state.sm.db.session_factory() as session:
        (await session.get(Tenant, tenant_id)).status = TenantStatus.SUSPENDED
        await session.commit()
    forget(None)


async def _post_webhook(app, fake, eid, sid="sub_1"):
    fake.events[eid] = WebhookEvent(
        id=eid, type="customer.subscription.updated", subscription_id=sid
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(c.WEBHOOK_PATH, content=eid.encode(), headers=HEADERS)
