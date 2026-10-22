"""Webhook deliveries the happy path never sees: an unknown price, a foreign
subscription, and a seat quantity that drifted."""

from __future__ import annotations

import pytest
from fake_provider import FakeProvider
from helpers import make_tenant
from sm_billing.contracts.provider import SubscriptionSnapshot
from sm_billing.models import Subscription
from sm_billing.models import WebhookEvent as EventRow
from sqlalchemy import select
from subscription_helpers import _post_webhook, _snap, _subscribe, _team


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def test_lapsing_snapshot_with_unknown_price_still_applies(app, fake):
    team = await _team(app)
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        await session.commit()
    await _subscribe(app, tenant.id, team)
    fake.snapshots["sub_1"] = _snap(tenant.id, status="canceled", price="price_gone")
    response = await _post_webhook(app, fake, "evt_1")
    assert response.status_code == 200, response.text
    async with app.state.sm.db.session_factory() as session:
        sub = (await session.execute(select(Subscription))).scalar_one()
        assert (sub.status, sub.plan_id) == ("canceled", team)


async def test_foreign_subscription_is_acknowledged_not_retried(app, fake):
    fake.snapshots["sub_1"] = SubscriptionSnapshot(
        "sub_1", "cus_stranger", None, "active", "price_x", 1, None, None, False
    )
    response = await _post_webhook(app, fake, "evt_1")
    assert response.status_code == 200
    async with app.state.sm.db.session_factory() as session:
        row = await session.get(EventRow, "evt_1")
        assert "unknown_tenant" in row.error
        assert row.processed_at is not None


async def test_lapse_for_unknown_price_without_local_row_is_acknowledged(app, fake):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        await session.commit()
    fake.snapshots["sub_1"] = _snap(tenant.id, status="canceled", price="price_gone")
    response = await _post_webhook(app, fake, "evt_1")
    assert response.status_code == 200, response.text
    async with app.state.sm.db.session_factory() as session:
        row = await session.get(EventRow, "evt_1")
        assert "nothing_to_apply" in row.error
        assert row.processed_at is not None
        assert (await session.execute(select(Subscription))).first() is None


async def test_webhook_pushes_drifted_seat_quantity(app, fake):
    team = await _team(app, pricing_model="per_seat")
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, members=3)
        await session.commit()
    await _subscribe(app, tenant.id, team)
    fake.snapshots["sub_1"] = _snap(tenant.id, quantity=1)
    assert (await _post_webhook(app, fake, "evt_1")).status_code == 200
    assert fake.called("set_quantity") == [{"subscription_id": "sub_1", "quantity": 3}]
