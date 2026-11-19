"""The registration columns, and the counter and seat tables (PR 9)."""

from __future__ import annotations

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Event, RegistrationCount, RegistrationSeat
from sm_events.models.registration import COUNT_CONSTRAINT, SEAT_CONSTRAINT
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.support.calendars import bare_event


async def _event(db, slug="team"):
    cal = Calendar(slug=slug, name=slug.title(), owner_id="o")
    db.add(cal)
    await db.flush()
    return await bare_event(db, cal, status="published")


def _seat(event, holder="h1", key=None, provider="records:registration", target="reg"):
    return RegistrationSeat(
        event_id=event.id,
        occurrence_key=key or str(event.id),
        provider=provider,
        target=target,
        holder=holder,
    )


async def test_event_registration_defaults(db):
    event = await _event(db)
    assert event.registration_mode == "none"
    assert event.registration_show_seats is False
    for name in (
        "registration_provider",
        "registration_target",
        "registration_capacity",
        "registration_opens_at",
        "registration_closes_at",
        "registration_reminder_minutes",
    ):
        assert getattr(event, name) is None, name


async def test_unique_seat_per_holder(db):
    event = await _event(db)
    db.add(_seat(event))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_seat(event, key=f"{event.id}:20260701T100000Z"))  # same holder, other key
            await db.flush()
    db.add(_seat(event, holder="h2"))
    db.add(_seat(event, provider="other:provider"))  # same holder, other provider
    await db.flush()
    assert len((await db.execute(select(RegistrationSeat))).scalars().all()) == 3
    assert SEAT_CONSTRAINT == "uq_events_registration_seat"


async def test_unique_counter_per_occurrence(db):
    event = await _event(db)
    key = str(event.id)
    db.add(RegistrationCount(event_id=event.id, occurrence_key=key, taken=0))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(RegistrationCount(event_id=event.id, occurrence_key=key, taken=1))
            await db.flush()
    assert COUNT_CONSTRAINT == "uq_events_registration_count"


async def test_rows_carry_the_bound_tenant(db):
    event = await _event(db)
    db.add(_seat(event))
    db.add(RegistrationCount(event_id=event.id, occurrence_key=str(event.id), taken=1))
    await db.flush()
    with tenant_scope("default"):
        for model in (RegistrationSeat, RegistrationCount):
            rows = (await db.execute(select(model))).scalars().all()
            assert [row.tenant_id for row in rows] == ["default"]


async def test_deleting_the_event_cascades(db):
    event = await _event(db)
    db.add(_seat(event))
    db.add(RegistrationCount(event_id=event.id, occurrence_key=str(event.id), taken=1))
    await db.flush()
    table = Event.__table__  # type: ignore[attr-defined]
    await db.execute(
        sa_delete(table).where(table.c.id == event.id).execution_options(include_deleted=True)
    )
    await db.flush()
    assert (await db.execute(select(RegistrationSeat))).scalars().all() == []
    assert (await db.execute(select(RegistrationCount))).scalars().all() == []
