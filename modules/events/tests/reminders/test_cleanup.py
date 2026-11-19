"""What a removed user, membership or tenant leaves behind, and the ledger's retention."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from simple_module_core.events import EventBus
from simple_module_core.tenant_events import TenantDeleted
from simple_module_core.user_events import UserDeleted
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, EventFollow, ReminderSent
from sm_events.module import EventsModule
from sm_events.reminders import cleanup, limits
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from tenants.contracts.events import MembershipRemoved

from tests.support.calendars import bare_event
from tests.support.tokens import token_app

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
U, V = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


async def _seed(state, tenant, *users, starts_at=NOW + timedelta(days=2), claimed_at=NOW):
    """One calendar and event in ``tenant``; each user follows it and has one ledger row."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            cal = Calendar(slug=f"c-{uuid.uuid4().hex[:8]}", name="C", owner_id="o")
            db.add(cal)
            await db.flush()
            event = await bare_event(db, cal, status="published", starts_at=starts_at)
            for user in users:
                db.add(EventFollow(event_id=event.id, user_id=user, lead_minutes=60, locale="en"))
                db.add(
                    ReminderSent(
                        event_id=event.id, occurrence_key=str(event.id), starts_at=starts_at,
                        recipient_id=user, lead_minutes=60, state="sent", claimed_at=claimed_at,
                    )
                )  # fmt: skip
            await db.commit()
            return event.id


async def _left(state) -> tuple[set, set]:
    """``(tenant, user)`` of every follow and every ledger row, across tenants."""
    from simple_module_db import all_tenants as unscoped
    from sm_events.core.tenancy import all_tenants

    with unscoped():
        async with state.session_factory() as db:
            follows = (await db.execute(all_tenants(select(EventFollow)))).scalars().all()
            ledger = (await db.execute(all_tenants(select(ReminderSent)))).scalars().all()
    return (
        {(r.tenant_id, r.user_id) for r in follows},
        {(r.tenant_id, r.recipient_id) for r in ledger},
    )


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
    assert await _left(state) == ({("a", V), ("b", V)}, {("a", V), ("b", V)})


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("stored", [U, U.upper(), U.replace("-", ""), U.replace("-", "").upper()])
@pytest.mark.parametrize("carried", [uuid.UUID(U), U, U.upper(), U.replace("-", "")])
async def test_user_deleted_matches_every_spelling(world, stored, carried):
    """Rows in any spelling go whatever spelling the framework's event carries."""
    _app, state, bus = world
    await _seed(state, "a", stored, V)
    await bus.publish(UserDeleted(user_id=carried))  # type: ignore[arg-type]
    assert await _left(state) == ({("a", V)}, {("a", V)})


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("carried", [U, U.upper(), U.replace("-", "")])
async def test_membership_removed_only_that_tenant(world, carried):
    _app, state, bus = world
    await _seed(state, "a", U, V)
    await _seed(state, "b", U)
    await bus.publish(MembershipRemoved(tenant_id="a", user_id=carried))
    assert await _left(state) == ({("a", V), ("b", U)}, {("a", V), ("b", U)})


@pytest.mark.unbound_tenant
async def test_tenant_deleted(world):
    _app, state, bus = world
    await _seed(state, "a", U, V)
    await _seed(state, "b", U)
    await bus.publish(TenantDeleted(tenant_id="a", slug="a", name="A"))
    assert await _left(state) == ({("b", U)}, {("b", U)})


@pytest.mark.unbound_tenant
async def test_an_invalid_tenant_id_deletes_nothing(world):
    _app, state, bus = world
    await _seed(state, "a", U)
    await bus.publish(TenantDeleted(tenant_id="platform", slug="p", name="P"))
    await bus.publish(MembershipRemoved(tenant_id="bad id!", user_id=U))
    assert await _left(state) == ({("a", U)}, {("a", U)})


