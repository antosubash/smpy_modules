"""Deleting a tenant cancels its subscription at the provider (#92, upstream #491).

Driven through the real ``TenantService.delete_tenant`` and
``finalize_session``, so ``MembershipRemoved`` and ``TenantDeleted`` reach
billing exactly as they do from the tenants module.
"""

from __future__ import annotations

import pytest
from fake_provider import FakeProvider
from helpers import make_plan, make_sub, make_tenant
from sm_billing.constants import PROVIDER_CANCELABLE_STATUSES, SubscriptionStatus
from sm_billing.contracts.provider import CheckoutSnapshot
from sm_billing.models import Customer
from sm_billing.reconcile import reconcile
from teardown_helpers import _delete, _make_due, _paying_tenant, _sub
from tenants.contracts.events import TenantDeleted
from tenants.models import Tenant

CUS = "cus_acme"


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def test_delete_cancels_immediately_and_keeps_the_rows(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    await _delete(app, tenant_id)

    assert fake.called("cancel_now") == [{"subscription_id": "sub_1"}]
    assert fake.called("cancel_at_period_end") == []
    # The local row turned canceled from a re-fetch, not from the cancel call.
    assert fake.called("fetch_subscription")[-1] == {"subscription_id": "sub_1"}
    assert fake.called("expire_checkout") == [{"session_id": "cs_open"}]
    # The members' MembershipRemoved events must not resize the subscription.
    assert fake.called("set_quantity") == []
    sub = await _sub(app, tenant_id)
    assert sub is not None and sub.status == SubscriptionStatus.CANCELED
    async with app.state.sm.db.session_factory() as session:
        assert await session.get(Tenant, tenant_id) is None
        customer = await session.get(Customer, tenant_id)
        assert customer is not None and customer.checkout_session_id is None


async def test_a_second_event_cancels_nothing_twice(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    await _delete(app, tenant_id)
    await app.state.sm.event_bus.publish(TenantDeleted(tenant_id, "acme", "Acme"))
    assert len(fake.called("cancel_now")) == 1


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
async def test_an_ended_subscription_is_not_canceled_again(app, fake, status):
    tenant_id = await _paying_tenant(app, fake, status=status)
    await _delete(app, tenant_id)
    assert fake.called("cancel_now") == []
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED


@pytest.mark.parametrize("status", sorted(PROVIDER_CANCELABLE_STATUSES))
async def test_every_live_status_is_canceled(app, fake, status):
    """The same set ``StripeProvider.live_subscription_ids`` filters on."""
    tenant_id = await _paying_tenant(app, fake, status=status)
    await _delete(app, tenant_id)
    assert fake.called("cancel_now") == [{"subscription_id": "sub_1"}]


async def test_a_local_only_row_still_cancels_the_customers_subscriptions(app, fake):
    tenant_id = await _paying_tenant(app, fake, sid=None)
    fake.live[CUS] = ["sub_unmirrored"]
    await _delete(app, tenant_id)
    assert fake.called("expire_checkout") == [{"session_id": "cs_open"}]
    assert fake.called("cancel_now") == [{"subscription_id": "sub_unmirrored"}]
    assert fake.called("fetch_subscription") == []  # nothing mirrored to resync
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED


async def _checkout_id(app, tenant_id: str) -> str | None:
    async with app.state.sm.db.session_factory() as session:
        return (await session.get(Customer, tenant_id)).checkout_session_id


@pytest.mark.parametrize("status", ["complete", "expired"])
async def test_a_checkout_that_cannot_be_paid_any_more_is_forgotten(app, fake, status):
    tenant_id = await _paying_tenant(app, fake)
    fake.fail.add("expire_checkout")
    fake.checkouts["cs_open"] = CheckoutSnapshot("cs_open", None, tenant_id, CUS, status)
    await _delete(app, tenant_id)
    assert await _checkout_id(app, tenant_id) is None
    assert fake.called("cancel_now") == [{"subscription_id": "sub_1"}]


@pytest.mark.parametrize("status", ["open", None])
async def test_a_checkout_still_open_is_kept_and_retried(app, fake, caplog, status):
    tenant_id = await _paying_tenant(app, fake)
    fake.fail.add("expire_checkout")
    fake.checkouts["cs_open"] = CheckoutSnapshot("cs_open", None, tenant_id, CUS, status)
    with caplog.at_level("WARNING"):
        await _delete(app, tenant_id)
    assert await _checkout_id(app, tenant_id) == "cs_open"
    assert any("deleted tenant" in r.message for r in caplog.records)
    # The expiry failure did not hold up the cancel.
    assert fake.called("cancel_now") == [{"subscription_id": "sub_1"}]
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED

    fake.fail.clear()
    await _make_due(app, tenant_id)
    assert (await reconcile(app)).errors == []
    assert await _checkout_id(app, tenant_id) is None
    assert len(fake.called("cancel_now")) == 1


async def test_a_live_subscription_not_mirrored_yet_is_canceled_too(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    fake.live[CUS] = ["sub_1", "sub_other_tab"]
    await _delete(app, tenant_id)
    assert {kw["subscription_id"] for kw in fake.called("cancel_now")} == {
        "sub_1",
        "sub_other_tab",
    }


async def test_tenant_without_billing_makes_no_provider_call(app, fake):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "free", members=2)
        await session.commit()
        tenant_id = tenant.id
    await _delete(app, tenant_id)
    assert fake.calls == []


async def test_a_subscription_never_at_the_provider_is_marked_canceled(app, fake):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "comp")
        await make_sub(session, tenant, await make_plan(session, "team"))
        await session.commit()
        tenant_id = tenant.id
    await _delete(app, tenant_id)
    assert fake.calls == []
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED


async def test_provider_failure_is_logged_and_reconcile_retries(app, fake, caplog):
    tenant_id = await _paying_tenant(app, fake)
    fake.fail.add("cancel_now")
    with caplog.at_level("WARNING"):
        await _delete(app, tenant_id)
    # The delete stands; the subscription is left for reconcile.
    async with app.state.sm.db.session_factory() as session:
        assert await session.get(Tenant, tenant_id) is None
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.ACTIVE
    assert any("deleted tenant" in r.message for r in caplog.records)

    fake.fail.clear()
    await _make_due(app, tenant_id)
    report = await reconcile(app)
    assert report.errors == []
    assert len(fake.called("cancel_now")) == 2
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED


async def test_reconcile_failure_is_reported_per_tenant(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    fake.fail.add("cancel_now")
    await _delete(app, tenant_id)
    await _make_due(app, tenant_id)
    report = await reconcile(app)
    assert [t for t, _ in report.errors] == [tenant_id]


async def test_a_deleted_tenant_on_the_manual_provider_is_left_alone(app, fake, caplog):
    tenant_id = await _paying_tenant(app, fake)
    fake.supports_checkout = False
    with caplog.at_level("WARNING"):
        await _delete(app, tenant_id)
    assert fake.called("cancel_now") == []
    assert any("at the provider" in r.message for r in caplog.records)


async def test_a_late_webhook_for_the_deleted_tenant_still_maps(app, fake):
    """The kept customer row maps Stripe's own ``subscription.deleted`` back."""
    from sm_billing.sync import apply_snapshot

    tenant_id = await _paying_tenant(app, fake)
    await _delete(app, tenant_id)
    async with app.state.sm.db.session_factory() as session:
        sub = await apply_snapshot(session, app, fake.snapshots["sub_1"], provider="stripe")
        assert sub.tenant_id == tenant_id
        assert sub.status == SubscriptionStatus.CANCELED
