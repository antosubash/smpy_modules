"""The beat as a Celery task: strict tenancy, the platform runtime, settings and the secret."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext

import pytest
from simple_module_db.query_filter import EngineTenancy, bind_engine_policy
from simple_module_db.tenancy import MissingTenantError
from sm_events import tasks
from sm_events.core import secret
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import refresh

from tests.core.test_worker import worker_db  # noqa: F401 - fixture
from tests.feeds.subscriptions.refresh_support import Fetcher, load, ok, seed, tick, titles
from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.subscriptions import ics, seed_calendar, seed_subscription, vevent


@pytest.mark.unbound_tenant
async def test_tick_under_strict_isolation(db_state):
    bind_engine_policy(db_state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    (a,) = await seed(db_state, tenant="a", slug="x")
    (b,) = await seed(db_state, tenant="b", slug="x")

    def by_tenant(url):
        name = "From A" if "//a-" in url else "From B"
        return ok(ics(vevent(UID="u@x", SUMMARY=name)))

    got = await tick(db_state, Fetcher(by_tenant))
    assert (got["fetched"], got["tenants"], got["failed"]) == (2, 2, 0)
    assert await titles(db_state, a, "a") == ["From A"]
    assert await titles(db_state, b, "b") == ["From B"]


@pytest.mark.unbound_tenant
async def test_the_enumeration_is_the_one_narrow_cross_tenant_read(db_state, monkeypatch):
    """Without the framework's ``all_tenants()`` the tagged read is refused under strict
    isolation: this proves the test exercises it."""
    bind_engine_policy(db_state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    await seed(db_state, tenant="a", slug="x")
    monkeypatch.setattr(refresh, "framework_all_tenants", nullcontext)
    with pytest.raises(MissingTenantError):
        await tick(db_state, Fetcher())


@pytest.mark.unbound_tenant
async def test_per_tenant_isolation(db_state):
    bind_engine_policy(db_state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    (a,) = await seed(db_state, tenant="a", slug="x")
    (b,) = await seed(db_state, tenant="b", slug="x")
    await tick(
        db_state, Fetcher(ok(ics(vevent(UID="only-b@x", SUMMARY="B only")))), now=refresh_now()
    )
    for tenant, sid in (("a", a), ("b", b)):
        with tenant_scope(tenant):
            async with db_state.session_factory() as db:
                from sm_events.models import ExternalItem
                from sqlalchemy import select

                rows = (await db.execute(select(ExternalItem))).scalars().all()
                assert {r.tenant_id for r in rows} == {tenant}
                assert {r.subscription_id for r in rows} == {sid}


def refresh_now():
    from tests.feeds.subscriptions.refresh_support import NOW

    return NOW


@pytest.fixture
def due_in_worker_db(worker_db):  # noqa: F811  # noqa: F811
    """A subscription due in tenant ``default`` of the worker's file database."""

    async def go():
        state = await make_db_state(file=worker_db)
        with tenant_scope("default"):
            async with state.session_factory() as s:
                sub = await seed_subscription(s, await seed_calendar(s, "sub-cal"))
                await s.commit()
                sid = sub.id
        await state.engine.dispose()
        return sid

    return asyncio.run(go())


def _install(monkeypatch, fetcher, settings=None):
    monkeypatch.setattr(secret, "resolve_worker_secret", lambda: "subscription-test-secret")
    monkeypatch.setattr(refresh, "fetch_feed", fetcher)
    monkeypatch.setattr(refresh, "_stored_settings", lambda: settings or EventsSettings())


async def _state(db_file, sid):
    state = await make_db_state(file=db_file)
    try:
        return await load(state, sid)
    finally:
        await state.engine.dispose()


@pytest.mark.skipif(USING_POSTGRES, reason="the worker tests use their own SQLite file")
def test_task_unbinds_callers_tenant_and_stores(
    due_in_worker_db,
    worker_db,  # noqa: F811
    monkeypatch,
):
    fetcher = Fetcher()
    _install(monkeypatch, fetcher)
    got = tasks.refresh_subscriptions()  # under the suite's bound tenant: the runtime unbinds it
    assert got["fetched"] == 1 and got["tenants"] == 1
    assert asyncio.run(_state(worker_db, due_in_worker_db)).status == "ok"
    assert tasks.refresh_subscriptions()["fetched"] == 0  # redelivery: nothing is due


@pytest.mark.skipif(USING_POSTGRES, reason="the worker tests use their own SQLite file")
def test_eager_task_runs(due_in_worker_db, monkeypatch):
    _install(monkeypatch, Fetcher())
    assert tasks.refresh_subscriptions.apply().get()["fetched"] == 1


@pytest.mark.skipif(USING_POSTGRES, reason="the worker tests use their own SQLite file")
def test_refresh_one_task(due_in_worker_db, monkeypatch):
    _install(monkeypatch, Fetcher())
    assert tasks.refresh_subscription("default", str(due_in_worker_db)) == "stored"
    assert tasks.refresh_subscription("default", str(due_in_worker_db)) == "busy"
    assert tasks.refresh_subscription("not a tenant", str(due_in_worker_db)) == "gone"
    assert tasks.refresh_subscription("default", "not-a-uuid") == "gone"


@pytest.mark.skipif(USING_POSTGRES, reason="the worker tests use their own SQLite file")
def test_settings_read_in_worker(due_in_worker_db, monkeypatch):
    fetcher = Fetcher()
    _install(monkeypatch, fetcher, EventsSettings(allow_private_subscription_urls=True))
    tasks.refresh_subscriptions()
    assert fetcher.calls[0]["policy"].allow_private is True


@pytest.mark.skipif(USING_POSTGRES, reason="the worker tests use their own SQLite file")
def test_no_secret_means_nothing_is_fetched_and_nothing_is_disabled(
    due_in_worker_db,
    worker_db,  # noqa: F811
    monkeypatch,
):
    fetcher = Fetcher()
    _install(monkeypatch, fetcher)

    def missing():
        raise secret.SecretMissing("no secret key")

    monkeypatch.setattr(secret, "resolve_worker_secret", missing)
    from sm_events.core import crypto

    monkeypatch.setattr(crypto, "_secret_provider", None)
    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    monkeypatch.setattr(crypto, "_dotenv_secret", lambda: "")
    got = tasks.refresh_subscriptions()
    assert got["unavailable"] == 1 and got["fetched"] == 0 and fetcher.calls == []
    sub = asyncio.run(_state(worker_db, due_in_worker_db))
    assert (sub.status, sub.consecutive_failures) == (
        "pending",
        0,
    )  # an ops problem, not the feed's


async def test_the_task_refuses_a_running_loop():
    with pytest.raises(RuntimeError, match="event loop"):
        tasks.refresh_subscriptions()