@pytest.mark.unbound_tenant
async def test_handler_failure_is_swallowed(caplog):
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
    assert caplog.text.count("ReminderCleanup failed (OperationalError)") == 3
    assert "Event handler" not in caplog.text and U not in caplog.text


async def test_subscriptions_registered_beside_the_feed_links(world):
    _app, _state, bus = world
    for event in (UserDeleted, MembershipRemoved, TenantDeleted):
        assert len(bus._emitter.listeners(bus._event_key(event))) >= 2, event.__name__


async def test_a_missing_event_class_is_skipped_with_a_log(caplog, monkeypatch):
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


async def test_a_hard_deleted_calendar_takes_follows_and_ledger_with_it(db, db_state):
    from sm_events.models import Calendar as Cal

    await _seed(db_state, "default", U, V)
    cal_id = (await db.execute(select(Cal.id))).scalar_one()
    await db.execute(
        delete(Cal.__table__).where(
            Cal.__table__.c.id == cal_id, Cal.__table__.c.tenant_id == "default"
        )
    )
    await db.commit()
    assert (await db.execute(select(EventFollow))).scalars().all() == []
    assert (await db.execute(select(ReminderSent))).scalars().all() == []


# --- the ledger's retention ------------------------------------------------------------------


async def _ages(db, **days_by_state):
    pass


async def test_prune_only_what_started_long_ago(db, db_state):
    old = NOW - timedelta(days=limits.LEDGER_DAYS + 1)
    kept = NOW - timedelta(days=limits.LEDGER_DAYS - 1)
    await _seed(db_state, "default", "old", starts_at=old)
    await _seed(db_state, "default", "recent", starts_at=kept)
    await _seed(
        db_state,
        "default",
        "future",
        starts_at=NOW + timedelta(days=1),
        claimed_at=NOW - timedelta(days=200),
    )
    # An unfinished claim of an occurrence long gone goes too: nothing can ever send it.
    with tenant_scope("default"):
        async with db_state.session_factory() as s:
            row = (
                await s.execute(select(ReminderSent).where(ReminderSent.recipient_id == "old"))
            ).scalar_one()
            row.state = "sending"
            await s.commit()
        async with db_state.session_factory() as s:
            assert await cleanup.prune_ledger(s, now=NOW) == 1
            await s.commit()
    left = {r.recipient_id for r in (await db.execute(select(ReminderSent))).scalars()}
    assert left == {"recent", "future"}
    # The follows are not the ledger's business.
    assert len((await db.execute(select(EventFollow))).scalars().all()) == 3


async def test_prune_is_bounded_per_pass(db, db_state, monkeypatch):
    monkeypatch.setattr(limits, "LEDGER_PRUNE_BATCH", 10)
    monkeypatch.setattr(limits, "LEDGER_PRUNE_MAX_BATCHES", 3)
    users = [f"user{i:02d}" for i in range(45)]
    await _seed(db_state, "default", *users, starts_at=NOW - timedelta(days=200))
    removed = []
    for _ in range(3):
        with tenant_scope("default"):
            async with db_state.session_factory() as s:
                removed.append(await cleanup.prune_ledger(s, now=NOW))
                await s.commit()
    assert removed == [30, 15, 0]  # at most 3 x 10 per pass; the rest waits for the next
    assert (await db.execute(select(ReminderSent))).scalars().all() == []


@pytest.mark.unbound_tenant
async def test_the_janitor_prunes_and_visits_tenants_with_only_a_ledger(world):
    from sm_events.feeds.importing.janitor import janitor_async

    _app, state, _bus = world
    await _seed(state, "a", U, starts_at=NOW - timedelta(days=200))
    await _seed(state, "b", V, starts_at=NOW + timedelta(days=1))
    summary = await janitor_async(state.session_factory, now=NOW, relaunch=lambda t, i: None)
    assert summary["ledger"] == 1 and summary["tenants"] >= 1
    assert await _left(state) == ({("a", U), ("b", V)}, {("b", V)})
