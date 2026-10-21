"""Loop lifecycle and provider-error backoff of the periodic reconcile (#122)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fake_provider import FakeProvider
from helpers import make_plan, make_sub, make_tenant
from sm_billing import scheduler, startup
from sm_billing.contracts.provider import ProviderError, SubscriptionSnapshot
from sm_billing.models import Subscription
from sm_billing.module import BillingModule
from sqlalchemy import select

HOUR = timedelta(hours=1)


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


async def _tenants(app, fake: FakeProvider, n: int) -> list[str]:
    ids = []
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team")
        for i in range(n):
            tenant = await make_tenant(session, f"org{i}", members=1)
            await make_sub(session, tenant, plan, provider_subscription_id=f"sub_{i}")
            fake.snapshots[f"sub_{i}"] = SubscriptionSnapshot(
                f"sub_{i}", f"cus_{i}", tenant.id, "active", "price_team_m", 1, None, None, False
            )
            ids.append(tenant.id)
        await session.commit()
    return ids


async def _stamps(app) -> dict[str, object]:
    stmt = select(Subscription.provider_subscription_id, Subscription.synced_at)
    async with app.state.sm.db.session_factory() as session:
        return dict((await session.execute(stmt)).tuples().all())


async def test_backoff_doubles_from_the_pace_and_is_capped(app, fake, pauses, monkeypatch):
    monkeypatch.setattr(scheduler, "MAX_PROVIDER_ERRORS", 100)
    await _tenants(app, fake, 9)
    fake.fail.add("fetch_subscription")
    report = await scheduler.reconcile_stale(app, HOUR)
    assert not report.skipped  # ran to the end of the list
    assert pauses == pytest.approx([0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 25.6, 30.0, 30.0])


async def test_a_success_resets_the_backoff_and_the_error_run(app, fake, pauses):
    await _tenants(app, fake, 8)
    # Four failures, a success, three failures: never MAX in a row.
    pattern = [True, True, True, True, False, True, True, True]
    calls = 0
    real = fake.fetch_subscription

    async def flaky(subscription_id: str) -> SubscriptionSnapshot:
        nonlocal calls
        calls += 1
        if pattern[calls - 1]:
            raise ProviderError("down")
        return await real(subscription_id)

    fake.fetch_subscription = flaky  # type: ignore[method-assign]
    report = await scheduler.reconcile_stale(app, HOUR)
    assert not report.skipped
    assert (report.synced, len(report.errors)) == (1, 7)
    assert pauses == pytest.approx([0.4, 0.8, 1.6, 3.2, scheduler.PACE_SECONDS, 0.4, 0.8, 1.6])


async def test_early_stop_skips_the_rest_and_leaves_no_claim_behind(app, fake, pauses):
    n = scheduler.MAX_PROVIDER_ERRORS + 3
    await _tenants(app, fake, n)
    fake.fail.add("fetch_subscription")
    report = await scheduler.reconcile_stale(app, HOUR)
    assert report.skipped == "provider failing"
    assert len(fake.called("fetch_subscription")) == scheduler.MAX_PROVIDER_ERRORS
    assert len(report.errors) == scheduler.MAX_PROVIDER_ERRORS
    # Failed ones were handed back, the rest never claimed: nothing is parked.
    assert set((await _stamps(app)).values()) == {None}
    assert len(pauses) == scheduler.MAX_PROVIDER_ERRORS - 1  # no pause after the break
    fake.fail.clear()
    assert (await scheduler.reconcile_stale(app, HOUR)).synced == n


async def test_non_provider_errors_do_not_trigger_early_stop(app, fake, pauses):
    n = scheduler.MAX_PROVIDER_ERRORS + 2
    await _tenants(app, fake, n)
    fake.snapshots.clear()  # KeyError per tenant, not a ProviderError
    report = await scheduler.reconcile_stale(app, HOUR)
    assert not report.skipped
    assert len(report.errors) == n
    assert set(pauses) == {scheduler.PACE_SECONDS}


async def test_cancellation_mid_sync_releases_the_claim(app, fake, pauses, monkeypatch):
    await _tenants(app, fake, 1)
    started = asyncio.Event()

    async def hang(*_args):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(scheduler, "reconcile_one", hang)
    task = asyncio.create_task(scheduler.reconcile_stale(app, HOUR))
    await asyncio.wait_for(started.wait(), 5)
    assert (await _stamps(app))["sub_0"] is not None  # claimed
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await _stamps(app))["sub_0"] is None


async def test_stop_cancels_a_loop_asleep_between_ticks(app, fake):
    loop = scheduler.ReconcileScheduler()
    loop.start(app, HOUR)
    await asyncio.sleep(0)
    task = loop._task
    assert loop.running
    await asyncio.wait_for(loop.stop(), 5)
    assert task is not None and task.cancelled()
    assert not loop.running
    await loop.stop()  # idempotent


async def test_stop_cancels_a_loop_stuck_inside_a_tick(app, fake, monkeypatch):
    inside = asyncio.Event()

    async def stuck(_app, _age, *_):
        inside.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(scheduler, "reconcile_stale", stuck)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(scheduler.asyncio, "sleep", lambda _s: real_sleep(0))
    loop = scheduler.ReconcileScheduler()
    loop.start(app, HOUR)
    await asyncio.wait_for(inside.wait(), 5)
    await asyncio.wait_for(loop.stop(), 5)
    assert not loop.running


async def test_on_shutdown_stops_the_started_loop(app, fake):
    app.state.sm_billing.settings.reconcile_interval_minutes = 30
    startup.start_reconcile(app)
    assert app.state.sm_billing.scheduler.running
    await BillingModule().on_shutdown(app)
    assert app.state.sm_billing.scheduler is None


async def test_rows_that_failed_last_tick_go_last(app, fake, pauses):
    """Five permanently failing rows must not end every tick before healthy ones."""
    ids = await _tenants(app, fake, 7)  # sub_0..sub_4 poisoned, sub_5/sub_6 healthy
    poisoned = {f"sub_{i}" for i in range(5)}
    real_fetch = fake.fetch_subscription

    async def fetch(subscription_id: str) -> SubscriptionSnapshot:
        if subscription_id in poisoned:
            raise ProviderError("resource_missing")
        return await real_fetch(subscription_id)

    fake.fetch_subscription = fetch  # type: ignore[method-assign]
    failing: set[int] = set()
    first = await scheduler.reconcile_stale(app, HOUR, failing)
    assert (first.synced, first.skipped, len(failing)) == (0, "provider failing", 5)
    second = await scheduler.reconcile_stale(app, HOUR, failing)
    assert second.synced == 2  # the healthy tenants ran before the poisoned rows
    assert {t for t, _ in second.errors} == set(ids[:5])
    stamps = await _stamps(app)
    assert stamps["sub_5"] and stamps["sub_6"]
    assert all(stamps[s] is None for s in poisoned)  # claims handed back
