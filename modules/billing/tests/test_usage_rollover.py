"""Counters reset when the provider starts a new period, with no job to run.

The period comes from ``Subscription.current_period_start``/``_end``, which
only ``sync.apply_snapshot`` writes, from a re-fetched provider snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime

from helpers import make_plan, make_tenant
from simple_module_db import finalize_session
from sm_billing.contracts.metering import Allowed
from sm_billing.contracts.provider import SubscriptionSnapshot
from sm_billing.models import Subscription
from sm_billing.providers.stripe import snapshot_from
from sm_billing.sync import apply_snapshot
from sqlalchemy import select
from usage_helpers import METER, Clock, service, used

A = (datetime(2026, 10, 7, 9, tzinfo=UTC), datetime(2026, 11, 7, 9, tzinfo=UTC))
B = (A[1], datetime(2026, 12, 7, 9, tzinfo=UTC))


def _snap(tenant_id: str, period: tuple[datetime, datetime]) -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        id="sub_1",
        customer_id="cus_1",
        tenant_id=tenant_id,
        status="active",
        price_id="price_team_m",
        quantity=1,
        trial_end=None,
        current_period_end=period[1],
        cancel_at_period_end=False,
        current_period_start=period[0],
    )


async def _sync(app, snap: SubscriptionSnapshot) -> Subscription:
    async with app.state.sm.db.session_factory() as session:
        sub = await apply_snapshot(session, app, snap, provider="stripe")
        await finalize_session(session)
        return sub


async def _tenant_on_team(app, limit: int) -> str:
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "acme")
        await make_plan(session, "team", limits={METER: limit})
        await finalize_session(session)
        return tenant.id


async def test_apply_snapshot_stores_the_period_start(app):
    tenant = await _tenant_on_team(app, 5)
    await _sync(app, _snap(tenant, A))
    async with app.state.sm.db.session_factory() as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.tenant_id == tenant))
        ).scalar_one()
    assert sub.current_period_start.replace(tzinfo=UTC) == A[0]


async def test_counter_resets_at_the_new_period_and_the_old_row_stays(app):
    factory = app.state.sm.db.session_factory
    tenant = await _tenant_on_team(app, 2)
    await _sync(app, _snap(tenant, A))
    clock = Clock(datetime(2026, 10, 20, tzinfo=UTC))
    usage = service(app, clock)
    for key in ("k1", "k2"):
        await usage.consume(tenant, METER, 1, key, source="test")
    refused = await usage.consume(tenant, METER, 1, "k3", source="test")
    assert refused.period_end == A[1]

    # The renewal webhook re-fetches the subscription: the new period lands.
    clock.now = datetime(2026, 11, 8, tzinfo=UTC)
    await _sync(app, _snap(tenant, B))
    fresh = await usage.consume(tenant, METER, 1, "k3", source="test")
    assert fresh == Allowed(used=1, limit=2, period_end=B[1])
    assert await used(factory, tenant, A[0]) == 2
    assert await used(factory, tenant, B[0]) == 1


def test_stripe_snapshot_reads_the_period_start():
    item = {"price": {"id": "price_team_m"}, "quantity": 1, "current_period_start": 1791363600}
    sub = {"id": "sub_1", "status": "active", "items": {"data": [item]}}
    assert snapshot_from(sub).current_period_start == datetime(2026, 10, 7, 9, tzinfo=UTC)
    on_sub = {**sub, "current_period_start": 1793548800}
    assert snapshot_from(on_sub).current_period_start == datetime(2026, 11, 1, 16, tzinfo=UTC)
