"""The beat across tenants: isolation under strict binding, fairness, budgets, concurrency."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from simple_module_core.mail import install_mail_sender
from simple_module_db.query_filter import EngineTenancy, bind_engine_policy
from sm_events.core.tenancy import tenant_scope
from sm_events.reminders import candidates, limits, tick

from tests.pg_support import USING_POSTGRES
from tests.reminders.support import ORIGIN, bulk_follows
from tests.reminders.tick_support import (
    NOW,
    Mailbox,
    ledger,
    run_tick,
    seed,
)
from tests.support.app import Directory, build_app
from tests.support.tokens import install_members


@pytest.mark.unbound_tenant
async def test_per_tenant_isolation_and_strict_binding():
    app, state = await build_app(multi=True)
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    app.state.user_directory = Directory(
        {"v": ("v@example.com", "V", True), "w": ("w@example.com", "W", True)},
        {"v": ("viewer",), "w": ("viewer",)},
    )
    app.state.sm.settings.public_base_url = ORIGIN
    install_members(app, {"a": {"v", "w"}, "b": {"v", "w"}})
    box = Mailbox()
    install_mail_sender(box)
    try:
        await seed(state, users=("v",), tenant="a")
        await seed(state, users=("w",), tenant="b")
        got = await run_tick(app, state)
        assert (got["sent"], got["tenants"]) == (2, 2)
        assert sorted(m.to for m in box.messages) == ["v@example.com", "w@example.com"]
        assert await ledger(state, "a") == [("v", "sent")]
        assert await ledger(state, "b") == [("w", "sent")]
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_the_tenant_enumeration_is_the_one_narrow_cross_tenant_read(monkeypatch):
    """The follower read runs inside the framework's ``all_tenants()`` (which strict isolation
    asks for), once per pass, and nothing else in the pass is wrapped by it."""
    from contextlib import contextmanager

    app, state = await build_app(multi=True)
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    app.state.user_directory = Directory({"v": ("v@example.com", "V", True)}, {"v": ("viewer",)})
    app.state.sm.settings.public_base_url = ORIGIN
    install_members(app, {"a": {"v"}})
    install_mail_sender(Mailbox())
    inside, entered, executed_inside = [False], [], []

    real = tick.framework_all_tenants

    @contextmanager
    def spy():
        entered.append(1)
        inside[0] = True
        try:
            with real():
                yield
        finally:
            inside[0] = False

    from sqlalchemy import event as sa_event

    def hook(conn, cursor, statement, params, context, many):
        if statement.startswith("SELECT DISTINCT events_follow.tenant_id"):
            executed_inside.append(inside[0])

    sa_event.listen(state.engine.sync_engine, "before_cursor_execute", hook)
    try:
        await seed(state, tenant="a")
        monkeypatch.setattr(tick, "framework_all_tenants", spy)
        got = await run_tick(app, state)
        assert got["sent"] == 1
        assert entered == [1] and executed_inside == [True]
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_one_tenants_follow_on_anothers_event_does_nothing():
    app, state = await build_app(multi=True)
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    app.state.user_directory = Directory({"v": ("v@example.com", "V", True)}, {"v": ("viewer",)})
    app.state.sm.settings.public_base_url = ORIGIN
    install_members(app, {"a": {"v"}, "b": {"v"}})
    box = Mailbox()
    install_mail_sender(box)
    try:
        ids = await seed(state, users=(), tenant="a")
        with tenant_scope("b"):
            async with state.session_factory() as db:
                await bulk_follows(db, ids["event"], ["v"])  # b's follow, a's event id
                await db.commit()
        got = await run_tick(app, state)
        assert got["sent"] == 0 and box.messages == []
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_a_failing_tenant_does_not_stop_the_others(monkeypatch):
    app, state = await build_app(multi=True)
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    app.state.user_directory = Directory(
        {"v": ("v@example.com", "V", True), "w": ("w@example.com", "W", True)},
        {"v": ("viewer",), "w": ("viewer",)},
    )
    app.state.sm.settings.public_base_url = ORIGIN
    install_members(app, {"a": {"v", "w"}, "b": {"v", "w"}})
    box = Mailbox()
    install_mail_sender(box)
    real = candidates.candidates

    async def sometimes(db, **kw):
        if tick.bound_tenant() == "a":
            raise RuntimeError("tenant a is broken v@example.com")
        return await real(db, **kw)

    try:
        await seed(state, users=("v",), tenant="a")
        await seed(state, users=("w",), tenant="b")
        monkeypatch.setattr(candidates, "candidates", sometimes)
        got = await run_tick(app, state)
        assert (got["sent"], got["tenants_failed"]) == (1, 1)
        assert [m.to for m in box.messages] == ["w@example.com"]
    finally:
        await state.engine.dispose()


def test_tenants_are_served_in_a_rotating_order():
    tenants = ["a", "b", "c"]
    firsts = [tick.order_tenants(tenants, NOW + timedelta(minutes=m))[0] for m in range(6)]
    assert firsts == ["a", "b", "c", "a", "b", "c"] or set(firsts) == {"a", "b", "c"}
    assert sorted(tick.order_tenants(tenants, NOW)) == tenants and tick.order_tenants([], NOW) == []


@pytest.mark.unbound_tenant
async def test_budgets_span_tenants_and_rotate(monkeypatch):
    monkeypatch.setattr(limits, "REMINDER_TENANT_BUDGET", 2)
    monkeypatch.setattr(limits, "REMINDER_SEND_BUDGET", 3)
    app, state = await build_app(multi=True)
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    users = {f"u{i}": (f"u{i}@example.com", f"U{i}", True) for i in range(10)}
    app.state.user_directory = Directory(users, dict.fromkeys(users, ("viewer",)))
    app.state.sm.settings.public_base_url = ORIGIN
    install_members(app, {"a": set(users), "b": set(users)})
    box = Mailbox()
    install_mail_sender(box)
    try:
        await seed(state, users=tuple(users)[:5], tenant="a")
        await seed(state, users=tuple(users)[5:], tenant="b")
        got = await run_tick(app, state)
        assert got["sent"] == 3 and got["deferred"] >= 7  # 2 + 1, whoever came first
        assert len(await ledger(state, "a")) + len(await ledger(state, "b")) == 3
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
@pytest.mark.skipif(not USING_POSTGRES, reason="two real beats")
async def test_two_ticks_concurrently_send_once(host):
    app, state = host
    box = Mailbox(delay=0.05)
    install_mail_sender(box)
    await seed(state, users=tuple(f"u{i}" for i in range(30)))
    first, second = await asyncio.gather(run_tick(app, state), run_tick(app, state))
    assert len(box.messages) == 30 and first["sent"] + second["sent"] == 30
    assert sorted(m.to for m in box.messages) == sorted(f"u{i}@example.com" for i in range(30))


@pytest.mark.unbound_tenant
async def test_without_the_framework_wrapper_strict_isolation_refuses_the_enumeration(monkeypatch):
    """Proof the tests above exercise it: the events tag alone is not enough under strict
    isolation, the read is refused."""
    from contextlib import nullcontext

    from simple_module_db.tenancy import MissingTenantError

    app, state = await build_app(multi=True)
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))
    app.state.user_directory = Directory({"v": ("v@example.com", "V", True)}, {"v": ("viewer",)})
    app.state.sm.settings.public_base_url = ORIGIN
    install_members(app, {"a": {"v"}})
    install_mail_sender(Mailbox())
    try:
        await seed(state, tenant="a")
        monkeypatch.setattr(tick, "framework_all_tenants", nullcontext)
        with pytest.raises(MissingTenantError):
            await run_tick(app, state)
    finally:
        await state.engine.dispose()
