"""Follow limits, lead validation and the races around them."""

from __future__ import annotations

import asyncio

import pytest
from sm_events.core.errors_reminders import FollowLimit, InvalidLead
from sm_events.core.tenancy import tenant_scope
from sm_events.models import EventFollow
from sm_events.reminders import follows, limits
from sqlalchemy import func, select

from tests.pg_support import USING_POSTGRES
from tests.reminders.support import NOW, OTHER, SETTINGS, U, follow_row, published, world


async def _set(db, who, event, leads, locale="en"):
    return await follows.set_follow(
        db, who, event.id, leads, locale=locale, settings=SETTINGS, now=NOW
    )


async def _rows(db, user="u"):
    got = await db.execute(select(EventFollow).where(EventFollow.user_id == user))
    return sorted((r.event_id.hex, r.lead_minutes) for r in got.scalars())


async def test_limit_200(db):
    cals = await world(db)
    events = [await published(db, cals["U"], title=f"E{i}") for i in range(limits.FOLLOWS_PER_USER)]
    # Two leads each: the limit counts distinct events, not rows.
    for event in events:
        db.add(follow_row(event, lead=60))
        db.add(follow_row(event, lead=15))
    await db.flush()
    extra = await published(db, cals["U"], title="One too many")
    with pytest.raises(FollowLimit):
        await _set(db, U, extra, [60])
    assert await _rows(db) == sorted((e.id.hex, lead) for e in events for lead in (15, 60))
    # Re-saving the 200th does not count again, and unfollowing never hits the limit.
    last = await _set(db, U, events[-1], [1440])
    assert last.leads == (1440,)
    await _set(db, U, extra, [])
    # Someone else's follows do not count against this user.
    assert (await _set(db, OTHER, extra, [60])).leads == (60,)
    # One fewer, and the extra event fits.
    await _set(db, U, events[0], [])
    assert (await _set(db, U, extra, [60])).leads == (60,)


async def test_invalid_lead(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    for bad in ([30], [0], [limits.MAX_LEAD_MINUTES + 1], [True], [60] * 17):
        with pytest.raises(InvalidLead):
            await _set(db, U, event, bad)
    assert await _rows(db) == []
    with pytest.raises(InvalidLead):
        await _set(db, U, event, [60, 45])  # one bad value spoils the set; nothing is half-written
    assert await _rows(db) == []


async def test_a_lost_race_for_the_same_lead_is_not_an_error(db):
    """Two requests both find the lead missing and both insert it: the loser's unique violation
    is recognised (savepoint, constraint name) and the result is the same set."""
    cals = await world(db)
    event = await published(db, cals["U"])
    db.add(follow_row(event, lead=60))
    await db.flush()
    await follows._insert_missing(db, "u", event.id, [60, 15], locale="en", now=NOW)
    assert await _rows(db) == sorted([(event.id.hex, 15), (event.id.hex, 60)])


async def test_another_constraint_is_never_swallowed(db):
    """Only the follow's own unique key means "someone got there first"; anything else is real."""
    cals = await world(db)
    event = await published(db, cals["U"])
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await follows._insert_missing(db, "u", event.id, [None], locale="en", now=NOW)  # type: ignore[list-item]


@pytest.mark.skipif(not USING_POSTGRES, reason="two sessions racing for a row lock")
async def test_limit_holds_under_concurrent_first_follows(db_state):
    """199 followed, two requests each following a different new event: exactly one wins."""
    async with db_state.session_factory() as setup:
        cals = await world(setup)
        events = [
            await published(setup, cals["U"], title=f"E{i}")
            for i in range(limits.FOLLOWS_PER_USER + 1)
        ]
        for event in events[: limits.FOLLOWS_PER_USER - 1]:
            setup.add(follow_row(event))
        await setup.commit()
        ids = [e.id for e in events[-2:]]

    async def attempt(event_id):
        async with db_state.session_factory() as session:
            try:
                await follows.set_follow(
                    session, U, event_id, [60], locale="en", settings=SETTINGS, now=NOW
                )
                await session.commit()
            except FollowLimit:
                await session.rollback()
                return "limit"
            return "ok"

    with tenant_scope("default"):
        results = await asyncio.gather(*(attempt(i) for i in ids))
    assert sorted(results) == ["limit", "ok"]
    async with db_state.session_factory() as check:
        assert (
            await check.execute(select(func.count(func.distinct(EventFollow.event_id))))
        ).scalar_one() == limits.FOLLOWS_PER_USER
