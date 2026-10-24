"""Every failed teardown has a retry path, and a finished one costs nothing (#92).

The reconcile sweep reaches what ``reconcile_one`` cannot: a deleted tenant
with no mirrored subscription. Driven through the real ``delete_tenant``.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fake_provider import FakeProvider
from sm_billing import teardown
from sm_billing.constants import PROVIDER_CANCELABLE_STATUSES, SubscriptionStatus
from sm_billing.contracts.provider import CheckoutSnapshot
from sm_billing.reconcile import reconcile
from sm_billing.scheduler import reconcile_stale
from subscription_helpers import _snap
from teardown_helpers import _customer, _delete, _paying_tenant, _sub

CUS = "cus_acme"


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    from sm_billing import scheduler

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(scheduler, "_pause", instant)


def _unmirrored(fake, tenant_id: str, sid: str = "sub_new") -> None:
    """A subscription live at Stripe that no webhook has mirrored yet."""
    fake.live[CUS] = [sid]
    fake.snapshots[sid] = _snap(tenant_id, sid=sid)


async def test_an_unmirrored_subscription_whose_cancel_failed_is_retried(app, fake):
    tenant_id = await _paying_tenant(app, fake, with_sub=False)
    _unmirrored(fake, tenant_id)
    fake.fail.add("cancel_now")
    await _delete(app, tenant_id)
    assert (await _customer(app, tenant_id)).teardown_done_at is None

    fake.fail.clear()
    report = await reconcile(app)
    assert (report.errors, report.torn_down) == ([], 1)
    assert fake.snapshots["sub_new"].status == "canceled"
    assert (await _customer(app, tenant_id)).teardown_done_at is not None


async def test_a_local_only_row_whose_customer_cancel_failed_is_retried(app, fake):
    tenant_id = await _paying_tenant(app, fake, sid=None)
    _unmirrored(fake, tenant_id)
    fake.fail.add("cancel_now")
    await _delete(app, tenant_id)
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED

    fake.fail.clear()
    assert (await reconcile(app)).torn_down == 1
    assert fake.snapshots["sub_new"].status == "canceled"


async def test_the_scheduled_tick_sweeps_too(app, fake):
    tenant_id = await _paying_tenant(app, fake, with_sub=False)
    _unmirrored(fake, tenant_id)
    fake.fail.add("cancel_now")
    await _delete(app, tenant_id)
    fake.fail.clear()
    report = await reconcile_stale(app, timedelta(minutes=60))
    assert report.torn_down == 1
    assert fake.snapshots["sub_new"].status == "canceled"


async def test_an_open_checkout_with_nothing_mirrored_is_retried(app, fake):
    tenant_id = await _paying_tenant(app, fake, with_sub=False)
    fake.fail.add("expire_checkout")
    fake.checkouts["cs_open"] = CheckoutSnapshot("cs_open", None, tenant_id, CUS, "open")
    await _delete(app, tenant_id)
    assert (await _customer(app, tenant_id)).checkout_session_id == "cs_open"

    fake.fail.clear()
    assert (await reconcile(app)).torn_down == 1
    customer = await _customer(app, tenant_id)
    assert customer.checkout_session_id is None
    assert customer.teardown_done_at is not None


async def test_a_finished_teardown_costs_the_sweep_nothing(app, fake):
    tenant_id = await _paying_tenant(app, fake, with_sub=False)
    _unmirrored(fake, tenant_id)
    await _delete(app, tenant_id)
    assert (await _customer(app, tenant_id)).teardown_done_at is not None
    fake.calls.clear()
    report = await reconcile(app)
    assert (report.torn_down, fake.calls) == (0, [])


async def test_a_second_event_after_success_only_checks_the_mirrored_one(app, fake):
    from tenants.contracts.events import TenantDeleted

    tenant_id = await _paying_tenant(app, fake)
    await _delete(app, tenant_id)
    fake.calls.clear()
    await app.state.sm.event_bus.publish(TenantDeleted(tenant_id, "acme", "Acme"))
    assert [name for name, _ in fake.calls] == ["fetch_subscription", "fetch_subscription"]


async def test_teardown_lists_with_the_cancelable_set(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    await _delete(app, tenant_id)
    assert fake.called("live_subscription_ids") == [
        {"customer_id": CUS, "statuses": PROVIDER_CANCELABLE_STATUSES}
    ]


async def test_a_cancel_refused_because_it_already_ended_counts_as_done(app, fake):
    """Another canceler (a concurrent reconcile, Stripe itself) won the race."""
    tenant_id = await _paying_tenant(app, fake, with_sub=False)
    fake.live[CUS] = ["sub_gone"]
    fake.snapshots["sub_gone"] = _snap(tenant_id, sid="sub_gone", status="canceled")
    fake.fail.add("cancel_now")
    await _delete(app, tenant_id)
    assert (await _customer(app, tenant_id)).teardown_done_at is not None


async def test_teardown_and_reconcile_at_once_end_canceled(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    async with app.state.sm.db.session_factory() as session:
        from tenants.models import Tenant

        await session.delete(await session.get(Tenant, tenant_id))
        await session.commit()  # gone, but no event yet: both race for it
    results = await asyncio.gather(
        teardown.cancel_for_deleted_tenant(app, tenant_id), reconcile(app)
    )
    assert results[1].errors == []
    assert fake.snapshots["sub_1"].status == "canceled"
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED


def test_an_older_tenants_without_the_event_subscribes_nothing(app, monkeypatch):
    """simple_module_tenants 0.0.36/0.0.37 has no TenantDeleted."""
    import tenants.contracts.events as events

    monkeypatch.delattr(events, "TenantDeleted")

    class Bus:
        def __init__(self) -> None:
            self.subscribed: list = []

        def subscribe(self, event_type, handler) -> None:
            self.subscribed.append(event_type)

    bus = Bus()
    teardown.subscribe(bus, app)
    assert bus.subscribed == []
