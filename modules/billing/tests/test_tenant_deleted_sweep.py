"""The deleted-tenant sweep: backoff, terminal "gone", the failure budget, live
settings, and never on a single-tenant host (#92)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fake_provider import FakeProvider
from helpers import make_plan, make_sub
from sm_billing import live, scheduler, sweep
from sm_billing.constants import SubscriptionStatus
from sm_billing.models import Customer
from sm_billing.reconcile import reconcile
from subscription_helpers import _snap
from teardown_helpers import _customer, _delete, _paying_tenant, _sub


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


@pytest.fixture
def pauses(monkeypatch) -> list[float]:
    seen: list[float] = []

    async def record(seconds: float) -> None:
        seen.append(seconds)

    monkeypatch.setattr(scheduler, "_pause", record)
    return seen


async def _failing_orphans(app, fake, n: int) -> list[str]:
    """``n`` deleted tenants whose customer listing keeps failing."""
    fake.fail.add("live_subscription_ids")
    ids = []
    for i in range(n):
        tenant_id = await _paying_tenant(app, fake, with_sub=False, slug=f"org{i}")
        await _delete(app, tenant_id)  # the event's own attempt fails too
        ids.append(tenant_id)
    return ids


async def test_a_failing_teardown_backs_off_instead_of_retrying_every_run(app, fake):
    [tenant_id] = await _failing_orphans(app, fake, 1)
    before = datetime.now(UTC)
    first = await reconcile(app)
    assert [t for t, _ in first.errors] == [tenant_id]
    customer = await _customer(app, tenant_id)
    assert customer.teardown_attempts == 1
    due = customer.teardown_next_attempt_at.replace(tzinfo=UTC)
    assert due >= before + sweep.RETRY_BASE - timedelta(seconds=5)

    fake.calls.clear()
    second = await reconcile(app)  # not due yet: no provider call at all
    assert (second.errors, fake.calls) == ([], [])

    async with app.state.sm.db.session_factory() as session:
        (await session.get(Customer, tenant_id)).teardown_next_attempt_at = before
        await session.commit()
    fake.fail.clear()
    assert (await reconcile(app)).torn_down == 1
    assert (await _customer(app, tenant_id)).teardown_done_at is not None


def test_the_retry_delay_doubles_up_to_a_cap():
    assert sweep.retry_delay(1) == sweep.RETRY_BASE
    assert sweep.retry_delay(3) == sweep.RETRY_BASE * 4
    assert sweep.retry_delay(50) == sweep.RETRY_CAP


async def test_a_customer_gone_at_the_provider_is_terminal(app, fake, caplog):
    tenant_id = await _paying_tenant(app, fake, with_sub=False)
    fake.missing.add("live_subscription_ids")
    with caplog.at_level("INFO"):
        await _delete(app, tenant_id)
    customer = await _customer(app, tenant_id)
    assert customer.teardown_done_at is not None
    assert customer.teardown_attempts == 0
    assert any("no longer exists at the provider" in r.message for r in caplog.records)
    fake.calls.clear()
    assert ((await reconcile(app)).errors, fake.calls) == ([], [])


async def test_a_mirrored_subscription_gone_at_the_provider_is_canceled_locally(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    fake.missing.add("fetch_subscription")
    await _delete(app, tenant_id)
    assert fake.called("cancel_now") == []
    assert (await _sub(app, tenant_id)).status == SubscriptionStatus.CANCELED
    assert (await _customer(app, tenant_id)).teardown_done_at is not None


async def test_the_sweep_spends_the_schedulers_failure_budget(app, fake, pauses):
    await _failing_orphans(app, fake, scheduler.MAX_PROVIDER_ERRORS + 1)
    report = await scheduler.reconcile_stale(app, timedelta(minutes=60))
    assert report.skipped == "provider failing"
    assert len(report.errors) == scheduler.MAX_PROVIDER_ERRORS
    assert pauses == [scheduler.PACE_SECONDS * 2**i for i in range(1, 5)]


async def test_the_sweep_stops_when_the_provider_settings_change(app, fake, monkeypatch):
    fake.fail.add("cancel_now")
    for slug in ("one", "two"):
        tenant_id = await _paying_tenant(app, fake, with_sub=False, slug=slug)
        fake.live[f"cus_{slug}"] = [f"sub_{slug}"]
        fake.snapshots[f"sub_{slug}"] = _snap(tenant_id, sid=f"sub_{slug}")
        await _delete(app, tenant_id)
    fake.fail.clear()
    fake.calls.clear()
    answers = iter([False, True])

    async def switched(_app) -> bool:
        return next(answers)

    monkeypatch.setattr(live, "ensure_current", switched)
    report = await reconcile(app)
    assert (report.torn_down, report.skipped) == (1, "settings changed")
    assert len(fake.called("cancel_now")) == 1


async def _default_tenant_billing(app, fake) -> None:
    """Billing rows under ``"default"``, which has no tenant row."""
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team")
        session.add(Customer(tenant_id="default", provider="stripe", provider_customer_id="cus_d"))
        await session.flush()
        sub = await make_sub(session, _Default(), plan, provider_subscription_id="sub_d")
        assert sub.tenant_id == "default"
        await session.commit()
    fake.live["cus_d"] = ["sub_d"]
    fake.snapshots["sub_d"] = _snap("default", sid="sub_d")


class _Default:
    id = "default"


@pytest.mark.parametrize("multi_tenant", [False, True])
async def test_default_is_never_torn_down(app, fake, monkeypatch, multi_tenant):
    monkeypatch.setattr(app.state.sm.settings, "multi_tenant", multi_tenant)
    await _default_tenant_billing(app, fake)
    report = await reconcile(app)
    assert fake.called("cancel_now") == []
    assert report.torn_down == 0
    sub = await _sub(app, "default")
    assert sub.status == SubscriptionStatus.ACTIVE
    assert (await _customer(app, "default")).teardown_done_at is None


async def test_a_single_tenant_host_refuses_a_teardown(app, fake, monkeypatch):
    from sm_billing.teardown import cancel_for_deleted_tenant

    monkeypatch.setattr(app.state.sm.settings, "multi_tenant", False)
    tenant_id = await _paying_tenant(app, fake)
    assert await cancel_for_deleted_tenant(app, tenant_id) == []
    assert fake.calls == []
