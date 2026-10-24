"""Workers that did not take a save still follow it, and re-timing the loop
never strands a reconcile claim (#85)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx
import pytest
from api_helpers import signed_stripe_event
from fake_provider import FakeProvider
from helpers import make_plan, make_sub, make_tenant, store_settings
from simple_module_db import finalize_session
from simple_module_test.database import is_sqlite
from sm_billing import constants as c
from sm_billing import crypto, live, scheduler, startup
from sm_billing.models import Subscription
from sm_billing.providers.manual import ManualProvider
from sm_billing.providers.stripe import StripeProvider
from sqlalchemy import select

WHSEC = "whsec_workers"


async def _boot(settings):
    from simple_module_hosting.app_builder import create_app
    from simple_module_test._schema import _create_all_tables
    from users.bootstrap import create_admin

    application = create_app(settings)
    await _create_all_tables(application.state.sm.db.engine)
    async with application.state.sm.db.session_factory() as session:
        await create_admin(session, email="admin@test", password="test-password", full_name="A")
    ctx = application.router.lifespan_context(application)
    await ctx.__aenter__()
    return application, ctx


@pytest.fixture
async def workers(settings, tmp_path):
    """Two instances of the app on one database, like two uvicorn workers."""
    if is_sqlite(settings.database_url):
        url = f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}"
        settings = settings.model_copy(update={"database_url": url})
    first, first_ctx = await _boot(settings)
    second, second_ctx = await _boot(settings)
    yield first, second
    for application, ctx in ((second, second_ctx), (first, first_ctx)):
        await startup.stop_reconcile(application)
        await ctx.__aexit__(None, None, None)


async def _save(app, **changes) -> None:
    """The framework's save path on one worker: persist, hot-swap, publish."""
    from settings.reload import apply_changes_and_reload
    from settings.service import SettingService
    from settings.store import SettingsStore

    async with app.state.sm.db.session_factory() as session:
        store = SettingsStore(SettingService(session))
        await apply_changes_and_reload(
            app, app.state.sm.event_bus, store, package=c.PACKAGE, changes=changes
        )
        await finalize_session(session)


async def _webhook(app) -> int:
    body, headers = signed_stripe_event(WHSEC)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(c.WEBHOOK_PATH, content=body, headers=headers)
    return response.status_code


def _billing(app):
    return getattr(app.state, c.PACKAGE)


async def test_a_switch_on_one_worker_reaches_the_other(workers):
    first, second = workers
    await _save(
        first,
        provider=c.PROVIDER_STRIPE,
        stripe_secret_key=crypto.encrypt_value("sk_test_1"),
        stripe_webhook_secret=crypto.encrypt_value(WHSEC),
        reconcile_interval_minutes=30,
    )
    assert isinstance(_billing(first).provider, StripeProvider)
    assert isinstance(_billing(second).provider, ManualProvider)  # no event crossed

    assert await _webhook(second) == 200  # the request itself caught up first
    assert isinstance(_billing(second).provider, StripeProvider)
    assert _billing(second).scheduler.running

    await _save(first, provider=c.PROVIDER_MANUAL)
    assert await _webhook(second) == 404  # refused, not processed with stale Stripe
    assert isinstance(_billing(second).provider, ManualProvider)
    assert _billing(second).scheduler is None


async def test_a_stale_reconcile_tick_writes_nothing(workers):
    first, second = workers
    stripe = {"provider": c.PROVIDER_STRIPE, "reconcile_interval_minutes": 30}
    await _save(first, **stripe)
    assert await live.ensure_current(second) is True
    fake = FakeProvider()
    _billing(second).provider = fake  # second runs "Stripe" from its boot
    async with second.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "acme", members=1)
        await make_sub(session, tenant, await make_plan(session), provider_subscription_id="sub_1")
        await session.commit()

    await _save(first, provider=c.PROVIDER_MANUAL)  # first switches; second has not heard
    report = await scheduler.reconcile_stale(second, timedelta(hours=1))
    assert report.skipped == "settings changed"
    assert fake.calls == []
    assert isinstance(_billing(second).provider, ManualProvider)


