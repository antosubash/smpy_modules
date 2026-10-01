"""Per-seat quantity sync, reconcile and the CLI wrapper."""

from __future__ import annotations

import pytest
from fake_provider import FakeProvider
from helpers import make_plan, make_sub, make_tenant
from sm_billing.cli import app as cli_app
from sm_billing.contracts.provider import SubscriptionSnapshot
from sm_billing.models import Subscription
from sm_billing.reconcile import reconcile
from sm_billing.seats import push_quantity
from sqlalchemy import select
from tenants.contracts.events import MembershipAdded, MembershipRemoved
from tenants.models import Membership
from typer.testing import CliRunner


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def _tenant_on(app, pricing_model: str, *, members: int, quantity: int = 1) -> str:
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, members=members)
        plan = await make_plan(session, "team", pricing_model=pricing_model)
        await make_sub(session, tenant, plan, provider_subscription_id="sub_1", quantity=quantity)
        await session.commit()
        return tenant.id


async def _quantity(app, tenant_id: str) -> int:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
        return (await session.execute(stmt)).scalar_one().quantity


async def test_member_added_pushes_quantity_on_per_seat(app, fake):
    tenant_id = await _tenant_on(app, "per_seat", members=3)
    await app.state.sm.event_bus.publish(MembershipAdded(tenant_id, "u-new", "member"))
    assert fake.called("set_quantity") == [{"subscription_id": "sub_1", "quantity": 3}]
    assert await _quantity(app, tenant_id) == 3


async def test_member_removed_pushes_quantity(app, fake):
    tenant_id = await _tenant_on(app, "per_seat", members=2, quantity=3)
    await app.state.sm.event_bus.publish(MembershipRemoved(tenant_id, "u-gone"))
    assert fake.called("set_quantity")[-1]["quantity"] == 2


async def test_flat_plan_never_touches_provider(app, fake):
    tenant_id = await _tenant_on(app, "flat", members=5)
    await app.state.sm.event_bus.publish(MembershipAdded(tenant_id, "u-new", "member"))
    assert fake.called("set_quantity") == []


async def test_unchanged_quantity_is_not_pushed(app, fake):
    tenant_id = await _tenant_on(app, "per_seat", members=2, quantity=2)
    assert await push_quantity(app, tenant_id) is False
    assert fake.called("set_quantity") == []


async def test_provider_failure_is_swallowed(app, fake, caplog):
    tenant_id = await _tenant_on(app, "per_seat", members=4)
    fake.fail.add("set_quantity")
    with caplog.at_level("WARNING"):
        await app.state.sm.event_bus.publish(MembershipAdded(tenant_id, "u-new", "member"))
    assert await _quantity(app, tenant_id) == 1
    assert any("seat sync" in r.message for r in caplog.records)


async def test_manual_provider_skips(app):
    tenant_id = await _tenant_on(app, "per_seat", members=4)
    assert await push_quantity(app, tenant_id) is False


async def test_reconcile_refreshes_status_and_pushes_drift(app, fake):
    tenant_id = await _tenant_on(app, "per_seat", members=3)
    fake.snapshots["sub_1"] = SubscriptionSnapshot(
        id="sub_1", customer_id="cus_1", tenant_id=tenant_id, status="past_due",
        price_id="price_team_m", quantity=1, trial_end=None, current_period_end=None,
        cancel_at_period_end=False,
    )
    report = await reconcile(app)
    assert (report.synced, report.pushed, report.errors) == (1, 1, [])
    async with app.state.sm.db.session_factory() as session:
        sub = (await session.execute(select(Subscription))).scalar_one()
        assert (sub.status, sub.quantity) == ("past_due", 3)


async def test_reconcile_collects_errors_and_filters_tenant(app, fake):
    tenant_id = await _tenant_on(app, "flat", members=1)
    report = await reconcile(app, tenant_id="someone-else")
    assert report.synced == 0
    report = await reconcile(app, tenant_id=tenant_id)  # no snapshot scripted → KeyError
    assert report.synced == 0
    assert report.errors and report.errors[0][0] == tenant_id


async def test_reconcile_under_manual_does_nothing(app):
    await _tenant_on(app, "flat", members=1)
    report = await reconcile(app)
    assert (report.synced, report.skipped) == (0, "manual provider")


def test_cli_lists_reconcile():
    result = CliRunner().invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    assert "reconcile" in result.output


async def test_members_count_matches_rows(app):
    tenant_id = await _tenant_on(app, "per_seat", members=2)
    async with app.state.sm.db.session_factory() as session:
        rows = (await session.execute(select(Membership).where(
            Membership.tenant_id == tenant_id))).scalars().all()
    assert len(rows) == 2
