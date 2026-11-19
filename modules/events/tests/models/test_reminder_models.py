"""The follow and reminder ledger tables (PR 8): keys, cascades and the calendar default."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, EventFollow, ReminderSent
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.support.calendars import bare_event

START = datetime(2026, 7, 1, 10, tzinfo=UTC)


async def _event(db, slug="team"):
    cal = Calendar(slug=slug, name=slug.title(), owner_id="o")
    db.add(cal)
    await db.flush()
    return cal, await bare_event(db, cal, status="published")


def _follow(event, lead=60, user="u") -> EventFollow:
    return EventFollow(event_id=event.id, user_id=user, lead_minutes=lead, locale="en")


def _sent(event, *, starts_at=START, user="u", lead=60, key=None) -> ReminderSent:
    return ReminderSent(
        event_id=event.id,
        occurrence_key=key or str(event.id),
        starts_at=starts_at,
        recipient_id=user,
        lead_minutes=lead,
        state="sending",
    )


async def test_follow_unique_per_lead(db):
    _, event = await _event(db)
    db.add(_follow(event, 60))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_follow(event, 60))
            await db.flush()
    db.add(_follow(event, 15))
    db.add(_follow(event, 60, user="other"))
    await db.flush()
    assert len((await db.execute(select(EventFollow))).scalars().all()) == 3


async def test_ledger_unique_key(db):
    _, event = await _event(db)
    db.add(_sent(event))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_sent(event))
            await db.flush()
    # A different start (a rescheduled occurrence), lead or recipient is another reminder.
    db.add(_sent(event, starts_at=START.replace(hour=11)))
    db.add(_sent(event, lead=15))
    db.add(_sent(event, user="other"))
    await db.flush()
    assert len((await db.execute(select(ReminderSent))).scalars().all()) == 4


async def test_ledger_defaults(db):
    _, event = await _event(db)
    row = _sent(event)
    db.add(row)
    await db.flush()
    assert row.id is not None
    assert row.claimed_at is not None and row.sent_at is None and row.code is None
    assert row.tenant_id == "default"


@pytest.mark.unbound_tenant
async def test_keys_are_tenant_leading(db):
    """The same user, event-less key in two tenants never collides: the tenant leads the key."""
    with tenant_scope("a"):
        _, first = await _event(db, "a")
        db.add(_follow(first))
        db.add(_sent(first))
        await db.flush()
    with tenant_scope("b"):
        _, second = await _event(db, "b")
        db.add(_follow(second))
        db.add(_sent(second))
        await db.flush()
    names = {c.name for t in (EventFollow, ReminderSent) for c in t.__table__.constraints}
    assert {"uq_events_follow", "uq_events_reminder_sent"} <= names
    for model in (EventFollow, ReminderSent):
        unique = next(
            c
            for c in model.__table__.constraints
            if c.name.startswith("uq_events_")  # type: ignore[union-attr]
        )
        assert next(iter(unique.columns)).name == "tenant_id"


async def test_cascade_on_event_delete(db):
    _, event = await _event(db)
    _, kept = await _event(db, "kept")
    for target in (event, kept):
        db.add(_follow(target))
        db.add(_sent(target))
    await db.flush()
    doomed_id, kept_id = event.id, kept.id
    # A hard delete (the ORM's ``delete`` would only trash an event): the database cascades.
    await db.execute(
        sa_delete(type(event).__table__).where(  # type: ignore[arg-type]
            type(event).__table__.c.id == doomed_id, type(event).__table__.c.tenant_id == "default"
        )
    )
    db.expire_all()
    for model in (EventFollow, ReminderSent):
        rows = (await db.execute(select(model))).scalars().all()
        assert [r.event_id for r in rows] == [kept_id], model


async def test_calendar_defaults_nullable(db):
    cal = Calendar(slug="c", name="C", owner_id="o")
    db.add(cal)
    await db.flush()
    assert cal.default_reminder_minutes is None
    cal_id = cal.id
    cal.default_reminder_minutes = [15, 60]
    await db.flush()
    db.expire_all()
    got = (await db.execute(select(Calendar).where(Calendar.id == cal_id))).scalar_one()
    assert got.default_reminder_minutes == [15, 60]
    got.default_reminder_minutes = None
    await db.flush()
    assert got.default_reminder_minutes is None