async def test_seat_push_follows_a_switch_made_elsewhere(workers):
    first, second = workers
    await _save(first, provider=c.PROVIDER_STRIPE)
    await live.ensure_current(second)
    fake = FakeProvider()
    _billing(second).provider = fake
    await _save(first, provider=c.PROVIDER_MANUAL)
    assert await live.ensure_current(second) is True
    assert isinstance(_billing(second).provider, ManualProvider)
    assert await live.ensure_current(second) is False  # in step now: no rebuild


async def test_retiming_mid_claim_hands_the_claim_back(app, monkeypatch):
    await store_settings(app, reconcile_interval_minutes=30)
    fake = FakeProvider()
    _billing(app).provider = fake
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "acme", members=1)
        await make_sub(session, tenant, await make_plan(session), provider_subscription_id="sub_1")
        await session.commit()

    claimed, hold = asyncio.Event(), asyncio.Event()
    real_claim, real_sleep = scheduler._claim, asyncio.sleep

    async def claim_then_wait(*args):
        won = await real_claim(*args)  # committed
        claimed.set()
        await hold.wait()  # the cancel lands here: after the commit, before the return
        return won

    monkeypatch.setattr(scheduler, "_claim", claim_then_wait)
    monkeypatch.setattr(scheduler.asyncio, "sleep", lambda _s: real_sleep(0))
    startup.start_reconcile(app)
    old = _billing(app).scheduler
    await asyncio.wait_for(claimed.wait(), 5)
    monkeypatch.setattr(scheduler.asyncio, "sleep", real_sleep)  # the new loop waits

    await store_settings(app, reconcile_interval_minutes=60)
    retime = asyncio.create_task(live.apply_reload(app, ["reconcile_interval_minutes"]))
    await real_sleep(0.05)
    hold.set()
    await asyncio.wait_for(retime, 5)

    assert not old.running and _billing(app).scheduler.interval == timedelta(minutes=60)
    async with app.state.sm.db.session_factory() as session:
        stamp = (await session.execute(select(Subscription.synced_at))).scalar_one()
    assert stamp is None  # handed back: the new loop's first tick takes it
    assert fake.calls == []
    await startup.stop_reconcile(app)


async def test_a_save_not_yet_committed_is_not_reverted(app):
    # The framework hot-swaps before the saving request commits: memory is
    # ahead of the database, and a concurrent request must not roll it back.
    services = _billing(app)
    services.settings = services.settings.model_copy(update={"provider": c.PROVIDER_STRIPE})
    assert await live.ensure_current(app) is False
    assert services.settings.provider == c.PROVIDER_STRIPE


async def test_usage_settings_saved_on_one_worker_reach_the_other(workers, monkeypatch):
    from sm_billing.metering import sweeper

    first, second = workers
    await _save(first, usage_event_retention_days=30, usage_sweep_interval_seconds=0)
    assert _billing(second).settings.usage_event_retention_days == 400  # not heard yet
    # The usage fields are followed, but nothing is rebuilt for them.
    assert await live.ensure_current(second) is False
    assert _billing(second).settings.usage_event_retention_days == 30
    assert _billing(second).settings.usage_sweep_interval_seconds == 0

    # A loop that last saw interval 1 idles from its next tick on: it re-reads first.
    await _save(first, usage_sweep_interval_seconds=1)
    await live.ensure_current(second)
    await _save(first, usage_sweep_interval_seconds=0)  # second has not heard
    assert _billing(second).settings.usage_sweep_interval_seconds == 1
    ticks: list[int] = []

    async def tick(self, _app):
        ticks.append(1)
        return sweeper.SweepReport()

    real_sleep = asyncio.sleep
    monkeypatch.setattr(sweeper.UsageSweeper, "tick", tick)
    monkeypatch.setattr(sweeper, "_sleep", lambda _s: real_sleep(0.01))
    loop = sweeper.UsageSweeper()
    loop.start(second)
    await real_sleep(0.2)
    await loop.stop()
    assert ticks == []
    assert _billing(second).settings.usage_sweep_interval_seconds == 0
