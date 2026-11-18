"""A removed user, membership or tenant takes its private links with it."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from simple_module_core.events import EventBus
from simple_module_core.tenant_events import TenantDeleted
from simple_module_core.user_events import UserDeleted
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.tokens import cleanup
from sm_events.models import Calendar, FeedToken
from sm_events.module import EventsModule
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from tenants.contracts.events import MembershipRemoved

from tests.support.tokens import NOW, token_app

U, V = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


async def _seed(state, tenant: str, *users: str, revoked_days: dict[str, int] | None = None):
    """One calendar in ``tenant`` and one link per user (a revoked one when asked)."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            cal = Calendar(slug="c", name="C", owner_id="o")
            db.add(cal)
            await db.flush()
            for n, user in enumerate(users):
                revoked = (revoked_days or {}).get(user)
                db.add(
                    FeedToken(
                        calendar_id=cal.id,
                        user_id=user,
                        token_hash=f"{tenant}-{user}-{n}".ljust(64, "0"),
                        label="L",
                        locale="en",
                        revoked_at=None if revoked is None else NOW - timedelta(days=revoked),
                    )
                )
            await db.commit()


async def _left(state) -> set[tuple[str, str]]:
    """Every ``(tenant, user)`` still holding a link, across tenants."""
    from simple_module_db import all_tenants as unscoped
    from sm_events.core.tenancy import all_tenants

    with unscoped():
        async with state.session_factory() as db:
            rows = (await db.execute(all_tenants(select(FeedToken)))).scalars().all()
    return {(r.tenant_id, r.user_id) for r in rows}


@pytest.fixture
async def world():
    app, state = await token_app(multi=True)
    bus = app.state.sm.event_bus
    EventsModule().register_event_handlers(bus, app)
    yield app, state, bus
    await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_user_deleted_removes_everywhere(world):
    _app, state, bus = world
    await _seed(state, "a", U, V)
    await _seed(state, "b", U, V)
    await bus.publish(UserDeleted(user_id=uuid.UUID(U)))
    assert await _left(state) == {("a", V), ("b", V)}


@pytest.mark.unbound_tenant
async def test_user_deleted_matches_any_spelling_of_the_id(world):
    _app, state, bus = world
    await _seed(state, "a", U.upper(), U.replace("-", ""), V)
    await bus.publish(UserDeleted(user_id=uuid.UUID(U)))
    assert await _left(state) == {("a", V)}


@pytest.mark.unbound_tenant
async def test_membership_removed_only_that_tenant(world):
    _app, state, bus = world
    await _seed(state, "a", U, V)
    await _seed(state, "b", U)
    await bus.publish(MembershipRemoved(tenant_id="a", user_id=U))
    assert await _left(state) == {("a", V), ("b", U)}


@pytest.mark.unbound_tenant
async def test_tenant_deleted(world):
    _app, state, bus = world
    await _seed(state, "a", U, V)
    await _seed(state, "b", U)
    await bus.publish(TenantDeleted(tenant_id="a", slug="a", name="A"))
    assert await _left(state) == {("b", U)}


@pytest.mark.unbound_tenant
async def test_an_invalid_tenant_id_deletes_nothing(world):
    _app, state, bus = world
    await _seed(state, "a", U)
    await bus.publish(TenantDeleted(tenant_id="platform", slug="p", name="P"))
    await bus.publish(MembershipRemoved(tenant_id="bad id!", user_id=U))
    assert await _left(state) == {("a", U)}


@pytest.mark.unbound_tenant
async def test_handler_failure_is_swallowed(caplog):
    """A database error is logged by class and never reaches the bus."""
    app = SimpleNamespace(state=SimpleNamespace())

    def broken():
        raise OperationalError("SELECT 1", {}, Exception(f"secret {U}"))

    app.state.sm = SimpleNamespace(db=SimpleNamespace(session_factory=broken))
    bus = EventBus()
    EventsModule().register_event_handlers(bus, app)
    with caplog.at_level(logging.DEBUG):
        await bus.publish(UserDeleted(user_id=uuid.UUID(U)))
        await bus.publish(MembershipRemoved(tenant_id="a", user_id=U))
        await bus.publish(TenantDeleted(tenant_id="a", slug="a", name="A"))
    assert caplog.text.count("TokenCleanup failed (OperationalError)") == 3
    assert "Event handler" not in caplog.text  # the bus never saw a failure
    assert U not in caplog.text


@pytest.mark.unbound_tenant
async def test_sweep_revoked_keeps_30_days():
    _app, state = await token_app()
    try:
        await _seed(
            state,
            "default",
            "u29",
            "u31",
            "live",
            revoked_days={"u29": 29, "u31": 31},
        )
        with tenant_scope("default"):
            async with state.session_factory() as db:
                removed = await cleanup.sweep_revoked(db, now=NOW)
                await db.commit()
        assert removed == 1
        assert {u for _t, u in await _left(state)} == {"u29", "live"}
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_sweep_revoked_is_tenant_bound():
    """A sweep in one tenant leaves another's revoked links to that tenant's own sweep."""
    _app, state = await token_app(multi=True)
    try:
        await _seed(state, "a", "old", revoked_days={"old": 40})
        await _seed(state, "b", "old", revoked_days={"old": 40})
        with tenant_scope("a"):
            async with state.session_factory() as db:
                assert await cleanup.sweep_revoked(db, now=NOW) == 1
                await db.commit()
        assert await _left(state) == {("b", "old")}
    finally:
        await state.engine.dispose()


async def test_subscriptions_registered(world):
    _app, _state, bus = world
    for event in (UserDeleted, MembershipRemoved, TenantDeleted):
        assert bus._emitter.listeners(bus._event_key(event)), event.__name__


async def test_a_missing_event_class_is_skipped_with_a_log(caplog, monkeypatch):
    """A framework without ``TenantDeleted`` still gets the others, and says so."""
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "simple_module_core.tenant_events":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    bus = EventBus()
    monkeypatch.setattr(builtins, "__import__", refuse)
    with caplog.at_level(logging.INFO):
        cleanup.subscribe(bus, SimpleNamespace())
    monkeypatch.undo()
    assert bus._emitter.listeners(bus._event_key(UserDeleted))
    assert not bus._emitter.listeners(bus._event_key(TenantDeleted))
    assert "TenantDeleted" in caplog.text
