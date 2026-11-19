"""Two accounts whose ids differ only by case or dashes are two people, everywhere."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_core.user_events import UserDeleted
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, EventFollow, FeedToken, ReminderSent
from sm_events.module import EventsModule
from sm_events.reminders import cleanup, stats
from sqlalchemy import select
from tenants.contracts.events import MembershipRemoved

from tests.support.calendars import bare_event
from tests.support.tokens import token_app

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)
PAIRS = [("Bob", "bob"), ("a-b", "ab"), ("BOB", "Bob")]


async def _seed(state, tenant, *users):
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            cal = Calendar(slug=f"c-{uuid.uuid4().hex[:6]}", name="C", owner_id="o")
            db.add(cal)
            await db.flush()
            event = await bare_event(db, cal, status="published")
            for n, user in enumerate(users):
                db.add(EventFollow(event_id=event.id, user_id=user, lead_minutes=60, locale="en"))
                db.add(
                    ReminderSent(
                        event_id=event.id, occurrence_key=str(event.id), starts_at=NOW,
                        recipient_id=user, lead_minutes=60, state="sent",
                        claimed_at=NOW - timedelta(minutes=5),
                    )
                )  # fmt: skip
                db.add(
                    FeedToken(
                        calendar_id=cal.id, user_id=user,
                        token_hash=f"{tenant}{user}{n}".ljust(64, "0"),
                        label="L", locale="en",
                    )
                )  # fmt: skip
            await db.commit()


async def _left(state):
    from simple_module_db import all_tenants as unscoped
    from sm_events.core.tenancy import all_tenants

    with unscoped():
        async with state.session_factory() as db:
            return {
                name: {
                    (r.tenant_id, getattr(r, col))
                    for r in (await db.execute(all_tenants(select(model)))).scalars()
                }
                for name, model, col in (
                    ("follows", EventFollow, "user_id"),
                    ("ledger", ReminderSent, "recipient_id"),
                    ("tokens", FeedToken, "user_id"),
                )
            }


@pytest.fixture
async def world():
    app, state = await token_app(multi=True)
    EventsModule().register_event_handlers(app.state.sm.event_bus, app)
    yield app, state, app.state.sm.event_bus
    await state.engine.dispose()


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(("one", "other"), PAIRS)
async def test_deleting_one_account_leaves_the_other_alone(world, one, other):
    _app, state, bus = world
    await _seed(state, "a", one, other)
    await bus.publish(UserDeleted(user_id=one))  # type: ignore[arg-type]
    left = await _left(state)
    assert all(rows == {("a", other)} for rows in left.values()), left


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(("one", "other"), PAIRS)
async def test_a_membership_removal_is_exact_and_one_tenants(world, one, other):
    _app, state, bus = world
    await _seed(state, "a", one, other)
    await _seed(state, "b", one, other)
    await bus.publish(MembershipRemoved(tenant_id="a", user_id=one))
    left = await _left(state)
    for rows in left.values():
        assert rows == {("a", other), ("b", one), ("b", other)}, left


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(("one", "other"), PAIRS)
async def test_the_cleanup_functions_are_exact_too(world, one, other):
    _app, state, _bus = world
    await _seed(state, "a", one, other)
    assert await cleanup.delete_user_data(state.session_factory, one) == 2
    assert await cleanup.delete_member_data(state.session_factory, "a", other) == 2


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(("one", "other"), PAIRS)
async def test_each_accounts_counts_are_its_own(world, one, other):
    _app, state, _bus = world
    await _seed(state, "a", one, other)
    with tenant_scope("a"):
        async with state.session_factory() as db:
            assert (await stats.counts(db, now=NOW, user_id=one)).sent == 1
            assert (await stats.counts(db, now=NOW, user_id=other)).sent == 1
            assert (await stats.counts(db, now=NOW)).sent == 2


@pytest.mark.unbound_tenant
async def test_uuid_ids_in_every_spelling_are_one_identity(world):
    from tests.core.test_user_ids import ID, SPELLINGS

    _app, state, bus = world
    await _seed(state, "a", str(ID), "other")
    with tenant_scope("a"):
        async with state.session_factory() as db:
            for form in SPELLINGS:
                assert (await stats.counts(db, now=NOW, user_id=form)).sent == 1, form
    await bus.publish(UserDeleted(user_id=SPELLINGS[3]))  # type: ignore[arg-type]
    assert all(rows == {("a", "other")} for rows in (await _left(state)).values())
