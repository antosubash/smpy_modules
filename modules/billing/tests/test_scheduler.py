"""The periodic reconcile (#122): per tenant, claimed, paced, and off by default."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fake_provider import FakeProvider
from helpers import make_plan, make_sub, make_tenant, store_settings
from simple_module_db import current_tenant_id
from simple_module_test.database import is_sqlite
from sm_billing import scheduler, startup
from sm_billing.contracts.provider import SubscriptionSnapshot
from sm_billing.models import Subscription
from sqlalchemy import select
from tenants.constants import TenantStatus

HOUR = timedelta(hours=1)


@pytest.fixture
def settings(settings, tmp_path):
    """A file database on SQLite, so each session gets its own connection (#207).

    In-memory aiosqlite runs on SQLAlchemy's ``StaticPool``: one connection
    shared by every session. Two ticks interleaved on it are not two
    transactions — when one tick's session closes, its reset-on-return
    ``ROLLBACK`` also undoes the other tick's claim ``UPDATE``, which has
    already reported ``rowcount == 1``; the row is stale again and the second
    tick claims it too. A file database pools real connections, so a claim is
    serialised by SQLite's write lock (``busy_timeout``) as it is on a host.
    Postgres (``SM_TEST_DATABASE_URL``) already gives each session its own.
    """
    if is_sqlite(settings.database_url):
        settings.database_url = f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}"
    return settings


class BindingProvider(FakeProvider):
    """Records which tenant was bound when each subscription was fetched."""

    def __init__(self) -> None:
        super().__init__()
        self.bound: dict[str, str | None] = {}

    async def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        self.bound[subscription_id] = current_tenant_id.get()
        return await super().fetch_subscription(subscription_id)


@pytest.fixture
def fake(app) -> BindingProvider:
    provider = BindingProvider()
    app.state.sm_billing.provider = provider
    return provider


@pytest.fixture
def pauses(monkeypatch) -> list[float]:
    seen: list[float] = []

    async def record(seconds: float) -> None:
        seen.append(seconds)

    monkeypatch.setattr(scheduler, "_pause", record)
    return seen


def _snap(sub_id: str, tenant_id: str, status: str = "active") -> SubscriptionSnapshot:
    return SubscriptionSnapshot(
        sub_id, f"cus_{sub_id}", tenant_id, status, "price_team_m", 1, None, None, False
    )


async def _tenants(app, fake: FakeProvider, n: int, *, synced_at=None) -> list[str]:
    """``n`` tenants on one flat plan, each with a Stripe subscription ``sub_<i>``."""
    ids = []
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team")
        for i in range(n):
            tenant = await make_tenant(session, f"org{i}", members=1)
            await make_sub(
                session, tenant, plan, provider_subscription_id=f"sub_{i}", synced_at=synced_at
            )
            fake.snapshots[f"sub_{i}"] = _snap(f"sub_{i}", tenant.id)
            ids.append(tenant.id)
        await session.commit()
    return ids


async def _synced_at(app, tenant_id: str) -> datetime | None:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(Subscription.synced_at).where(Subscription.tenant_id == tenant_id)
        return (await session.execute(stmt)).scalar_one()


async def test_tick_reconciles_each_tenant_bound_to_it(app, fake, pauses):
    ids = await _tenants(app, fake, 2)
    report = await scheduler.reconcile_stale(app, HOUR)
    assert (report.synced, report.errors) == (2, [])
    assert fake.bound == {"sub_0": ids[0], "sub_1": ids[1]}
    assert all([await _synced_at(app, t) for t in ids])


async def test_one_tenant_failing_does_not_stop_the_rest(app, fake, pauses):
    ids = await _tenants(app, fake, 3)
    del fake.snapshots["sub_1"]  # KeyError for the middle tenant
    report = await scheduler.reconcile_stale(app, HOUR)
    assert report.synced == 2
    assert [t for t, _ in report.errors] == [ids[1]]
    # The failed claim was handed back, so the next tick retries it.
    assert await _synced_at(app, ids[1]) is None
    fake.snapshots["sub_1"] = _snap("sub_1", ids[1])
    assert (await scheduler.reconcile_stale(app, HOUR)).synced == 1


async def test_status_change_publishes_tenant_status_changed(app, fake, status_events, pauses):
    [tenant_id] = await _tenants(app, fake, 1)
    fake.snapshots["sub_0"] = _snap("sub_0", tenant_id, "unpaid")
    assert (await scheduler.reconcile_stale(app, HOUR)).synced == 1
    assert status_events == [TenantStatus.SUSPENDED]


async def test_recently_synced_subscriptions_are_left_alone(app, fake, pauses):
    await _tenants(app, fake, 2, synced_at=datetime.now(UTC) - timedelta(minutes=5))
    report = await scheduler.reconcile_stale(app, HOUR)
    assert report.synced == 0
    assert fake.called("fetch_subscription") == []


async def test_concurrent_instances_fetch_each_subscription_once(app, fake, pauses):
    """Two loops ticking at once (two replicas) claim disjoint tenants."""
    await _tenants(app, fake, 4)
    first, second = await asyncio.gather(
        scheduler.reconcile_stale(app, HOUR), scheduler.reconcile_stale(app, HOUR)
    )
    assert first.synced + second.synced == 4
    fetched = [kw["subscription_id"] for kw in fake.called("fetch_subscription")]
    assert sorted(fetched) == ["sub_0", "sub_1", "sub_2", "sub_3"]
    # And an immediate re-run finds nothing stale.
    assert (await scheduler.reconcile_stale(app, HOUR)).synced == 0


async def test_provider_outage_backs_off_then_ends_the_tick(app, fake, pauses):
    await _tenants(app, fake, scheduler.MAX_PROVIDER_ERRORS + 2)
    fake.fail.add("fetch_subscription")
    report = await scheduler.reconcile_stale(app, HOUR)
    assert report.skipped == "provider failing"
    assert len(fake.called("fetch_subscription")) == scheduler.MAX_PROVIDER_ERRORS
    assert pauses == sorted(pauses) and pauses[0] > scheduler.PACE_SECONDS
    assert max(pauses) <= scheduler.MAX_BACKOFF_SECONDS


async def test_manual_provider_skips(app, pauses):
    report = await scheduler.reconcile_stale(app, HOUR)
    assert report.skipped == "manual provider"


async def test_disabled_by_default_starts_no_task(app, fake):
    assert app.state.sm_billing.settings.reconcile_interval_minutes == 0
    startup.start_reconcile(app)
    assert app.state.sm_billing.scheduler is None


async def test_enabled_without_a_syncing_provider_starts_no_task(app):
    app.state.sm_billing.settings.reconcile_interval_minutes = 30
    startup.start_reconcile(app)
    assert app.state.sm_billing.scheduler is None


async def test_enabled_starts_a_loop_that_ticks_and_stops(app, fake, pauses, monkeypatch):
    await store_settings(app, reconcile_interval_minutes=30)
    await _tenants(app, fake, 1)
    ticked = asyncio.Event()
    real = scheduler.reconcile_stale

    async def tick(app_, max_age, *rest):
        report = await real(app_, max_age, *rest)
        ticked.set()
        return report

    monkeypatch.setattr(scheduler, "reconcile_stale", tick)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(scheduler.asyncio, "sleep", lambda _s: real_sleep(0))
    startup.start_reconcile(app)
    assert app.state.sm_billing.scheduler.running
    await asyncio.wait_for(ticked.wait(), 5)
    assert fake.called("fetch_subscription") == [{"subscription_id": "sub_0"}]
    await startup.stop_reconcile(app)
    assert app.state.sm_billing.scheduler is None


async def test_a_failed_tick_does_not_stop_the_loop(app, fake, monkeypatch):
    calls = 0
    done = asyncio.Event()

    async def tick(_app, _max_age, *_):
        nonlocal calls
        calls += 1
        if calls >= 2:
            done.set()
        raise RuntimeError("database down")

    monkeypatch.setattr(scheduler, "reconcile_stale", tick)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(scheduler.asyncio, "sleep", lambda _s: real_sleep(0))
    loop = scheduler.ReconcileScheduler()
    loop.start(app, HOUR)
    await asyncio.wait_for(done.wait(), 5)
    await loop.stop()
    assert not loop.running


async def test_admin_screen_reports_sync_health(app, fake):
    from sm_billing.admin import sync_health
    from sm_billing.models import WebhookEvent

    ids = await _tenants(app, fake, 2)
    old = datetime(2026, 1, 1, tzinfo=UTC)
    async with app.state.sm.db.session_factory() as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.tenant_id == ids[0]))
        ).scalar_one()
        sub.synced_at = old
        session.add(WebhookEvent(id="evt_1", provider="stripe", type="x"))
        await session.commit()
        health = await sync_health(session, app)
    assert health.oldest_synced_at.replace(tzinfo=UTC) == old
    assert (health.never_synced, health.unprocessed_webhooks) == (1, 1)
    assert (health.reconcile_interval_minutes, health.reconcile_running) == (0, False)
