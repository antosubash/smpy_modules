"""The public gate: anonymous principal, published events of public calendars."""

from __future__ import annotations

from sm_events.contracts.occurrences import occurrences as contract_occurrences
from sm_events.core.access.public import ANONYMOUS, public_calendars, public_events

from tests.support.calendars import seed_public_fixture
from tests.support.occurrences import utc


async def test_anonymous_has_nothing():
    assert ANONYMOUS.user_id is None
    assert ANONYMOUS.permissions == frozenset()


async def test_anonymous_matches_policy(db):
    fx = await seed_public_fixture(db)
    calendars = (await db.execute(public_calendars())).scalars().all()
    assert {c.id for c in calendars} == {fx.pub.id}
    events = (await db.execute(public_events())).scalars().all()
    assert {e.id for e in events} == {e.id for e in fx.public_events}


async def test_hidden_events_are_not_selected(db):
    fx = await seed_public_fixture(db)
    ids = {e.id for e in (await db.execute(public_events())).scalars().all()}
    for name, event in fx.hidden.items():
        assert event.id not in ids, name


async def test_same_as_contract(db):
    fx = await seed_public_fixture(db)
    page = await contract_occurrences(
        db,
        tenant_id="default",
        viewer=None,
        start=utc(2026, 3, 1),
        end=utc(2027, 3, 1),
    )
    assert not page.truncated
    seen = {o.event_id for o in page.items}
    selected = {e.id for e in (await db.execute(public_events())).scalars().all()}
    assert seen == selected == {e.id for e in fx.public_events}
